"""Listen aus Tabellendateien -- Katalog und Abfrage.

Bestandslisten, Preislisten, Stuecklisten: solche Dateien gehoeren nicht in
die Vektordatenbank. Eine Liste mit 50.000 Zeilen zeilenweise zu
vektorisieren kostet Stunden Modellzeit, ist beim naechsten Export veraltet,
und semantische Aehnlichkeit ist bei Teilenummern und Mengen ohnehin das
falsche Werkzeug.

Stattdessen dasselbe Vorgehen wie bei der Datenbank: erst entscheiden, WO
die Antwort stehen koennte, dann dort gezielt nachsehen.

Der Katalog
-----------
Beim Einlesen wird je Datei und Blatt mechanisch erfasst, was darin steht:
Spaltennamen, Datentypen, Zeilenzahl, und bei Spalten mit wenigen
verschiedenen Werten deren Liste. Der letzte Teil ist der wichtigste -- eine
Spalte "Status" sagt wenig, "Status: frei, gesperrt, ausgebucht" sagt alles.
Kein Modell noetig, in Sekunden erledigt.

Die Daten
---------
Der Katalog haelt nur die Struktur. Die Zeilen werden bei jeder Frage frisch
aus der Datei gelesen, zwischengespeichert nur solange Aenderungsdatum und
Groesse gleich bleiben. Neue oder geaenderte Zeilen wirken damit sofort; der
Katalog muss nur neu aufgebaut werden, wenn sich Spalten aendern.

Die Abfrage
-----------
Das gewaehlte Blatt kommt in eine SQLite-Datenbank im Arbeitsspeicher, und
das Sprachmodell formuliert ein SELECT darauf. Geprueft wird es mit
derselben Kette wie eine Abfrage an den SQL-Server (sqlpruefung.py). Es wird
kein erzeugter Code ausgefuehrt.
"""
import json
import os
import re
import sqlite3

import paths
import sqlpruefung

# Wo der Ordner liegt, steht an drei Stellen -- in dieser Reihenfolge:
#
#   1. config/tabellen_pfad.txt   in der Oberflaeche eingetragen
#   2. TABELLEN_PFAD              in der .env
#   3. data/tabellen              Vorgabe
#
# Der Weg ueber die Oberflaeche ist der praktische: Dateien in einen Ordner
# zu kopieren, den die Fachabteilung ohnehin pflegt, ist doppelte Arbeit.
# Erreichbar ist dabei nur, was jemand vorher in den Container eingehaengt
# hat -- und der Katalog liest ausschliesslich Tabellendateien.
PFAD_DATEI = os.path.join(paths.CONFIG_DIR, "tabellen_pfad.txt")

# Der Katalog liegt bewusst NICHT beim Ordner: der kann ausserhalb und nur
# lesbar eingehaengt sein, etwa ein Netzlaufwerk der Firma.
KATALOG = os.path.join(paths.DATA_DIR, "tabellen_katalog.json")

# Obergrenze fuer die Zahl der durchsuchten Dateien. Ein versehentlich
# eingetragenes "/" wuerde sonst den ganzen Container durchlaufen.
MAX_DATEIEN = paths.env_int("TABELLEN_MAX_DATEIEN", 500)


def pfad():
    """Der Ordner, in dem die Listen liegen."""
    try:
        with open(PFAD_DATEI, "r", encoding="utf-8") as f:
            eigen = f.read().strip()
        if eigen:
            return eigen
    except OSError:
        pass
    return paths.TABELLEN_DIR


def pruefe_pfad(p):
    """(ok, meldung) fuer einen eingetragenen Ordner."""
    p = (p or "").strip()
    if not p:
        return True, "Zurueck auf die Vorgabe."
    if not os.path.isabs(p):
        return False, ("Bitte einen vollstaendigen Pfad angeben, wie er im "
                       "Container gilt -- etwa /listen.")
    if not os.path.exists(p):
        return False, (f"'{p}' gibt es im Container nicht. Ist das "
                       f"Verzeichnis eingehaengt? Siehe README, Abschnitt "
                       f"Listen.")
    if not os.path.isdir(p):
        return False, f"'{p}' ist eine Datei, kein Ordner."
    if not os.access(p, os.R_OK):
        return False, f"'{p}' ist nicht lesbar."
    return True, "Verknuepft."


def setze_pfad(p):
    """Legt den Ordner fest. (ok, meldung)."""
    ok, meldung = pruefe_pfad(p)
    if not ok:
        return False, meldung
    try:
        os.makedirs(paths.CONFIG_DIR, exist_ok=True)
        vorlaeufig = PFAD_DATEI + ".neu"
        with open(vorlaeufig, "w", encoding="utf-8", newline="\n") as f:
            f.write((p or "").strip())
        os.replace(vorlaeufig, PFAD_DATEI)
    except OSError as e:
        return False, f"Konnte nicht gespeichert werden: {e}"
    _zwischenspeicher.clear()
    return True, meldung

ENDUNGEN = (".xlsx", ".xlsm", ".csv", ".tsv")

# Ab dieser Zeilenzahl gilt ein Blatt als gross. Solche Blaetter stehen im
# Katalog, werden aber nur abgefragt, wenn der Nutzer sie ausdruecklich
# einbezieht -- das Laden dauert dann spuerbar.
GROSS_AB = paths.env_int("TABELLEN_GROSS_AB", 50_000)

# Wie viele verschiedene Werte je Spalte in den Katalog kommen, und bis zu
# welcher Vielfalt ueberhaupt. Beispielwerte sind der nuetzlichste Teil des
# Katalogs und zugleich der einzige, der echte Daten in den Prompt traegt.
BEISPIELE_MAX = paths.env_int("TABELLEN_BEISPIELE", 12)
BEISPIELE_BIS = paths.env_int("TABELLEN_BEISPIELE_BIS", 25)

# Obergrenze fuer den Katalog im Prompt. Ein Ordner mit hundert Dateien
# wuerde sonst den Platz fuellen, der fuer die Dokumente gebraucht wird.
KATALOG_MAX_CHARS = paths.env_int("TABELLEN_KATALOG_MAX_CHARS", 12_000)

MAX_ZEILEN = paths.env_int("TABELLEN_MAX_ZEILEN", 200)

MARKER_KEINE_ABFRAGE = "KEINE_ABFRAGE"

_zwischenspeicher = {}


# --- SPALTENNAMEN ---

def sicherer_name(name, vergeben):
    """Ein Spaltenname, den SQLite ohne Anfuehrungszeichen versteht.

    Echte Tabellenkoepfe enthalten Leerzeichen, Umlaute, Klammern und
    Zeilenumbrueche. Sie in der Abfrage zu zitieren waere moeglich, aber das
    Sprachmodell vergisst die Anfuehrungszeichen zuverlaessig -- und ein
    Syntaxfehler ist eine schlechtere Antwort als ein umbenannter Kopf.
    Der Originalname steht im Katalog daneben, damit die Antwort ihn nennen
    kann.
    """
    k = str(name).strip().lower()
    for alt, neu in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        k = k.replace(alt, neu)
    k = re.sub(r"[^0-9a-z]+", "_", k).strip("_")
    if not k or k[0].isdigit():
        k = "s_" + k
    grund, n = k, 2
    while k in vergeben:
        k = f"{grund}_{n}"
        n += 1
    return k


# --- EINLESEN ---

def _blaetter(pfad):
    """(blattname, dataframe) je Blatt einer Datei."""
    import pandas as pd

    endung = os.path.splitext(pfad)[1].lower()
    if endung in (".csv", ".tsv"):
        trenner = "\t" if endung == ".tsv" else None
        # sep=None laesst pandas den Trenner erkennen -- deutsche Exporte
        # verwenden haeufig das Semikolon.
        yield "", pd.read_csv(pfad, sep=trenner, engine="python",
                              dtype=str, keep_default_na=False)
        return

    mappe = pd.ExcelFile(pfad)
    for blatt in mappe.sheet_names:
        yield blatt, mappe.parse(blatt, dtype=str, keep_default_na=False)


def _spaltenangaben(rahmen):
    """Spalten mit Originalnamen, sicherem Namen und Beispielwerten."""
    angaben, vergeben = [], set()
    for spalte in rahmen.columns:
        sicher = sicherer_name(spalte, vergeben)
        vergeben.add(sicher)
        eintrag = {"name": str(spalte).strip(), "feld": sicher}
        werte = rahmen[spalte].astype(str).str.strip()
        werte = werte[werte != ""]
        verschieden = werte.unique()
        if 0 < len(verschieden) <= BEISPIELE_BIS:
            eintrag["werte"] = [str(w)[:60] for w in verschieden[:BEISPIELE_MAX]]
        elif len(verschieden):
            eintrag["beispiel"] = str(verschieden[0])[:60]
        angaben.append(eintrag)
    return angaben


def baue_katalog():
    """Liest den Ordner neu ein und legt den Katalog an.

    Rueckgabe: (katalog, fehler). fehler ist eine Liste aus (datei, grund) --
    eine unlesbare Datei soll den Katalog nicht verhindern, aber auch nicht
    stillschweigend fehlen.
    """
    ordner = pfad()
    try:
        os.makedirs(ordner, exist_ok=True)
    except OSError:
        pass
    eintraege, fehler = [], []
    if not os.path.isdir(ordner):
        fehler.append((ordner, "Ordner nicht erreichbar"))

    gesehen = 0
    for wurzel, _, dateien in os.walk(ordner):
        for name in sorted(dateien):
            if not name.lower().endswith(ENDUNGEN) or name.startswith("~$"):
                continue
            gesehen += 1
            if gesehen > MAX_DATEIEN:
                fehler.append((ordner, f"Mehr als {MAX_DATEIEN} Dateien -- "
                                       f"abgebrochen. Zeigt der Pfad auf das "
                                       f"richtige Verzeichnis?"))
                break
            datei_pfad = os.path.join(wurzel, name)
            rel = os.path.relpath(datei_pfad, ordner).replace("\\", "/")
            try:
                for blatt, rahmen in _blaetter(datei_pfad):
                    eintraege.append({
                        "datei": rel,
                        "blatt": blatt,
                        "zeilen": int(len(rahmen)),
                        "gross": len(rahmen) >= GROSS_AB,
                        "spalten": _spaltenangaben(rahmen),
                        "groesse": os.path.getsize(datei_pfad),
                        "geaendert": int(os.path.getmtime(datei_pfad)),
                    })
            except Exception as e:
                fehler.append((rel, f"{type(e).__name__}: {e}"))
        if gesehen > MAX_DATEIEN:
            break

    katalog = {"eintraege": eintraege, "fehler": fehler}
    try:
        os.makedirs(os.path.dirname(KATALOG), exist_ok=True)
        vorlaeufig = KATALOG + ".neu"
        with open(vorlaeufig, "w", encoding="utf-8") as f:
            json.dump(katalog, f, indent=1, ensure_ascii=False)
        os.replace(vorlaeufig, KATALOG)
    except OSError:
        pass
    return katalog, fehler


def lies_katalog():
    """Der abgelegte Katalog, oder ein leerer."""
    try:
        with open(KATALOG, "r", encoding="utf-8") as f:
            k = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"eintraege": [], "fehler": []}
    return k if isinstance(k, dict) else {"eintraege": [], "fehler": []}


def vorhanden():
    """Liegt ueberhaupt eine Tabellendatei im Ordner?"""
    ordner = pfad()
    if not os.path.isdir(ordner):
        return False
    for _, _, dateien in os.walk(ordner):
        if any(d.lower().endswith(ENDUNGEN) and not d.startswith("~$")
               for d in dateien):
            return True
    return False


def bereiche(eintraege):
    """Die Unterordner, in denen Listen liegen.

    Ein Bereich ist der oberste Unterordner unter dem Listenordner --
    "einkauf/preise.xlsx" gehoert zu "einkauf". Damit lassen sich Listen
    genauso eingrenzen wie Dokumente ueber ihr Sachgebiet, ohne dass
    irgendwo ein Pfad eingegeben werden muss.
    """
    gefunden = set()
    for e in eintraege:
        teil, _, rest = e.get("datei", "").partition("/")
        gefunden.add(teil if rest else "(Basis)")
    return sorted(gefunden)


def im_bereich(eintrag, gewaehlt):
    """Gehoert ein Eintrag zu einem der gewaehlten Bereiche?"""
    if not gewaehlt:
        return True
    teil, _, rest = eintrag.get("datei", "").partition("/")
    return (teil if rest else "(Basis)") in gewaehlt


# --- KATALOG FUER DEN PROMPT ---

def als_text(eintraege):
    """Der Katalog in der Form, die das Sprachmodell liest."""
    zeilen = []
    for e in eintraege:
        kennung = e["datei"] + (f"#{e['blatt']}" if e["blatt"] else "")
        zeilen.append(f'BLATT {kennung}  ({e["zeilen"]} Zeilen)')
        for s in e["spalten"]:
            teil = f'  {s["feld"]}'
            if s["name"].lower() != s["feld"]:
                teil += f'  [{s["name"]}]'
            if s.get("werte"):
                teil += "  Werte: " + ", ".join(s["werte"])
            elif s.get("beispiel"):
                teil += f'  z.B. {s["beispiel"]}'
            zeilen.append(teil)
        zeilen.append("")

    text = "\n".join(zeilen)
    if len(text) > KATALOG_MAX_CHARS:
        text = (text[:KATALOG_MAX_CHARS] +
                "\n-- gekuerzt. Mit TABELLEN_KATALOG_MAX_CHARS erweitern oder "
                "weniger Dateien ablegen.")
    return text


# --- DATEN LADEN UND ABFRAGEN ---

def _lade(datei, blatt):
    """Ein Blatt als SQLite-Verbindung im Arbeitsspeicher.

    Zwischengespeichert ueber Aenderungsdatum und Groesse: solange die Datei
    unveraendert ist, wird sie nicht erneut gelesen. Wird sie ersetzt --
    ein neuer Export --, faellt der Eintrag weg und die naechste Frage sieht
    die neuen Zeilen.
    """
    import pandas as pd

    voll = os.path.join(pfad(), datei)
    if not os.path.isfile(voll):
        raise ValueError(f"Datei nicht gefunden: {datei}")
    kennung = (voll, blatt, os.path.getmtime(voll), os.path.getsize(voll))
    if kennung in _zwischenspeicher:
        return _zwischenspeicher[kennung]

    rahmen = None
    for name, r in _blaetter(voll):
        if name == blatt or not blatt:
            rahmen = r
            break
    if rahmen is None:
        raise ValueError(f"Blatt nicht gefunden: {blatt}")

    vergeben = set()
    namen = []
    for spalte in rahmen.columns:
        s = sicherer_name(spalte, vergeben)
        vergeben.add(s)
        namen.append(s)
    rahmen = rahmen.copy()
    rahmen.columns = namen

    con = sqlite3.connect(":memory:", check_same_thread=False)
    rahmen.to_sql("daten", con, index=False)
    _zwischenspeicher.clear()          # nur das zuletzt benutzte Blatt halten
    _zwischenspeicher[kennung] = con
    return con


def fuehre_aus(datei, blatt, sql, max_zeilen=None):
    """Fuehrt eine gepruefte Abfrage gegen ein Blatt aus.

    Rueckgabe: (spalten, zeilen). Loest ValueError aus, wenn die Pruefung
    fehlschlaegt -- die Abfrage erreicht die Daten dann nicht.
    """
    ok, grund = sqlpruefung.pruefe_abfrage(sql)
    if not ok:
        raise ValueError(f"Abfrage abgelehnt: {grund}")

    max_zeilen = max_zeilen or MAX_ZEILEN
    con = _lade(datei, blatt)
    cur = con.execute(sqlpruefung.begrenze_zeilen(sql, max_zeilen, "sqlite"))
    spalten = [d[0] for d in (cur.description or [])]
    return spalten, cur.fetchmany(max_zeilen)


def formuliere(client, modell, frage, katalogtext, verlauf="", zeitlimit=60):
    """Laesst das Modell Blatt und Abfrage waehlen.

    Rueckgabe: (datei, blatt, sql) oder (None, None, "") wenn die Frage sich
    nicht aus den Listen beantworten laesst.
    """
    with open(paths.resolve_prompt("tabellen_prompt.txt"),
              "r", encoding="utf-8") as f:
        vorlage = f.read()

    prompt = (vorlage
              .replace("{KATALOG}", katalogtext)
              .replace("{HISTORY}", verlauf)
              .replace("{FRAGE}", frage)
              .replace("{MARKER}", MARKER_KEINE_ABFRAGE))

    roh = (client.chat.completions.create(
        model=modell,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        timeout=zeitlimit,
    ).choices[0].message.content or "")

    if MARKER_KEINE_ABFRAGE in roh.upper():
        return None, None, ""
    return zerlege(roh)


def zerlege(antwort):
    """Trennt die Antwort des Modells in Blattangabe und Abfrage."""
    datei = blatt = None
    m = re.search(r"^\s*BLATT:\s*(.+)$", antwort, re.M | re.I)
    if m:
        kennung = m.group(1).strip().strip("`")
        datei, _, blatt = kennung.partition("#")
        datei, blatt = datei.strip(), blatt.strip()

    rest = re.sub(r"^\s*BLATT:.*$", "", antwort, count=1, flags=re.M | re.I)
    sql = sqlpruefung.bereinige(re.sub(r"^\s*SQL:\s*", "", rest.strip(),
                                       count=1, flags=re.I))
    if not datei or not sql:
        return None, None, ""
    return datei, blatt, sql
