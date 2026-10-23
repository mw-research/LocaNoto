"""Alte ownCloud-10-Ablage mit dem Bestand von LocaNoto vergleichen.

    python altbestand.py liste > lokal.json                  im LocaNoto-Pod
    python altbestand.py vergleiche ALT lokal.json [--andere KONTEN]
    python altbestand.py hochladen ALT fehlt.txt [--pruefen]

WOFUER. Nach dem Wechsel auf eine neue Ablage bringt spiegeln.py hinueber,
was LocaNoto lokal hat. Das ist nicht alles, was in der alten lag:

  * Dateitypen, die der Abgleich nie holt (xlsx, pptx, zip, ...),
  * was nach dem letzten Abgleich dort abgelegt wurde,
  * die eigenen Dateien der Nutzer ausserhalb des LocaNoto-Baums.

Die ersten beiden findet dieses Skript und kann sie hochladen; die
dritten zaehlt es nur -- sie gehoeren den Nutzern, nicht LocaNoto.

WO DIE ALTEN DATEIEN LIEGEN. ownCloud 10 legt sie als gewoehnliche Dateien
ab: <datadir>/files/<konto>/files/<pfad>. ALT ist dieser Ordner des
Dienstkontos, also etwa /alt/files/admin/files.

ABLAUF IM CLUSTER. Ein Hilfs-Pod haengt das alte Volume NUR LESEND ein:

    apiVersion: v1
    kind: Pod
    metadata: {name: altbestand}
    spec:
      restartPolicy: Never
      containers:
        - name: py
          image: python:3.12-slim
          command: ["sleep", "86400"]
          securityContext: {runAsUser: 0}   # Dateien gehoeren www-data
          env:
            - {name: OWNCLOUD_URL, value: "http://opencloud:9200"}
            - {name: OWNCLOUD_USER, value: "admin"}
            - name: OWNCLOUD_PASSWORT
              valueFrom: {secretKeyRef: {name: <secret>, key: <token-key>}}
          volumeMounts: [{name: alt, mountPath: /alt, readOnly: true}]
      volumes:
        - {name: alt, persistentVolumeClaim: {claimName: owncloud-daten,
                                              readOnly: true}}

    kubectl exec deploy/locanoto -c app -- python altbestand.py liste > lokal.json
    kubectl cp altbestand.py altbestand:/tmp/altbestand.py
    kubectl cp lokal.json   altbestand:/tmp/lokal.json
    kubectl exec altbestand -- python /tmp/altbestand.py vergleiche \\
        /alt/files/admin/files /tmp/lokal.json --andere /alt/files
    kubectl exec altbestand -- python /tmp/altbestand.py hochladen \\
        /alt/files/admin/files /tmp/fehlt.txt --pruefen
    kubectl exec altbestand -- python /tmp/altbestand.py hochladen \\
        /alt/files/admin/files /tmp/fehlt.txt
    kubectl delete pod altbestand

Hochgeladen wird an denselben Pfad wie in der alten Ablage und nie
ueber eine vorhandene Datei. Der naechste Abgleich holt die neuen
Dokumente dann wie jede andere neue Datei und liest sie ein.

Verglichen wird ueber die Groesse. Gleich gross und doch verschieden ist
bei Dokumenten selten; --pruefsumme vergleicht zusaetzlich SHA-256 und
liest dafuer jede Datei ganz.
"""
import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
from urllib.parse import quote


# --- 1. LISTE: was LocaNoto hat, unter dem Pfad in der Ablage ---

def liste(pruefsumme=False):
    """{"wurzeln": [...], "dateien": {fernpfad: {groesse, sha256}}}.

    Dieselbe Abbildung wie spiegeln.py: je Raum der Ordner in der Ablage,
    darunter der Pfad relativ zur lokalen Ablage des Raums.
    """
    import paths
    paths.bootstrap()
    import owncloud
    import raeume
    import spiegeln

    wurzeln, dateien = [], {}
    for raum in sorted(owncloud.zuordnung_wirksam()):
        if raum not in raeume.liste():
            continue
        ziel = owncloud.ordner_fuer(raum)
        if not ziel:
            continue
        ziel = ziel.strip("/")
        wurzeln.append(ziel)
        ausser = (spiegeln._fremde_ordner(raum)
                  if raum == raeume.ALLGEMEIN else ())
        for voll, rel in spiegeln._dateien(owncloud.ablage(raum), ausser):
            eintrag = {"groesse": os.path.getsize(voll)}
            if pruefsumme:
                eintrag["sha256"] = _sha256(voll)
            dateien[f"{ziel}/{rel}"] = eintrag
    return {"wurzeln": sorted(set(wurzeln)), "dateien": dateien}


def _sha256(pfad):
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for stueck in iter(lambda: f.read(1 << 20), b""):
            h.update(stueck)
    return h.hexdigest()


# --- 2. VERGLEICHE: was in der alten Ablage liegt und LocaNoto nicht hat ---

def _alte_dateien(alt):
    """{rel: vollpfad} unterhalb von alt, ohne versteckte Dateien."""
    aus = {}
    for pfad, unter, namen in os.walk(alt):
        unter[:] = [u for u in unter if not u.startswith(".")]
        for n in namen:
            if n.startswith("."):
                continue
            voll = os.path.join(pfad, n)
            aus[os.path.relpath(voll, alt).replace("\\", "/")] = voll
    return aus


def _unter(rel, wurzeln):
    return any(rel == w or rel.startswith(w + "/") for w in wurzeln)


def vergleiche(alt, lokal, pruefsumme=False):
    """Bericht als dict. Nichts wird veraendert."""
    wurzeln = lokal.get("wurzeln") or []
    bekannt = lokal.get("dateien") or {}
    alte = _alte_dateien(alt)

    fehlt, abweichend, gleich = [], [], 0
    for rel, voll in sorted(alte.items()):
        e = bekannt.get(rel)
        if e is None:
            fehlt.append(rel)
            continue
        if os.path.getsize(voll) != e.get("groesse"):
            abweichend.append(rel)
        elif pruefsumme and e.get("sha256") and _sha256(voll) != e["sha256"]:
            abweichend.append(rel)
        else:
            gleich += 1
    return {
        "gleich": gleich,
        "abweichend": abweichend,
        "fehlt_im_baum": [r for r in fehlt if _unter(r, wurzeln)],
        "fehlt_ausserhalb": [r for r in fehlt if not _unter(r, wurzeln)],
        "nur_lokal": sorted(set(bekannt) - set(alte)),
        "groesse_fehlt": sum(os.path.getsize(alte[r]) for r in fehlt),
    }


def andere_konten(dateiordner, dienstkonto):
    """{konto: (anzahl, bytes)} der eigenen Dateien anderer Konten.

    Nur Zahlen, keine Namen: es sind die Dateien der Nutzer, und fuer
    die Entscheidung genuegt, ob und wie viel dort liegt.
    """
    aus = {}
    for konto in sorted(os.listdir(dateiordner)):
        ordner = os.path.join(dateiordner, konto, "files")
        if konto == dienstkonto or not os.path.isdir(ordner):
            continue
        dateien = _alte_dateien(ordner)
        if dateien:
            aus[konto] = (len(dateien),
                          sum(os.path.getsize(v) for v in dateien.values()))
    return aus


def _endung(rel):
    return os.path.splitext(rel)[1].lower() or "(ohne)"


def _mb(n):
    return f"{n / 1e6:.1f} MB"


# --- 3. HOCHLADEN: das Fehlende in die neue Ablage ---

def _dav(methode, url, benutzer, passwort, daten=None, kopf=None):
    anfrage = urllib.request.Request(url, data=daten, method=methode)
    zugang = base64.b64encode(f"{benutzer}:{passwort}".encode()).decode()
    anfrage.add_header("Authorization", "Basic " + zugang)
    for k, v in (kopf or {}).items():
        anfrage.add_header(k, v)
    try:
        with urllib.request.urlopen(anfrage, timeout=120) as a:
            return a.status
    except urllib.error.HTTPError as e:
        return e.code


def hochladen(alt, relpfade, url, benutzer, passwort, pruefen=False,
              sagen=print):
    """(hochgeladen, vorhanden, fehler). Ueberschreibt nie."""
    basis = f"{url.rstrip('/')}/remote.php/dav/files/{quote(benutzer)}"
    angelegt = set()
    hoch = da = fehler = 0
    for n, rel in enumerate(relpfade, start=1):
        voll = os.path.join(alt, *rel.split("/"))
        if not os.path.isfile(voll):
            sagen(f"  [!] {rel}: nicht in der alten Ablage")
            fehler += 1
            continue
        ziel = f"{basis}/{quote(rel)}"
        stand = _dav("PROPFIND", ziel, benutzer, passwort,
                     kopf={"Depth": "0"})
        if stand == 207:
            da += 1
            continue
        if stand != 404:
            sagen(f"  [!] {rel}: Ablage antwortete {stand}")
            fehler += 1
            continue
        if pruefen:
            sagen(f"  wuerde hochladen: {rel}")
            hoch += 1
            continue
        teile = rel.split("/")[:-1]
        for i in range(1, len(teile) + 1):
            ordner = "/".join(teile[:i])
            if ordner not in angelegt:
                # 405 heisst: gibt es schon.
                _dav("MKCOL", f"{basis}/{quote(ordner)}", benutzer, passwort)
                angelegt.add(ordner)
        with open(voll, "rb") as f:
            stand = _dav("PUT", ziel, benutzer, passwort, daten=f.read())
        if stand in (200, 201, 204):
            hoch += 1
        else:
            sagen(f"  [!] {rel}: Hochladen ergab {stand}")
            fehler += 1
        if n % 25 == 0:
            sagen(f"  {n}/{len(relpfade)}")
    return hoch, da, fehler


# --- AUFRUF ---

def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    teil = p.add_subparsers(dest="schritt", required=True)

    a = teil.add_parser("liste", help="Bestand von LocaNoto als JSON")
    a.add_argument("--pruefsumme", action="store_true")

    b = teil.add_parser("vergleiche", help="alte Ablage gegen die Liste")
    b.add_argument("alt", help="Ordner des Dienstkontos, .../files/<konto>/files")
    b.add_argument("lokal", help="Ausgabe von 'liste'")
    b.add_argument("--andere", metavar="DATEIORDNER",
                   help="<datadir>/files: eigene Dateien der anderen Konten zaehlen")
    b.add_argument("--pruefsumme", action="store_true")
    b.add_argument("--ausgabe", default="",
                   help="Liste des Fehlenden (Vorgabe: fehlt.txt neben lokal)")

    c = teil.add_parser("hochladen", help="Fehlendes in die neue Ablage")
    c.add_argument("alt")
    c.add_argument("liste", help="Ausgabe von 'vergleiche' (fehlt.txt)")
    c.add_argument("--pruefen", action="store_true",
                   help="nur zeigen, nichts hochladen")
    args = p.parse_args()

    if args.schritt == "liste":
        json.dump(liste(args.pruefsumme), sys.stdout, ensure_ascii=False,
                  indent=1)
        return 0

    if args.schritt == "vergleiche":
        with open(args.lokal, encoding="utf-8") as f:
            lokal = json.load(f)
        b = vergleiche(args.alt, lokal, args.pruefsumme)
        fehlt = b["fehlt_im_baum"] + b["fehlt_ausserhalb"]
        print(f"gleich:               {b['gleich']}")
        print(f"abweichende Groesse:  {len(b['abweichend'])}")
        print(f"fehlt im LocaNoto-Baum:   {len(b['fehlt_im_baum'])}")
        print(f"fehlt ausserhalb:         {len(b['fehlt_ausserhalb'])}"
              f"  (Handordner oder Reste)")
        print(f"zusammen fehlend:     {len(fehlt)}, {_mb(b['groesse_fehlt'])}")
        print(f"nur in LocaNoto:      {len(b['nur_lokal'])}"
              f"  (bringt spiegeln.py hinueber)")
        if fehlt:
            print("\nFehlend nach Endung:")
            for endung, zahl in Counter(map(_endung, fehlt)).most_common():
                print(f"  {endung:<10} {zahl}")
        for titel, liste_ in (("Fehlend im Baum", b["fehlt_im_baum"]),
                              ("Fehlend ausserhalb", b["fehlt_ausserhalb"]),
                              ("Abweichend", b["abweichend"])):
            if liste_:
                print(f"\n{titel} (erste 30):")
                for rel in liste_[:30]:
                    print(f"  {rel}")
        if args.andere:
            konto = os.path.basename(os.path.dirname(
                os.path.normpath(args.alt)))
            andere = andere_konten(args.andere, konto)
            print(f"\nEigene Dateien anderer Konten: {len(andere)} Konten")
            for k, (zahl, groesse) in andere.items():
                print(f"  {k:<24} {zahl:>6} Dateien  {_mb(groesse)}")
        ausgabe = args.ausgabe or os.path.join(
            os.path.dirname(os.path.abspath(args.lokal)), "fehlt.txt")
        with open(ausgabe, "w", encoding="utf-8") as f:
            f.write("".join(r + "\n" for r in fehlt))
        print(f"\nListe des Fehlenden: {ausgabe} -- vor dem Hochladen "
              f"lesen und streichen, was nicht hinueber soll.")
        return 0

    url = os.getenv("OWNCLOUD_URL", "").strip()
    benutzer = os.getenv("OWNCLOUD_USER", "").strip()
    passwort = os.getenv("OWNCLOUD_PASSWORT", "")
    if not (url and benutzer and passwort):
        print("OWNCLOUD_URL, OWNCLOUD_USER und OWNCLOUD_PASSWORT fehlen.")
        return 2
    with open(args.liste, encoding="utf-8") as f:
        relpfade = [z.strip() for z in f if z.strip()]
    hoch, da, fehler = hochladen(args.alt, relpfade, url, benutzer, passwort,
                                 pruefen=args.pruefen)
    print(f"\n{'wuerde hochladen' if args.pruefen else 'hochgeladen'}: "
          f"{hoch}, lag schon dort: {da}, Fehler: {fehler}")
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
