"""Document actions with their permission checks: move, delete, wipe.

These lived in the Streamlit page, which also decided who may use them by
showing or hiding a button. Here every function checks the permission
itself, so any front end (API, web pages) can call it directly.

    move(user, file_name, from_room, to_room, is_admin=False)
    delete(user, file_name, room, is_admin=False)
    foreign_documents(user, is_admin)        admin: [(room, file_id)], no names
    foreign_rooms(user)                      admin: [(room, passages)]
    delete_foreign(user, room, file_id)      admin: delete by file id
    wipe_room(user, room, confirm)           admin: every passage of a room

Moving keeps the vectors and re-encrypts text and file name for the target
room (a passage is bound to the room it lies in). The file goes along, on
disk and in OpenCloud, so the next sync does not bring it back.
"""
import os

import aufnehmen
import keyword_index
import notzugang
import owncloud
import paths
import raeume
import statefiles
import store


class Denied(Exception):
    """Not allowed. Raised before anything is looked up."""


class NotFound(Exception):
    pass


def _collection(room, create=True):
    return store.sammlung(raeume.sammlung(room), anlegen=create)


def _all_room_collections():
    return aufnehmen._alle_raum_sammlungen()


# --- MOVE ---

def move(user, file_name, from_room, to_room, is_admin=False):
    """Move a document with its passages to another room. Returns a message.

    The user must be allowed to write in both rooms.
    """
    emergency = notzugang.raeume_fuer(user)
    for room in (from_room, to_room):
        if not raeume.darf_schreiben(user, room, is_admin, emergency):
            raise Denied(f"No write access to '{room}'.")
    if from_room == to_room:
        return "Already there."
    source = _collection(from_room, create=False)
    if source is None:
        raise NotFound("The source room has no data.")
    data = store.hole(source, raeume.sammlung(from_room),
                      where=store.datei_filter(file_name),
                      include=["documents", "metadatas", "embeddings"])
    ids = data.get("ids") or []
    if not ids:
        raise NotFound("No passages of this document in the source room.")
    vectors = data.get("embeddings")
    if vectors is None or len(vectors) != len(ids):
        raise ValueError("The vectors are missing; moving would mean "
                         "reading the document again.")
    metas = []
    for m in data.get("metadatas") or []:
        meta = dict(m or {})
        meta["raum"] = to_room
        metas.append(meta)
    # Name and text are bound to the room they lay in: re-encrypt both.
    metas = store.metadaten_umschluesseln(from_room, to_room, metas)
    docs = store.umschluesseln(from_room, to_room,
                               data.get("documents") or [], user)
    store.schreibe(_collection(to_room), ids, documents=docs,
                   metadatas=metas, embeddings=vectors)
    source.delete(ids=ids)
    keyword_index.delete_document(file_name, raum=from_room)
    keyword_index.add_chunks(
        zip(ids, store.klartext(from_room, data.get("documents") or [], user),
            store.metadaten_klartext(to_room, metas)))
    return (f"Moved to '{raeume.bezeichnung(to_room)}'."
            + _move_file(file_name, from_room, to_room))


def _move_file(file_name, from_room, to_room):
    """The file goes along, on disk and in OpenCloud. Returns a remark."""
    source = aufnehmen.dokument_pfad(file_name, from_room)
    if not source or not statefiles.exists(source):
        return ""

    def base(room):
        return (paths.DOCS_DIR if room == raeume.ALLGEMEIN
                else paths.raum_ordner(room))
    try:
        rel = os.path.relpath(os.path.dirname(source), base(from_room))
    except ValueError:
        rel = "."
    if rel.startswith("..") or rel in (".", ""):
        rel = ""
    folder = os.path.join(base(to_room), rel) if rel else base(to_room)
    target = os.path.join(folder, os.path.basename(source))
    if os.path.normpath(target) == os.path.normpath(source):
        return ""
    if statefiles.exists(target):
        return (" The file stayed where it was: the target already has a "
                "file of that name, so the page view will not work there.")
    try:
        statefiles.makedirs(folder, exist_ok=True)
        statefiles.rename(source, target)
    except OSError as e:
        return f" The file could not be moved ({e})."
    ok, m = owncloud.verschiebe(from_room, source, to_room, target)
    if not ok:
        return (f" WARNING: {m} The next sync brings the file back into "
                f"'{raeume.bezeichnung(from_room)}'.")
    return ""


# --- DELETE ---

def delete(user, file_name, room, is_admin=False):
    """Delete a document from one room. Returns (message, report)."""
    try:
        return aufnehmen.entferne_dokument(
            file_name, room, benutzer_=user, ist_verwalter=is_admin,
            notzugang=notzugang.raeume_fuer(user))
    except aufnehmen.KeinRecht as e:
        raise Denied(str(e))
    except aufnehmen.NichtGefunden as e:
        raise NotFound(str(e))


# --- ADMIN: FOREIGN ROOMS, WITHOUT INSIGHT ---

def foreign_documents(user, is_admin):
    """[(room, file_id)] in rooms the admin cannot read -- never names.

    For clearing orphaned storage of people who left. A right to delete
    is not a right to read: a file name already tells the matter, so only
    datei_id (not reversible) is shown. With PRIVAT_STRENG even this list
    stays empty for personal rooms; foreign_rooms() remains.
    """
    import raumschluessel
    if not is_admin:
        raise Denied("Admins only.")
    emergency = notzugang.raeume_fuer(user)
    seen = set()
    for room, sml in _all_room_collections():
        if raeume.darf_lesen(user, room, emergency):
            continue
        if not raeume.darf_dateien_sehen(user, room, ist_verwalter=True):
            continue
        try:
            data = sml.get(include=["metadatas"])
        except Exception:
            continue
        for m in data.get("metadatas") or []:
            if not m:
                continue
            fid = m.get("datei_id") or raumschluessel.datei_id(
                m.get("file_name") or "")
            if fid:
                seen.add((room, fid))
    return sorted(seen)


def foreign_rooms(user, is_admin):
    """[(room, passages)] of rooms this admin cannot read."""
    if not is_admin:
        raise Denied("Admins only.")
    emergency = notzugang.raeume_fuer(user)
    out = []
    for room, sml in _all_room_collections():
        if raeume.darf_lesen(user, room, emergency):
            continue
        try:
            n = sml.count()
        except Exception:
            continue
        if n:
            out.append((room, n))
    return sorted(out)


def delete_foreign(user, is_admin, room, file_id):
    """Delete a document in a foreign room by its file id."""
    if (room, file_id) not in set(foreign_documents(user, is_admin)):
        raise NotFound("No such document in a foreign room.")
    try:
        return aufnehmen.entferne_dokument(file_id, room,
                                           kennung_statt_name=True)
    except aufnehmen.NichtGefunden as e:
        raise NotFound(str(e))


def wipe_room(user, is_admin, room, confirm):
    """Delete every passage of a room. confirm must repeat the room id.

    The typed id binds the confirmation to the target -- a flag set for
    one room cannot be reused for another. The room itself (members,
    settings) stays. Returns (ok, message, owncloud_failures).
    """
    if not is_admin:
        raise Denied("Admins only.")
    if confirm != room:
        raise ValueError("Confirmation does not match the room id.")
    ok, message = store.loesche(raeume.sammlung(room))
    keyword_index.delete_document_by_raum(room)
    _n, failed = owncloud.leere_raumordner(room)
    return ok, message, len(failed or [])
