# LocaNoto installieren

*English below.*

Ein Programm, ein paar Fragen, fertig. Es richtet LocaNoto auf **diesem
Rechner** (Docker – Linux-Server, Mac mit Apple Silicon, NVIDIA DGX Spark)
oder in einem **Kubernetes-Cluster** ein, besorgt die Zertifikate selbst
und prüft am Ende, ob alles läuft.

## Was Sie brauchen

| Ziel | auf dem Rechner, auf dem Sie den Installer starten |
|---|---|
| Docker | Python 3.8 oder neuer, Docker mit `docker compose` |
| Kubernetes | Python 3.8 oder neuer, `kubectl` mit Zugriff auf den Cluster, ein Ingress-Controller im Cluster |

Dazu: die Adresse eines Modellservers (OpenAI-kompatibel, z. B. vLLM oder
Ollama mit `/v1`), und eine Adresse, unter der LocaNoto erreichbar sein soll
(Hostname oder – nur bei Docker – eine IP-Adresse).

## In drei Schritten

```bash
curl -fsSLO https://raw.githubusercontent.com/mw-research/LocaNoto/enterprise/deploy/locanoto-setup.py
python3 locanoto-setup.py
```

1. **Fragen beantworten.** Wohin (Docker/Kubernetes), unter welcher Adresse,
   ob sie aus dem Internet erreichbar ist, Firmenproxy ja/nein, Modellserver,
   welche Funktionen (Websuche, Dateiablage OpenCloud, Modell-Gateway,
   Anmeldung über das Firmenverzeichnis, klassische Oberfläche), erstes
   Admin-Konto. Zu jeder Frage steht ein Vorschlag in eckigen Klammern –
   Enter übernimmt ihn.
2. **Bestätigen.** Der Installer zeigt eine Zusammenfassung und fragt
   „Jetzt installieren?“.
3. **Warten.** Er holt die Images, startet alles, legt das Admin-Konto an,
   trägt die Websuche ein, erzeugt bei OpenCloud das Zugangs-Token und prüft
   zum Schluss jeden Teil. Jede Zeile, die nicht stimmt, sagt, was zu tun ist.

Danach im Browser `https://<Ihre Adresse>` öffnen.

## Zertifikate – was der Installer übernimmt

| Ihre Antwort | was passiert |
|---|---|
| Adresse ist aus dem Internet erreichbar | Zertifikat von Let's Encrypt, erneuert sich selbst. Der Name muss im DNS auf den Rechner bzw. Ingress zeigen, Port 80 und 443 offen. |
| nur im Firmennetz | Der Installer legt eine **eigene Zertifizierungsstelle** an. Ihr Stammzertifikat (`~/.locanoto/ca.crt`) **einmal** an die Rechner verteilen (Gruppenrichtlinie, Geräteverwaltung oder von Hand in Browser/Systemschlüsselbund) – danach ist jede LocaNoto-Adresse vertrauenswürdig. Die Serverzertifikate stellt Caddy bzw. cert-manager daraus aus und erneuert sie. |
| Sie haben schon ein Zertifikat | Pfad zu `.crt` (mit Zwischenzertifikaten) und `.key` angeben. |
| Firmenproxy bricht TLS auf / eigene Firmen-CA | Pfad zum CA-Zertifikat angeben – es landet automatisch in **jedem** Container (Websuche, Modelle, Dateiablage). |

Innerhalb der Installation sprechen die Dienste unverschlüsselt über ihre
Dienstnamen; nach außen gibt es nur die eine Adresse (plus die der
Dateiablage, falls gewählt).

## Danach

```bash
python3 locanoto-setup.py --check      # läuft alles?
python3 locanoto-setup.py --upgrade    # neue Version, gleiche Antworten
python3 locanoto-setup.py              # Antworten ändern (alte sind Vorschläge)
```

**Wichtig:** `~/.locanoto/secrets.json` enthält den Installationsschlüssel
und alle Passwörter. **Eine Kopie offline aufbewahren.** Ohne den Schlüssel
lassen sich Chats und Dokumente nicht mehr lesen – auch nicht aus einer
Sicherung.

Entfernen: Docker `docker compose -f <Ordner>/compose.yaml down` (Daten
bleiben in den Volumes; mit `-v` auch die Daten), Kubernetes `kubectl delete
namespace <Namensraum>` (löscht auch die Daten).

## Ohne Fragen (Automatisierung)

```bash
LOCANOTO_ADMIN_PASSWORD=... LOCANOTO_MODEL_API_KEY=... \
  python3 locanoto-setup.py --answers antworten.json --yes
```

Ein Beispiel für `antworten.json` steht in `.github/workflows/installation.yml`
– dort wird bei jedem Stand auf Docker und Kubernetes genau so installiert
und von außen geprüft.

---

# Installing LocaNoto

One program, a few questions, done. It sets LocaNoto up on **this machine**
(Docker – Linux server, Apple Silicon Mac, NVIDIA DGX Spark) or in a
**Kubernetes cluster**, gets the certificates itself and checks at the end
that everything works.

**You need:** Python 3.8+, plus Docker with `docker compose`, or `kubectl`
with access to a cluster that has an ingress controller; the address of an
OpenAI-compatible model server; the address LocaNoto should answer at.

```bash
curl -fsSLO https://raw.githubusercontent.com/mw-research/LocaNoto/enterprise/deploy/locanoto-setup.py
python3 locanoto-setup.py --en
```

Answer the questions (Enter takes the suggestion in brackets), confirm,
wait. The installer pulls the images, starts everything, creates the admin
account, registers web search, creates the OpenCloud token and checks every
part; each failing line says what to do.

**Certificates:** reachable from the internet → Let's Encrypt, renewed
automatically. Company network only → an own certificate authority is
created; distribute its root certificate `~/.locanoto/ca.crt` once.
Existing certificate → give `.crt` and `.key`. Company proxy or CA → give
its certificate; it reaches every container.

**Afterwards:** `--check`, `--upgrade`, or run again to change answers.
**Keep an offline copy of `~/.locanoto/secrets.json`** – without the
installation key in it, chats and documents cannot be read, not even from
backups.
