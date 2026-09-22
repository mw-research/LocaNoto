"""Die Lizenzen der Abhaengigkeiten -- gegen die GEPINNTEN Fassungen.

Nicht gegen das, was hier zufaellig installiert ist: gefragt wird PyPI
nach genau der Fassung, die in requirements.txt steht. Eine
Lizenzaufstellung, die eine andere Fassung beschreibt als die, die im
Abbild liegt, ist keine.

Die Angabe kommt zuerst aus den Klassifizierern (License :: ...), denn
die sind ein geschlossener Wortschatz. Erst wenn dort nichts steht, wird
das Freitextfeld genommen -- das enthaelt mal "MIT", mal den ganzen
Lizenztext.
"""
import io
import json
import re
import sys
import time
import urllib.request

QUELLE = sys.argv[1] if len(sys.argv) > 1 else "requirements.txt"
ZIEL = sys.argv[2] if len(sys.argv) > 2 else "lizenzen.json"

pakete = []
for zeile in io.open(QUELLE, encoding="utf-8"):
    zeile = zeile.split("#")[0].strip()
    m = re.match(r"^([A-Za-z0-9._-]+)==([^\s;]+)", zeile)
    if m:
        pakete.append((m.group(1), m.group(2)))

print(f"{len(pakete)} gepinnte Pakete in {QUELLE}", file=sys.stderr)

aus = {}
for i, (name, fassung) in enumerate(pakete, 1):
    url = f"https://pypi.org/pypi/{name}/{fassung}/json"
    lizenz, quelle_, seite = "?", "nicht gefunden", ""
    for versuch in range(3):
        try:
            with urllib.request.urlopen(url, timeout=20) as a:
                d = json.load(a)
            info = d.get("info", {})
            klass = [k for k in (info.get("classifiers") or [])
                     if k.startswith("License ::")]
            if klass:
                # "License :: OSI Approved :: MIT License" -> letzter Teil
                lizenz = "; ".join(k.split(" :: ")[-1] for k in klass)
                quelle_ = "Klassifizierer"
            else:
                roh = (info.get("license") or "").strip()
                if info.get("license_expression"):
                    lizenz, quelle_ = info["license_expression"], "SPDX"
                elif roh and len(roh) < 60:
                    lizenz, quelle_ = roh, "Freitext"
                elif roh:
                    lizenz, quelle_ = roh.split("\n")[0][:60] + " …", "Lizenztext"
            seite = info.get("home_page") or info.get("project_url") or ""
            break
        except Exception as e:
            if versuch == 2:
                lizenz, quelle_ = "?", f"Abruf fehlgeschlagen: {type(e).__name__}"
            time.sleep(1)
    aus[name] = {"fassung": fassung, "lizenz": lizenz, "woher": quelle_,
                 "seite": seite}
    if i % 20 == 0:
        print(f"  {i}/{len(pakete)}", file=sys.stderr)

io.open(ZIEL, "w", encoding="utf-8").write(
    json.dumps(aus, ensure_ascii=False, indent=1))
print(f"geschrieben: {ZIEL}", file=sys.stderr)
