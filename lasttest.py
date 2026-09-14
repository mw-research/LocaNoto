"""Wie viele Leute gleichzeitig? -- python lasttest.py

Misst gegen die SCHNITTSTELLE, nicht gegen die Oberflaeche. Das ist
Absicht: die Oberflaeche haelt Sitzungen im Arbeitsspeicher und laesst
sich nicht vervielfachen, die Schnittstelle ist zustandslos. Was hier
herauskommt, ist also die Obergrenze dessen, was die Anwendung
LEISTEN kann -- nicht das, was Streamlit davon durchlaesst.

    python lasttest.py --adresse http://127.0.0.1:8600 \\
        --token DEIN_TOKEN --gleichzeitig 1,2,4,8 --je 6

Je Stufe der Gleichzeitigkeit werden --je Fragen gestellt und die
Zeiten je Abschnitt genommen. Am Ende steht eine Tabelle, aus der sich
ablesen laesst, WO es klemmt:

    Einbettung      der Modellserver (Vektorisierung)
    Vektorsuche     Chroma
    Stichwortsuche  SQLite
    Rangfolge       Reranker -- Endpunkt oder Modell im Abbild
    Antwort         der Modellserver (Erzeugung)

Die letzte Zahl ist fast immer die groesste, und das ist richtig so.
Interessant ist, welche der anderen MITWAECHST, wenn mehr Leute
gleichzeitig fragen -- das ist die, die nicht parallel kann.

WARNUNG: das hier erzeugt echte Last auf dem Modellserver. Nicht
waehrend der Arbeitszeit gegen den Betrieb laufen lassen.
"""
import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

# Ohne eigene Fragen diese. Sie sind bewusst verschieden: dieselbe
# Frage N-mal zu stellen misst den Zwischenspeicher und nicht die Last.
FRAGEN = [
    "Welche Fristen sind zu beachten?",
    "Wie wird ein neuer Eintrag angelegt?",
    "Welche Angaben gehoeren in die Stammdaten?",
    "Was ist beim Abschluss eines Vorgangs zu pruefen?",
    "Welche Rollen gibt es und was duerfen sie?",
    "Wo finde ich die Uebersicht der offenen Posten?",
]

STUFEN = ("einbettung", "vektorsuche", "stichwortsuche", "rangfolge")

# Der Kopf, den die Schnittstelle liest. Er heisst ausdruecklich NICHT
# Authorization: api.benutzer() nimmt x_locanoto_token entgegen, woraus
# FastAPI diesen Namen ableitet.
#
# Das stand hier einmal als "Authorization: Bearer", weil das ueblich ist.
# Die Folge war kein Fehler im Werkzeug, sondern eine vollstaendige
# Tabelle aus Nullen: der fremde Kopf wird still verworfen, die Anfrage
# kommt ohne Token an, und die Schnittstelle antwortet voellig zu Recht
# mit 401. Der Selbsttest vergleicht diesen Namen deshalb mit dem, den
# api.py tatsaechlich entgegennimmt.
KOPF = "X-LocaNoto-Token"


def _eine_frage(adresse, token, frage, zeitlimit):
    # token ist EIN Token. Die Auswahl trifft _runde -- siehe dort,
    # warum das nicht gleichgueltig ist.
    """(gesamt_ms, zeiten, fehler)."""
    t0 = time.perf_counter()
    try:
        a = requests.post(
            adresse.rstrip("/") + "/frage",
            headers={KOPF: token},
            json={"frage": frage},
            timeout=zeitlimit)
    except requests.RequestException as e:
        return (time.perf_counter() - t0) * 1000, {}, f"{type(e).__name__}"
    gesamt = (time.perf_counter() - t0) * 1000
    if a.status_code != 200:
        return gesamt, {}, f"HTTP {a.status_code}"
    try:
        daten = a.json()
    except ValueError:
        return gesamt, {}, "keine JSON-Antwort"
    zeiten = dict((daten.get("zahlen") or {}).get("zeiten") or {})
    # Die Erzeugung ist das, was uebrig bleibt: alles andere ist
    # serverseitig gemessen, die Gesamtzeit hier.
    #
    # Bleibt NICHTS uebrig, wird daraus keine Null. Eine Null hiesse
    # "die Antwort entstand in null Millisekunden" -- und das ist
    # keine Messung, sondern eine Notluege. Es hiesse in Wahrheit,
    # dass die Stufenzeiten nicht zu dieser Anfrage gehoeren, etwa
    # weil die Antwort aus einem Zwischenspeicher kam. Dann gehoert
    # ein Fragezeichen hin.
    rest = round(gesamt - sum(v for v in zeiten.values()
                              if isinstance(v, (int, float))))
    zeiten["antwort"] = rest if rest >= 0 else None
    return gesamt, zeiten, ""


def _runde(adresse, token, gleichzeitig, je, zeitlimit, fragen):
    """Eine Stufe. (ergebnisse, fehler).

    token darf mehrere sein. Das ist kein Komfort, sondern eine
    Frage der Gueltigkeit: das Entnahmebudget zaehlt JE NUTZER. Mit
    einem einzigen Token treffen sechzehn gleichzeitige Anfragen
    gebuendelt eine Schwelle, die sich bei sechzehn Menschen auf
    sechzehn Konten verteilt haette. Gemessen wuerde dann nicht die
    Gleichzeitigkeit, sondern das Budget -- und die Tabelle saehe aus
    wie ein Engpass, wo keiner ist.
    """
    aufgaben = [fragen[i % len(fragen)] for i in range(je)]
    ergebnisse, fehler = [], []
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=gleichzeitig) as pool:
        for gesamt, zeiten, grund in pool.map(
                lambda p: _eine_frage(adresse, token[p[0] % len(token)],
                                      p[1], zeitlimit),
                list(enumerate(aufgaben))):
            if grund:
                fehler.append(grund)
            else:
                ergebnisse.append((gesamt, zeiten))
    return ergebnisse, fehler, time.perf_counter() - t0


def _p(werte, anteil):
    if not werte:
        return 0
    werte = sorted(werte)
    return werte[min(len(werte) - 1, int(len(werte) * anteil))]


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--adresse", default="http://127.0.0.1:8600")
    p.add_argument("--token", required=True,
                   help="Zugangstoken (create_token.py). Mehrere durch "
                        "Komma getrennt -- dann wird reihum gefragt, "
                        "wie es mehrere Menschen taeten. Das Budget "
                        "zaehlt je Nutzer, siehe _runde().")
    p.add_argument("--gleichzeitig", default="1,2,4,8",
                   help="Stufen, kommagetrennt (Vorgabe 1,2,4,8)")
    p.add_argument("--je", type=int, default=6,
                   help="Fragen je Stufe (Vorgabe 6)")
    p.add_argument("--zeitlimit", type=int, default=300)
    p.add_argument("--fragen", default="",
                   help="Datei mit einer Frage je Zeile")
    args = p.parse_args()

    token = [t.strip() for t in args.token.split(",") if t.strip()]
    if not token:
        print("Kein Token.")
        return 2

    fragen = FRAGEN
    if args.fragen:
        with open(args.fragen, encoding="utf-8") as f:
            fragen = [z.strip() for z in f if z.strip()]
    if not fragen:
        print("Keine Fragen.")
        return 2

    print("=" * 72)
    print(f"LASTTEST  {args.adresse}")
    print("=" * 72)
    print(f"{len(fragen)} verschiedene Fragen, je Stufe {args.je} "
          f"Anfragen, {len(token)} Token.")
    if len(token) == 1:
        print("HINWEIS: nur EIN Token. Das Entnahmebudget zaehlt je")
        print("Nutzer -- ab etwa vierzig Fragen in der Stunde antwortet")
        print("die Schnittstelle mit 429, und die Messung misst dann das")
        print("Budget statt der Last. Fuer hohe Stufen mehrere Token")
        print("anlegen und durch Komma trennen.")
    print()

    kopf = (f"{'gleichz.':>8} {'ok':>4} {'Fehler':>6} {'Durchsatz':>10} "
            f"{'Gesamt p50':>11} {'p90':>7}   "
            + " ".join(f"{s[:9]:>9}" for s in STUFEN) + f" {'Antwort':>9}")
    print(kopf)
    print("-" * len(kopf))

    for stufe in [int(x) for x in args.gleichzeitig.split(",") if x.strip()]:
        ergebnisse, fehler, dauer = _runde(
            args.adresse, token, stufe, args.je, args.zeitlimit, fragen)
        gesamt = [g for g, _z in ergebnisse]
        durchsatz = len(ergebnisse) / dauer * 60 if dauer else 0
        zeile = (f"{stufe:>8} {len(ergebnisse):>4} {len(fehler):>6} "
                 f"{durchsatz:>7.1f}/min "
                 f"{_p(gesamt, 0.5)/1000:>9.1f}s "
                 f"{_p(gesamt, 0.9)/1000:>6.1f}s  ")
        for s in STUFEN + ("antwort",):
            werte = [z.get(s) for _g, z in ergebnisse
                     if isinstance(z.get(s), (int, float))]
            if werte:
                zeile += f" {_p(werte, 0.5):>8}ms"[:10]
            else:
                zeile += f" {'?':>8}  "[:10]
        print(zeile)
        if fehler:
            haeufig = {}
            for f in fehler:
                haeufig[f] = haeufig.get(f, 0) + 1
            print(" " * 20 + "Fehler: "
                  + ", ".join(f"{k} ({v}x)" for k, v in haeufig.items()))

        # Keine einzige Antwort: die weiteren Stufen messen dasselbe
        # Nichts. Vier Zeilen Nullen sehen aus wie ein Ergebnis und sind
        # keines -- lieber hier abbrechen und sagen, woran es liegt.
        if not ergebnisse:
            print()
            if all(f == "HTTP 429" for f in fehler):
                print("KEINE MESSUNG -- das Entnahmebudget ist")
                print("  aufgebraucht. Es zaehlt JE NUTZER in einem")
                print("  gleitenden Fenster von 60 Minuten; mit einem")
                print("  einzigen Token laufen alle Anfragen auf dasselbe")
                print("  Konto. Entweder mehrere Token durch Komma")
                print("  trennen, oder eine Stunde warten, oder fuer den")
                print("  Messlauf BUDGET_ABSCHNITTE heraufsetzen.")
            elif all(f == "HTTP 401" for f in fehler):
                print("KEINE MESSUNG -- die Schnittstelle weist das Token ab.")
                print(f"  Der Kopf heisst {KOPF}. Zum Nachstellen von Hand:")
                print(f"    curl -H \"{KOPF}: DEIN_TOKEN\" "
                      f"{args.adresse.rstrip('/')}/status")
                print("  Antwortet /status ebenfalls mit 401, ist das Token")
                print("  abgelaufen, widerrufen oder gehoert zu einer anderen")
                print("  Installation: python create_token.py --liste")
            elif all(f == "HTTP 404" for f in fehler):
                print("KEINE MESSUNG -- /frage gibt es unter dieser Adresse")
                print("  nicht. Laeuft dort wirklich api:app?")
            else:
                print("KEINE MESSUNG -- keine einzige Anfrage kam durch.")
            return 1

    print()
    print("ABLESEN:")
    print("  Waechst GESAMT etwa linear mit der Gleichzeitigkeit, ist")
    print("  irgendwo ein Engpass, der nicht parallel kann. Welcher, sagt")
    print("  die Spalte, die mitwaechst.")
    print()
    print("  Waechst nur ANTWORT, ist es der Modellserver -- das ist der")
    print("  gutartige Fall: mehr Karten oder groessere Stapel helfen.")
    print()
    print("  Waechst VEKTORSUCHE oder STICHWORTSUCHE, liegt es an der")
    print("  Anwendung. Dann lohnt Chroma als eigener Dienst")
    print("  (CHROMA_HOST) beziehungsweise ein anderer Stichwortindex.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
