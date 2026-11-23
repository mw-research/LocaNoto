"""Signing in to tool servers with OAuth 2.1, the MCP authorization standard.

A tool server (MCP over HTTP) that wants to know who asks -- Exchange
Online through Microsoft Graph, a data connector with personal rights --
answers an unauthorised call with 401 and says where to sign in. Every
user then signs in at that provider once; LocaNoto gets a token for that
user and sends it with each call. The provider decides what the user
may do. This module does the steps of the standard:

  discover()     the server's protected-resource metadata (RFC 9728), from
                 the WWW-Authenticate header or the well-known address,
                 then the metadata of its authorization server (RFC 8414,
                 OpenID discovery as fallback). A server without metadata
                 (MCP 2025-03-26): the authorization server is the MCP
                 server's origin, with /authorize, /token, /register.
  client_for()   dynamic client registration (RFC 7591) as a public
                 client, once per server and redirect address; or the
                 client id an admin entered (option oauth_client_id).
  start()        authorization code with PKCE (S256), state and the
                 resource indicator (RFC 8707): the address the browser
                 goes to, and the sealed flow for a cookie.
  finish()       the code for tokens.
  refresh_due()  renews tokens that are about to expire, with the refresh
                 token (rotated as OAuth 2.1 asks).

WHERE THE TOKENS LIVE. Like a mailbox password: only in the user's sealed
session cookie (sessions.seal), never on the server. The cookie holds

    sealed[server]            {"Authorization": "Bearer <access token>"}
    sealed["oauth:" + server] {"r": refresh token, "e": expires at,
                               "tok": token endpoint, "c": client id,
                               "res": resource}

The first is what every other part of LocaNoto already reads for a
mailbox; the second is only for renewing it. server.py renews due tokens
before a request is handled and writes the cookie back.

WHAT IS STORED ON THE SERVER: per tool server the registered client
(client id, a client secret if the provider insists on one -- encrypted
with the installation key) in config/mcp_oauth_clients.json. That is the
installation's registration, not a person's credential.
"""
import base64
import hashlib
import json
import os
import re
import secrets
import threading
import time
from urllib.parse import urlencode, urlsplit

import dateisperre
import geheim
import paths
import statefiles

CLIENTS = os.path.join(paths.CONFIG_DIR, "mcp_oauth_clients.json")
TIMEOUT = paths.env_float("MCP_OAUTH_TIMEOUT", 15)
FLOW_SECONDS = 600
# Renew a token when it has less than this left: a long answer must not
# run into its expiry.
REFRESH_MARGIN = 120
PREFIX = "oauth:"
FLOW_PURPOSE = "mcp-oauth-flow"


class Refused(Exception):
    """A step of the sign-in did not work. The text is for the user."""


# --- ADDRESSES ---

def _origin(url):
    u = urlsplit(url)
    return f"{u.scheme}://{u.netloc}"


def _allowed(url, mcp_url):
    """May LocaNoto ask this address on behalf of a server?

    https only. Plain http only where the tool server itself is reached
    over http -- a test installation or a server inside the cluster --
    and only on the same host: a server must not send LocaNoto or the
    browser to an unencrypted address elsewhere.
    """
    u, m = urlsplit(url or ""), urlsplit(mcp_url or "")
    if u.scheme == "https" and u.hostname:
        return True
    return (u.scheme == "http" and m.scheme == "http"
            and bool(u.hostname) and u.hostname == m.hostname)


def _http():
    import httpx
    return httpx


def _get_json(url, mcp_url):
    if not _allowed(url, mcp_url):
        return None
    try:
        r = _http().get(url, timeout=TIMEOUT, follow_redirects=False,
                        headers={"Accept": "application/json"})
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


_PARAM = re.compile(r'(\w+)="([^"]*)"')


def _challenge(mcp_url):
    """(resource_metadata url, scope) from the server's 401, or ("", "")."""
    try:
        r = _http().post(
            mcp_url, timeout=TIMEOUT,
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                             "clientInfo": {"name": "LocaNoto", "version": "1.0"}}},
            headers={"Accept": "application/json, text/event-stream"})
    except Exception as e:
        raise Refused(f"Der Server ist nicht erreichbar ({type(e).__name__}).")
    if r.status_code != 401:
        return "", ""
    params = dict(_PARAM.findall(r.headers.get("www-authenticate", "")))
    return params.get("resource_metadata", ""), params.get("scope", "")


def discover(mcp_url, scopes=""):
    """Where and how to sign in for this tool server.

    Returns {"resource", "authorization_endpoint", "token_endpoint",
    "registration_endpoint", "scope"}. Raises Refused.
    """
    meta_url, scope = _challenge(mcp_url)
    u = urlsplit(mcp_url)
    path = u.path.rstrip("/")
    prm = None
    for candidate in (meta_url,
                      f"{_origin(mcp_url)}/.well-known/oauth-protected-resource{path}",
                      f"{_origin(mcp_url)}/.well-known/oauth-protected-resource"):
        if candidate:
            prm = _get_json(candidate, mcp_url)
            if prm:
                break
    if prm:
        resource = str(prm.get("resource") or mcp_url)
        # The metadata must be about this server: a server that names
        # another resource would get a token meant for something else.
        if not mcp_url.rstrip("/").startswith(resource.rstrip("/")):
            raise Refused("Die Metadaten des Servers nennen eine andere Adresse.")
        servers = [s for s in (prm.get("authorization_servers") or []) if isinstance(s, str)]
        if not servers:
            raise Refused("Der Server nennt keinen Anmeldedienst.")
        issuer = servers[0]
        scope = scope or " ".join(str(s) for s in (prm.get("scopes_supported") or []))
    else:
        resource, issuer = mcp_url, _origin(mcp_url)

    ipath = urlsplit(issuer).path.rstrip("/")
    meta = None
    for candidate in (f"{_origin(issuer)}/.well-known/oauth-authorization-server{ipath}",
                      f"{_origin(issuer)}/.well-known/openid-configuration{ipath}",
                      f"{issuer.rstrip('/')}/.well-known/openid-configuration"):
        meta = _get_json(candidate, mcp_url)
        if meta:
            break
    if meta is None:
        if prm:
            raise Refused("Der Anmeldedienst beschreibt sich nicht (keine Metadaten).")
        # MCP 2025-03-26: no metadata, the standard paths at the server.
        meta = {"authorization_endpoint": issuer + "/authorize",
                "token_endpoint": issuer + "/token",
                "registration_endpoint": issuer + "/register"}
    methods = meta.get("code_challenge_methods_supported")
    if methods is not None and "S256" not in methods:
        raise Refused("Der Anmeldedienst unterstützt kein PKCE (S256).")
    out = {"resource": resource,
           "authorization_endpoint": str(meta.get("authorization_endpoint") or ""),
           "token_endpoint": str(meta.get("token_endpoint") or ""),
           "registration_endpoint": str(meta.get("registration_endpoint") or ""),
           "scope": (scopes or scope or "").strip()}
    for key in ("authorization_endpoint", "token_endpoint"):
        if not _allowed(out[key], mcp_url):
            raise Refused("Der Anmeldedienst nennt eine unsichere oder fremde Adresse.")
    if out["registration_endpoint"] and not _allowed(out["registration_endpoint"], mcp_url):
        out["registration_endpoint"] = ""
    return out


# --- THE REGISTERED CLIENT ---

_clients_lock = threading.Lock()


def _clients():
    try:
        with statefiles.open(CLIENTS, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _secret(server, entry):
    raw = entry.get("secret") or ""
    if not raw:
        return ""
    try:
        return geheim.entschluessele(base64.b64decode(raw),
                                     ("mcp-oauth:" + server).encode()).decode()
    except Exception:
        return ""


def client_for(server, entry, meta, redirect_uri):
    """{"client_id", "secret"} for this server; registers when needed."""
    given = str(entry.get("oauth_client_id") or "").strip()
    if given:
        return {"client_id": given, "secret": ""}
    with _clients_lock:
        known = _clients().get(server) or {}
        if (known.get("client_id") and known.get("redirect_uri") == redirect_uri
                and known.get("token_endpoint") == meta["token_endpoint"]):
            return {"client_id": known["client_id"], "secret": _secret(server, known)}
        if not meta["registration_endpoint"]:
            raise Refused("Der Anmeldedienst erlaubt keine automatische "
                          "Registrierung. Ein Admin trägt beim Eintrag eine "
                          "Client-ID ein (oauth_client_id).")
        body = {"client_name": "LocaNoto", "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"], "token_endpoint_auth_method": "none"}
        if meta["scope"]:
            body["scope"] = meta["scope"]
        try:
            r = _http().post(meta["registration_endpoint"], json=body,
                             timeout=TIMEOUT, headers={"Accept": "application/json"})
            data = r.json() if r.status_code in (200, 201) else {}
        except Exception:
            data = {}
        if not isinstance(data, dict) or not data.get("client_id"):
            raise Refused("Die Registrierung beim Anmeldedienst ist gescheitert.")
        record = {"client_id": str(data["client_id"]), "redirect_uri": redirect_uri,
                  "token_endpoint": meta["token_endpoint"]}
        secret = str(data.get("client_secret") or "")
        if secret:
            record["secret"] = base64.b64encode(geheim.verschluessele(
                secret.encode(), ("mcp-oauth:" + server).encode())).decode()
        everything = _clients()
        everything[server] = record
        statefiles.makedirs(os.path.dirname(CLIENTS), exist_ok=True)
        dateisperre.schreibe_atomar(CLIENTS, json.dumps(everything, indent=1), 0o600)
        return {"client_id": record["client_id"], "secret": secret}


def forget_client(server):
    """Drop the registration of a server (when its entry is removed)."""
    with _clients_lock:
        everything = _clients()
        if everything.pop(server, None) is not None:
            dateisperre.schreibe_atomar(CLIENTS, json.dumps(everything, indent=1), 0o600)


# --- THE FLOW ---

def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def start(user, server, entry, redirect_uri):
    """(address for the browser, sealed flow for a cookie)."""
    import sessions
    mcp_url = str(entry.get("url") or "")
    meta = discover(mcp_url, str(entry.get("oauth_scopes") or ""))
    client = client_for(server, entry, meta, redirect_uri)
    verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(24)
    params = {"response_type": "code", "client_id": client["client_id"],
              "redirect_uri": redirect_uri, "state": state,
              "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()),
              "code_challenge_method": "S256", "resource": meta["resource"]}
    if meta["scope"]:
        params["scope"] = meta["scope"]
    ep = meta["authorization_endpoint"]
    url = ep + ("&" if "?" in ep else "?") + urlencode(params)
    flow = sessions.seal(FLOW_PURPOSE, {
        "u": user, "server": server, "v": verifier, "s": state, "t": time.time(),
        "c": client["client_id"], "tok": meta["token_endpoint"],
        "res": meta["resource"], "ru": redirect_uri})
    return url, flow


def _token_request(server, endpoint, data, client_id, secret=""):
    form = dict(data, client_id=client_id)
    try:
        r = _http().post(endpoint, data=form, timeout=TIMEOUT,
                         auth=(client_id, secret) if secret else None,
                         headers={"Accept": "application/json"})
        body = r.json() if r.status_code == 200 else {}
    except Exception:
        body = {}
    if not isinstance(body, dict) or not body.get("access_token"):
        raise Refused("Der Anmeldedienst hat kein Token ausgegeben.")
    if str(body.get("token_type") or "bearer").lower() != "bearer":
        raise Refused("Der Anmeldedienst gibt ein unbekanntes Token aus.")
    return body


def _entry(tokens, token_endpoint, client_id, resource, old_refresh=""):
    try:
        lifetime = int(tokens.get("expires_in") or 3600)
    except (TypeError, ValueError):
        lifetime = 3600
    return {"a": str(tokens["access_token"]),
            "r": str(tokens.get("refresh_token") or old_refresh or ""),
            "e": int(time.time()) + max(lifetime, 1),
            "tok": token_endpoint, "c": client_id, "res": resource}


def finish(code, state, flow_cookie):
    """(user, server, entry) after the provider sent the browser back."""
    import sessions
    flow = sessions.unseal(FLOW_PURPOSE, flow_cookie)
    if not flow or time.time() - flow.get("t", 0) > FLOW_SECONDS:
        raise Refused("Die Anmeldung hat zu lange gedauert oder wurde woanders begonnen.")
    if not state or not secrets.compare_digest(str(state), str(flow.get("s"))):
        raise Refused("Die Anmeldung gehört nicht zu diesem Browser.")
    secret = _secret(flow["server"], _clients().get(flow["server"]) or {})
    tokens = _token_request(flow["server"], flow["tok"], {
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": flow["ru"], "code_verifier": flow["v"],
        "resource": flow["res"]}, flow["c"], secret)
    return flow["u"], flow["server"], _entry(tokens, flow["tok"], flow["c"], flow["res"])


def store(sealed, server, entry):
    """Put a token into the sealed dict: the header for the server, and the
    rest for renewing it."""
    sealed[server] = {"Authorization": "Bearer " + entry["a"]}
    sealed[PREFIX + server] = {k: v for k, v in entry.items() if k != "a"}


def forget(sealed, server):
    sealed.pop(server, None)
    sealed.pop(PREFIX + server, None)


# --- RENEWING ---
#
# OAuth 2.1 rotates refresh tokens: using one hands out a new one and the
# old is spent. Two requests of one browser renewing at the same moment
# would spend it twice, and the second would lose the sign-in. Within a
# process the first result is kept for a minute and handed to the second.
_recent = {}
_recent_lock = threading.Lock()


def _renew(server, entry):
    key = hashlib.sha256((server + "\0" + entry.get("r", "")).encode()).hexdigest()
    with _recent_lock:
        hit = _recent.get(key)
        if hit and time.time() - hit[1] < 60:
            return hit[0]
        secret = _secret(server, _clients().get(server) or {})
        tokens = _token_request(server, entry["tok"], {
            "grant_type": "refresh_token", "refresh_token": entry["r"],
            "resource": entry.get("res") or ""}, entry["c"], secret)
        new = _entry(tokens, entry["tok"], entry["c"], entry.get("res") or "",
                     old_refresh=entry["r"])
        _recent[key] = (new, time.time())
        for k in [k for k, (_n, t) in _recent.items() if time.time() - t > 60]:
            _recent.pop(k, None)
        return new


def refresh_due(sealed):
    """Renew the tokens in a sealed dict that are about to expire.

    Returns True when the dict changed (renewed, or a sign-in dropped
    because it could not be renewed -- then the user connects again).
    """
    changed = False
    now = time.time()
    for key in [k for k in list(sealed) if k.startswith(PREFIX)]:
        server, entry = key[len(PREFIX):], sealed.get(key) or {}
        if not isinstance(entry, dict) or entry.get("e", 0) - now > REFRESH_MARGIN:
            continue
        if not entry.get("r"):
            if entry.get("e", 0) <= now:
                forget(sealed, server)
                changed = True
            continue
        try:
            store(sealed, server, _renew(server, entry))
        except Refused:
            forget(sealed, server)
        changed = True
    return changed
