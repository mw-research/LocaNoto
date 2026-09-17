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
import json
import os
import time

import paths
import keyword_index
import raeume
import ranking
import presets
import store
from embedding import embed_batch

# --- ZEITLIMITS ---
# Ohne timeout= wartet der Client bis zu 600 s. Haengt ein Aufruf, steht die
# Bedienung zehn Minuten ohne Rueckmeldung -- fuer den Nutzer nicht von
# "kaputt" zu unterscheiden.
HELPER_TIMEOUT = paths.env_float("HELPER_TIMEOUT", 60)    # Sonden
ANSWER_TIMEOUT = paths.env_float("ANSWER_TIMEOUT", 300)   # Antwort

# Zeitlimit fuer das Vektorisieren der Sonden. Kuerzer als das des
# Ingest (EMBED_TIMEOUT=120): dort wartet niemand zu, hier sitzt ein
# Mensch vor einem Spinner. Laeuft es ab, sagt die Meldung warum.
SUCHE_EMBED_TIMEOUT = paths.env_float("SUCHE_EMBED_TIMEOUT", 45)

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


def _vorlage(dateiname, rueckfall, preset=None):
    """Prompt-Vorlage aus einer Datei neben dem Code.

    Als Datei, damit sich die Formulierung je Bestand anpassen laesst: was
    ein Regelwerk braucht (Fundstelle, Tabelle, Anhang), ist bei einer
    Papersammlung die falsche Frage. Bearbeitet wird sie unter config/ --
    paths.resolve_prompt() nimmt die dortige Fassung, sonst die
    mitgelieferte. Fehlt beides, greift der Rueckfall: eine geloeschte
    Vorlage legt die Anwendung nicht lahm.
    """
    # Kette: Voreinstellung, dann config/, dann die mitgelieferte Fassung.
    pfad = presets.vorlage_pfad(preset, dateiname) or paths.resolve_prompt(dateiname)
    try:
        with open(pfad, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return rueckfall


def glossar(preset=None):
    """Der Sprachgebrauch des Hauses, aus config/glossar.txt.

    Mitarbeiter fragen in ihren eigenen Abkuerzungen -- "BANF", "FA", "WE" --,
    und die stehen im Handbuch nicht: dort heisst es "Bestellanforderung"
    oder es steht nur eine Modulnummer. Weder eine Vektorsuche noch FTS5
    ueberbrueckt das; die Frage findet nichts, obwohl die Antwort im Bestand
    steht.

    Die Datei ist bewusst getrennt vom Prompt: sie waechst mit jeder Frage,
    die ins Leere lief, und gehoert damit dem Betrieb, nicht dem Code.
    Fehlt sie, bleibt alles wie zuvor.
    """
    # Zeilen mit # sind Erklaerungen fuer den, der die Datei pflegt. Sie
    # gehoeren nicht in den Prompt: das Modell wuerde sie als Inhalt lesen.
    pfad = presets.vorlage_pfad(preset, "glossar.txt") or paths.resolve_glossar()
    try:
        with open(pfad, "r", encoding="utf-8") as f:
            roh = f.read()
    except OSError:
        roh = ""
    zeilen = [z.rstrip() for z in roh.splitlines()]
    return chr(10).join(z for z in zeilen
                        if z.strip() and not z.lstrip().startswith("#"))


def _glossarblock(preset=None):
    """Der Glossartext, eingefasst -- oder nichts."""
    text = glossar(preset)
    if not text:
        return ""
    return ("Sprachgebrauch im Betrieb. Diese Zuordnungen stammen nicht aus "
            "den Dokumenten, sondern von den Nutzern:" + chr(10) + text
            + chr(10))


def verlaufstext(nachrichten, ohne_letzte=True):
    """Die letzten Nachrichten als Text fuer die Sondenbildung."""
    vorher = nachrichten[:-1] if ohne_letzte else list(nachrichten)
    if not vorher:
        return ""
    letzte = vorher[-VERLAUF_NACHRICHTEN:]
    zeilen = [f"{m['role']}: {m['content'][:VERLAUF_ZEICHEN]}" for m in letzte]
    return "\nChatverlauf:\n" + "\n".join(zeilen)


def sonden(client, modell, frage, verlauf="", bild_texte=(), preset=None):
    """Suchsonden zu einer Frage.

    Rueckgabe: (sonden, hinweis). hinweis ist None, wenn das Umschreiben
    geklappt hat, sonst ein kurzer Grund. Scheitert es, bleibt die
    Originalfrage als einzige Sonde -- eine schlechtere Suche ist besser als
    keine.
    """
    liste = [frage]
    hinweis = None

    prompt = (_vorlage("search_prompt.txt", RUECKFALL_SUCHPROMPT, preset)
              .replace("{GLOSSAR}", _glossarblock(preset))
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


def _where(dateien=None):
    """Auswahlfilter fuer die Vektorsuche -- ohne Rechte.

    Die Rechte stehen nicht mehr in diesem Filter. Sie liegen darin, WELCHE
    Sammlungen ueberhaupt gefragt werden: eine nicht gefragte Sammlung kann
    nichts preisgeben, ein vergessener Filter dagegen alles. Gemessen an
    3.000 Abschnitten: ohne Trennung erschienen in 200 Proben 75 fremde
    Treffer in den ersten fuenf, mit Trennung keiner.
    """
    bedingungen = []
    if dateien:
        # Ueber store.datei_filter, damit sowohl verdeckte Namen
        # (datei_id) als auch die alten Klarnamen getroffen werden.
        bedingungen.append(store.datei_filter(list(dateien)))
    if not bedingungen:
        return None
    return {"$and": bedingungen} if len(bedingungen) > 1 else bedingungen[0]


def sammlungen(benutzer, nur=None, notzugang=()):
    """Die Sammlungen, die dieser Nutzer fragen darf: [(raum, sammlung)].

    nur schraenkt zusaetzlich ein -- fuer die Auswahl in der Oberflaeche.
    Raeume ausserhalb der Berechtigung werden dabei still verworfen und
    nicht als Fehler gemeldet: eine Auswahl kommt vom Client, und ein
    Client darf sich nicht mehr nehmen, als ihm zusteht.

    notzugang sind fremde persoenliche Raeume mit bestaetigtem Notzugang
    (siehe notzugang.py). Sie werden durchgereicht und nicht hier
    nachgeschlagen: wer den Parameter vergisst, bekommt keinen Zugang
    statt versehentlich einen.
    """
    erlaubt = raeume.lesbar(benutzer, notzugang)
    if nur:
        gewaehlt = set(nur)
        erlaubt = [r for r in erlaubt if r in gewaehlt]
    paare = []
    for r in erlaubt:
        sml = store.sammlung(raeume.sammlung(r), anlegen=False)
        if sml is not None:
            paare.append((r, sml))
    return paare


def _vektortreffer(paare_sammlungen, vektoren, breit, filter_,
                   benutzer="?"):
    """Eine Rangliste je Sonde, ueber alle Raeume zusammengefuehrt.

    Bewusst NICHT eine Rangliste je Raum: die Fusion gewichtet nach Rang,
    und der beste Treffer eines Raums mit fuenfzig Abschnitten bekaeme
    denselben Rang 1 wie der beste aus dem gemeinsamen Bestand -- ein
    winziger Raum wuerde die Rangfolge dominieren.

    Stattdessen wird nach Abstand zusammengeschoben und abgeschnitten.
    Damit steht am Ende genau das, was eine einzige gefilterte Sammlung
    geliefert haette.
    """
    je_sonde = [[] for _ in vektoren]
    ausfaelle = {}
    for raum, sml in paare_sammlungen:
        try:
            res = sml.query(query_embeddings=vektoren, n_results=breit,
                            where=filter_,
                            include=["documents", "metadatas", "distances"])
        except Exception as e:
            # Ein Raum, dessen Sammlung gerade nicht antwortet, darf die
            # Suche in den anderen nicht mitnehmen -- diese Absicht war
            # richtig und bleibt.
            #
            # FALSCH WAR, dass es danach niemand erfuhr. In einer
            # Installation lagen die Vektoren mit 2560 Dimensionen,
            # waehrend das Modell 4096 liefert: jede Vektorabfrage warf,
            # und die Antworten kamen weiter -- getragen allein vom
            # Stichwortindex, sauber formuliert, mit richtigen
            # Fundstellen. Von aussen sah die Anlage gesund aus. Seit
            # dem Umzug.
            #
            # Ein voruebergehender Aussetzer und ein dauerhafter
            # Strukturfehler sahen gleich aus, naemlich nach gar nichts.
            # Jetzt wird gezaehlt.
            ausfaelle[raum] = f"{type(e).__name__}: {e}"
            continue
        for i in range(len(vektoren)):
            # Aufschliessen, sobald die Treffer feststehen -- und nicht
            # frueher. Entschluesselt wird damit genau das Dutzend, das
            # in die Antwort geht, nicht der Raum. Gezaehlt wird es auch
            # (budget.py): eine Frage sind ein paar Abschnitte aus ein
            # bis drei Raeumen, ein Abzug sind Zehntausende aus allen.
            texte = store.klartext(raum, res["documents"][i], benutzer)
            # Auch der Dateiname liegt verdeckt. Ohne das stuende unter
            # der Antwort "LNX1:OiD8..." statt "Betriebsanweisung.pdf".
            metas = store.metadaten_klartext(raum, res["metadatas"][i],
                                             benutzer)
            abstaende = res["distances"][i]
            for t, m, d in zip(texte, metas, abstaende):
                meta = dict(m or {})
                meta["raum"] = raum
                je_sonde[i].append((d, t, meta))
    return ([sorted(l, key=lambda x: x[0])[:breit] for l in je_sonde],
            ausfaelle)


def suche(paare_sammlungen, embed_client, embed_modell, sonden_liste,
          benutzer, top_k, dateien=None, bewerter=None,
          raeume_liste=None):
    """Hybride Suche und Rangfolge.

    paare_sammlungen: [(raum, sammlung)] -- aus sammlungen(benutzer).

    Rueckgabe: (treffer, zahlen). treffer ist eine Liste aus
    {"text", "meta"} in der Reihenfolge der Rangfolge; zahlen nennt
    Kandidaten und Ranglisten fuer die Anzeige.

    zahlen["vektorausfall"] nennt die Raeume, deren Vektorsuche nicht
    antworten konnte, samt Grund. Leer heisst: alle wurden gefragt. Das
    steht dort, weil eine Antwort ohne Vektorsuche aussieht wie eine
    gewoehnliche Antwort -- und in einer Installation monatelang genau
    so aussah.

    Loest ValueError aus, wenn sich keine einzige Sonde vektorisieren
    laesst -- dann ist der Embedding-Endpunkt nicht erreichbar, und eine
    leere Trefferliste waere die falsche Auskunft.
    """
    # KEIN keep_alive=0. Der Wert bedeutet in diesem Code 'Modell jetzt
    # entladen' -- die Ingest-Skripte schicken ihn genau einmal am Ende
    # unter der Ueberschrift VRAM freigeben. Bei jeder Suche geschickt,
    # wies er den Server an, das 8B-Embeddingmodell nach JEDER Frage
    # wegzuwerfen: die naechste Frage zahlte den Kaltstart, ganz gleich
    # wie kurz sie darauf folgte.
    #
    # Und keine Einzelnacharbeit: drei kurze Sonden koennen das
    # Kontextfenster nicht ueberschreiten. Sie kostete bei einem
    # haengenden Endpunkt dreimal das Zeitlimit obendrauf -- gemessen
    # acht Minuten Spinner, bevor eine Meldung erschien.
    # ZEITEN JE STUFE.
    #
    # Ohne sie sagt eine langsame Antwort nur, dass sie langsam ist.
    # Mit ihnen sagt sie, WO -- und das ist der Unterschied zwischen
    # "wir brauchen mehr Hardware" und "der Rerank-Endpunkt antwortet
    # nicht". Gemessen wird in Millisekunden und mitgegeben in zahlen;
    # das kostet nichts und steht damit auch in der Schnittstelle.
    _t0 = time.perf_counter()
    _zeiten = {}

    def _merke(name):
        nonlocal _t0
        _jetzt = time.perf_counter()
        _zeiten[name] = round((_jetzt - _t0) * 1000)
        _t0 = _jetzt

    vektoren = embed_batch(embed_client, list(sonden_liste), embed_modell,
                           timeout=SUCHE_EMBED_TIMEOUT,
                           nacharbeit=False)
    _merke("einbettung")
    # Sonde und Vektor gemeinsam filtern. Wuerde man nur die Vektoren
    # zusammenschieben, verschoeben sich die Indizes und die Treffer
    # bekaemen die falsche Sonde zugeordnet.
    paare = [(s, v) for s, v in zip(sonden_liste, vektoren) if v is not None]
    if not paare:
        grund = getattr(embed_batch, "letzter_fehler", None)
        raise ValueError(
            "Keine Suchanfrage konnte vektorisiert werden"
            + (f": {type(grund).__name__}: {grund}" if grund else "."))

    breit = max(10, top_k * 3)

    # Die Stichwortsuche kennt keine Sammlungen -- sie liegt in einer
    # Tabelle. Ihr Rechtefilter ist deshalb die Raumliste, und sie kommt
    # aus derselben Quelle wie die Sammlungen: nicht vom Client.
    erlaubte_raeume = ([r for r, _ in paare_sammlungen]
                       if paare_sammlungen is not None
                       else raeume.lesbar(benutzer))

    # Jede Sonde und jeder Suchweg liefert eine EIGENE Rangliste. Die
    # Reihenfolge innerhalb der Listen ist die eigentliche Information fuer
    # die Fusion -- frueher wurde sie beim Entdoppeln weggeworfen.
    ranglisten = []

    # A. VEKTORSUCHE -- je Raum eine Abfrage, danach zusammengefuehrt
    _vektorlisten, _vektorausfall = _vektortreffer(
        paare_sammlungen, [v for _, v in paare], breit,
        _where(dateien), benutzer)
    for i, liste_roh in enumerate(_vektorlisten):
        probe = paare[i][0]
        liste = [{"text": t, "meta": m, "probe": probe}
                 for _d, t, m in liste_roh]
        if liste:
            ranglisten.append(liste)
    _merke("vektorsuche")

    # B. STICHWORTSUCHE (SQLite FTS5)
    #
    # Rechte- und Dokumentenfilter laufen in SQL statt nachtraeglich in
    # Python. Dort hing der Rechtecheck an meta.get('access', 'shared') --
    # Chunks ohne access-Schluessel galten damit als oeffentlich.
    for probe, _ in paare:
        gefunden = keyword_index.search(
            probe, benutzer, limit=breit,
            file_names=list(dateien) if dateien else None,
            raeume=erlaubte_raeume)
        liste = [{"text": h["text"], "meta": h["meta"], "probe": probe}
                 for h in gefunden]
        if liste:
            ranglisten.append(liste)

    _merke("stichwortsuche")
    zahlen = {"kandidaten": sum(len(l) for l in ranglisten),
              "ranglisten": len(ranglisten),
              "zeiten": _zeiten,
              # Welche Raeume die Vektorsuche nicht beantworten konnte.
              # Leer heisst: alle wurden gefragt.
              "vektorausfall": _vektorausfall}

    if not ranglisten:
        return [], zahlen

    ergebnis = []
    _rang = ranking.rank(ranglisten, top_k, bewerter=bewerter)
    _merke("rangfolge")
    for text, _score, eintrag in _rang:
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


def systemprompt(kontexttext, preset=None):
    """Vorlage mit Rolle und Kontext gefuellt."""
    rolle = os.getenv("EXPERT_ROLE", "Forschungsassistent für das Bauwesen")
    return (_vorlage("system_prompt.txt", RUECKFALL_SYSTEMPROMPT, preset)
            .replace("{EXPERT_ROLE}", rolle)
            .replace("{GLOSSAR}", _glossarblock(preset))
            .replace("{CONTEXT_PLATZHALTER}", kontexttext))


# Wie oft das Modell hoechstens nachschlagen darf, bevor es antworten
# muss. Ohne Grenze kann es sich im Kreis drehen -- und jede Runde
# kostet einen Modellaufruf und die Wartezeit des Menschen davor.
WERKZEUG_RUNDEN = paths.env_int("MCP_RUNDEN", 4)


def werkzeuglauf(client, modell, system, nachrichten, verbindungen,
                 verlauf_anzahl=20, fortschritt=None):
    """Laesst das Modell Werkzeuge rufen, bis es antworten kann.

    Rueckgabe: (zusatz, entwuerfe)

      zusatz     Nachrichten, die an den Verlauf gehaengt werden, damit
                 die Antwort das Nachgeschlagene kennt.
      entwuerfe  Aufrufe, die NICHT ausgefuehrt wurden, weil sie etwas
                 verschicken wuerden. Sie warten auf einen Menschen.

    OHNE SERVER PASSIERT NICHTS: kein Modellaufruf, keine Werkzeugliste,
    ([], []) zurueck. Eine Installation ohne Postfach merkt von diesem
    Code nichts.
    """
    import mcp

    if not verbindungen:
        return [], []
    werkzeuge = mcp.als_werkzeugliste(verbindungen, sagen=fortschritt)
    if not werkzeuge:
        return [], []

    an_modell = [{"role": "system", "content": system}]
    for m in nachrichten[-verlauf_anzahl:]:
        an_modell.append({"role": m["role"], "content": m["content"]})

    zusatz, entwuerfe = [], []
    for _runde in range(max(1, WERKZEUG_RUNDEN)):
        try:
            a = client.chat.completions.create(
                model=modell, messages=an_modell + zusatz,
                tools=werkzeuge, tool_choice="auto",
                timeout=HELPER_TIMEOUT)
        except Exception as e:
            # Ein Modell, das mit Werkzeugen nicht umgehen kann, darf die
            # Antwort nicht verhindern. Dann eben ohne Nachschlagen --
            # das ist genau der Zustand von vor dieser Erweiterung.
            if fortschritt:
                fortschritt(f"Werkzeuge nicht nutzbar: {type(e).__name__}")
            return [], []

        nachricht = a.choices[0].message if a.choices else None
        rufe = list(getattr(nachricht, "tool_calls", None) or [])
        if not rufe:
            break

        zusatz.append({
            "role": "assistant",
            "content": nachricht.content or "",
            "tool_calls": [{"id": r.id, "type": "function",
                            "function": {"name": r.function.name,
                                         "arguments": r.function.arguments}}
                           for r in rufe],
        })

        for r in rufe:
            server, name = mcp.teile_namen(r.function.name)
            try:
                argumente = json.loads(r.function.arguments or "{}")
            except ValueError:
                argumente = {}
            if fortschritt:
                fortschritt(f"{server}: {name}")

            if server not in verbindungen:
                ergebnis = f"Kein Server namens '{server}'."
            elif mcp.braucht_bestaetigung(server, name, argumente):
                # NICHT ausfuehren. Der Entwurf geht an die Oberflaeche,
                # und das Modell erfaehrt ausdruecklich, dass nichts
                # verschickt wurde -- sonst schreibt es dem Nutzer, die
                # Nachricht sei unterwegs.
                entwuerfe.append({"server": server, "werkzeug": name,
                                  "argumente": argumente})
                ergebnis = ("NICHT ausgefuehrt. Der Entwurf liegt dem "
                            "Nutzer zur Bestaetigung vor; erst sein Klick "
                            "verschickt ihn. Sage ihm, dass ein Entwurf "
                            "bereitliegt -- nicht, dass gesendet wurde.")
            else:
                if mcp.sendet(server, name):
                    argumente = mcp.mit_hinweis(server, argumente)
                try:
                    ergebnis = verbindungen[server].rufe(name, argumente)
                except Exception as e:
                    ergebnis = f"Fehler: {e}"

            zusatz.append({"role": "tool", "tool_call_id": r.id,
                           "content": (ergebnis or "")[:8000]})

    return zusatz, entwuerfe


def antwort(client, modell, system, nachrichten, verlauf_anzahl=20,
            zusatz=()):
    """Erzeugt die Antwort und gibt sie stueckweise aus.

    Stueckweise, weil eine Antwort auf einem lokalen 27B-Modell leicht eine
    halbe Minute dauert -- am Stueck ist das eine halbe Minute ohne jedes
    Lebenszeichen.
    """
    an_modell = [{"role": "system", "content": system}]
    for m in nachrichten[-verlauf_anzahl:]:
        an_modell.append({"role": m["role"], "content": m["content"]})
    # Was der Werkzeugkreis nachgeschlagen hat, gehoert dazu -- sonst
    # antwortet das Modell, ohne zu wissen, was es gerade erfragt hat.
    an_modell.extend(zusatz or [])

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
    """Fasst die Treffer nach Raum, Datei und Seite zusammen.

    Mehrere Abschnitte derselben Seite werden zu einem Eintrag -- sonst
    stuende dieselbe Fundstelle mehrfach unter der Antwort.

    Der Raum gehoert in den Schluessel und nicht nur ins Ergebnis. Zwei
    Raeume duerfen dieselbe 'Angebot.pdf' fuehren; ohne ihn waeren ihre
    Abschnitte zu einer Fundstelle verschmolzen, und die Quellenansicht
    haette zu ihr eine der beiden Dateien gezeigt -- welche, entschied die
    Reihenfolge auf der Platte.
    """
    gesammelt = {}
    for eintrag in treffer:
        meta = eintrag["meta"]
        schluessel = (meta.get("raum") or "", meta.get("file_name", "?"),
                      meta.get("page", "?"))
        gesammelt.setdefault(schluessel, []).append(eintrag["text"])
    return [{"file": datei, "page": seite, "raum": raum, "texts": texte}
            for (raum, datei, seite), texte in gesammelt.items()]


def projekte(benutzer, raum, notzugang=()):
    """{projekt: [dateien]} eines Raums, aus dem Ordner je Datei.

    Zum SORTIEREN, nicht zum Teilen. Wer viele Vorgaenge im eigenen
    Raum hat, will eine Frage zu Projekt B stellen, ohne dass A
    mitantwortet -- und das ist keine Rechtefrage, sondern eine der
    Menge: ein Modell, das zwoelf Abschnitte aus fuenf Vorgaengen
    bekommt, mischt sie.

    Eine Berechtigung ist das ausdruecklich NICHT. Geteilt wird ueber
    Raeume; ein Ordner, der aussieht wie ein Recht und keines ist, war
    schon einmal da und hiess Sachgebiet.
    """
    aus = {}
    for r, sml in sammlungen(benutzer, nur=[raum], notzugang=notzugang):
        try:
            daten = sml.get(include=["metadatas"])
        except Exception:
            continue
        for m in store.metadaten_klartext(r, daten.get("metadatas") or []):
            if not m or not m.get("file_name"):
                continue
            aus.setdefault(str(m.get("folder") or ""), set()).add(
                m["file_name"])
    return {k: sorted(v) for k, v in sorted(aus.items())}


def dokumente(benutzer, nur=None, notzugang=()):
    """Welche Dokumente dieser Nutzer sehen darf, je Raum.

    Dieselbe Quelle wie die Suche: durchgegangen werden genau die Raeume
    aus sammlungen(benutzer). Steht hier statt in der Oberflaeche, damit
    Oberflaeche und Schnittstelle nicht zwei Auffassungen davon entwickeln,
    was sichtbar ist.

    Rueckgabe: {raum: sortierte Dateiliste}.

    Frueher kam ein zweiter Wert dazu, die Sachgebiete. Die gibt es nicht
    mehr: ein Sachgebiet war ein Unterordner, der die Suche einschraenkte,
    ohne ein Recht zu sein -- ein zweiter Filter, der aussah wie eine
    Rechteeinschraenkung und keine war. Der Raum leistet dasselbe und
    bindet es an eine Berechtigung.
    """
    nach_raum = {}
    for raum, sml in sammlungen(benutzer, nur=nur,
                                notzugang=notzugang):
        dateien = set()
        try:
            daten = sml.get(include=["metadatas"])
        except Exception:
            continue
        for m in store.metadaten_klartext(raum,
                                          daten.get("metadatas") or []):
            if not m:
                continue
            if m.get("file_name"):
                dateien.add(m["file_name"])
        nach_raum[raum] = sorted(dateien)
    return nach_raum
