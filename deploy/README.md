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
curl -fsSLO https://raw.githubusercontent.com/mw-research/LocaNoto/main/deploy/locanoto-setup.py
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

**Dateiablage:** OpenCloud schickt jedes Hochladen an seine eigene
öffentliche Adresse. Unter Docker leitet der Installer diesen Namen intern
direkt auf Caddy. In Kubernetes muss das Cluster-DNS den Namen zum Ingress
führen – sonst bei der Frage „IP, unter der Pods den Ingress erreichen“ die
Cluster-IP des Ingress-Controllers angeben
(`kubectl get svc -A | grep -i ingress`). Der Installer prüft das am Ende.

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

| Schlüssel | Bedeutung |
|---|---|
| `target` | `docker` oder `kubernetes` |
| `dir` | nur Docker: Ordner der Installation |
| `namespace`, `ingress_class`, `storage_class`, `replicas` | nur Kubernetes; Vorgaben `locanoto`, erkannte Klasse, Standard, `1` |
| `host` | Adresse von LocaNoto |
| `tls` | `letsencrypt` (+ `acme_email`), `internal`, `own` (+ `own_cert`, `own_key`), `none` |
| `install_cert_manager` | `false`: cert-manager nicht selbst installieren |
| `company_ca`, `proxy`, `no_proxy` | Firmen-CA (Liste von Pfaden), Proxy für den Weg nach außen |
| `model_url`, `chat_model`, `embedding_model`, `vision_model` | Modellserver (`/v1`) und Modelle |
| `dimensions` | Vektorlänge in der Datenbank, Vorgabe `2048` |
| `features` | `websearch`, `opencloud`, `gateway`, `oidc`, `pages` (je `true`/`false`) |
| `cloud_host`, `cloud_internal_ip` | Adresse der Dateiablage; IP, unter der Pods den Ingress erreichen |
| `oidc_issuer`, `oidc_client_id`, `oidc_admin_groups` | Anmeldung über das Firmenverzeichnis |
| `lists_pvc`, `lists_dir` | Netzlaufwerk für Listen (siehe unten) |
| `admin_name` | erstes Admin-Konto, Vorgabe `admin` |
| `env` | weitere Einstellungen aus `.env.example` (siehe unten) |

Listen (Excel, CSV) von einem Netzlaufwerk: `"lists_pvc"` nennt einen
PersistentVolumeClaim im Namensraum (NFS, SMB über dessen CSI-Treiber, …),
`"lists_dir"` einen Ordner auf dem Docker-Rechner. Er wird nur lesend unter
`/mnt/listen` eingehängt; die Ordner je Arbeitsbereich stehen danach unter
Admin → Listen.

Weitere Einstellungen aus `.env.example` (Reranker, eigener Embedding-Server,
`REEMBED_HOURS`, …) stehen in der Antwortdatei unter `"env"`, etwa
`"env": {"RERANKER_BASE_URL": "http://modelle:8000", "REEMBED_HOURS": "20-6"}`.
Sie bleiben bei `--upgrade` erhalten. Schlüssel und Passwörter gehören nicht
hinein – die Antwortdatei ist nicht geheim; der Installer lehnt sie ab.

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
curl -fsSLO https://raw.githubusercontent.com/mw-research/LocaNoto/main/deploy/locanoto-setup.py
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

**File store:** OpenCloud sends every upload to its own public address.
With Docker the installer leads that name straight to Caddy inside. In
Kubernetes the cluster DNS has to lead it to the ingress – otherwise give
the ingress controller's cluster IP when asked for the IP at which pods
reach the ingress. The installer checks this at the end.

**Afterwards:** `--check`, `--upgrade`, or run again to change answers.
**Keep an offline copy of `~/.locanoto/secrets.json`** – without the
installation key in it, chats and documents cannot be read, not even from
backups.
