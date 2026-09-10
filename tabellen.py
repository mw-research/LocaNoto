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
import collections
import json
import os
import re
import sqlite3

import paths
import sqlpruefung

# Der Raum, dem eine Liste ohne eigene Angabe gehoert -- so hiess
# frueher der eine Ordner, in dem alles lag.
_ALLGEMEIN = "allgemein"

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
# Ableitbar: der Katalog entsteht aus den Tabellendateien und laesst sich
# jederzeit neu einlesen. Deshalb neben den Index und nicht auf den
# persistenten Speicher.
KATALOG = os.path.join(paths.INDEX_DIR, "tabellen_katalog.json")

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

# Wie viele Blaetter eine Frage hoechstens abfragt. Eine Frage wie "welche
# Saegeblaetter gibt es" gilt bei einem gewachsenen Ordner mehreren
# Blaettern zugleich -- ein Jahrgang je Blatt, ein Standort je Datei. Ein
# einziges Blatt zu waehlen beantwortet sie halb.
BLAETTER_MAX = paths.env_int("TABELLEN_BLAETTER", 3)

# Ab wie vielen Blaettern in zwei Schritten gearbeitet wird: erst waehlen,
# dann abfragen. Darunter bleibt es beim einen Aufruf -- bei fuenf
# Blaettern passt der volle Katalog bequem, und ein zweiter Aufruf waere
# nur Wartezeit.
ROUTEN_AB = paths.env_int("TABELLEN_ROUTEN_AB", 6)

# Wie viele Blaetter hoechstens Zeilen beisteuern duerfen -- die
# gewaehlten und die, auf die dieselbe Abfrage zusaetzlich passt.
# Eine Antwort aus zwanzig Blaettern ist keine Antwort mehr.
WEITERE_BLAETTER = paths.env_int("TABELLEN_TREFFER_BLAETTER", 8)

MAX_ZEILEN = paths.env_int("TABELLEN_MAX_ZEILEN", 200)

# Von Hand gesetzte Kopfzeilen. Die Erkennung liegt meistens richtig --
# wo nicht, ist der Katalog fuer diese Datei falsch, und das faellt erst
# auf, wenn eine Antwort nicht stimmt.
KOPF_DATEI = os.path.join(paths.CONFIG_DIR, "tabellen_kopf.json")

# So viele Zeilen werden nach der Kopfzeile abgesucht.
KOPF_SUCHEN = paths.env_int("TABELLEN_KOPF_SUCHEN", 15)

MARKER_KEINE_ABFRAGE = "KEINE_ABFRAGE"

# Wie viele Blaetter im Arbeitsspeicher bleiben. Frueher war es
# genau eines, und jede Frage an ein anderes Blatt las wieder von
# der Platte -- bei 28 Blaettern kostete das 58 Sekunden je Runde.
SPEICHER_BLAETTER = paths.env_int("TABELLEN_SPEICHER_BLAETTER", 60)

# Geordnet, damit der aelteste Eintrag zuerst herausfaellt.
_zwischenspeicher = collections.OrderedDict()


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

_ZAHL = re.compile(r"[-+]?[\d.,]+\s*%?")


def _ist_zahl(x):
    return bool(_ZAHL.fullmatch(str(x).strip()))


def finde_kopfzeile(roh, pruefen=None):
    """Welche Zeile die Spaltennamen traegt.

    Echte Tabellen fangen selten in Zeile 1 an: darueber stehen ein Titel,
    ein Ausdruckdatum, eine Leerzeile. Wer stur die erste Zeile nimmt,
    bekommt Spalten namens "Unnamed: 1" -- und das Sprachmodell weiss dann
    nicht, was in ihnen steht, obwohl die Daten in Ordnung sind.

    Gewertet wird nach gefuellten Zellen und Textanteil: eine Kopfzeile ist
    breit und besteht aus Woertern, eine Datenzeile ist oft schmaler und
    enthaelt Zahlen. Bei Gleichstand gewinnt die obere.
    """
    pruefen = KOPF_SUCHEN if pruefen is None else pruefen
    beste, bestwert = 0, -1
    for i in range(min(pruefen, len(roh))):
        gefuellt = [str(x).strip() for x in roh.iloc[i] if str(x).strip()]
        if len(gefuellt) < 2 or i >= len(roh) - 1:
            continue
        wert = len(gefuellt) + sum(1 for x in gefuellt if not _ist_zahl(x))
        if wert > bestwert:
            beste, bestwert = i, wert
    return beste


def _kopfzeilen():
    """Von Hand gesetzte Kopfzeilen, je 'datei#blatt'."""
    try:
        with open(KOPF_DATEI, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def setze_kopfzeile(datei, blatt, zeile):
    """Setzt die Kopfzeile eines Blattes von Hand. zeile=None loescht sie.

    Die Erkennung liegt meistens richtig und manchmal daneben. Wo sie
    danebenliegt, ist der Katalog fuer diese Datei falsch -- und das faellt
    erst auf, wenn eine Antwort nicht stimmt. Deshalb muss sich das von Hand
    richtigstellen lassen.
    """
    d = _kopfzeilen()
    schluessel = f"{datei}#{blatt}" if blatt else datei
    if zeile is None:
        d.pop(schluessel, None)
    else:
        d[schluessel] = int(zeile)
    try:
        os.makedirs(paths.CONFIG_DIR, exist_ok=True)
        vorlaeufig = KOPF_DATEI + ".neu"
        with open(vorlaeufig, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1, ensure_ascii=False)
        os.replace(vorlaeufig, KOPF_DATEI)
    except OSError as e:
        return False, f"Konnte nicht gespeichert werden: {e}"
    _zwischenspeicher.clear()
    return True, "Gespeichert."


def _aufbereiten(roh, schluessel):
    """(dataframe, kopfzeile) -- Kopf gesetzt, Leerzeilen entfernt."""
    gesetzt = _kopfzeilen().get(schluessel)
    k = int(gesetzt) if gesetzt is not None else finde_kopfzeile(roh)
    k = max(0, min(k, max(0, len(roh) - 1)))

    rahmen = roh.iloc[k + 1:].copy()

    # Namen eindeutig und nicht leer machen. Trifft die Kopfzeile
    # daneben, sind alle Zellen leer -- ohne das bekaemen alle Spalten
    # denselben Namen, der Zugriff darauf liefert eine Tabelle statt
    # einer Spalte, und das Blatt landete mit einem pandas-Fehler in
    # der Fehlerliste statt im Katalog. Eine falsche Kopfzeile soll
    # sichtbar falsch sein, nicht verschwinden: "Spalte 1" faellt
    # beim Durchsehen auf.
    namen, gesehen = [], {}
    for j, x in enumerate(roh.iloc[k]):
        n = str(x).strip().replace("\n", " ") or f"Spalte {j + 1}"
        if n in gesehen:
            gesehen[n] += 1
            n = f"{n} ({gesehen[n]})"
        else:
            gesehen[n] = 1
        namen.append(n)
    rahmen.columns = namen
    # Leerzeilen unter der Tabelle sind in Exportdateien die Regel. Sie
    # blaehen die Zeilenzahl auf und machen jede Zaehlung falsch --
    # beobachtet an einer Liste, die sich mit dem Zwanzigfachen ihrer
    # tatsaechlichen Positionen meldete.
    rahmen = rahmen[rahmen.apply(
        lambda r: any(str(x).strip() for x in r), axis=1)]
    return rahmen.reset_index(drop=True), k


def _blaetter(voll):
    """(blattname, dataframe, kopfzeile) je Blatt einer Datei."""
    import pandas as pd

    try:
        rel = os.path.relpath(voll, pfad()).replace(os.sep, "/")
    except ValueError:
        rel = os.path.basename(voll)

    endung = os.path.splitext(voll)[1].lower()
    if endung in (".csv", ".tsv"):
        trenner = "\t" if endung == ".tsv" else None
        # sep=None laesst pandas den Trenner erkennen -- deutsche Exporte
        # verwenden haeufig das Semikolon.
        roh = pd.read_csv(voll, sep=trenner, engine="python", header=None,
                          dtype=str, keep_default_na=False)
        rahmen, k = _aufbereiten(roh, rel)
        yield "", rahmen, k
        return

    mappe = pd.ExcelFile(voll)
    for blatt in mappe.sheet_names:
        roh = mappe.parse(blatt, header=None, dtype=str, keep_default_na=False)
        rahmen, k = _aufbereiten(roh, f"{rel}#{blatt}")
        yield blatt, rahmen, k


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
        # BEISPIELE_BIS=0 heisst: keine Werte in den Katalog. Frueher
        # rutschte dann trotzdem einer durch den elif-Zweig -- wer die
        # Beispielwerte abschaltet, will keinen einzigen, und einer ist
        # bei einer Lieferantenliste schon ein Name zu viel.
        if BEISPIELE_BIS > 0 and 0 < len(verschieden) <= BEISPIELE_BIS:
            eintrag["werte"] = [str(w)[:60] for w in verschieden[:BEISPIELE_MAX]]
        elif BEISPIELE_BIS > 0 and len(verschieden):
            eintrag["beispiel"] = str(verschieden[0])[:60]
        angaben.append(eintrag)
    return angaben


def quellen():
    """[(raum, ordner)] -- woher gelesen wird.

    Ohne hinterlegte Quellen bleibt es beim einen Ordner von frueher,
    zugeordnet zum allgemeinen Raum. Eine bestehende Installation
    verhaelt sich damit unveraendert, bis jemand Quellen eintraegt --
    eine Umstellung, die am ersten Tag alle Listen verschwinden liesse,
    wuerde zurueckgedreht und nicht verstanden.
    """
    try:
        import listenquellen
        eigene = listenquellen.aufgeloest()
    except Exception:
        eigene = []
    if eigene:
        return eigene
    return [(_ALLGEMEIN, pfad())]


def _lies_ordner(ordner, raum, uebrig):
    """Ein Ordner in Katalogeintraege. (eintraege, fehler, gelesen)."""
    eintraege, fehler, gesehen = [], [], 0
    if not os.path.isdir(ordner):
        # Kein Fehlschlag des Ganzen: ein nicht eingehaengtes
        # Heimlaufwerk ist der Normalfall, nicht die Ausnahme. Nur
        # feste Quellen werden gemeldet -- bei einem Muster je Nutzer
        # stuenden sonst zwanzig Zeilen "nicht erreichbar" da.
        return [], ([(ordner, "Ordner nicht erreichbar")]
                    if not raum.startswith("privat_") else []), 0

    for wurzel, _, dateien in os.walk(ordner):
        for name in sorted(dateien):
            if not name.lower().endswith(ENDUNGEN) or name.startswith("~$"):
                continue
            gesehen += 1
            if gesehen > uebrig:
                fehler.append((ordner, f"Mehr als {MAX_DATEIEN} Dateien -- "
                                       f"abgebrochen. Zeigt der Pfad auf das "
                                       f"richtige Verzeichnis?"))
                return eintraege, fehler, gesehen
            datei_pfad = os.path.join(wurzel, name)
            rel = os.path.relpath(datei_pfad, ordner).replace("\\", "/")
            try:
                for blatt, rahmen, kopf in _blaetter(datei_pfad):
                    eintraege.append({
                        "datei": rel,
                        "blatt": blatt,
                        "raum": raum,
                        "wurzel": ordner,
                        "kopfzeile": kopf,
                        "zeilen": int(len(rahmen)),
                        "gross": len(rahmen) >= GROSS_AB,
                        "spalten": _spaltenangaben(rahmen),
                        "groesse": os.path.getsize(datei_pfad),
                        "geaendert": int(os.path.getmtime(datei_pfad)),
                    })
            except Exception as e:
                fehler.append((rel, f"{type(e).__name__}: {e}"))
    return eintraege, fehler, gesehen


def baue_katalog():
    """Liest alle Quellen neu ein und legt den Katalog an.

    Rueckgabe: (katalog, fehler). fehler ist eine Liste aus (datei, grund) --
    eine unlesbare Datei soll den Katalog nicht verhindern, aber auch nicht
    stillschweigend fehlen.

    Je Eintrag steht der RAUM dabei. Er entscheidet spaeter, wer die
    Liste ueberhaupt zu sehen bekommt -- mit derselben Funktion, die
    ueber die Dokumente entscheidet. Ein zweites Berechtigungssystem
    daneben waere das erste, das jemand vergisst mitzupflegen.
    """
    eintraege, fehler = [], []
    gesamt = 0
    for raum, ordner in quellen():
        teil, fehl, gesehen = _lies_ordner(ordner, raum,
                                           MAX_DATEIEN - gesamt)
        eintraege.extend(teil)
        fehler.extend(fehl)
        gesamt += gesehen
        if gesamt >= MAX_DATEIEN:
            break

    # Verdeckt abgelegt, im Arbeitsspeicher offen zurueckgegeben: der
    # Aufrufer hat gerade selbst eingelesen und weiss ohnehin alles.
    katalog = {"eintraege": [_verdecke(e) for e in eintraege],
               "fehler": fehler}
    try:
        os.makedirs(os.path.dirname(KATALOG), exist_ok=True)
        vorlaeufig = KATALOG + ".neu"
        with open(vorlaeufig, "w", encoding="utf-8") as f:
            json.dump(katalog, f, indent=1, ensure_ascii=False)
        os.replace(vorlaeufig, KATALOG)
    except OSError:
        pass
    return {"eintraege": eintraege, "fehler": fehler}, fehler


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


def beschreibbar():
    """Laesst sich in den Listenordner schreiben?

    Bei einer Nur-Lese-Einhaengung nicht -- dann pflegt die Fachabteilung
    die Dateien, und ein Upload waere ohnehin der falsche Weg.
    """
    ordner = pfad()
    return os.path.isdir(ordner) and os.access(ordner, os.W_OK)


def sicherer_dateiname(name):
    """Ein Dateiname ohne Pfadanteile. Leer, wenn nichts uebrig bleibt."""
    name = os.path.basename((name or "").replace(chr(92), "/")).strip()
    name = re.sub(r"[^0-9A-Za-zäöüÄÖÜß ._-]",
                  "", name).strip(" .")
    if not name.lower().endswith(ENDUNGEN):
        return ""
    return name


def lege_ab(daten, name, bereich=""):
    """Speichert eine hochgeladene Tabellendatei. (ok, meldung)."""
    if not beschreibbar():
        return False, ("Der Listenordner ist nicht beschreibbar -- "
                       "vermutlich nur lesend eingehaengt.")
    sicher = sicherer_dateiname(name)
    if not sicher:
        return False, (f"'{name}' ist kein zulaessiger Name. Erlaubt sind "
                       f"{', '.join(ENDUNGEN)}.")

    bereich = re.sub(r"[^0-9A-Za-zäöüÄÖÜß _-]",
                     "", (bereich or "").strip()).strip()
    wurzel = os.path.realpath(pfad())
    ziel_ordner = os.path.join(wurzel, bereich) if bereich else wurzel
    ziel = os.path.realpath(os.path.join(ziel_ordner, sicher))

    # Nach dem Aufloesen muss die Datei noch im Listenordner liegen. Sonst
    # haette ein praeparierter Name aus ihm herausgefuehrt.
    if not (ziel == wurzel or ziel.startswith(wurzel + os.sep)):
        return False, "Ziel liegt ausserhalb des Listenordners."

    try:
        os.makedirs(os.path.dirname(ziel), exist_ok=True)
        with open(ziel, "wb") as f:
            f.write(daten)
    except OSError as e:
        return False, f"Konnte nicht gespeichert werden: {e}"
    _zwischenspeicher.clear()
    return True, os.path.relpath(ziel, wurzel).replace(os.sep, "/")


# --- DER KATALOG SELBST ---
#
# Der Katalog haelt keine Zeilen, aber er haelt genug: Dateinamen,
# Blattnamen, Spaltennamen und -- bei Spalten mit wenigen verschiedenen
# Werten -- deren LISTE. Das ist der Teil, der die Routenwahl traegt
# ("Status: frei, gesperrt, ausgebucht"), und derselbe Teil, der aus
# einer Lieferantenliste die Lieferanten preisgibt.
#
# Bis hierher lag er offen in einer JSON-Datei. Solange es einen Ordner
# fuer alle gab, war das folgerichtig -- alle durften alles sehen. Mit
# Raeumen ist es das nicht mehr: der Katalog fuehrt dann die Blattnamen
# des Heimlaufwerks jedes Kollegen. Und er liegt seit der Trennung
# ausgerechnet neben dem Stichwortindex, also NICHT auf dem
# verschluesselten Datentraeger.
#
# Verdeckt wird deshalb alles, was etwas verraet, mit dem Schluessel des
# Raums. Offen bleiben nur Zahlen: Raum, Zeilenzahl, Groesse,
# Aenderungsdatum. Damit laesst sich der Katalog weiter pruefen und
# aufraeumen, ohne ihn aufzuschliessen.
_VERDECKT = ("datei", "blatt", "wurzel", "spalten", "kopfzeile")


def _verdecke(eintrag):
    """Ein Katalogeintrag fuer die Ablage."""
    raum = eintrag.get("raum") or _ALLGEMEIN
    try:
        import raumschluessel
        if not raumschluessel.verfuegbar():
            return eintrag
        inhalt = json.dumps({k: eintrag.get(k) for k in _VERDECKT},
                            ensure_ascii=False)
        offen = {k: v for k, v in eintrag.items() if k not in _VERDECKT}
        offen["geheim"] = raumschluessel.verschluessele_text(raum, inhalt)
        return offen
    except Exception:
        # Ohne Schluessel bleibt es beim Klartext. Ein Katalog, der sich
        # nicht schreiben laesst, waere schlechter: dann gibt es gar
        # keine Listensuche mehr, und der Grund stuende nirgends.
        return eintrag


def _schliesse_auf(eintrag):
    """Ein Katalogeintrag zum Benutzen. None, wenn er nicht aufgeht."""
    if "geheim" not in eintrag:
        return eintrag
    raum = eintrag.get("raum") or _ALLGEMEIN
    try:
        import raumschluessel
        inhalt = json.loads(
            raumschluessel.entschluessele_text(raum, eintrag["geheim"]))
    except Exception:
        # Der Schluessel dieses Raums fehlt oder passt nicht. Den
        # Eintrag weglassen und nicht halb anzeigen: eine Zeile
        # "(nicht lesbar), 8.412 Zeilen" ist keine Auskunft, sondern
        # eine ueber die Existenz.
        return None
    offen = {k: v for k, v in eintrag.items() if k != "geheim"}
    offen.update(inhalt)
    return offen


def sichtbar(eintraege, benutzer, notzugang=()):
    """Nur die Listen, die dieser Mensch lesen darf.

    Dieselbe Pruefung wie bei den Dokumenten: raeume.lesbar(). Ein
    Eintrag OHNE Raum stammt aus einem Katalog von vor der Umstellung
    und gehoert dem allgemeinen Raum -- er verschwindet also nicht
    stillschweigend, sondern wird behandelt wie das, was er war.
    """
    import raeume
    erlaubt = set(raeume.lesbar(benutzer, notzugang=notzugang))
    aus = []
    for e in eintraege:
        if (e.get("raum") or _ALLGEMEIN) not in erlaubt:
            continue
        offen = _schliesse_auf(e)
        if offen is not None:
            aus.append(offen)
    return aus


def raeume_von(eintraege):
    """Die Raeume, aus denen Listen im Katalog stehen."""
    return sorted({e.get("raum") or _ALLGEMEIN for e in eintraege})


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


def als_kurztext(eintraege):
    """Der Katalog nur mit Kopfzeilen -- fuer die Wahl des Blattes.

    Zum Routen braucht es die Header und sonst nichts. Die Beispielwerte
    sind fuer das Formulieren des WHERE da, nicht fuer die Frage "welches
    Blatt". Sie machen aber den Grossteil des Katalogs aus: gemessen an 26
    Blaettern mit je 20 Spalten sind es 44.500 Zeichen mit Werten und
    7.165 ohne. Das entscheidet darueber, ob ein gewachsener Listenordner
    ueberhaupt noch in einen Prompt passt.
    """
    zeilen = []
    for e in eintraege:
        kennung = e["datei"] + (f"#{e['blatt']}" if e["blatt"] else "")
        zeilen.append(f'BLATT {kennung}  ({e["zeilen"]} Zeilen)')
        zeilen.append("  " + ", ".join(s["feld"] for s in e["spalten"]))
    return chr(10).join(zeilen)


def zerlege_viele(antwort, hoechstens=None):
    """Alle BLATT/SQL-Paare einer Antwort. [(datei, blatt, sql)].

    Getrennt wird an den BLATT-Zeilen. zerlege() nimmt nur das erste Paar
    -- fuer den Fall, dass ein Modell mehr liefert als gefragt, waere das
    ein stiller Verlust.
    """
    stellen = [m.start() for m in re.finditer(r"^\s*BLATT:", antwort,
                                              re.M | re.I)]
    aus = []
    for i, start in enumerate(stellen):
        ende = stellen[i + 1] if i + 1 < len(stellen) else len(antwort)
        datei, blatt, sql = zerlege(antwort[start:ende])
        if datei and sql:
            aus.append((datei, blatt, sql))
    if hoechstens:
        aus = aus[:hoechstens]
    return aus


def _passendes(eintraege, datei, blatt):
    """Der Katalogeintrag zu einer Blattangabe des Modells. None, wenn
    es sie nicht gibt.

    Ein erfundener oder verstuemmelter Name darf nicht bis zum Laden
    durchkommen -- dort waere er ein Dateifehler statt einer klaren
    Auskunft, dass das Modell danebengegriffen hat.
    """
    for e in eintraege:
        if e["datei"] == datei and (e.get("blatt") or "") == (blatt or ""):
            return e
    # Ohne Blattangabe: das erste Blatt dieser Datei.
    if not blatt:
        for e in eintraege:
            if e["datei"] == datei:
                return e
    return None


# --- DATEN LADEN UND ABFRAGEN ---

_LIKE_MUSTER = {}


def _like_regex(muster, escape=None):
    """SQLite-LIKE-Muster als regulaerer Ausdruck. Zwischengespeichert.

    % steht fuer beliebig viel, _ fuer genau ein Zeichen. Alles andere
    wird woertlich genommen -- deshalb re.escape auf jedes Zeichen, das
    keine Platzhalterbedeutung hat.
    """
    schluessel = (muster, escape)
    fertig = _LIKE_MUSTER.get(schluessel)
    if fertig is not None:
        return fertig
    teile, i, n = [], 0, len(muster)
    while i < n:
        z = muster[i]
        if escape and z == escape and i + 1 < n:
            teile.append(re.escape(muster[i + 1]))
            i += 2
            continue
        if z == "%":
            teile.append(".*")
        elif z == "_":
            teile.append(".")
        else:
            teile.append(re.escape(z))
        i += 1
    fertig = re.compile("".join(teile) + r"\Z",
                        re.DOTALL | re.IGNORECASE | re.UNICODE)
    if len(_LIKE_MUSTER) > 200:
        _LIKE_MUSTER.clear()
    _LIKE_MUSTER[schluessel] = fertig
    return fertig


def _like(muster, wert, escape=None):
    """LIKE, das auch Umlaute faltet. SQLite ruft like(muster, wert)."""
    if muster is None or wert is None:
        return None
    return 1 if _like_regex(str(muster), escape).match(str(wert)) else 0


def _unicode_funktionen(con):
    """Ersetzt LIKE, lower und upper durch unicode-faehige Fassungen.

    SQLite faltet Gross- und Kleinschreibung von Haus aus NUR fuer ASCII.
    In einer deutschen Bestandsliste ist das kein Randfall, sondern der
    Normalfall:

        'SAEGEBLATT' LIKE '%saegeblatt%'   trifft
        'SAEGEBLATT' mit Umlaut geschrieben, klein gesucht -- trifft NICHT

    Eine Inventurliste fuehrt ihre Bezeichnungen oft durchgaengig in
    Grossbuchstaben. Das Modell schreibt die Suche klein, weil der Prompt
    es so verlangt, und bekommt null Zeilen. Von aussen sieht das aus wie
    "gibt es nicht" -- die schlechteste Art, falsch zu antworten.

    Die eigene Fassung kostet die LIKE-Optimierung von SQLite. Hier ist
    das ohne Belang: die Blaetter liegen als Tabelle im Arbeitsspeicher,
    ohne Index, und werden ohnehin durchlaufen.
    """
    con.create_function("like", 2, _like, deterministic=True)
    con.create_function("like", 3, _like, deterministic=True)
    con.create_function("lower", 1,
                        lambda s: None if s is None else str(s).lower(),
                        deterministic=True)
    con.create_function("upper", 1,
                        lambda s: None if s is None else str(s).upper(),
                        deterministic=True)


def _lade(datei, blatt, wurzel=None):
    """Ein Blatt als SQLite-Verbindung im Arbeitsspeicher.

    Zwischengespeichert ueber Aenderungsdatum und Groesse. Das ist die
    Zusage, auf der das ganze Verfahren beruht: die Listen werden von den
    Fachabteilungen auf einem Netzlaufwerk gepflegt, und wer dort Zeilen
    ergaenzt und speichert, soll sie in der naechsten Frage sehen -- ohne
    Einlesen, ohne Knopf. Aendert sich die Datei, aendert sich der
    Schluessel, und der alte Eintrag gilt nicht mehr.

    ZWEI AENDERUNGEN, beide aus derselben Messung:

        ein Blatt kalt           0,81 s
        dasselbe warm            0,00 s
        alle 28 nacheinander    58    s

    Erstens wurde bisher genau EIN Blatt gehalten -- _zwischenspeicher
    wurde vor jedem Eintrag geleert. Die naechste Frage an ein anderes
    Blatt las wieder von der Platte, und bei 28 Blaettern kostete jede
    Runde von vorn. Jetzt bleiben bis zu SPEICHER_BLAETTER stehen, die
    aeltesten fallen zuerst heraus.

    Zweitens wurde je Blatt die GANZE Arbeitsmappe geparst und danach ein
    Blatt daraus behalten. Die 28 Blaetter liegen aber in sieben Dateien;
    eine davon fuehrt zwoelf. Wer nacheinander alle zwoelf fragte, parste
    dieselbe Mappe zwoelfmal. Jetzt kommen beim ersten Zugriff auf eine
    Mappe ALLE ihre Blaetter in den Speicher -- geparst wird sie ohnehin.

    Nichts davon haelt eine Zeile laenger, als die Datei unveraendert ist.
    """
    # Die Wurzel kommt aus dem Katalogeintrag, nicht mehr aus dem einen
    # Ordner: seit jede Quelle zu einem Raum gehoert, liegen zwei
    # Dateien gleichen Namens in verschiedenen Raeumen -- und "inventur.xlsx"
    # allein sagt nicht mehr, welche gemeint ist.
    wurzel_ = os.path.realpath(wurzel or pfad())
    voll = os.path.realpath(os.path.join(wurzel_, datei))
    if not (voll == wurzel_ or voll.startswith(wurzel_ + os.sep)):
        raise ValueError("Die Datei liegt ausserhalb ihrer Quelle.")
    if not os.path.isfile(voll):
        raise ValueError(f"Datei nicht gefunden: {datei}")
    stand = (voll, os.path.getmtime(voll), os.path.getsize(voll))
    kennung = stand + (blatt,)
    con = _zwischenspeicher.get(kennung)
    if con is not None:
        _zwischenspeicher.move_to_end(kennung)
        return con

    gefunden = None
    for name, rahmen, _kopf in _blaetter(voll):
        con = _als_tabelle(rahmen)
        _merke(stand + (name,), con)
        if name == blatt or (not blatt and gefunden is None):
            gefunden = con
        # Ohne Blattangabe meint der Aufrufer das erste. Die uebrigen
        # kommen trotzdem in den Speicher: sie sind schon geparst.
    if gefunden is None:
        raise ValueError(f"Blatt nicht gefunden: {blatt}")
    return gefunden


def _als_tabelle(rahmen):
    """Ein Rahmen als SQLite-Verbindung mit der Tabelle `daten`."""
    vergeben, namen = set(), []
    for spalte in rahmen.columns:
        s = sicherer_name(spalte, vergeben)
        vergeben.add(s)
        namen.append(s)
    rahmen = rahmen.copy()
    rahmen.columns = namen
    con = sqlite3.connect(":memory:", check_same_thread=False)
    rahmen.to_sql("daten", con, index=False)
    _unicode_funktionen(con)
    return con


def _merke(kennung, con):
    """Legt eine Verbindung ab und wirft die aeltesten heraus.

    Die Grenze ist eine Zahl von Blaettern und keine Speichergroesse:
    letztere liesse sich nur schaetzen, und eine falsche Schaetzung waere
    entweder ein voller Arbeitsspeicher oder ein Zwischenspeicher, der
    nichts behaelt. Ein Blatt mit 2.000 Zeilen und 14 Spalten liegt bei
    wenigen Megabyte.
    """
    _zwischenspeicher[kennung] = con
    _zwischenspeicher.move_to_end(kennung)
    while len(_zwischenspeicher) > SPEICHER_BLAETTER:
        _alt, alte_con = _zwischenspeicher.popitem(last=False)
        try:
            alte_con.close()
        except Exception:
            pass


def fuehre_aus(datei, blatt, sql, max_zeilen=None, wurzel=None):
    """Fuehrt eine gepruefte Abfrage gegen ein Blatt aus.

    Rueckgabe: (spalten, zeilen). Loest ValueError aus, wenn die Pruefung
    fehlschlaegt -- die Abfrage erreicht die Daten dann nicht.
    """
    ok, grund = sqlpruefung.pruefe_abfrage(sql)
    if not ok:
        raise ValueError(f"Abfrage abgelehnt: {grund}")

    max_zeilen = max_zeilen or MAX_ZEILEN
    con = _lade(datei, blatt, wurzel)
    cur = con.execute(sqlpruefung.begrenze_zeilen(sql, max_zeilen, "sqlite"))
    spalten = [d[0] for d in (cur.description or [])]
    return spalten, cur.fetchmany(max_zeilen)


MEHRERE_HINWEIS = (
    "Passt die Frage zu MEHREREN der unten stehenden Blaetter -- etwa weil "
    "sie ohne Jahr oder ohne Standort gestellt ist und mehrere Blaetter "
    "denselben Inhalt fuer verschiedene Jahre oder Orte fuehren --, gib "
    "fuer jedes ein eigenes Paar aus: BLATT-Zeile, dann SQL-Zeile, "
    "hoechstens {N} Paare und nichts dazwischen. Jede Abfrage laeuft "
    "gegen ihr eigenes Blatt, dieselbe Frage auf zwei Jahrgaenge ergibt "
    "also zwei Paare mit derselben Struktur. Passt nur eines, gib nur "
    "eines aus.")


def _sql_prompt(frage, katalogtext, verlauf, hoechstens):
    with open(paths.resolve_prompt("tabellen_prompt.txt"),
              "r", encoding="utf-8") as f:
        vorlage = f.read()
    mehrere = (MEHRERE_HINWEIS.replace("{N}", str(hoechstens))
               if hoechstens and hoechstens > 1 else "")
    return (vorlage
            .replace("{MEHRERE}", mehrere)
            .replace("{KATALOG}", katalogtext)
            .replace("{HISTORY}", verlauf)
            .replace("{FRAGE}", frage)
            .replace("{MARKER}", MARKER_KEINE_ABFRAGE))


def formuliere_viele(client, modell, frage, eintraege, verlauf="",
                     hoechstens=None, zeitlimit=60):
    """Blatt und Abfrage fuer MEHRERE Blaetter. [(datei, blatt, sql)].

    Der zweite von zwei Schritten. Der Katalog enthaelt hier nur noch die
    vorher gewaehlten Blaetter -- dafuer mit allen Spalten und
    Beispielwerten, die das Formulieren des WHERE braucht.

    Leere Liste heisst: das Modell sieht keine beantwortbare Frage.
    """
    hoechstens = hoechstens or BLAETTER_MAX
    prompt = _sql_prompt(frage, als_text(eintraege), verlauf, hoechstens)
    roh = (client.chat.completions.create(
        model=modell,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        timeout=zeitlimit,
    ).choices[0].message.content or "")
    if MARKER_KEINE_ABFRAGE in roh.upper():
        return []
    return zerlege_viele(roh, hoechstens)


def formuliere(client, modell, frage, katalogtext, verlauf="", zeitlimit=60):
    """Laesst das Modell Blatt und Abfrage waehlen.

    Rueckgabe: (datei, blatt, sql) oder (None, None, "") wenn die Frage sich
    nicht aus den Listen beantworten laesst.
    """
    prompt = _sql_prompt(frage, katalogtext, verlauf, hoechstens=1)

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


def waehle_blaetter(client, modell, frage, eintraege, hoechstens=None,
                    zeitlimit=45):
    """Welche Blaetter kommen fuer diese Frage in Frage? Liste von Eintraegen.

    Der erste von zwei Schritten. Gefragt wird mit dem Kurzkatalog --
    Kopfzeilen und sonst nichts. Das ist nicht nur billiger, es ist auch
    die bessere Frage: welches Blatt gemeint ist, entscheiden die
    Spaltennamen, nicht die Beispielwerte.

    Leere Liste heisst: kein Blatt passt. Das ist etwas anderes als ein
    Fehlschlag -- bei einem Fehler wird auf ALLE Blaetter zurueckgefallen,
    damit ein hakender Modellserver nicht wie "keine Liste passt"
    aussieht.
    """
    hoechstens = hoechstens or BLAETTER_MAX
    with open(paths.resolve_prompt("tabellen_wahl_prompt.txt"),
              "r", encoding="utf-8") as f:
        vorlage = f.read()
    prompt = (vorlage
              .replace("{KATALOG}", als_kurztext(eintraege))
              .replace("{HOECHSTENS}", str(hoechstens))
              .replace("{MARKER}", MARKER_KEINE_ABFRAGE)
              .replace("{FRAGE}", frage))

    roh = (client.chat.completions.create(
        model=modell,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        timeout=zeitlimit,
    ).choices[0].message.content or "")

    if MARKER_KEINE_ABFRAGE in roh.upper():
        return []

    gewaehlt = []
    for m in re.finditer(r"^\s*BLATT:\s*(.+)$", roh, re.M | re.I):
        kennung = m.group(1).strip().strip("`")
        datei, _, blatt = kennung.partition("#")
        e = _passendes(eintraege, datei.strip(), blatt.strip())
        if e is not None and e not in gewaehlt:
            gewaehlt.append(e)
        if len(gewaehlt) >= hoechstens:
            break
    return gewaehlt


def _schema_fehler(e):
    """Passt die Abfrage nicht zu diesem Blatt? Dann kein Fehler, sondern
    schlicht das falsche Blatt."""
    t = str(e).lower()
    return ("no such column" in t or "no such table" in t
            or "has no column" in t)


def abfragen(client, modell, frage, eintraege, verlauf="", hoechstens=None,
             max_zeilen=None, zeitlimit=60):
    """Eine Frage gegen die passenden Blaetter. Liste von Ergebnissen.

    Der ganze Ablauf an einer Stelle, damit Oberflaeche und Schnittstelle
    nicht zwei Auffassungen davon entwickeln, wie eine Listenfrage
    beantwortet wird.

        1. Bei wenigen Blaettern gar nicht routen -- der volle Katalog
           passt, und ein zweiter Modellaufruf waere nur Wartezeit.
        2. Sonst mit dem Kurzkatalog waehlen, dann die vollen Angaben NUR
           der gewaehlten Blaetter in den zweiten Prompt geben.
        3. Die fertige Abfrage auf ALLE Blaetter anwenden, deren Spalten
           dazu passen -- nicht nur auf die gewaehlten.

    Schritt 3 ist der wichtige, und er kam aus einer Fehlanzeige: die
    Frage nach Saegeblaettern lieferte nichts, obwohl 18 Zeilen in sechs
    Blaettern standen. Das Modell hatte ein Blatt gewaehlt, in dem keines
    lag -- und es konnte nicht anders. Alle 28 Blaetter fuehren dieselben
    Spalten: bezeichnung, menge, lagerort. Welches Blatt ein Saegeblatt
    fuehrt, steht im INHALT, und den sieht der Katalog nicht. Eine Wahl
    nach Kopfzeilen ist dort kein schwaches Verfahren, sondern gar keines.

    Die Abfrage einfach auf alle anzuwenden beantwortet das, ohne es
    raten zu muessen. Bezahlbar ist es, seit die Blaetter im
    Arbeitsspeicher bleiben: gemessen 0,03 s fuer 28 Blaetter, wenn sie
    warm sind, und 8,9 s beim ersten Mal.

    Blaetter, deren Spalten nicht passen, fallen dabei still heraus --
    "no such column" ist hier keine Stoerung, sondern die Antwort "dieses
    Blatt fuehrt das nicht".

    Rueckgabe: [{datei, blatt, sql, spalten, zeilen, grund, gewaehlt}].
    grund ist gesetzt, wenn dieses eine Blatt nicht ging. Eine leere
    Liste heisst, dass keine Liste zur Frage passt.
    """
    hoechstens = hoechstens or BLAETTER_MAX
    if not eintraege:
        return []

    if len(eintraege) < ROUTEN_AB:
        auswahl = list(eintraege)
    else:
        try:
            auswahl = waehle_blaetter(client, modell, frage, eintraege,
                                      hoechstens, zeitlimit)
        except Exception:
            # Der Modellserver hat nicht geantwortet. Mit allen Blaettern
            # weiterzumachen ist teurer, aber ehrlicher als so zu tun, als
            # passe keine Liste.
            auswahl = list(eintraege)
        else:
            if not auswahl:
                return []

    paare = formuliere_viele(client, modell, frage, auswahl, verlauf,
                             hoechstens, zeitlimit)
    if not paare:
        return []

    aus, erledigt = [], set()
    for datei, blatt, sql in paare:
        e = _passendes(auswahl, datei, blatt)
        if e is None:
            # Ein Blatt, das nicht zur Auswahl gehoert. Das Modell hat den
            # Namen erfunden oder verstuemmelt gelesen -- nicht ausfuehren.
            aus.append({"datei": datei, "blatt": blatt, "sql": sql,
                        "spalten": [], "zeilen": [], "gewaehlt": True,
                        "grund": "Dieses Blatt steht nicht im Katalog."})
            continue
        erledigt.add((e["datei"], e.get("blatt") or ""))
        aus.append(_ausfuehren(e, sql, max_zeilen, gewaehlt=True))

    # Dieselbe Abfrage auf die uebrigen Blaetter. Nur die mit Zeilen
    # kommen dazu: ein leeres Ergebnis aus einem Blatt, das niemand
    # gewaehlt hat, ist keine Auskunft, sondern Rauschen.
    for e in eintraege:
        if (e["datei"], e.get("blatt") or "") in erledigt:
            continue
        if len([x for x in aus if x["zeilen"]]) >= WEITERE_BLAETTER:
            break
        for _datei, _blatt, sql in paare[:1]:
            t = _ausfuehren(e, sql, max_zeilen, gewaehlt=False)
            if t["zeilen"]:
                aus.append(t)
    return aus


def _ausfuehren(eintrag, sql, max_zeilen, gewaehlt):
    """Eine Abfrage gegen ein Blatt. Immer ein Ergebnis, nie eine Ausnahme."""
    datei, blatt = eintrag["datei"], eintrag.get("blatt") or ""
    fertig = {"datei": datei, "blatt": blatt, "sql": sql,
              "spalten": [], "zeilen": [], "grund": "", "gewaehlt": gewaehlt}
    try:
        fertig["spalten"], fertig["zeilen"] = fuehre_aus(
            datei, blatt, sql, max_zeilen, eintrag.get("wurzel"))
    except Exception as e:
        if _schema_fehler(e) and not gewaehlt:
            # Das Blatt fuehrt diese Spalten nicht. Kein Fehler, sondern
            # die Auskunft, dass es nicht gemeint war.
            return fertig
        fertig["grund"] = f"{type(e).__name__}: {e}"
    return fertig
