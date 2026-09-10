"""Die Vektordatenbank sichern und zurueckholen -- ohne Modell.

Das Problem, das dieses Modul loest: die Vektordatenbank ist der einzige
Zustand, der nicht ableitbar ist und trotzdem nicht auf den Netzspeicher
gehoert.

    Der Stichwortindex ist ableitbar -- er baut sich aus den Sammlungen neu
    auf, 18.600 Abschnitte je Sekunde.

    Chats, Konfiguration und Dokumente liegen auf dem persistenten Speicher
    und sind gewoehnliche Dateien.

    Die Vektordatenbank dagegen ist SQLite plus binaere Indexdateien. Auf
    einem Netzlaufwerk ist das kein Fehler, sondern ein beschaedigter Index
    -- der WAL-Betrieb braucht gemeinsamen Speicher im selben Dateisystem,
    und die Dateisperren sind unzuverlaessig. Ginge sie verloren, waere die
    einzige Wiederherstellung ein vollstaendiges Neueinlesen: Stunden
    GPU-Zeit fuer ein Ergebnis, das man schon hatte.

Also: der laufende Bestand auf schnellem, lokalem oder Blockspeicher, und
ein Abzug davon auf dem persistenten Speicher. Nicht die lebenden Dateien
kopieren -- eine Sicherung mitten in einem Schreibvorgang ist ein Abzug,
der sich nicht zurueckholen laesst und das erst beim Zurueckholen zeigt.
Stattdessen ueber die Schnittstelle gelesen, Abschnitt fuer Abschnitt, mit
den Vektoren.

Format je Raum zwei Dateien:

    <raum>.npy      die Vektoren als float32-Matrix
    <raum>.jsonl    je Zeile {id, text, meta}

Getrennt, weil Vektoren als JSON das Zehnfache braeuchten und beim
Zurueckholen jede Zahl neu geparst werden muesste. numpy liegt ohnehin im
Image.

Das Zurueckholen braucht kein Modell und keinen Endpunkt: die Vektoren
liegen im Abzug. Ein Rechner ohne Grafikkarte kann eine Installation
wiederherstellen.
"""
import json
import os
import shutil
import sys
import time

import numpy as np

import paths
import raeume
import store

# Wohin gesichert wird. Unter DATA_DIR und damit auf dem persistenten
# Speicher -- das ist der Sinn der Uebung. SICHERUNG_PFAD zeigt es
# woandershin, etwa auf ein Sicherungslaufwerk, das nicht dasselbe Schicksal
# teilt wie der Datenspeicher.
ORDNER = (os.getenv("SICHERUNG_PFAD", "").strip()
          or os.path.join(paths.DATA_DIR, "sicherungen"))

# Wie viele Abschnitte je Griff aus der Sammlung geholt werden. Mit
# Vektoren haengt an jedem ein Tausenderfeld; 2000 sind rund 8 MB und damit
# unauffaellig im Speicher.
STAPEL = 2000

# Wie viele Abzuege behalten werden. 0 heisst: alle.
BEHALTEN = paths.env_int("SICHERUNG_BEHALTEN", 7)


VORSILBE = "raum_"


def _raum_sammlungen():
    """[(kennung, sammlung)] ueber ALLE vorhandenen Sammlungen.

    Ausgangspunkt sind die Sammlungen und nicht die Raumverwaltung. Der
    Unterschied ist nicht theoretisch -- beim Bauen dieses Moduls fiel er
    im Test auf:

      * raeume.entfernen() nimmt einen Raum aus der Verwaltung und LAESST
        die Sammlung absichtlich stehen, als Rueckweg. Ueber die
        Raumverwaltung gesichert waeren ihre Abschnitte still uebergangen
        worden -- und beim Zurueckholen einfach nicht mehr da.
      * Ein persoenlicher Raum entsteht beim ersten Upload. Faellt der
        Eintrag aus, hat der Nutzer Daten und die Verwaltung weiss es
        nicht.

    Was gesichert werden muss, sagen die Daten, nicht das Verzeichnis
    darueber. Der allgemeine Raum ist dabei der groesste und der
    wichtigste; ihn auszunehmen, weil er "nur" der gemeinsame Bestand ist,
    waere die Sicherung, die im Ernstfall fehlt.
    """
    paare = []
    for name in store.namen():
        if name.startswith(VORSILBE):
            kennung = name[len(VORSILBE):]
        elif name == paths.COLLECTION_NAME:
            # Der Bestand von vor den Raeumen. Er wird nicht mehr
            # durchsucht, aber solange er dasteht, gehoert er in den Abzug
            # -- sonst nimmt eine Wiederherstellung ihm den Rueckweg.
            kennung = "_alt_" + name
        else:
            continue
        sml = store.sammlung(name, anlegen=False)
        if sml is not None:
            paare.append((kennung, sml))
    return sorted(paare, key=lambda p: p[0])


def _sammlungsname(kennung):
    """Zurueck vom Abzugsnamen zur Sammlung."""
    if kennung.startswith("_alt_"):
        return kennung[len("_alt_"):]
    return raeume.sammlung(kennung)


def liste():
    """Vorhandene Abzuege, neueste zuerst: [(name, pfad, bytes, stand)]."""
    if not os.path.isdir(ORDNER):
        return []
    aus = []
    for name in sorted(os.listdir(ORDNER), reverse=True):
        p = os.path.join(ORDNER, name)
        if not os.path.isdir(p):
            continue
        gr = 0
        for w, _u, dateien in os.walk(p):
            for d in dateien:
                try:
                    gr += os.path.getsize(os.path.join(w, d))
                except OSError:
                    pass
        stand = {}
        try:
            with open(os.path.join(p, "stand.json"), encoding="utf-8") as f:
                stand = json.load(f)
        except (OSError, ValueError):
            pass
        aus.append((name, p, gr, stand))
    return aus


def _lies_raum(kennung, sml, gesamt, fortschritt=None, versuche=4):
    """(zeilen, vektoren) eines Raums. Wirft, wenn es nicht zu holen ist.

    Mit Wiederholung, und der Grund ist ein Fehlschlag, der beim Bauen
    dieses Moduls in etwa einem von zwanzig Laeufen auftrat:

        Error creating hnsw segment reader: Nothing found on disk

    Chroma legt seine Vektorsegmente verzoegert ab. Wird eine Sammlung
    gelesen, kurz nachdem in sie geschrieben wurde, kann der Leser das
    Segment noch nicht finden -- und er merkt sich das. Die Wiederholung
    steckt in store.hole(), samt Neuverbinden; ohne das scheitert der
    zweite Versuch genauso.

    Vorher kostete das den ganzen Raum: der Fehler landete in der
    Fehlerliste, der Abzug wurde trotzdem geschrieben und sah brauchbar
    aus -- ohne den allgemeinen Raum, den groessten von allen. Auffallen
    wuerde das erst beim Zurueckholen.
    """
    name = _sammlungsname(kennung)
    zeilen, vektoren, gelesen = [], [], 0
    while gelesen < gesamt:
        # store.hole und nicht sml.get: die Wiederholung samt
        # Neuverbinden steckt dort, weil derselbe Fehlschlag auch das
        # Verschieben und die Umsortierung trifft.
        b = store.hole(sml, name, versuche=versuche,
                       include=["documents", "metadatas", "embeddings"],
                       limit=STAPEL, offset=gelesen)
        ids = b.get("ids") or []
        if not ids:
            break
        embs = b.get("embeddings")
        if embs is None or len(embs) != len(ids):
            raise ValueError(
                "Die Sammlung gibt keine Vektoren heraus -- ohne "
                "sie waere der Abzug nur Text.")
        docs = b.get("documents") or []
        metas = b.get("metadatas") or []
        for i, kid in enumerate(ids):
            zeilen.append(json.dumps(
                {"id": kid,
                 "text": docs[i] if i < len(docs) else "",
                 "meta": metas[i] if i < len(metas) else {}},
                ensure_ascii=False))
        vektoren.extend(embs)
        gelesen += len(ids)
        if fortschritt:
            fortschritt(kennung, gelesen, gesamt)
    return zeilen, vektoren


def sichere(fortschritt=None):
    """Schreibt einen vollstaendigen Abzug. Rueckgabe: Bericht als dict.

    Erst in einen Ordner mit Endung .teil, dann umbenannt. Ein
    abgebrochener Abzug soll nicht als brauchbarer daliegen -- das faellt
    sonst erst auf, wenn man ihn braucht.
    """
    name = time.strftime("%Y-%m-%d_%H-%M-%S")
    # Zwei Abzuege in derselben Sekunde traten sich sonst gegenseitig weg:
    # der Name traegt nur Sekunden, und unten wird das Ziel vor dem
    # Umbenennen geleert. Passiert, wenn ein Zeitplan und ein Klick auf
    # "Jetzt sichern" zusammenfallen -- und dann kann der unvollstaendige
    # den vollstaendigen ueberschreiben.
    if os.path.isdir(os.path.join(ORDNER, name)):
        for n in range(2, 100):
            if not os.path.isdir(os.path.join(ORDNER, f"{name}_{n}")):
                name = f"{name}_{n}"
                break
    ziel = os.path.join(ORDNER, name)
    vorlaeufig = ziel + ".teil"
    shutil.rmtree(vorlaeufig, ignore_errors=True)
    os.makedirs(vorlaeufig, exist_ok=True)

    bericht = {"name": name, "raeume": {}, "fehler": [],
                "abschnitte": 0, "bytes": 0,
                "begonnen": time.strftime("%Y-%m-%dT%H:%M:%S")}
    t0 = time.time()

    for kennung, sml in _raum_sammlungen():
        try:
            gesamt = sml.count()
        except Exception as e:
            bericht["fehler"].append({"raum": kennung, "grund": str(e)})
            continue
        if not gesamt:
            continue

        try:
            zeilen, vektoren = _lies_raum(kennung, sml, gesamt, fortschritt)
        except Exception as e:
            bericht["fehler"].append({"raum": kennung, "grund": str(e)})
            continue
        gelesen = len(zeilen)

        sichere_kennung = paths.sicherer_teil(kennung)
        # float32 und nicht float64: die Vektoren kommen aus einem Modell,
        # das ohnehin in einfacher Genauigkeit rechnet. Das halbiert den
        # Abzug, ohne einen Treffer zu verschieben.
        matrix = np.asarray(vektoren, dtype=np.float32)
        np.save(os.path.join(vorlaeufig, sichere_kennung + ".npy"), matrix)
        with open(os.path.join(vorlaeufig, sichere_kennung + ".jsonl"),
                  "w", encoding="utf-8") as f:
            f.write("\n".join(zeilen) + "\n")

        bericht["raeume"][kennung] = {"abschnitte": gelesen,
                                      "dimension": int(matrix.shape[1])
                                      if matrix.ndim == 2 else 0,
                                      "datei": sichere_kennung}
        bericht["abschnitte"] += gelesen

    bericht["dauer"] = round(time.time() - t0, 1)
    bericht["beendet"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    # Ausdruecklich vermerkt, und zwar IM Abzug. Ein Abzug, dem ein Raum
    # fehlt, ist von einem vollstaendigen von aussen nicht zu
    # unterscheiden -- die Dateien der anderen Raeume liegen ja da. Ohne
    # diese Angabe faellt es erst beim Zurueckholen auf, und dann ist es
    # der falsche Zeitpunkt.
    bericht["vollstaendig"] = not bericht["fehler"]

    with open(os.path.join(vorlaeufig, "stand.json"), "w",
              encoding="utf-8") as f:
        json.dump(bericht, f, ensure_ascii=False, indent=2)

    # Die Raumverwaltung mit sichern: ein Abzug ohne sie liesse die
    # Abschnitte wiederherstellen, aber niemand wuesste mehr, wer sie
    # sehen darf.
    #
    # raumschluessel.json GEHOERT DAZU, und das ist keine Aufweichung der
    # Trennung. Darin stehen die Raumschluessel -- verpackt mit dem
    # Installationsschluessel, also ohne ihn wertlos. Der Abzug bleibt
    # damit genauso unlesbar wie zuvor.
    #
    # Ohne sie waere er dagegen ENDGUELTIG unlesbar: die Raumschluessel
    # sind Zufall, sie lassen sich aus nichts wiederherstellen. Wer nur
    # schluessel.key sichert und diese Datei verliert, hat einen Abzug,
    # den auch der richtige Installationsschluessel nicht mehr oeffnet.
    # Das war eine Verlustmoeglichkeit, die beim Bauen der
    # Raumschluessel uebersehen wurde.
    #
    # Der Installationsschluessel selbst geht weiterhin NICHT mit -- er
    # gehoert in eine andere Aufbewahrung als die Daten, die er lesbar
    # macht.
    for datei in ("raeume.json", "owncloud.json", "raumschluessel.json"):
        quelle = os.path.join(paths.CONFIG_DIR, datei)
        if os.path.exists(quelle):
            shutil.copy(quelle, os.path.join(vorlaeufig, datei))

    shutil.rmtree(ziel, ignore_errors=True)
    os.replace(vorlaeufig, ziel)

    gr = 0
    for w, _u, dateien in os.walk(ziel):
        for d in dateien:
            gr += os.path.getsize(os.path.join(w, d))
    bericht["bytes"] = gr
    bericht["pfad"] = ziel
    _aufraeumen()
    return bericht


def _aufraeumen():
    """Loescht die aeltesten Abzuege ueber BEHALTEN hinaus.

    Der neueste VOLLSTAENDIGE bleibt immer stehen, auch wenn er aus der
    Zahl herausfaellt. Sonst genuegten BEHALTEN Laeufe mit einem
    Lesefehler, um den letzten brauchbaren Abzug wegzuraeumen -- und die
    Aufbewahrung waere zu dem Zeitpunkt am duennsten, an dem sie am
    meisten gebraucht wird.
    """
    if BEHALTEN <= 0:
        return 0
    vorhanden = liste()
    bewahrt = None
    for name, _p, _gr, stand in vorhanden:
        if stand.get("vollstaendig") and not stand.get("fehler"):
            bewahrt = name
            break
    weg = 0
    for name, pfad, _gr, _stand in vorhanden[BEHALTEN:]:
        if name == bewahrt:
            continue
        shutil.rmtree(pfad, ignore_errors=True)
        weg += 1
    return weg


def _hat_klartext(pfad):
    """Enthaelt dieser Abzug Abschnitte im Klartext?

    Nur die ersten Zeilen je Datei -- es geht um "ja oder nein", nicht um
    eine Zaehlung, und ein Abzug hat leicht hunderttausend Zeilen.
    """
    try:
        for d in os.listdir(pfad):
            if not d.endswith(".jsonl"):
                continue
            with open(os.path.join(pfad, d), encoding="utf-8",
                      errors="replace") as f:
                for i, z in enumerate(f):
                    if i > 50:
                        break
                    if '"text": "' in z and '"text": "LNX1:' not in z:
                        return True
    except OSError:
        pass
    return False


def entferne(name, trotzdem=False):
    """Loescht einen Abzug. (ok, meldung).

    Der NEUESTE VOLLSTAENDIGE bleibt stehen, es sei denn, jemand besteht
    ausdruecklich darauf. Ein Abzug ist die Antwort auf einen Fehlgriff,
    und ihn wegzuraeumen, weil gerade aufgeraeumt wird, ist der
    Fehlgriff, gegen den es keinen zweiten Abzug gibt.

    Geloescht wird IM Container -- die Ordner gehoeren dem Konto, unter
    dem er laeuft, und auf dem Wirt scheitert ein rm an den Rechten. Das
    ist kein Randfall: die Abzuege sind das Erste, was jemand wegraeumen
    will, wenn der Platz knapp wird.
    """
    ziel = os.path.join(ORDNER, name)
    if not os.path.isdir(ziel):
        return False, f"Kein Abzug namens '{name}'."

    vollstaendige = [n for n, _p, _g, s in liste()
                     if s.get("vollstaendig") and not s.get("fehler")]
    if vollstaendige and vollstaendige[0] == name and not trotzdem:
        return False, (
            f"'{name}' ist der neueste VOLLSTAENDIGE Abzug. Er bleibt "
            f"stehen. Erst einen neuen ziehen (python sicherung.py), "
            f"dann diesen entfernen -- oder mit --trotzdem darauf "
            f"bestehen.")

    shutil.rmtree(ziel, ignore_errors=True)
    if os.path.isdir(ziel):
        return False, (f"'{name}' liess sich nicht entfernen. Rechte des "
                       f"Kontos pruefen, unter dem der Container laeuft.")
    return True, f"'{name}' entfernt."


def _leer_genug():
    """Ist noch nichts in den Sammlungen? Bei Zweifel: nein.

    Der Wiederanlauf soll einen leeren Bestand fuellen und niemals einen
    vorhandenen ueberschreiben. Laesst sich das nicht feststellen --
    Chroma antwortet nicht, eine Sammlung fehlt --, gilt der Bestand als
    vorhanden. Ein nicht eingespielter Abzug ist ein Ausfall; ein
    faelschlich eingespielter ist ein Datenverlust.
    """
    try:
        import store
        for name in store.namen():
            if not name.startswith("raum_"):
                continue
            sml = store.sammlung(name, anlegen=False)
            if sml is not None and sml.count() > 0:
                return False
        return True
    except Exception:
        return False


def hole_zurueck(name, nur_raum=None, fortschritt=None):
    """Spielt einen Abzug in die Sammlungen zurueck.

    upsert und nicht add: ein zweiter Lauf soll den Bestand nicht
    verdoppeln und nicht an bekannten Kennungen scheitern. Vorhandene
    Abschnitte werden dabei ueberschrieben -- was im Abzug steht, gilt.

    Kein Modell noetig: die Vektoren liegen im Abzug.
    """
    quelle = os.path.join(ORDNER, name)
    if not os.path.isdir(quelle):
        return {"fehler": [f"Kein Abzug namens '{name}'."], "raeume": {}}

    try:
        with open(os.path.join(quelle, "stand.json"), encoding="utf-8") as f:
            stand = json.load(f)
    except (OSError, ValueError):
        return {"fehler": ["Der Abzug hat keine lesbare stand.json."],
                "raeume": {}}

    bericht = {"name": name, "raeume": {}, "fehler": []}
    # Zuerst gesagt, nicht nebenbei: wer einen Abzug einspielt, tut es in
    # einer Lage, in der er den Bestand nicht mehr hat. Dass diesem Abzug
    # ein Raum fehlt, muss er vorher wissen und nicht hinterher merken.
    if stand.get("vollstaendig") is False or stand.get("fehler"):
        fehlten = [f.get("raum") for f in (stand.get("fehler") or [])
                   if f.get("raum")]
        bericht["unvollstaendig"] = fehlten or True
        bericht["fehler"].append(
            {"raum": ", ".join(fehlten) or "unbekannt",
             "grund": ("Dieser Abzug wurde als unvollstaendig vermerkt: "
                       "beim Sichern liessen sich diese Raeume nicht "
                       "lesen. Was hier eingespielt wird, ist alles, was "
                       "der Abzug hat.")})
    for kennung, angabe in (stand.get("raeume") or {}).items():
        if nur_raum and kennung != nur_raum:
            continue
        basis = os.path.join(quelle, angabe.get("datei")
                             or paths.sicherer_teil(kennung))
        try:
            matrix = np.load(basis + ".npy")
            with open(basis + ".jsonl", encoding="utf-8") as f:
                zeilen = [json.loads(z) for z in f if z.strip()]
        except (OSError, ValueError) as e:
            bericht["fehler"].append({"raum": kennung, "grund": str(e)})
            continue
        if len(zeilen) != len(matrix):
            bericht["fehler"].append({
                "raum": kennung,
                "grund": (f"{len(zeilen)} Abschnitte, aber "
                          f"{len(matrix)} Vektoren -- der Abzug ist "
                          f"unvollstaendig.")})
            continue

        sml = store.sammlung(_sammlungsname(kennung))
        geschrieben = 0
        try:
            # store.schreibe teilt selbst auf: ueber HTTP lehnt der Server
            # eine zu grosse Anfrage ab, und wie gross zu gross ist, haengt
            # an der Vektorlaenge des Modells.
            geschrieben = store.schreibe(
                sml,
                [z["id"] for z in zeilen],
                documents=[z.get("text") or "" for z in zeilen],
                metadatas=[z.get("meta") or {} for z in zeilen],
                embeddings=matrix.tolist(),
                fortschritt=(lambda n, g, k=kennung: fortschritt(k, n, g))
                if fortschritt else None)
        except Exception as e:
            bericht["fehler"].append({"raum": kennung, "grund": str(e)})
        bericht["raeume"][kennung] = geschrieben

    # Der Stichwortindex wird NICHT aus dem Abzug geholt, sondern neu
    # gebaut: er ist ableitbar, und ein Abzug davon waere ein zweiter Ort,
    # der mit dem ersten aus dem Takt geraten kann.
    return bericht


def main():
    paths.bootstrap()
    befehl = sys.argv[1] if len(sys.argv) > 1 else "sichern"

    if befehl in ("--hilfe", "-h", "hilfe"):
        print(__doc__)
        print("  python sicherung.py               Abzug schreiben")
        print("  python sicherung.py liste         vorhandene Abzuege")
        print("  python sicherung.py zurueck NAME  Abzug einspielen")
        print("  python sicherung.py entferne NAME  Abzug loeschen")
        print("  python sicherung.py entferne --klartext")
        return 0

    if befehl == "liste":
        vorhanden = liste()
        if not vorhanden:
            print(f"Keine Abzuege in {ORDNER}.")
            return 0
        print(f"{'NAME':22} {'GROESSE':>10}  ABSCHNITTE  RAEUME  ZUSTAND")
        for name, _p, gr, stand in vorhanden:
            zustand = ("unvollstaendig"
                       if stand.get("vollstaendig") is False
                       or stand.get("fehler") else "vollstaendig")
            print(f"{name:22} {gr / 1e6:9.1f} MB  "
                  f"{stand.get('abschnitte', '?'):>10}  "
                  f"{len(stand.get('raeume') or {}):>6}  {zustand}")
        return 0

    if befehl in ("entferne", "loeschen"):
        namen = [a for a in sys.argv[2:] if not a.startswith("--")]
        trotzdem = "--trotzdem" in sys.argv
        if "--klartext" in sys.argv:
            # Alle, die noch Text im Klartext fuehren -- der haeufige
            # Fall nach dem Nachverschluesseln. VOR der Pruefung auf
            # leere Namen: sonst landet "entferne --klartext" in der
            # Aufforderung, Namen anzugeben, und die einzige Form, die
            # man tatsaechlich tippt, ist die, die nicht geht.
            namen = [n for n, pf, _g, _s in liste() if _hat_klartext(pf)]
            if not namen:
                print("Kein Abzug enthaelt Klartext.")
                return 0
            print(f"{len(namen)} Abzug/Abzuege mit Klartext: "
                  f"{', '.join(namen)}")
        if not namen:
            print("Namen angeben. 'liste' zeigt sie.")
            print("  python sicherung.py entferne 2026-09-10_07-56-42")
            print("  python sicherung.py entferne --klartext")
            return 1
        fehler = 0
        for n in namen:
            ok, meldung = entferne(n, trotzdem)
            print(("  " if ok else "  [!] ") + meldung)
            fehler += 0 if ok else 1
        return 1 if fehler else 0

    if befehl == "zurueck":
        name = None
        if "--neuester" in sys.argv:
            # Fuer einen Start ohne Menschen davor: ein Pod, dessen
            # Datenbank auf fluechtigem Speicher liegt, muss sich beim
            # Hochkommen selbst wiederherstellen. Er kann dabei keinen
            # Namen kennen.
            vollstaendige = [n for n, _p, _g, s in liste()
                             if s.get("vollstaendig") and not s.get("fehler")]
            if not vollstaendige:
                print("Kein vollstaendiger Abzug vorhanden.")
                # KEIN Fehler: beim allerersten Start gibt es keinen, und
                # das ist der Normalfall. Ein Fehlschlag hier liesse den
                # Pod in einer Schleife haengen, ohne dass etwas kaputt
                # waere.
                return 0
            name = vollstaendige[0]
            if not _leer_genug() and "--trotzdem" not in sys.argv:
                print(f"Es liegen schon Abschnitte in den Sammlungen. "
                      f"'{name}' wird NICHT eingespielt -- sonst"
                      f" ueberschriebe ein Start die Arbeit des "
                      f"vorherigen. Mit --trotzdem erzwingen.")
                return 0
            print(f"Spiele den neuesten Abzug ein: {name}")
        elif len(sys.argv) < 3:
            print("Name des Abzugs angeben. 'liste' zeigt sie.")
            print("  python sicherung.py zurueck --neuester")
            return 1
        bericht = hole_zurueck(
            name or sys.argv[2],
            fortschritt=lambda r, n, g: print(f"   {r}: {n}/{g}", end="\r"))
        print(" " * 50, end="\r")
        for raum, n in sorted(bericht["raeume"].items()):
            print(f"  {raum}: {n} Abschnitte eingespielt")
        for f in bericht["fehler"]:
            print(f"  [!] {f}")
        print("\nDer Stichwortindex baut sich beim naechsten Start neu auf.")
        return 1 if bericht["fehler"] else 0

    print(f"Sichere nach {ORDNER} ...")
    bericht = sichere(
        fortschritt=lambda r, n, g: print(f"   {r}: {n}/{g}", end="\r"))
    print(" " * 50, end="\r")
    for raum, angabe in sorted(bericht["raeume"].items()):
        print(f"  {raum:<28} {angabe['abschnitte']:>8} Abschnitte "
              f"(Dimension {angabe['dimension']})")
    for f in bericht["fehler"]:
        print(f"  [!] {f}")
    print(f"\n{bericht['abschnitte']} Abschnitte, "
          f"{bericht['bytes'] / 1e6:.1f} MB, {bericht['dauer']} s")
    print(f"Abzug: {bericht['pfad']}")
    return 1 if bericht["fehler"] else 0


if __name__ == "__main__":
    sys.exit(main())
