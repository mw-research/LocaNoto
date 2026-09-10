"""Liegt ein Verzeichnis auf einem verschluesselten Datentraeger?

Die Grundlage der ganzen Absicherung ist ein verschluesseltes Volume --
alles, was die Anwendung selbst verschluesselt, ist die zweite Schicht
darueber. Die Originaldokumente, die Vektoren und der Stichwortindex
lassen sich nicht verdecken; sie muessen lesbar sein, damit die Anwendung
arbeitet. Wer die Platte hat, liest sie, wenn die Platte offen ist.

Deshalb wird hier NACHGESEHEN statt gefragt. Ein Haken in einer
Einrichtungsanleitung sagt aus, dass jemand ihn gesetzt hat; /sys sagt
aus, was wirklich unter dem Verzeichnis liegt.

DREI ZUSTAENDE, und der dritte ist wichtig:

    "ja"        ein dm-crypt-Geraet traegt das Verzeichnis
    "nein"      ein gewoehnliches Blockgeraet, unverschluesselt
    "unklar"    laesst sich hier nicht feststellen

"unklar" wird nie zu "ja" geschoent. Ein Container ohne /sys, ein
Netzlaufwerk, ein Dateisystem, dessen Herkunft nicht aufloesbar ist --
in all diesen Faellen weiss die Anwendung es nicht, und das gehoert
gesagt. Eine Zusicherung, die auf Nichtwissen beruht, ist schlechter als
keine: nach ihr richtet sich jemand.
"""
import os


def _mounts():
    """[(mountpunkt, geraet, dateisystem)] -- laengster Punkt zuerst."""
    try:
        with open("/proc/mounts", "r", encoding="utf-8") as f:
            zeilen = f.read().splitlines()
    except OSError:
        return []
    aus = []
    for z in zeilen:
        teile = z.split()
        if len(teile) < 3:
            continue
        geraet, punkt, fs = teile[0], teile[1].replace("\\040", " "), teile[2]
        aus.append((punkt, geraet, fs))
    return sorted(aus, key=lambda x: -len(x[0]))


def _traeger(pfad):
    """(mountpunkt, geraet, dateisystem) fuer diesen Pfad."""
    ziel = os.path.abspath(pfad)
    for punkt, geraet, fs in _mounts():
        if ziel == punkt or ziel.startswith(punkt.rstrip("/") + "/"):
            return punkt, geraet, fs
    return None, None, None


def _dm_name(geraet):
    """Der dm-Name eines Geraets, etwa 'dm-3'. None, wenn keiner."""
    if not geraet:
        return None
    name = os.path.basename(geraet)
    if name.startswith("dm-"):
        return name
    # /dev/mapper/<name> ist ein Verweis auf /dev/dm-N.
    if "/mapper/" in geraet:
        try:
            return os.path.basename(os.path.realpath(geraet))
        except OSError:
            return None
    return None


def _ist_crypt(dm):
    """Traegt dieses Device-Mapper-Geraet eine Verschluesselung?

    /sys/class/block/dm-N/dm/uuid beginnt bei dm-crypt mit "CRYPT-".
    LUKS steht dann als CRYPT-LUKS1 oder CRYPT-LUKS2 darin, ein einfaches
    dm-crypt als CRYPT-PLAIN.
    """
    try:
        with open(f"/sys/class/block/{dm}/dm/uuid",
                  "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


# Dateisysteme, bei denen die Frage anders lautet: was unter der Freigabe
# liegt, entscheidet der andere Rechner, und von hier ist es nicht zu
# sehen.
FREIGABEN = {"nfs", "nfs4", "cifs", "smb3", "fuse.sshfs", "9p", "virtiofs"}


def lage(pfad):
    """(zustand, meldung) -- "ja", "nein" oder "unklar"."""
    if os.name != "posix":
        return "unklar", ("Nur unter Linux feststellbar. Auf diesem System "
                          "laeuft die Anwendung ohnehin nicht im Betrieb.")
    punkt, geraet, fs = _traeger(pfad)
    if punkt is None:
        return "unklar", (f"Zu {pfad} laesst sich kein Datentraeger "
                          f"aufloesen -- /proc/mounts kennt ihn nicht.")
    if fs in FREIGABEN:
        return "unklar", (
            f"{punkt} ist eine Netzfreigabe ({fs}). Ob dort verschluesselt "
            f"wird, entscheidet der andere Rechner, und von hier ist es "
            f"nicht zu sehen. Nebenbei: SQLite gehoert nicht auf eine "
            f"Freigabe -- siehe LOCANOTO_INDEX.")
    if fs in ("overlay", "tmpfs"):
        return "unklar", (
            f"{punkt} liegt auf {fs} -- dem Schreibbereich des Containers. "
            f"Das ist kein persistenter Speicher: der Bestand ist beim "
            f"naechsten Ausrollen weg. Setze LOCANOTO_DATEN auf ein "
            f"eingehaengtes Volume.")

    dm = _dm_name(geraet)
    if dm:
        uuid = _ist_crypt(dm)
        if uuid and uuid.startswith("CRYPT-"):
            art = uuid.split("-")[1] if "-" in uuid else "?"
            return "ja", (f"{punkt} liegt auf {geraet} -- ein "
                          f"verschluesselter Datentraeger ({art}). Eine "
                          f"ausgebaute Platte gibt nichts her.")
        if uuid is not None:
            return "nein", (
                f"{punkt} liegt auf {geraet} (Device Mapper, aber KEINE "
                f"Verschluesselung: {uuid.split('-')[0] or 'unbekannt'}).")
        return "unklar", (f"{punkt} liegt auf {geraet}; /sys ist von hier "
                          f"nicht lesbar. Im Container ist das normal.")
    if geraet and geraet.startswith("/dev/"):
        return "nein", (
            f"{punkt} liegt auf {geraet} -- ein gewoehnliches Blockgeraet "
            f"ohne Verschluesselung. Wer die Platte ausbaut, liest die "
            f"Dokumente, den Stichwortindex und die Vektoren.")
    return "unklar", (f"{punkt} liegt auf '{geraet}' ({fs}) -- daraus "
                      f"laesst sich nicht ablesen, ob verschluesselt wird.")


def kurz(pfad):
    zustand, meldung = lage(pfad)
    return {"ja": "verschluesselt", "nein": "NICHT verschluesselt"}.get(
        zustand, "unklar"), meldung
