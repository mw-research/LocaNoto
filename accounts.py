"""User accounts together with their storage account (OpenCloud).

Each step is a function, so every front end does all of them:

    create(name, password, role, by)        user + personal room + storage account
    left_over(name)                         what a former account of the name left
    purge_left_over(name, by)               remove it (server shell only)
    set_password(name, password, by)        user file + storage password
    change_own_password(name, old, new)     checks the old one first
    delete(name, by)                        user, instruction, storage account

Each returns (ok, message, notes); notes are the storage steps worth
showing ("account created", "password not changed: not managed", ...).
"""
import os

import benutzer
import owncloud
import paths
import prompts
import statefiles


def _storage_password(name, password, by):
    """Create the storage account if missing, else change its password."""
    notes = []
    if not owncloud.eingerichtet():
        return notes
    report = owncloud.richte_nutzer_ein(name, password, by) or {}
    notes += list(report.get("schritte") or [])
    notes += [f"error: {f}" for f in report.get("fehler") or []]
    if any("gab es schon" in s for s in report.get("schritte") or []):
        ok, message = owncloud.passwort_setzen(name, password)
        if message:
            notes.append(message)
    return notes


# The emergency role confirms an admin's access to a personal workspace.
# If an admin could hand it out, the second person could be the admin's
# own puppet account. So it is assigned outside the app only: the company
# directory (OIDC_EMERGENCY_GROUPS) or scripts/manage_users.py on the server.
APP_ROLES = ("admin", "nutzer")


def left_over(name):
    """What a former account of this name left behind: a list of words.

    Deleting an account keeps its chats and its personal workspace. Both
    are bound to the NAME -- a new account of that name would open them.
    An admin could read anyone's personal workspace that way: delete the
    account, create it again, sign in.
    """
    import raeume
    import store
    name = (name or "").strip().lower()
    found = []
    try:
        sml = store.sammlung(raeume.sammlung(raeume.privat_kennung(name)),
                             anlegen=False)
        if sml is not None and sml.count():
            found.append("personal workspace")
    except Exception:
        found.append("personal workspace")      # unreadable: assume it is
    folder = os.path.join(paths.CHATS_DIR, name)
    try:
        if statefiles.isdir(folder) and statefiles.listdir(folder):
            found.append("chats and files")
    except OSError:
        found.append("chats and files")
    return found


def purge_left_over(name, by="?"):
    """Remove what a deleted account left. Returns (ok, message).

    Not offered in the pages or the API: it deletes what only its owner
    could read. Run on the server: python accounts.py purge <name>.
    """
    import aufnehmen
    import keyword_index
    import raeume
    import store
    name = (name or "").strip().lower()
    if benutzer.eintrag(name):
        return False, f"'{name}' is an account. Delete it first."
    room = raeume.privat_kennung(name)
    store.loesche(raeume.sammlung(room))
    keyword_index.delete_document_by_raum(room)
    aufnehmen.leere_ablage(room)
    statefiles.rmtree(os.path.join(paths.CHATS_DIR, name), ignore_errors=True)
    benutzer.protokolliere("nachlass_entfernt", name, by)
    return True, f"What '{name}' left is removed."


def create(name, password, role="nutzer", by="?"):
    if role not in APP_ROLES:
        return False, ("The role notzugang is assigned through the directory "
                       "or scripts/manage_users.py on the server."), []
    rest = left_over(name)
    if rest and not benutzer.eintrag((name or "").strip().lower()):
        return False, ("A former account of this name left " + " and ".join(rest)
                       + ". They would belong to the new account. Remove them "
                         "on the server first: python accounts.py purge "
                       + (name or "").strip().lower()), []
    ok, message = benutzer.anlege(name, password, rolle=role, von=by)
    if not ok:
        return ok, message, []
    notes = []
    if owncloud.eingerichtet():
        report = owncloud.richte_nutzer_ein(name.strip().lower(), password,
                                            by) or {}
        notes += list(report.get("schritte") or [])
        notes += [f"error: {f}" for f in report.get("fehler") or []]
    return ok, message, notes


def reset_refused(name, by):
    """Why 'by' may not set this account's password, or "".

    Whoever sets a password can sign in with it. For an account with
    chats or a personal workspace that is a way in past the two-person
    emergency access. So it needs exactly that access: requested by this
    admin for the account's personal workspace and confirmed by a second
    person. An account that holds nothing yet, one's own, and accounts
    from the company directory (no password is used there) are free.
    """
    import notzugang
    import raeume
    name = (name or "").strip().lower()
    if name == (by or "").strip().lower():
        return ""
    if (benutzer.eintrag(name) or {}).get("anmeldung") == "oidc":
        return ""
    if not left_over(name):
        return ""
    if raeume.privat_kennung(name) in notzugang.raeume_fuer(by):
        return ""
    return ("This account has chats or a personal workspace. With a password "
            "you set, they would be open to you. Request emergency access to "
            "its personal workspace first; once a second person has confirmed "
            "it, you can set the password.")


def set_password(name, password, by="?"):
    refused = reset_refused(name, by)
    if refused:
        return False, refused, []
    ok, message = benutzer.passwort_setzen(name, password, von=by)
    if not ok:
        return ok, message, []
    return ok, message, _storage_password(name.strip().lower(), password, by)


def change_own_password(name, old, new):
    if new == old:
        return False, "The new password equals the old one.", []
    if not benutzer.pruefe(name, old):
        return False, "The current password is wrong.", []
    return set_password(name, new, by=name)


def set_role(name, role, by="?"):
    if role not in APP_ROLES or benutzer.hat_rolle(name, "notzugang"):
        return False, ("The role notzugang is assigned and removed through "
                       "the directory or scripts/manage_users.py on the server."), []
    ok, message = benutzer.rolle_setzen(name, role, von=by)
    return ok, message, []


def delete(name, by="?"):
    """The user goes; their documents and rooms stay (an admin decides)."""
    # One spelling: the user file keeps names in lower case. "Bob" deleted
    # the account "bob" and left his tokens, which matched "Bob" nowhere.
    name = (name or "").strip().lower()
    if name == (by or "").strip().lower():
        return False, "You cannot delete yourself.", []
    ok, message = benutzer.loesche(name, von=by)
    if not ok:
        return ok, message, []
    notes = []
    # Tokens go with the account. Left behind, they would still sign in
    # -- and a later account of the same name would inherit them.
    import auth
    for token_id, entry in auth.liste():
        if entry.get("benutzer") == name:
            auth.widerrufe(token_id)
            notes.append("token revoked")
    try:
        prompts.anweisung_loeschen(name)
    except Exception as e:
        notes.append(f"instruction not removed: {e}")
    if owncloud.eingerichtet():
        ok_s, m = owncloud.konto_loeschen(name)
        if m:
            notes.append(m)
    return ok, message, notes


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "purge":
        paths.bootstrap()
        _ok, _message = purge_left_over(sys.argv[2], by="server")
        print(_message)
        sys.exit(0 if _ok else 1)
    print("python accounts.py purge <name>   remove what a deleted account left")
    sys.exit(2)
