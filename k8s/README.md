# LocaNoto in Kubernetes

Der Pod ist nur das Gerüst. Der ganze Bestand — Vektordatenbank
eingeschlossen — liegt auf einem externen Volume, und zwar **in genau der
`data/`-Struktur, die es bisher neben der Compose-Datei gab**:

```
Pod locanoto                    PVC locanoto-daten  →  /app/data
 ├── chroma  (Sidecar)              dokumente/              Originaldateien
 ├── app     (Streamlit)            chats/                  Verläufe, verschlüsselt
 └── api     (uvicorn)              chroma_db/              die Vektordatenbank
                                    keyword_index.sqlite3   Stichwortindex
                                    tabellen_katalog.json   Listenkatalog
                                    feedback.jsonl          Rückmeldungen
                                    sicherungen/            Abzüge
                                    owncloud/               Stand des Abgleichs

                                PVC locanoto-konfig →  /app/config
                                    users.json  tokens.json
                                    schluessel.key  raeume.json
                                    owncloud.json  presets/
```

Nichts davon liegt im Abbild, nichts im Pod. **Nachgewiesen**: bei einem
Durchlauf mit Anmeldung, Benutzeranlage, Raumanlage, Chat, Rückmeldung,
Ingest, Listenkatalog und Abzug — mit den Wurzeln auf Fremdverzeichnisse
gesetzt — entstand im Abbild *keine einzige Datei*.

Nur zwei Volumes, weil die Konfiguration getrennt gehört: dort liegt der
Schlüssel, mit dem alle Chatverläufe lesbar sind. Andere Rechte, andere
Aufbewahrung, andere Sicherung — eine Sicherung der Dokumente soll ihn
nicht mitnehmen.

## Der eine Punkt, den du vorher prüfen musst

Das Datenvolume trägt zwei SQLite-Bestände (`chroma_db`,
`keyword_index.sqlite3`). Es braucht deshalb **ein echtes Dateisystem**:

| Persistenter Speicher | taugt für das Datenvolume |
|---|---|
| angeschlossene Platte, local path | **ja** |
| Ceph RBD, iSCSI, EBS, Azure Disk | **ja** |
| NFS, SMB, CephFS, EFS | **nein** — siehe `90-variante-freigabe.yaml` |

Persistent heißt nicht automatisch Dateifreigabe, und das ist die
Verwechslung, an der es beim Aufsetzen scheitert. Blockspeicher trägt ein
ext4 oder xfs, und darauf läuft SQLite einwandfrei. Eine Freigabe trägt es
nicht: SQLite braucht im WAL-Betrieb gemeinsamen Speicher im selben
Dateisystem, den es dort nicht gibt, und die Dateisperren sind
unzuverlässig. Das Ergebnis ist kein Fehler, sondern ein beschädigter
Index — und SQLite fällt dabei **still** auf einen anderen Journalmodus
zurück.

Die Oberfläche liest den tatsächlichen Modus zurück und meldet es unter
*Speicherorte*, wenn dort nicht `wal` steht. Das ist die Prüfung nach dem
ersten Start.

`kubectl get storageclass` zeigt, was der Cluster anbietet.

## Aufsetzen

```bash
# 1. Abbild bauen und in die Registry des Clusters bringen
docker build -t deine-registry/locanoto:1.0 .
docker push deine-registry/locanoto:1.0

# 2. Geheimnisse aus dem Stand erzeugen -- nicht aus der Vorlage
kubectl create secret generic locanoto \
  --from-literal=OPENAI_API_KEY=... \
  --from-literal=OWNCLOUD_PASSWORT=...

# 3. Speicher, Konfiguration, Pod
kubectl apply -f k8s/10-speicher.yaml
kubectl apply -f k8s/20-konfiguration.yaml   # nur die ConfigMap, siehe Datei
kubectl apply -f k8s/30-anwendung.yaml

# 4. Ersten Benutzer anlegen -- er wird Verwalter
kubectl exec -it deploy/locanoto -c app -- python create_user.py

# 5. Optional: nächtlicher Abgleich und Abzug
kubectl apply -f k8s/40-zeitplan.yaml
```

Der Abbildname in den Manifesten ist `locanoto:lokal`. Ersetze ihn durch
deinen; die Manifeste setzen bewusst keine `imagePullPolicy`, damit ein
lokal gebautes Abbild in einem Einzelknoten-Cluster (k3s, minikube, Docker
Desktop) ohne Registry funktioniert.

## Umzug einer bestehenden Installation

Weil die Struktur dieselbe bleibt, ist der Umzug ein Kopiervorgang:

```bash
# Alten Bestand in das neue Volume bringen
kubectl cp ./data  locanoto-xxxxx:/app/data  -c app
kubectl cp ./config locanoto-xxxxx:/app/config -c app
```

Oder von der Gegenseite: das Volume auf dem Knoten einhängen und `data/`
sowie `config/` hineinkopieren. Es ist Datei für Datei dieselbe Anordnung
— **ein Update verschiebt nichts von selbst**, und ein Update, das die
Vektordatenbank an einen anderen Ort legte, fände dort nichts vor und
stünde ohne Fehlermeldung mit leeren Sammlungen da.

## Warum Chroma ein eigener Prozess im selben Pod ist

Nicht wegen der Skalierung, sondern wegen des Schreibens. Ohne den Dienst
legte jeder Container eine eigene Dateiablage auf denselben Dateien an —
Oberfläche und Schnittstelle gleichzeitig. Zwei Prozesse auf denselben
SQLite-Dateien sind kein sauberer Fehler, sondern ein beschädigter Index,
der erst auffällt, wenn Antworten fehlen. Als Dienst entscheidet Chroma
selbst, wer schreibt; die anderen beiden sind Clients auf `127.0.0.1`.

Und im selben Pod, weil alle drei denselben Bestand brauchen und der auf
einem Volume liegt, das genau ein Knoten einhängt. Getrennte Pods
bräuchten getrennte Volumes — damit wäre die `data/`-Struktur
auseinandergerissen, was nicht das Ziel ist.

Chroma steht als `initContainer` mit `restartPolicy: Always` — ein nativer
Sidecar ab Kubernetes 1.29. Er startet **vor** den anderen und läuft
weiter, und die anderen warten auf seine `startupProbe`. Ohne das ist die
Startreihenfolge in einem Pod nicht festgelegt. Für Cluster vor 1.29 steht
im Manifest, was zu ändern ist.

## Warum genau eine Instanz

`replicas: 1`, und das ist eine Grenze, keine Einstellung:

1. Das Datenvolume ist `ReadWriteOnce` — ein zweiter Pod könnte es nicht
   einhängen.
2. Streamlit hält den Sitzungszustand im Arbeitsspeicher. Ein zweiter Pod
   bräuchte klebende Sitzungen, sonst landet jeder zweite Klick bei einer
   Instanz, die den Chat nicht kennt.
3. Prozesskennungen (PID) gelten nur auf ihrem Rechner.

Was mehrere Instanzen möglich machen würde: Stichwortindex und
Sitzungszustand in eine Server-Datenbank verlegen. Das ist ein Umbau. Für
eine interne Wissenssuche mit drei bis einigen hundert Nutzern trägt eine
Instanz; die Modellzeit ist der Engpass, nicht die Anwendung.

`strategy: Recreate` gehört dazu: beim Ausrollen darf nicht kurz ein
zweiter Pod dasselbe Volume einhängen wollen. Er käme nicht hoch, und der
alte würde nicht abgelöst.

## Was ein Verlust kostet

| | Verlust bedeutet |
|---|---|
| **der Pod** | nichts |
| `locanoto-konfig` | Nutzer, Räume und der **Schlüssel** — alle Chatverläufe unlesbar |
| `locanoto-daten` | Dokumente, Chats, Vektoren, Rückmeldungen |

Die erste Zeile ist das Ziel dieser Aufteilung. Die dritte ist der Grund
für den Abzug (`SICHERUNG_PFAD`): innerhalb des Volumes ist er der
Rückweg nach einem Fehlgriff, gegen den Verlust des Volumes selbst hilft
nur ein eigenes Ziel — ein zweites PVC oder ein Sicherungslaufwerk.

Der Abzug enthält die Vektoren, ein Einspielen braucht deshalb kein Modell
und keinen Endpunkt. Gemessen: 20.500 Abschnitte in 2,6 s (112 MB),
Einspielen 29 s.

## Der Schlüssel

Ohne Angabe legt die Anwendung ihn beim ersten Start als
`config/schluessel.key` auf dem Konfigvolume ab. Das genügt und ist
einfacher. Über das Secret (`LOCANOTO_SCHLUESSEL`) liegt er nicht im
Dateisystem, sondern nur im Speicher des Pods.

**In beiden Fällen gehört er in die Sicherung.** Geht er verloren, sind
alle Chatverläufe unlesbar, und zwar ohne Fehlermeldung — die Dateien sind
ja noch da.

## Erreichbarkeit

Die Manifeste enthalten bewusst **kein** Ingress: TLS, Hostname und
Zugangsschutz unterscheiden sich in jedem Haus. Zum Ausprobieren:

```bash
kubectl port-forward deploy/locanoto 8501:8501
```

Für den Betrieb gehört ein Ingress mit TLS davor. Die HTTP-Schnittstelle
(8600) überträgt ihr Token im Kopf der Anfrage — unverschlüsselt wäre es
auf dem Draht mitlesbar.

Chroma steht absichtlich **nicht** im Service und lauscht nur auf
`127.0.0.1`. Er kennt keine Nutzer: wer ihn erreicht, liest alles und darf
Sammlungen löschen. Im Pod ist er damit eingeschlossen.
