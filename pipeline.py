"""Suche und Antwort -- unabhaengig von der Oberflaeche.

Dieser Ablauf steckte bis hierher mitten im Streamlit-Skript: Sonden
erzeugen, hybrid suchen, Ranglisten verschmelzen, Kontext bauen, Antwort
holen -- verschachtelt mit st.spinner, st.caption und st.session_state.
Damit konnte ihn nichts anderes aufrufen als die Oberflaeche selbst.

Hier steht er ohne Streamlit. Was hineingeht, wird uebergeben; was
herauskommt, sind Daten. Eine zweite Bedienung -- ein Aufruf ueber HTTP,
ein Skript -- benutzt dieselben Funktionen und bekommt damit auch dieselben
Antworten. Zwei getrennte Umsetzungen wuerden auf dieselbe Frage
verschieden antworten, und der Unterschied faellt erst auf, wenn ihn jemand
sucht.

Anzeigetexte gehoeren nicht hierher. Die Funktionen geben Zahlen und
Hinweise zurueck; wie daraus eine Bildschirmzeile wird, entscheidet die
Oberflaeche.
"""
import os

import paths
import keyword_index
import ranking
from embedding import embed_batch

# --- ZEITLIMITS ---
# Ohne timeout= wartet der Client bis zu 600 s. Haengt ein Aufruf, steht die
# Bedienung zehn Minuten ohne Rueckmeldung -- fuer den Nutzer nicht von
# "kaputt" zu unterscheiden.
HELPER_TIMEOUT = paths.env_float("HELPER_TIMEOUT", 60)    # Sonden
ANSWER_TIMEOUT = paths.env_float("ANSWER_TIMEOUT", 300)   # Antwort

# So viele Sonden erzeugt das Modell, und so viele werden verwendet.
SONDEN_ANZAHL = 3

# Wie viel Verlauf in die Sondenbildung geht. Er dient nur dazu, Pronomen
# aufzuloesen ("wie hoch darf der sein?"), nicht dazu, das Thema zu setzen.
VERLAUF_NACHRICHTEN = 3
VERLAUF_ZEICHEN = 300

# Eine Bildbeschreibung ist mehrere Absaetze lang. Als Suchsonde zaehlt
# davon der Anfang; der Rest verwaessert die Suche nur.
BILD_SONDE_ZEICHEN = 400

RUECKFALL_SUCHPROMPT = """Du bist ein präziser Suchbegriff-Generator für eine universelle Wissens-Datenbank.
Generiere exakt 3 verschiedene Suchanfragen für die aktuelle Nutzerfrage, um sowohl Fließtexte (wie wissenschaftliche Paper) als auch strukturierte Daten (wie Tabellen/Normen) optimal zu finden:
1. Die präzise, umformulierte Kernfrage (löse Pronomen durch echte Begriffe aus dem Chatverlauf auf).
2. Eine Suche nach der Fundstelle: Abschnitt, Anhang oder Tabelle, in der die gesuchte Angabe steht -- und, wo es passt, nach der zugrundeliegenden Definition oder Methode.
3. Eine hochspezifische Stichwort-Suche (Eigennamen, Fachbegriffe, genaue Maße oder Variablen aus der Frage).

{HISTORY}

Aktuelle Frage: {FRAGE}

Antworte AUSSCHLIESSLICH mit den 3 Suchanfragen, getrennt durch Zeilenumbrüche. Keine Zahlen davor, keine Einleitung."""

RUECKFALL_SYSTEMPROMPT = ("Du bist ein {EXPERT_ROLE}.\n<context>\n"
                          "{CONTEXT_PLATZHALTER}\n</context>\n"
                          "Beantworte die Frage nur anhand des Kontexts.")


def _vorlage(dateiname, rueckfall):
    """Prompt-Vorlage aus einer Datei neben dem Code.

    Als Datei, damit sich die Formulierung je Bestand anpassen laesst: was
    ein Regelwerk braucht (Fundstelle, Tabelle, Anhang), ist bei einer
    Papersammlung die falsche Frage. Fehlt die Datei, greift der Rueckfall
    -- eine geloeschte Vorlage legt die Anwendung nicht lahm.
    """
    try:
        with open(os.path.join(paths.BASE_DIR, dateiname),
                  "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return rueckfall


def verlaufstext(nachrichten, ohne_letzte=True):
    """Die letzten Nachrichten als Text fuer die Sondenbildung."""
    vorher = nachrichten[:-1] if ohne_letzte else list(nachrichten)
    if not vorher:
        return ""
    letzte = vorher[-VERLAUF_NACHRICHTEN:]
    zeilen = [f"{m['role']}: {m['content'][:VERLAUF_ZEICHEN]}" for m in letzte]
    return "\nChatverlauf:\n" + "\n".join(zeilen)


def sonden(client, modell, frage, verlauf="", bild_texte=()):
    """Suchsonden zu einer Frage.

    Rueckgabe: (sonden, hinweis). hinweis ist None, wenn das Umschreiben
    geklappt hat, sonst ein kurzer Grund. Scheitert es, bleibt die
    Originalfrage als einzige Sonde -- eine schlechtere Suche ist besser als
    keine.
    """
    liste = [frage]
    hinweis = None

    prompt = (_vorlage("search_prompt.txt", RUECKFALL_SUCHPROMPT)
              .replace("{HISTORY}", verlauf)
              .replace("{FRAGE}", frage))
    try:
        antwort = client.chat.completions.create(
            model=modell,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            timeout=HELPER_TIMEOUT,
        )
        erzeugt = [z.strip("- 1234567890.")
                   for z in (antwort.choices[0].message.content or "").split("\n")
                   if z.strip()]
        if len(erzeugt) >= SONDEN_ANZAHL:
            liste = erzeugt[:SONDEN_ANZAHL]
        else:
            hinweis = "Das Modell lieferte zu wenige Sonden."
    except Exception as e:
        hinweis = f"{type(e).__name__}: {e}"

    # Aus einer Bildbeschreibung wird eine eigene Sonde. Ohne sie koennte die
    # Suche nur nach dem gehen, was der Nutzer tippt -- und "was ist das
    # hier?" trifft nichts. Ausserhalb des try, damit sie auch dann greift,
    # wenn das Umschreiben scheitert.
    for text in bild_texte:
        liste.append(text[:BILD_SONDE_ZEICHEN])

    return liste, hinweis


def _where(benutzer, dateien=None, ordner=None):
    """Rechte- und Auswahlfilter fuer die Vektorsuche."""
    grund = {"$or": [{"access": {"$eq": "shared"}},
                     {"owner": {"$eq": benutzer}}]}
    bedingungen = [grund]
    if dateien:
        bedingungen.append({"file_name": {"$in": list(dateien)}})
    if ordner:
        bedingungen.append({"folder": {"$in": list(ordner)}})
    return {"$and": bedingungen} if len(bedingungen) > 1 else grund


def suche(collection, embed_client, embed_modell, sonden_liste, benutzer,
          top_k, dateien=None, ordner=None, bewerter=None):
    """Hybride Suche und Rangfolge.

    Rueckgabe: (treffer, zahlen). treffer ist eine Liste aus
    {"text", "meta"} in der Reihenfolge der Rangfolge; zahlen nennt
    Kandidaten und Ranglisten fuer die Anzeige.

    Loest ValueError aus, wenn sich keine einzige Sonde vektorisieren
    laesst -- dann ist der Embedding-Endpunkt nicht erreichbar, und eine
    leere Trefferliste waere die falsche Auskunft.
    """
    vektoren = embed_batch(embed_client, list(sonden_liste), embed_modell,
                           keep_alive=0)
    # Sonde und Vektor gemeinsam filtern. Wuerde man nur die Vektoren
    # zusammenschieben, verschoeben sich die Indizes und die Treffer
    # bekaemen die falsche Sonde zugeordnet.
    paare = [(s, v) for s, v in zip(sonden_liste, vektoren) if v is not None]
    if not paare:
        raise ValueError("Keine Suchanfrage konnte vektorisiert werden.")

    breit = max(10, top_k * 3)

    # Jede Sonde und jeder Suchweg liefert eine EIGENE Rangliste. Die
    # Reihenfolge innerhalb der Listen ist die eigentliche Information fuer
    # die Fusion -- frueher wurde sie beim Entdoppeln weggeworfen.
    ranglisten = []

    # A. VEKTORSUCHE
    treffer = collection.query(
        query_embeddings=[v for _, v in paare],
        n_results=breit,
        where=_where(benutzer, dateien, ordner),
    )
    for i, (texte, metas) in enumerate(zip(treffer["documents"],
                                           treffer["metadatas"])):
        probe = paare[i][0]
        liste = [{"text": t, "meta": m, "probe": probe}
                 for t, m in zip(texte, metas)]
        if liste:
            ranglisten.append(liste)

    # B. STICHWORTSUCHE (SQLite FTS5)
    #
    # Rechte- und Dokumentenfilter laufen in SQL statt nachtraeglich in
    # Python. Dort hing der Rechtecheck an meta.get('access', 'shared') --
    # Chunks ohne access-Schluessel galten damit als oeffentlich.
    for probe, _ in paare:
        gefunden = keyword_index.search(
            probe, benutzer, limit=breit,
            file_names=list(dateien) if dateien else None,
            folders=list(ordner) if ordner else None)
        liste = [{"text": h["text"], "meta": h["meta"], "probe": probe}
                 for h in gefunden]
        if liste:
            ranglisten.append(liste)

    zahlen = {"kandidaten": sum(len(l) for l in ranglisten),
              "ranglisten": len(ranglisten)}

    if not ranglisten:
        return [], zahlen

    ergebnis = []
    for text, _score, eintrag in ranking.rank(ranglisten, top_k,
                                              bewerter=bewerter):
        # Kopie: die Metadaten kommen direkt aus ChromaDB und sollen dort
        # nicht veraendert werden.
        meta = dict(eintrag["meta"] or {})
        meta["found_by_query"] = eintrag["probe"]
        ergebnis.append({"text": text, "meta": meta})
    return ergebnis, zahlen


def kontext(treffer, bild_texte=(), bloecke=()):
    """Baut den Kontext fuer das Sprachmodell.

    Jede Herkunft bekommt einen eigenen, benannten Block. Ohne diese
    Trennung gaebe das Modell aus, ein Dokument habe etwas gezeigt, was in
    Wahrheit auf einem hochgeladenen Bild stand oder aus einer Abfrage kam.

    bloecke nimmt zusaetzliche (name, inhalt)-Paare auf -- so haengt hier
    nichts, was nur eine der Installationen kennt.
    """
    teile = []
    for eintrag in treffer:
        meta = eintrag["meta"]
        teile.append('<chunk file="{}" page="{}">\n{}\n</chunk>'.format(
            meta.get("file_name", "?"), meta.get("page", "?"),
            eintrag["text"]))
    if not teile:
        teile.append("Keine relevanten Dokumenten-Abschnitte gefunden.")

    for n, text in enumerate(bild_texte, 1):
        teile.append('<hochgeladenes_bild nr="{}">\n{}\n</hochgeladenes_bild>'
                     .format(n, text))

    for name, inhalt in bloecke:
        teile.append("<{0}>\n{1}\n</{0}>".format(name, inhalt))

    return "\n\n".join(teile) + "\n\n"


def systemprompt(kontexttext):
    """Vorlage mit Rolle und Kontext gefuellt."""
    rolle = os.getenv("EXPERT_ROLE", "Forschungsassistent für das Bauwesen")
    return (_vorlage("system_prompt.txt", RUECKFALL_SYSTEMPROMPT)
            .replace("{EXPERT_ROLE}", rolle)
            .replace("{CONTEXT_PLATZHALTER}", kontexttext))


def antwort(client, modell, system, nachrichten, verlauf_anzahl=20):
    """Erzeugt die Antwort und gibt sie stueckweise aus.

    Stueckweise, weil eine Antwort auf einem lokalen 27B-Modell leicht eine
    halbe Minute dauert -- am Stueck ist das eine halbe Minute ohne jedes
    Lebenszeichen.
    """
    an_modell = [{"role": "system", "content": system}]
    for m in nachrichten[-verlauf_anzahl:]:
        an_modell.append({"role": m["role"], "content": m["content"]})

    strom = client.chat.completions.create(
        model=modell,
        messages=an_modell,
        stream=True,
        timeout=ANSWER_TIMEOUT,
    )
    for teil in strom:
        if not teil.choices:
            continue
        delta = teil.choices[0].delta
        if delta and delta.content:
            yield delta.content


def quellen(treffer):
    """Fasst die Treffer nach Datei und Seite zusammen.

    Mehrere Abschnitte derselben Seite werden zu einem Eintrag -- sonst
    stuende dieselbe Fundstelle mehrfach unter der Antwort.
    """
    gesammelt = {}
    for eintrag in treffer:
        meta = eintrag["meta"]
        schluessel = (meta.get("file_name", "?"), meta.get("page", "?"))
        gesammelt.setdefault(schluessel, []).append(eintrag["text"])
    return [{"file": datei, "page": seite, "texts": texte}
            for (datei, seite), texte in gesammelt.items()]


def dokumente(collection, benutzer):
    """Welche Dokumente dieser Nutzer sehen darf.

    Dieselbe Trennung wie in der Suche: geteilte Dokumente sehen alle,
    private nur ihr Eigentuemer. Steht hier statt in der Oberflaeche, damit
    Oberflaeche und Schnittstelle nicht zwei Auffassungen davon entwickeln,
    was sichtbar ist.

    Rueckgabe: (geteilt, privat, sachgebiete) -- jeweils sortierte Listen.
    """
    def sammle(daten):
        dateien, ordner = set(), set()
        for m in (daten.get("metadatas") or []):
            if not m:
                continue
            if m.get("file_name"):
                dateien.add(m["file_name"])
            if m.get("folder"):
                ordner.add(m["folder"])
        return sorted(dateien), sorted(ordner)

    geteilt, ordner_g = sammle(collection.get(where={"access": "shared"},
                                              include=["metadatas"]))
    privat, ordner_p = sammle(collection.get(
        where={"$and": [{"access": "private"}, {"owner": benutzer}]},
        include=["metadatas"]))
    return geteilt, privat, sorted(set(ordner_g) | set(ordner_p))
