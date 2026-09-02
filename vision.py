"""Bilder aus dem Chat beschreiben lassen.

Der Chat kann Bilder entgegennehmen -- einen Bildschirmausschnitt, ein Foto
einer Anlage, eine abfotografierte Seite. Das Sehmodell wandelt sie in Text
um, und dieser Text wird an zwei Stellen gebraucht:

1. als zusaetzliche Suchsonde, damit die Dokumentensuche findet, was zum
   Bild gehoert -- ohne ihn koennte sie nur nach dem suchen, was der Nutzer
   dazu tippt, und "was ist das hier?" trifft nichts;
2. im Kontext der Antwort, klar als Bild gekennzeichnet, damit das
   Sprachmodell nicht behauptet, etwas im Handbuch gelesen zu haben.

Das Chat-Modell selbst bekommt das Bild nicht: es kann in dieser Aufteilung
ein reines Textmodell sein, waehrend die Bildverarbeitung an dem Endpunkt
haengt, der VISION_BASE_URL zugewiesen ist.
"""
import base64
import io
import os

import paths
import llm

VISION_TIMEOUT = paths.env_float("VISION_TIMEOUT", 120)

# Kantenlaenge, auf die ein hochgeladenes Bild gebracht wird. Groesser bringt
# selten mehr Erkennung, kostet aber Speicher im Sehmodell.
MAX_KANTE = paths.env_int("CHAT_BILD_MAX_KANTE", 1280)

# Obergrenze fuer die Laenge der Beschreibung. 0 = keine.
#
# Gebraucht wird der lesbare Inhalt eines Bildes, nicht die Feststellung,
# dass der Hintergrund einheitlich weiss ist. Bei einem grossen Sehmodell
# macht die Erzeugung den Hauptteil der Zeit aus -- ein Deckel wirkt dort
# unmittelbar, waehrend an der Bildgroesse kaum etwas zu holen ist.
MAX_TOKENS = paths.env_int("VISION_MAX_TOKENS", 0)

ERLAUBTE_TYPEN = ["png", "jpg", "jpeg", "webp", "gif", "bmp"]

PROMPT = """Beschreibe dieses Bild vollstaendig und sachlich, damit jemand, der es
nicht sieht, damit arbeiten kann.

- Gib saemtlichen lesbaren Text woertlich wieder: Beschriftungen, Feldnamen,
  Schaltflaechen, Menuepunkte, Fehlermeldungen, Zahlenwerte, Einheiten.
- Beschreibe bei Bildschirmausschnitten, welche Maske oder welcher Dialog zu
  sehen ist und wie die Elemente angeordnet sind.
- Beschreibe bei Zeichnungen und Diagrammen Achsen, Bemassungen, Bauteile und
  ihre Beziehung zueinander.
- Erfinde nichts. Was unleserlich ist, benennst du als unleserlich.
"""


def _als_datenurl(daten, mime="image/jpeg"):
    return f"data:{mime};base64," + base64.b64encode(daten).decode("ascii")


def vorbereiten(daten):
    """Verkleinert das Bild und wandelt es nach JPEG.

    Ein Bildschirmfoto aus der Zwischenablage kann mehrere Megabyte gross
    sein; unveraendert weitergereicht belastet es den Modellserver ohne
    Gewinn an Erkennung.
    """
    from PIL import Image

    bild = Image.open(io.BytesIO(daten))
    if max(bild.size) > MAX_KANTE:
        faktor = MAX_KANTE / max(bild.size)
        bild = bild.resize((int(bild.width * faktor), int(bild.height * faktor)),
                           Image.Resampling.LANCZOS)
    if bild.mode in ("RGBA", "P", "LA"):
        bild = bild.convert("RGB")
    puffer = io.BytesIO()
    bild.save(puffer, format="JPEG", quality=90)
    return puffer.getvalue()


def beschreibe(daten, frage=""):
    """Beschreibung eines Bildes als Text.

    frage ist die Frage des Nutzers. Sie geht mit in den Prompt, damit das
    Sehmodell weiss, worauf es achten soll -- bei "welche Fehlermeldung steht
    da?" ist eine andere Beschreibung nuetzlich als bei "welche Felder gibt
    es?".
    """
    jpeg = vorbereiten(daten)
    zusatz = (f"\n\nDer Nutzer fragt dazu: {frage}\nGeh in der Beschreibung "
              f"besonders auf das ein, was fuer diese Frage zaehlt."
              if frage.strip() else "")

    zusatz_args = {"max_tokens": MAX_TOKENS} if MAX_TOKENS else {}
    antwort = llm.client("VISION").chat.completions.create(
        model=llm.modell("VISION"),
        timeout=VISION_TIMEOUT,
        **zusatz_args,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT + zusatz},
                {"type": "image_url", "image_url": {"url": _als_datenurl(jpeg)}},
            ],
        }],
    )
    return (antwort.choices[0].message.content or "").strip()


def anhang_verzeichnis(benutzer):
    """Ablage fuer Bilder eines Nutzers, neben seinen Chats."""
    pfad = os.path.join(paths.CHATS_DIR, benutzer, "anhaenge")
    os.makedirs(pfad, exist_ok=True)
    return pfad


def speichern(daten, benutzer, name):
    """Legt das Bild ab und gibt den Pfad zurueck.

    Gespeichert wird die verkleinerte Fassung: sie reicht zur Anzeige im
    Verlauf, und der Chat-Ordner waechst nicht mit jedem Bildschirmfoto um
    mehrere Megabyte.
    """
    ziel = os.path.join(anhang_verzeichnis(benutzer), name)
    with open(ziel, "wb") as f:
        f.write(vorbereiten(daten))
    return ziel
