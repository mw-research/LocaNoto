"""User accounts together with their storage account (OpenCloud).

The Streamlit pages did these steps one after another in three places
(own password, admin password, new user, delete user). Here they are
functions, so every front end does all of them:

    create(name, password, role, by)        user + personal room + storage account
    set_password(name, password, by)        user file + storage password
    change_own_password(name, old, new)     checks the old one first
    delete(name, by)                        user, instruction, storage account

Each returns (ok, message, notes); notes are the storage steps worth
showing ("account created", "password not changed: not managed", ...).
"""
import benutzer
import owncloud
import prompts


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


def create(name, password, role="nutzer", by="?"):
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


def set_password(name, password, by="?"):
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
    ok, message = benutzer.rolle_setzen(name, role, von=by)
    return ok, message, []


def delete(name, by="?"):
    """The user goes; their documents and rooms stay (an admin decides)."""
    if name == by:
        return False, "You cannot delete yourself.", []
    ok, message = benutzer.loesche(name, von=by)
    if not ok:
        return ok, message, []
    notes = []
    try:
        prompts.anweisung_loeschen(name)
    except Exception as e:
        notes.append(f"instruction not removed: {e}")
    if owncloud.eingerichtet():
        ok_s, m = owncloud.konto_loeschen(name)
        if m:
            notes.append(m)
    return ok, message, notes
