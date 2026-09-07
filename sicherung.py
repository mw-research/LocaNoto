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


def sichere(fortschritt=None):
    """Schreibt einen vollstaendigen Abzug. Rueckgabe: Bericht als dict.

    Erst in einen Ordner mit Endung .teil, dann umbenannt. Ein
    abgebrochener Abzug soll nicht als brauchbarer daliegen -- das faellt
    sonst erst auf, wenn man ihn braucht.
    """
    name = time.strftime("%Y-%m-%d_%H-%M-%S")
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

        vektoren, zeilen, gelesen = [], [], 0
        try:
            while gelesen < gesamt:
                b = sml.get(include=["documents", "metadatas", "embeddings"],
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
        except Exception as e:
            bericht["fehler"].append({"raum": kennung, "grund": str(e)})
            continue

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

    with open(os.path.join(vorlaeufig, "stand.json"), "w",
              encoding="utf-8") as f:
        json.dump(bericht, f, ensure_ascii=False, indent=2)

    # Die Raumverwaltung mit sichern: ein Abzug ohne sie liesse die
    # Abschnitte wiederherstellen, aber niemand wuesste mehr, wer sie
    # sehen darf. Der Schluessel geht NICHT mit -- er gehoert in eine
    # andere Aufbewahrung als die Daten, die er lesbar macht.
    for datei in ("raeume.json", "owncloud.json"):
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
    """Loescht die aeltesten Abzuege ueber BEHALTEN hinaus."""
    if BEHALTEN <= 0:
        return 0
    vorhanden = liste()
    weg = 0
    for name, pfad, _gr, _stand in vorhanden[BEHALTEN:]:
        shutil.rmtree(pfad, ignore_errors=True)
        weg += 1
    return weg


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
        for a in range(0, len(zeilen), STAPEL):
            teil = zeilen[a:a + STAPEL]
            try:
                sml.upsert(
                    ids=[z["id"] for z in teil],
                    documents=[z.get("text") or "" for z in teil],
                    metadatas=[z.get("meta") or {} for z in teil],
                    embeddings=matrix[a:a + len(teil)].tolist())
                geschrieben += len(teil)
            except Exception as e:
                bericht["fehler"].append({"raum": kennung, "grund": str(e)})
                break
            if fortschritt:
                fortschritt(kennung, geschrieben, len(zeilen))
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
        return 0

    if befehl == "liste":
        vorhanden = liste()
        if not vorhanden:
            print(f"Keine Abzuege in {ORDNER}.")
            return 0
        print(f"{'NAME':22} {'GROESSE':>10}  ABSCHNITTE  RAEUME")
        for name, _p, gr, stand in vorhanden:
            print(f"{name:22} {gr / 1e6:9.1f} MB  "
                  f"{stand.get('abschnitte', '?'):>10}  "
                  f"{len(stand.get('raeume') or {})}")
        return 0

    if befehl == "zurueck":
        if len(sys.argv) < 3:
            print("Name des Abzugs angeben. 'liste' zeigt sie.")
            return 1
        bericht = hole_zurueck(
            sys.argv[2],
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
