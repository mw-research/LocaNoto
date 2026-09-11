"""Ein Ticket fuer genau eine Fundstelle, fuer kurze Zeit.

Die Quellenansicht im eigenen Tab braucht eine Berechtigung -- ein
neuer Tab ist eine neue Sitzung, und dort ist niemand angemeldet.

Der naheliegende Weg waere, die Anmeldung mitzugeben. Er ist falsch:
die Bescheinigung stuende dann in jedem Quellenverweis, also in jeder
Antwort, und wer eine Antwort weiterleitet, gaebe seine Anmeldung mit.

Ein Ticket kann viel weniger. Es nennt genau eine Fundstelle -- Raum,
Datei, Seite -- und gilt Minuten. Wer es abfaengt, sieht diese eine
Seite und sonst nichts, und morgen auch die nicht mehr.

Es steht NICHT im gespeicherten Verlauf: die Verweise entstehen beim
Zeichnen, nicht beim Schreiben. Ein alter Chat traegt weiter den
blossen Text "[Datei, Seite 3]" und bekommt beim Ansehen ein frisches.
"""
import base64
import json
import os
import time

import geheim
import paths

# Wie lange ein Ticket gilt. Kurz genug, dass ein weitergereichter
# Verweis nichts mehr wert ist; lang genug, um eine Antwort zu lesen
# und dann nachzusehen.
MINUTEN = paths.env_int("QUELLE_TICKET_MINUTEN", 30)


def _kern(raum, datei, seite, benutzer):
    return json.dumps({"r": raum, "d": datei, "s": str(seite),
                       "b": benutzer, "bis": int(time.time() + MINUTEN * 60)},
                      sort_keys=True, separators=(",", ":"))


def stelle_aus(raum, datei, seite, benutzer):
    """Ein Ticket, oder "" ohne Schluessel."""
    if not geheim.verfuegbar():
        return ""
    kern = _kern(raum, datei, seite, benutzer)
    roh = base64.urlsafe_b64encode(kern.encode("utf-8")).decode().rstrip("=")
    return roh + "." + geheim.signiere(kern.encode("utf-8"))


def loese_ein(ticket):
    """Die Fundstelle hinter dem Ticket, oder None.

    Geprueft wird BEIDES: die Unterschrift und die Frist. Und danach
    noch einmal die Berechtigung des genannten Nutzers -- ein Ticket
    ist eine Abkuerzung fuer den Weg dorthin, kein Ersatz fuer das
    Recht, dort zu sein. Wer aus einem Raum entfernt wurde, kommt auch
    mit einem gueltigen Ticket nicht mehr hinein.
    """
    try:
        roh, unterschrift = str(ticket).rsplit(".", 1)
        fehlt = "=" * (-len(roh) % 4)
        kern = base64.urlsafe_b64decode(roh + fehlt).decode("utf-8")
    except Exception:
        return None
    if not geheim.pruefe_signatur(kern.encode("utf-8"), unterschrift):
        return None
    try:
        daten = json.loads(kern)
        if time.time() > int(daten["bis"]):
            return None
    except Exception:
        return None

    import raeume
    if not raeume.darf_lesen(daten["b"], daten["r"]):
        return None
    return {"raum": daten["r"], "datei": daten["d"],
            "seite": daten["s"], "benutzer": daten["b"]}
