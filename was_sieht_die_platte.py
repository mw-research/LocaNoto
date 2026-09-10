"""Was liest jemand, der die Platte hat -- aber nicht den Schluessel?

Die ehrliche Antwort auf "ist das jetzt verschluesselt?". Das Skript tut,
was ein Finder taete: es geht ueber das Datenverzeichnis, ohne die
Anwendung zu benutzen und ohne den Installationsschluessel, und sagt je
Bestandteil, was daraus zu holen ist.

    python was_sieht_die_platte.py [DATENVERZEICHNIS]

Es gibt KEINE Inhalte aus -- nur Kategorie, Zahl und Beispielumfang. Was
auf dem Bildschirm landet, darf weitergegeben werden.
"""
import glob
import os
import re
import sqlite3
import sys

WURZEL = sys.argv[1] if len(sys.argv) > 1 else None
if WURZEL is None:
    import paths
    WURZEL = paths.DATA_DIR

# Endungen, die als Originaldokument zaehlen.
DOKUMENTE = (".pdf", ".docx", ".doc", ".md", ".txt", ".xlsx", ".xlsm",
             ".csv", ".pptx")


def groesse(pfad):
    n = 0
    for w, _u, dateien in os.walk(pfad):
        for d in dateien:
            try:
                n += os.path.getsize(os.path.join(w, d))
            except OSError:
                pass
    return n


def zeile(was, lesbar, angabe, rat=""):
    marke = "LESBAR  " if lesbar else "verdeckt"
    print(f"  [{marke}] {was}")
    print(f"             {angabe}")
    if rat:
        print(f"             -> {rat}")


print("=" * 70)
print(f"WAS SIEHT JEMAND MIT DER PLATTE?   {WURZEL}")
print("=" * 70)
if not os.path.isdir(WURZEL):
    print("Verzeichnis nicht gefunden.")
    sys.exit(2)

# --- 1. Die Originaldokumente ---
docs = os.path.join(WURZEL, "dokumente")
anzahl = 0
if os.path.isdir(docs):
    for w, _u, dateien in os.walk(docs):
        anzahl += sum(1 for d in dateien if d.lower().endswith(DOKUMENTE))
zeile("Originaldokumente", anzahl > 0,
      f"{anzahl} Dateien, {groesse(docs) / 1e6:.1f} MB -- vollstaendig "
      f"lesbar, es sind gewoehnliche PDFs und Tabellen.",
      "Nur ein verschluesselter Datentraeger hilft. Die Anwendung kann "
      "sie nicht verschluesseln: der Ingest liest sie, die "
      "Quellenansicht zeigt sie, und ownCloud legt sie dort ab."
      if anzahl else "")

# --- 2. Der Stichwortindex ---
gefunden = glob.glob(os.path.join(WURZEL, "**", "keyword_index.sqlite3"),
                     recursive=True)
if gefunden:
    n, beispiel = 0, 0
    try:
        con = sqlite3.connect("file:" + gefunden[0] + "?mode=ro", uri=True)
        n = con.execute("SELECT count(*) FROM chunks").fetchone()[0]
        beispiel = len(con.execute(
            "SELECT text FROM chunks LIMIT 1").fetchone()[0] or "")
        con.close()
    except Exception as e:
        beispiel = -1
        print(f"      (Index nicht lesbar: {e})")
    zeile("Stichwortindex (FTS5)", True,
          f"{n} Abschnitte im KLARTEXT, erster rund {beispiel} Zeichen. "
          f"Er liegt hier, weil LOCANOTO_INDEX nicht gesetzt ist.",
          "LOCANOTO_INDEX auf einen containerlokalen Pfad setzen. Der "
          "Index ist ableitbar und baut sich in Sekunden neu auf.")
else:
    zeile("Stichwortindex (FTS5)", False,
          "Nicht in diesem Verzeichnis -- LOCANOTO_INDEX zeigt woandershin. "
          "Richtig so: er traegt den Text im Klartext.")

# --- 3. Die Vektordatenbank ---
chroma = glob.glob(os.path.join(WURZEL, "**", "chroma.sqlite3"),
                   recursive=True)
if chroma:
    verschluesselt = klar = 0
    namen = set()
    try:
        con = sqlite3.connect("file:" + chroma[0] + "?mode=ro", uri=True)
        for (wert,) in con.execute(
                "SELECT string_value FROM embedding_metadata "
                "WHERE string_value IS NOT NULL LIMIT 4000"):
            if not isinstance(wert, str):
                continue
            if wert.startswith("LNX1:"):
                verschluesselt += 1
            elif len(wert) > 120:
                klar += 1
            elif re.search(r"\.(pdf|docx?|xlsx?|md|txt)$", wert, re.I):
                namen.add(wert)
        con.close()
    except Exception as e:
        print(f"      (Chroma nicht lesbar: {e})")
    zeile("Abschnittstexte in Chroma", klar > 0,
          f"{verschluesselt} verschluesselt, {klar} im Klartext "
          f"(Stichprobe von 4000 Feldern).",
          "Der Altbestand ist noch nicht verschluesselt." if klar else "")
    zeile("Dateinamen in den Metadaten", bool(namen),
          f"{len(namen)} verschiedene, im Klartext. Ein Name wie "
          f"'Kuendigung_Mueller_2026.pdf' verraet den Vorgang, ohne dass "
          f"jemand die Datei oeffnet.",
          "Noch nicht verschluesselt -- sie dienen als Filter in der "
          "Suche." if namen else "")
    zeile("Vektoren", True,
          "Lesbar und nicht verschluesselbar -- sonst gibt es keine "
          "Aehnlichkeitssuche.",
          "Aus ihnen laesst sich mit demselben Modell ein guter Teil des "
          "Textes rekonstruieren.")

# --- 4. Chats und Rueckmeldungen ---
chats = os.path.join(WURZEL, "chats")
zahl_v = zahl_k = 0
for w, _u, dateien in os.walk(chats):
    for d in dateien:
        try:
            with open(os.path.join(w, d), "rb") as f:
                if f.read(4) == b"LNC1":
                    zahl_v += 1
                else:
                    zahl_k += 1
        except OSError:
            pass
if zahl_v or zahl_k:
    zeile("Chatverlaeufe", zahl_k > 0,
          f"{zahl_v} verschluesselt, {zahl_k} im Klartext.",
          "Alte Verlaeufe von vor der Umstellung." if zahl_k else "")

fb = os.path.join(WURZEL, "feedback.jsonl")
if os.path.exists(fb):
    offen = 0
    with open(fb, encoding="utf-8", errors="replace") as f:
        offen = sum(1 for z in f if z.strip().startswith("{"))
    zeile("Rueckmeldungen", offen > 0,
          f"{offen} Zeilen im Klartext." if offen else
          "Alle verschluesselt.",
          "In der Seitenleiste neu verschluesseln." if offen else "")

# --- 4b. Die Abzuege ---
#
# Der blinde Fleck, der beim ersten Bau fehlte: ein Abzug enthaelt den
# Text so, wie er in der Sammlung stand. Vor der Umstellung war das
# Klartext -- und er liegt unter data/sicherungen, also GENAU DORT, wo
# ein Kopierer als Erstes hinsieht. Eine verschluesselte Sammlung neben
# einem Abzug im Klartext ist keine verschluesselte Sammlung.
sich = os.path.join(WURZEL, "sicherungen")
if os.path.isdir(sich):
    klar_abz, verschl_abz, alt = 0, 0, []
    for name in sorted(os.listdir(sich)):
        ordner = os.path.join(sich, name)
        if not os.path.isdir(ordner):
            continue
        offen = 0
        for d in os.listdir(ordner):
            if not d.endswith(".jsonl"):
                continue
            try:
                with open(os.path.join(ordner, d), encoding="utf-8",
                          errors="replace") as f:
                    for i, z in enumerate(f):
                        if i > 50:
                            break
                        if '"text": "LNX1:' in z:
                            verschl_abz += 1
                        elif '"text": "' in z:
                            offen += 1
            except OSError:
                pass
        if offen:
            klar_abz += offen
            alt.append(name)
    if klar_abz:
        zeile("Abzuege der Vektordatenbank", True,
              f"{len(alt)} Abzug/Abzuege enthalten Text im KLARTEXT "
              f"({', '.join(alt[:3])}). Sie stammen von vor der "
              f"Umstellung.",
              "Nach dem Nachverschluesseln einen frischen Abzug ziehen "
              "und die alten loeschen -- sonst liegt der Klartext weiter "
              "hier.")
    elif verschl_abz:
        zeile("Abzuege der Vektordatenbank", False,
              "Vorhanden und verschluesselt.")

# --- 5. Was NICHT hier liegt ---
print()
print("  Nicht in diesem Verzeichnis, und das ist der Sinn:")
print("     Installationsschluessel und Raumschluessel liegen unter")
print("     LOCANOTO_KONFIG -- einem anderen Volume. Der Abzug nimmt sie")
print("     nicht mit. Am dichtesten ist LOCANOTO_SCHLUESSEL als Secret:")
print("     dann liegen sie auf gar keiner Platte.")
print()
print("=" * 70)
print("FAZIT")
print("=" * 70)
print("  Die Anwendung kann verdecken, was sie selbst schreibt:")
print("  Abschnittstexte, Chats, Rueckmeldungen.")
print()
print("  Sie kann NICHT verdecken, was sie lesen koennen muss:")
print("  die Originaldokumente, die Vektoren und den Stichwortindex.")
print()
print("  Wer die Platte hat, liest also die Dokumente -- es sei denn,")
print("  der Datentraeger selbst ist verschluesselt. Ein LUKS- oder")
print("  dm-crypt-Volume ist deshalb keine Ergaenzung, sondern die")
print("  Grundlage. Alles hier oben ist die zweite Schicht darueber.")
