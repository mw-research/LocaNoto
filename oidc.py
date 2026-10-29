"""Sign-in through the company directory (OpenID Connect).

Entra ID, Keycloak, Authentik, ... -- anything that speaks OIDC with the
authorization code flow. Local accounts keep working next to it (small
installations, and an admin account for when the directory is down).

    OIDC_ISSUER=https://login.microsoftonline.com/<tenant>/v2.0
    OIDC_CLIENT_ID=...
    OIDC_CLIENT_SECRET=...                       (a Secret, not the ConfigMap)
    OIDC_REDIRECT_URI=https://locanoto.example.com/api/v1/auth/oidc/callback
    OIDC_SCOPES=openid profile email
    OIDC_USERNAME_CLAIM=preferred_username       local part before @ is used
    OIDC_GROUPS_CLAIM=groups
    OIDC_ALLOWED_GROUPS=                         empty: everyone the directory admits
    OIDC_ADMIN_GROUPS=locanoto-admins
    OIDC_EMERGENCY_GROUPS=locanoto-notzugang
    OIDC_LINK_EXISTING=0                         1: take over local accounts of the same name

THE FLOW. /auth/oidc/login sends the browser to the directory with a
PKCE challenge, a random state and a nonce; those three are sealed into a
cookie (sessions.seal) that lives ten minutes. /auth/oidc/callback checks
state, exchanges the code (with the PKCE verifier), checks the ID token
(signature from the provider's keys, issuer, audience, expiry, nonce) and
ends in the same session cookie as a password sign-in.

ACCOUNTS. The first sign-in creates the account (random, unknown
password; it cannot sign in with a password) and binds it to the
directory's identity issuer|sub. A later sign-in must come with the same
identity -- a name the directory gives to someone else later does not
open the old account. An existing LOCAL account of the same name is not
taken over unless OIDC_LINK_EXISTING=1 (for moving an installation to the
directory on purpose).

ROLES AND GROUPS come from the directory at every sign-in: admin and
emergency role from the groups above, workspace membership through the
group a workspace names (raeume.gruppe_setzen) -- see
raeume.oidc_gruppen_setzen.
"""
import base64
import hashlib
import os
import re
import secrets
import threading
import time

import benutzer
import paths
import raeume
import sessions

ISSUER = os.getenv("OIDC_ISSUER", "").strip().rstrip("/")
CLIENT_ID = os.getenv("OIDC_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv("OIDC_REDIRECT_URI", "").strip()
SCOPES = os.getenv("OIDC_SCOPES", "openid profile email").strip()
USERNAME_CLAIM = os.getenv("OIDC_USERNAME_CLAIM", "preferred_username").strip()
GROUPS_CLAIM = os.getenv("OIDC_GROUPS_CLAIM", "groups").strip()
LINK_EXISTING = os.getenv("OIDC_LINK_EXISTING", "0").strip() == "1"
FLOW_SECONDS = 600


def _groups_env(name):
    return {g.strip() for g in os.getenv(name, "").split(",") if g.strip()}


ALLOWED_GROUPS = _groups_env("OIDC_ALLOWED_GROUPS")
ADMIN_GROUPS = _groups_env("OIDC_ADMIN_GROUPS")
EMERGENCY_GROUPS = _groups_env("OIDC_EMERGENCY_GROUPS")
TIMEOUT = paths.env_float("OIDC_TIMEOUT", 15)

_cache = {}
_cache_lock = threading.Lock()


class Refused(Exception):
    """The sign-in is not accepted. The message is safe to show."""


def enabled():
    return bool(ISSUER and CLIENT_ID and REDIRECT_URI)


# --- PROVIDER ---

def _http():
    import httpx
    return httpx.Client(timeout=TIMEOUT, follow_redirects=False)


def discovery():
    """The provider's metadata, kept for an hour."""
    with _cache_lock:
        hit = _cache.get("discovery")
        if hit and time.time() - hit[0] < 3600:
            return hit[1]
    with _http() as h:
        r = h.get(ISSUER + "/.well-known/openid-configuration")
        r.raise_for_status()
        doc = r.json()
    if doc.get("issuer", "").rstrip("/") != ISSUER:
        raise Refused("The provider names another issuer.")
    with _cache_lock:
        _cache["discovery"] = (time.time(), doc)
    return doc


def exchange(code, verifier):
    """Authorization code -> token response (dict)."""
    doc = discovery()
    with _http() as h:
        r = h.post(doc["token_endpoint"], data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": REDIRECT_URI, "client_id": CLIENT_ID,
            "code_verifier": verifier},
            auth=(CLIENT_ID, CLIENT_SECRET) if CLIENT_SECRET else None)
    if r.status_code != 200:
        raise Refused("The directory did not accept the sign-in code.")
    return r.json()


def signing_key(id_token):
    """The provider key that signed this token (from its JWKS)."""
    import jwt
    with _cache_lock:
        client = _cache.get("jwks")
        if client is None:
            client = jwt.PyJWKClient(discovery()["jwks_uri"], cache_keys=True,
                                     lifespan=3600, timeout=TIMEOUT)
            _cache["jwks"] = client
    return client.get_signing_key_from_jwt(id_token).key


def verify_id_token(id_token, nonce):
    import jwt
    try:
        claims = jwt.decode(
            id_token, signing_key(id_token),
            algorithms=["RS256", "RS384", "RS512", "PS256", "ES256", "ES384"],
            audience=CLIENT_ID, issuer=ISSUER,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=60)
    except jwt.PyJWTError as e:
        raise Refused(f"ID token not valid ({type(e).__name__}).")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise Refused("ID token does not belong to this sign-in.")
    return claims


# --- THE FLOW ---

def start(next_path="/"):
    """(redirect_url, sealed_flow) for /auth/oidc/login."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()).decode().rstrip("=")
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    flow = sessions.seal("oidc-flow", {"v": verifier, "s": state, "n": nonce,
                                       "t": int(time.time()),
                                       "next": safe_next(next_path)})
    from urllib.parse import urlencode
    url = discovery()["authorization_endpoint"] + "?" + urlencode({
        "response_type": "code", "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI, "scope": SCOPES, "state": state,
        "nonce": nonce, "code_challenge": challenge,
        "code_challenge_method": "S256"})
    return url, flow


def finish(code, state, sealed_flow):
    """(username, next_path) after the provider sent the browser back."""
    flow = sessions.unseal("oidc-flow", sealed_flow)
    if not flow or time.time() - flow.get("t", 0) > FLOW_SECONDS:
        raise Refused("The sign-in took too long or was started elsewhere.")
    if not state or not secrets.compare_digest(state, flow["s"]):
        raise Refused("The sign-in does not belong to this browser.")
    tokens = exchange(code, flow["v"])
    claims = verify_id_token(tokens.get("id_token", ""), flow["n"])
    return provision(claims), flow.get("next", "/")


def safe_next(path):
    """Only paths on this site -- no open redirect."""
    path = str(path or "/")
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    return path


def local_name(claims):
    raw = str(claims.get(USERNAME_CLAIM) or claims.get("email") or "")
    raw = raw.split("@", 1)[0].strip().lower()
    name = re.sub(r"[^a-z0-9._-]", "", raw)
    if not name:
        raise Refused("The directory sent no usable user name.")
    return name


def role_for(groups):
    if groups & ADMIN_GROUPS:
        return "admin"
    if groups & EMERGENCY_GROUPS:
        return "notzugang"
    return "nutzer"


def provision(claims):
    """Create or update the account behind these claims. Returns its name."""
    identity = f"{claims['iss']}|{claims['sub']}"
    groups = {str(g) for g in (claims.get(GROUPS_CLAIM) or [])}
    if ALLOWED_GROUPS and not groups & ALLOWED_GROUPS:
        raise Refused("Your account is not cleared for LocaNoto.")
    name = local_name(claims)
    entry = benutzer.lade()[0].get(name)
    role = role_for(groups)
    if entry is None:
        ok, message = benutzer.anlege(name, secrets.token_urlsafe(32),
                                      rolle=role, von="oidc")
        if not ok:
            raise Refused(message)
        benutzer.anmeldung_setzen(name, "oidc", von="oidc", extern=identity)
    else:
        bound = entry.get("extern")
        if bound and bound != identity:
            benutzer.protokolliere("abgewiesen", name, "oidc",
                                   "andere Verzeichnisidentitaet")
            raise Refused("This name belongs to another directory account.")
        if not bound:
            if entry.get("anmeldung") != "oidc" and not LINK_EXISTING:
                raise Refused("A local account of this name exists. An "
                              "admin can link it (OIDC_LINK_EXISTING=1).")
            benutzer.anmeldung_setzen(name, "oidc", von="oidc",
                                      extern=identity)
        if entry.get("rolle") != role:
            benutzer.rolle_setzen(name, role, von="oidc")
    raeume.oidc_gruppen_setzen(name, sorted(groups))
    benutzer.protokolliere("anmeldung", name, name, "oidc")
    return name
