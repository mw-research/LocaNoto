"""Zugangstoken fuer die Schnittstelle anlegen, auflisten, widerrufen.

    python create_token.py markus --bezeichnung "Terminal Laptop"
    python create_token.py --liste
    python create_token.py --widerrufe 3f9a1c

Das Token wird genau einmal ausgegeben. Gespeichert ist nur sein Hashwert;
verloren heisst neu anlegen.
"""
import argparse
import json
import os
import sys

import paths
import auth


def _benutzer():
    """Die angelegten Kennungen -- ein Token soll auf eine davon zeigen."""
    datei = paths.resolve_user_file()
    if not os.path.exists(datei) or os.path.getsize(datei) == 0:
        return []
    try:
        with open(datei, "r", encoding="utf-8") as f:
            return sorted(json.load(f).keys())
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return []


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("benutzer", nargs="?", help="Kennung, fuer die das Token gilt")
    p.add_argument("--bezeichnung", default="",
                   help="wofuer das Token gedacht ist, etwa 'Terminal Laptop'")
    p.add_argument("--tage", type=int, default=None,
                   help="Gueltigkeitsdauer in Tagen (ohne Angabe unbegrenzt)")
    p.add_argument("--liste", action="store_true", help="vorhandene Token zeigen")
    p.add_argument("--widerrufe", metavar="KENNUNG",
                   help="Token entfernen (Anfang der Kennung aus --liste)")
    args = p.parse_args()

    paths.bootstrap()

    if args.liste:
        eintraege = auth.liste()
        if not eintraege:
            print("Keine Token angelegt.")
            return
        print(f"{'KENNUNG':10} {'BENUTZER':16} {'ERSTELLT':22} BEZEICHNUNG")
        for h, e in eintraege:
            bis = e.get("gueltig_bis")
            zusatz = e.get("bezeichnung", "")
            if bis:
                zusatz = (zusatz + " ") if zusatz else ""
                zusatz += f"(bis {bis[:10]})"
            print(f"{h[:8]:10} {e.get('benutzer', '?'):16} "
                  f"{e.get('erstellt', '?')[:19]:22} {zusatz}")
        return

    if args.widerrufe:
        anzahl = auth.widerrufe(args.widerrufe)
        if anzahl == 1:
            print("Token widerrufen.")
        elif anzahl == 0:
            print("Keine Kennung passt.", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"{anzahl} Kennungen passen -- bitte mehr Zeichen angeben.",
                  file=sys.stderr)
            sys.exit(1)
        return

    if not args.benutzer:
        p.error("Kennung angeben, oder --liste / --widerrufe verwenden.")

    benutzer = args.benutzer.strip().lower()
    bekannt = _benutzer()
    if bekannt and benutzer not in bekannt:
        # Ein Token auf eine nicht angelegte Kennung waere still wirkungslos:
        # es kaeme durch die Pruefung und faende dann nur geteilte Dokumente.
        print(f"'{benutzer}' ist keine angelegte Kennung. Vorhanden: "
              f"{', '.join(bekannt)}", file=sys.stderr)
        sys.exit(1)

    token = auth.erzeuge(benutzer, args.bezeichnung, args.tage)
    print()
    print(f"  Token fuer '{benutzer}':")
    print()
    print(f"    {token}")
    print()
    print("  Es wird nur dieses eine Mal angezeigt. Verwendung:")
    print()
    print(f'    curl -H "X-LocaNoto-Token: {token}" ...')
    print()


if __name__ == "__main__":
    main()
