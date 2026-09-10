"""Plattenbasierter Keyword-Index auf SQLite FTS5.

Ersetzt den In-Memory-BM25 (rank_bm25). Der hielt den gesamten Korpus im
Arbeitsspeicher und legte pro Chunk ein dict in BM25Okapi.doc_freqs an --
bei rund 324.000 Chunks (Hochrechnung fuer 1,6 GB PDF) sind das 8-15 GB RAM,
die bei jedem Start neu aufgebaut werden muessen.

FTS5 liegt auf der Platte, wird beim Ingest geschrieben und live abgefragt.
Damit entfaellt zugleich der Cache-Invalidierungsfehler: der alte Index war
mit @st.cache_resource eingefroren, sodass frisch hochgeladene Dokumente bis
zum Neustart nicht keyword-suchbar waren und geloeschte weiterhin
auftauchten.

Kein Stemming -- genau wie der bisherige Tokenizer re.findall(r'\w+'), also
keine Regression. Fuer deutsche Komposita gleicht die Praefix-Suche das
teilweise aus ("Toleranz*" findet "Toleranzen", "Toleranzangaben").
"""
import os
import re
import sqlite3

import paths

# INDEX_DIR und nicht DATA_DIR: eine SQLite-Datei braucht ein echtes
# Dateisystem. Ueber NFS oder SMB funktioniert der WAL-Betrieb nicht --
# SQLite braucht dafuer gemeinsamen Speicher im selben Dateisystem -- und
# die Dateisperren sind unzuverlaessig. Ein PersistentVolume auf
# Blockspeicher traegt sie dagegen einwandfrei, und dort gehoert sie hin:
# persistent, aber keine Freigabe.
#
# Der Neuaufbau aus den Sammlungen kostet gemessen rund 17 Sekunden bei
# 324.000 Abschnitten -- diese Datei allein waere also ersetzbar. Die
# Vektordatenbank daneben ist es nicht.
# LOCANOTO_STICHWORTINDEX trennt diese Datei von LOCANOTO_INDEX, und der
# Grund ist ein Zielkonflikt, der sonst unaufloesbar ist:
#
#   * Diese Datei traegt den Text im KLARTEXT -- FTS5 kann nicht anders.
#     Sie gehoert damit NICHT auf das Datenvolume, sonst liegt der
#     Klartext neben der verschluesselten Sammlung und die ganze
#     Verschluesselung ist Zierde.
#   * Die Vektordatenbank daneben ist NICHT ableitbar. Sie vom
#     Datenvolume zu nehmen heisst, dass ein verlorenes Volume Stunden
#     GPU-Zeit kostet.
#
# Unter einer gemeinsamen Variable muesste man sich fuer eines von
# beidem entscheiden. Mit zwei Variablen wandert nur diese Datei -- und
# sie darf wandern: der Neuaufbau aus den Sammlungen kostet gemessen
# rund 17 Sekunden bei 324.000 Abschnitten.
#
# Ohne Angabe bleibt alles, wo es war.
STICHWORT_DIR = (os.getenv("LOCANOTO_STICHWORTINDEX", "").strip()
                 or paths.INDEX_DIR)
try:
    os.makedirs(STICHWORT_DIR, exist_ok=True)
except OSError:
    pass
DB_PATH = os.path.join(STICHWORT_DIR, "keyword_index.sqlite3")

# Ab dieser Laenge wird ein Suchbegriff als Praefix gesucht. Kuerzere Begriffe
# ergaeben zu unspezifische Treffer ("der*", "und*").
_PREFIX_MIN_LEN = 5

_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
    chunk_id  UNINDEXED,
    file_name UNINDEXED,
    page      UNINDEXED,
    access    UNINDEXED,
    owner     UNINDEXED,
    folder    UNINDEXED,
    doc_type  UNINDEXED,
    raum      UNINDEXED,
    text,
    tokenize = "unicode61 remove_diacritics 2"
);
"""

# Spalten, die ein aktuelles Schema haben muss. Eine FTS5-Tabelle laesst
# sich nicht per ALTER TABLE erweitern, also wird sie bei Bedarf neu
# aufgebaut -- verlustfrei, weil der Index vollstaendig aus den Sammlungen
# ableitbar ist.
_SPALTEN = ("chunk_id", "file_name", "page", "access", "owner", "folder",
            "doc_type", "raum", "text")


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    # WAL: Leser blockieren einander und den Schreiber nicht.
    con.execute("PRAGMA journal_mode=WAL")
    # Ohne Wartezeit bricht ein gleichzeitiger Schreibzugriff sofort mit
    # "database is locked" ab, statt kurz zu warten. Sobald neben der
    # Oberflaeche ein zweiter Prozess arbeitet -- die Schnittstelle, ein
    # laufender Ingest --, trifft das sonst irgendwann zu.
    con.execute("PRAGMA busy_timeout=5000")
    con.executescript(_SCHEMA)
    return con


def journal_modus(con=None):
    """Welcher Journalmodus tatsaechlich gilt.

    PRAGMA journal_mode=WAL schlaegt nicht fehl, wenn das Dateisystem es
    nicht kann -- SQLite bleibt dann still beim alten Modus. Genau das
    passiert auf einem Netzlaufwerk. Ohne Rueckfrage merkt es niemand, und
    die Anwendung laeuft langsamer und empfindlicher als gedacht.
    """
    own = con is None
    con = con or connect()
    try:
        return (con.execute("PRAGMA journal_mode").fetchone() or ["?"])[0]
    except sqlite3.Error:
        return "?"
    finally:
        if own:
            con.close()


def schema_aktuell(con=None):
    """Hat die Tabelle die Raumspalte?

    Ein Index aus der Zeit vor den Raeumen hat sie nicht. Er ist dann nicht
    kaputt, aber er kann nicht nach Raum filtern -- und ein Stichworttreffer
    ohne Raumfilter waere genau das Leck, das die Raeume schliessen sollen.
    """
    own = con is None
    con = con or connect()
    try:
        vorhanden = {r[1] for r in con.execute("PRAGMA table_info(chunks)")}
        return "raum" in vorhanden
    except sqlite3.Error:
        return False
    finally:
        if own:
            con.close()


def passt_zu(paare, con=None):
    """(passt, im_index, in_sammlungen).

    Ein Vergleich der Anzahlen, kein Abgleich Abschnitt fuer Abschnitt --
    der waere teuer und muesste den ganzen Bestand lesen. Die Anzahl
    genuegt fuer die Frage, die hier zaehlt: hat ein anderer Prozess in die
    Sammlungen geschrieben, ohne diesen Index zu erreichen?

    Das ist kein erfundener Fall. Laeuft der Ingest als eigener Job -- in
    Kubernetes ein CronJob, im Container ein abgekoppelter Lauf --, dann
    fuellt er die Sammlungen ueber den Chroma-Dienst, aber der
    Stichwortindex liegt an einer anderen Stelle. Ohne diese Pruefung
    fehlen dessen Treffer, bis jemand neu startet, und niemand sieht
    warum: die Vektorsuche antwortet ja.
    """
    own = con is None
    con = con or connect()
    try:
        im_index = count(con)
    finally:
        if own:
            con.close()
    in_sammlungen = 0
    for _kennung, sml in paare:
        try:
            in_sammlungen += sml.count()
        except Exception:
            # Eine Sammlung, die gerade nicht antwortet, darf keinen
            # Neuaufbau ausloesen -- das waere ein Neuaufbau bei jedem
            # Wackler.
            return True, im_index, im_index
    return im_index == in_sammlungen, im_index, in_sammlungen


def neu_anlegen(con=None):
    """Verwirft die Tabelle und legt sie mit aktuellem Schema an."""
    own = con is None
    con = con or connect()
    try:
        con.execute("DROP TABLE IF EXISTS chunks")
        con.executescript(_SCHEMA)
        con.commit()
    finally:
        if own:
            con.close()


def count(con=None):
    own = con is None
    con = con or connect()
    try:
        return con.execute("SELECT count(*) FROM chunks").fetchone()[0]
    finally:
        if own:
            con.close()


def add_chunks(rows, con=None):
    """rows: Iterable von (chunk_id, text, metadata-dict)."""
    own = con is None
    con = con or connect()
    try:
        payload = []
        for chunk_id, text, meta in rows:
            meta = meta or {}
            payload.append((
                chunk_id,
                meta.get("file_name", ""),
                str(meta.get("page", "")),
                meta.get("access", "shared"),
                meta.get("owner", ""),
                meta.get("folder", ""),
                meta.get("type", ""),
                meta.get("raum", ""),
                text or "",
            ))
        if not payload:
            return 0
        con.executemany(
            "INSERT INTO chunks (chunk_id, file_name, page, access, owner, "
            "folder, doc_type, raum, text) VALUES (?,?,?,?,?,?,?,?,?)", payload)
        con.commit()
        return len(payload)
    finally:
        if own:
            con.close()


def delete_document(file_name, access=None, owner=None, con=None, raum=None):
    """Entfernt Eintraege eines Dokuments. Spiegelt die Filter der
    Chroma-Loeschung, damit beide Indizes deckungsgleich bleiben."""
    own = con is None
    con = con or connect()
    try:
        sql = "DELETE FROM chunks WHERE file_name = ?"
        args = [file_name]
        if access is not None:
            sql += " AND access = ?"
            args.append(access)
        if owner is not None:
            sql += " AND owner = ?"
            args.append(owner)
        if raum is not None:
            sql += " AND raum = ?"
            args.append(raum)
        con.execute(sql, args)
        con.commit()
    finally:
        if own:
            con.close()


def delete_document_by_raum(raum, con=None):
    """Entfernt alle Eintraege eines Raums.

    Gegenstueck zum Loeschen einer Sammlung: bliebe der Stichwortindex
    stehen, wuerden Treffer auf Abschnitte zeigen, die es nicht mehr gibt --
    mit Text, denn den haelt diese Tabelle selbst.
    """
    own = con is None
    con = con or connect()
    try:
        con.execute("DELETE FROM chunks WHERE raum = ?", (raum,))
        con.commit()
    finally:
        if own:
            con.close()


def set_access(file_name, owner, new_access, con=None):
    """Haelt den Index nach einer Freigabe aktuell."""
    own = con is None
    con = con or connect()
    try:
        con.execute("UPDATE chunks SET access = ? WHERE file_name = ? AND owner = ?",
                    (new_access, file_name, owner))
        con.commit()
    finally:
        if own:
            con.close()


def build_match_query(text):
    """Baut aus freiem Text einen sicheren FTS5-MATCH-Ausdruck.

    Jeder Begriff wird in Anfuehrungszeichen gesetzt, damit FTS5-Operatoren
    im Nutzertext (AND, OR, NOT, NEAR, *, ^, :) nicht als Syntax gedeutet
    werden und keine Fehler ausloesen.
    """
    terms = re.findall(r"\w+", text.lower(), flags=re.UNICODE)
    if not terms:
        return None
    parts = []
    for t in terms:
        if len(t) >= _PREFIX_MIN_LEN:
            parts.append('"%s"*' % t.replace('"', ""))
        else:
            parts.append('"%s"' % t.replace('"', ""))
    return " OR ".join(parts)


def search(query_text, username, limit=5, file_names=None,
           con=None, raeume=None):
    """BM25-gerankte Keyword-Suche mit Rechtefilter.

    Der Rechtefilter laeuft in SQL statt nachtraeglich in Python. Dort war
    er auf meta.get('access', 'shared') angewiesen -- Chunks ohne
    access-Key galten damit als oeffentlich.

    Mit raeume wird nach Raum gefiltert, ohne nach access/owner. Ein
    Abschnitt ohne Raum faellt dann heraus, statt als oeffentlich zu
    gelten: bei einer unfertigen Umsortierung fehlen lieber Treffer, als
    dass fremde erscheinen.
    """
    match = build_match_query(query_text)
    if not match:
        return []

    own = con is None
    con = con or connect()
    try:
        sql = ["SELECT chunk_id, file_name, page, access, owner, folder, "
               "doc_type, text, bm25(chunks) AS score, raum FROM chunks "
               "WHERE chunks MATCH ?"]
        args = [match]
        if raeume is None:
            sql.append("AND (access = 'shared' OR owner = ?)")
            args.append(username)
        elif raeume:
            sql.append("AND raum IN (%s)" % ",".join("?" * len(raeume)))
            args.extend(raeume)
        else:
            # Keine Raeume heisst kein Zugang, nicht kein Filter.
            return []

        if file_names:
            sql.append("AND file_name IN (%s)" % ",".join("?" * len(file_names)))
            args.extend(file_names)

        # bm25() liefert negative Werte, kleiner ist besser.
        sql.append("ORDER BY score LIMIT ?")
        args.append(limit)

        out = []
        for r in con.execute(" ".join(sql), args):
            out.append({
                "chunk_id": r[0],
                "text": r[7],
                "score": r[8],
                "meta": {"file_name": r[1], "page": _as_int(r[2]),
                         "access": r[3], "owner": r[4],
                         "folder": r[5], "type": r[6], "raum": r[9]},
            })
        return out
    except sqlite3.OperationalError:
        # Unbrauchbarer MATCH-Ausdruck -- lieber keine Keyword-Treffer als
        # eine gescheiterte Anfrage. Die Vektorsuche laeuft weiter.
        return []
    finally:
        if own:
            con.close()


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


def rebuild_from_raeume(paare, batch_size=5000, progress=None):
    """Baut den Index aus mehreren Raum-Sammlungen neu auf.

    paare: Iterable von (raumkennung, sammlung). Der Raum kommt aus dem
    Paar und nicht aus den Metadaten des Abschnitts -- die Sammlung, in der
    ein Abschnitt liegt, ist die Wahrheit; ein abweichender Metadateneintrag
    waere ein Fehler und darf den Index nicht in die Irre fuehren.
    """
    con = connect()
    try:
        neu_anlegen(con)
        gesamt = 0
        for kennung, sml in paare:
            if sml is None:
                continue
            total = sml.count()
            done = 0
            while done < total:
                batch = sml.get(include=["documents", "metadatas"],
                                limit=batch_size, offset=done)
                ids = batch.get("ids") or []
                if not ids:
                    break
                # Aufschliessen: der Stichwortindex braucht Klartext,
                # er ist ableitbar und liegt containerlokal. Genau
                # deshalb darf LOCANOTO_INDEX nicht auf das Datenvolume
                # zeigen -- sonst laege der Klartext neben dem
                # Verschluesselten und das Ganze waere Theater.
                import store as _s
                # wartung=True: der Aufbau liest den ganzen Bestand,
                # das ist seine Aufgabe. Auf das Entnahmebudget
                # angerechnet, koennte die Anwendung mit einem echten
                # Bestand nicht mehr starten -- der Aufbau laeuft beim
                # Start und uebersteigt jede sinnvolle Schwelle. Das
                # Protokoll bekommt ihn trotzdem.
                dokumente = _s.klartext(kennung,
                                        batch.get("documents") or [],
                                        benutzer="aufbau", wartung=True)
                metas = batch.get("metadatas") or []
                zeilen = []
                for i, kennung_chunk in enumerate(ids):
                    meta = dict(metas[i] if i < len(metas) else {})
                    meta["raum"] = kennung
                    zeilen.append((kennung_chunk,
                                   dokumente[i] if i < len(dokumente) else "",
                                   meta))
                add_chunks(zeilen, con=con)
                done += len(ids)
                gesamt += len(ids)
                if progress:
                    progress(kennung, done, total)
        return gesamt
    finally:
        con.close()
