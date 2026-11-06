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
import re
import time

import local_time
import paths
import statefiles
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
        with statefiles.open(pfad, "r", encoding="utf-8") as f:
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
        with statefiles.open(pfad, "r", encoding="utf-8") as f:
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
            # Ueber store.frage: ein Raum, in den gerade zum ersten Mal
            # geschrieben wurde, hat sein Vektorsegment vielleicht noch
            # nicht abgelegt. Das wird dort wiederholt und ist kein
            # Ausfall; alles andere kommt hier an.
            res = store.frage(sml, name=raeume.sammlung(raum),
                              query_embeddings=vektoren, n_results=breit,
                              where=filter_,
                              include=["documents", "metadatas",
                                       "distances"])
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
        # Ein gelesener Scan sagt dem Modell, dass er gelesen ist: Zahlen
        # darin koennen falsch erkannt sein.
        _h = {"ocr": ' herkunft="texterkennung"',
              "sehmodell": ' herkunft="sehmodell"'}.get(meta.get("quelle"), "")
        teile.append('<chunk file="{}" page="{}"{}>\n{}\n</chunk>'.format(
            meta.get("file_name", "?"), meta.get("page", "?"), _h,
            eintrag["text"]))
    if not teile:
        teile.append("Keine relevanten Dokumenten-Abschnitte gefunden.")

    for n, text in enumerate(bild_texte, 1):
        teile.append('<hochgeladenes_bild nr="{}">\n{}\n</hochgeladenes_bild>'
                     .format(n, text))

    for name, inhalt in bloecke:
        teile.append("<{0}>\n{1}\n</{0}>".format(name, inhalt))

    return "\n\n".join(teile) + "\n\n"


def systemprompt(kontexttext, preset=None, benutzer=None):
    """Vorlage mit Rolle und Kontext gefuellt.

    benutzer haengt dessen persoenliche Anweisung an (prompts.anweisung).
    Ohne ihn -- Werkzeuge, die keinen Menschen kennen -- bleibt es bei der
    Vorlage.
    """
    import prompts
    rolle = os.getenv("EXPERT_ROLE", "technischer Assistent")
    text = (_vorlage("system_prompt.txt", RUECKFALL_SYSTEMPROMPT, preset)
            .replace("{EXPERT_ROLE}", rolle)
            .replace("{GLOSSAR}", _glossarblock(preset))
            .replace("{CONTEXT_PLATZHALTER}", kontexttext))
    # Today and the weekdays around it: the model has no clock, and a
    # weekday it computes itself is wrong often enough to matter.
    text += "\n" + local_time.calendar_block(_language(benutzer))
    return prompts.mit_anweisung(text, benutzer) if benutzer else text


def _language(user):
    if not user:
        return "de"
    try:
        import sprache
        return "en" if sprache.gewaehlt(user) == "en" else "de"
    except Exception:
        return "de"


# --- THE HISTORY THE MODEL SEES ---
#
# An answer that used tools (a mailbox, the calendar, web search) keeps
# the calls and their results (answering.py, "tool_log"). Without them
# the next question only shows the model its own summary: it no longer
# knows the mails it listed, and asked about them it may even say it made
# them up. The log goes back in as what it was -- tool calls and tool
# results before the answer -- for the last TOOL_LOG_TURNS answers.
TOOL_LOG_TURNS = paths.env_int("TOOL_LOG_TURNS", 3)
TOOL_LOG_CHARS = paths.env_int("TOOL_LOG_CHARS", 4000)

_DRAFT_STATE = {
    "sent": "Der Nutzer hat den Entwurf bestaetigt; er wurde ausgefuehrt.",
    "discarded": "Der Nutzer hat den Entwurf verworfen; nichts wurde ausgefuehrt.",
    "sending": "Der Entwurf wird gerade ausgefuehrt.",
    "failed": "Der Nutzer hat den Entwurf bestaetigt, die Ausfuehrung ist fehlgeschlagen.",
    "unclear": ("Der Nutzer hat den Entwurf bestaetigt; ob er ausgefuehrt "
                "wurde, ist unklar (keine Antwort vom Server)."),
}


def tool_log(zusatz, entwuerfe=()):
    """The tool messages of one answer, cut for storing with it."""
    out = []
    for m in zusatz or []:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            out.append({"role": "assistant", "content": m.get("content") or "",
                        "tool_calls": m["tool_calls"]})
        elif m.get("role") == "tool":
            text = str(m.get("content") or "")
            if len(text) > TOOL_LOG_CHARS:
                text = text[:TOOL_LOG_CHARS] + " ... (gekuerzt)"
            out.append({"role": "tool", "tool_call_id": m.get("tool_call_id"),
                        "content": text})
    return out


def _draft_result(draft):
    state = draft.get("state")
    text = _DRAFT_STATE.get(state, "NICHT ausgefuehrt. Der Entwurf wartet "
                                   "noch auf die Bestaetigung des Nutzers.")
    detail = draft.get("result") or draft.get("error")
    return text + (f" Rueckmeldung: {detail}" if detail else "")


def history_for_model(nachrichten, anzahl=20):
    """The last messages for the model, with the tool calls of recent answers."""
    recent = [m for m in (nachrichten or []) if not m.get("laeuft")][-anzahl:]
    logged = [i for i, m in enumerate(recent)
              if m.get("role") == "assistant" and m.get("tool_log")]
    keep = set(logged[-max(0, TOOL_LOG_TURNS):])
    out = []
    for i, m in enumerate(recent):
        if i in keep:
            drafts = {d.get("call_id"): d for d in m.get("entwuerfe") or []
                      if d.get("call_id")}
            for t in m["tool_log"]:
                t = dict(t)
                if t.get("role") == "tool" and t.get("tool_call_id") in drafts:
                    t["content"] = _draft_result(drafts[t["tool_call_id"]])
                out.append(t)
        out.append({"role": m["role"], "content": m.get("content") or ""})
    return out


# Wie oft das Modell hoechstens nachschlagen darf, bevor es antworten
# muss. Ohne Grenze kann es sich im Kreis drehen -- und jede Runde
# kostet einen Modellaufruf und die Wartezeit des Menschen davor.
# Eight: "check my mail and invite A and B" is a mail search, one search
# per address, a look into the calendar and the invitation -- with four
# the invitation never came, and the answer announced it all the same.
WERKZEUG_RUNDEN = paths.env_int("MCP_RUNDEN", 8)

# How long one round of the tool loop may take. It sends the whole
# history and every tool description; on a local model that took longer
# than the 60 s of HELPER_TIMEOUT, the loop gave up quietly, and the
# model then answered that it could not send mail -- one message after
# it had done so.
TOOL_TIMEOUT = paths.env_float("TOOL_TIMEOUT", 180)


# A question that names a mailbox or the calendar. When the model answers
# it in the first round without calling a tool, it is asked once more
# with tool_choice "required" -- a model that "forgot" its tools then
# claims to have no access, or invents the mails.
_ASKS_FOR_TOOLS = re.compile(
    r"(postfach|posteingang|mail|kalender|termin|einlad|besprechung|"
    r"meeting|calendar|inbox|verschick|weiterleit)", re.I)

# Some servers (vLLM without a tool parser, a gateway in between) hand a
# tool call back as text: <tool_call>{"name": ..., "arguments": {...}}</tool_call>.
_TEXT_TOOL_CALL = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)


def _text_tool_calls(content):
    """Tool calls written as text, as objects like the API's."""
    import types
    out = []
    for n, raw in enumerate(_TEXT_TOOL_CALL.findall(content or "")):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        name = data.get("name")
        if not name:
            continue
        args = data.get("arguments") or data.get("parameters") or {}
        out.append(types.SimpleNamespace(
            id=f"text_{n}", function=types.SimpleNamespace(
                name=name, arguments=args if isinstance(args, str)
                else json.dumps(args, ensure_ascii=False))))
    return out


def tools_preamble(beschreibungen):
    """What the model has to know about its tools, for the tool round and
    the answer: they exist, their results are real data, and asked about
    mail or the calendar it calls them instead of saying it cannot."""
    if not beschreibungen:
        return ""
    return ("\n<werkzeuge>\nIn diesem Gespraech stehen dir Werkzeuge zur "
            "Verfuegung: " + "; ".join(beschreibungen) + ".\n"
            "Ergebnisse von Werkzeugaufrufen sind echte Daten aus diesen "
            "Systemen und gelten wie der <context>; sie sind nicht erfunden "
            "und werden nicht im Format [Datei, Seite] zitiert. Wird nach "
            "Mail, Postfach, Kalender oder Terminen gefragt, rufe das "
            "passende Werkzeug auf -- sage nie, du haettest keinen Zugriff.\n"
            "</werkzeuge>\n")


def answer_tool_note(zusatz, beschreibungen, entwuerfe=()):
    """For the answer: which tools ran and which drafts wait. Without a
    call it must not present mailbox or calendar data that no tool
    returned; without a draft it must not say it creates or sends one."""
    if not beschreibungen:
        return ""
    import mcp
    names = []
    for m in zusatz or []:
        for r in m.get("tool_calls") or []:
            names.append("__".join(mcp.teile_namen(r["function"]["name"])))
    if entwuerfe:
        drafts = ("Unter der Antwort liegen dem Nutzer diese Entwuerfe zur "
                  "Bestaetigung vor: " + "; ".join(
                      f"{d.get('werkzeug')} ({d.get('vorschau') or d.get('server')})"
                      for d in entwuerfe) + ". Sage ihm, dass er sie dort bestaetigt.")
    else:
        drafts = ("Es liegt KEIN Entwurf vor: schreibe nicht, du legst einen "
                  "Termin, eine Einladung oder eine Mail an oder habest es "
                  "getan.")
    if names:
        return ("\nIn dieser Antwort aufgerufene Werkzeuge: "
                + ", ".join(dict.fromkeys(names)) + ". Ihre Ergebnisse "
                "stehen oben als Werkzeugergebnisse. " + drafts + "\n")
    return ("\nIn dieser Antwort wurde KEIN Werkzeug aufgerufen. Gib keine "
            "Mails, Termine oder Webinhalte wieder, die nicht in einem "
            "frueheren Werkzeugergebnis stehen. Fragt der Nutzer danach, "
            "sage, dass du nachsehen kannst, wenn er die Frage noch einmal "
            "stellt -- nicht, dass du keinen Zugriff hast.\n")


def werkzeuglauf(client, modell, system, nachrichten, verbindungen,
                 verlauf_anzahl=20, fortschritt=None, vorab=None,
                 hinweise=None):
    """Laesst das Modell Werkzeuge rufen, bis es antworten kann.

    Rueckgabe: (zusatz, entwuerfe)

      zusatz     Nachrichten, die an den Verlauf gehaengt werden, damit
                 die Antwort das Nachgeschlagene kennt.
      entwuerfe  Aufrufe, die NICHT ausgefuehrt wurden, weil sie etwas
                 verschicken wuerden. Sie warten auf einen Menschen.

    vorab: tool messages already there (a confirmed web search), the
    loop continues after them. hinweise: a list that collects what the
    answer has to tell (a mailbox not signed in, tools not reachable),
    so the model says so instead of guessing.

    OHNE SERVER PASSIERT NICHTS: kein Modellaufruf, keine Werkzeugliste,
    ([], []) zurueck. Eine Installation ohne Postfach merkt von diesem
    Code nichts.
    """
    import mcp

    hinweise = hinweise if hinweise is not None else []
    if not verbindungen:
        return list(vorab or []), []

    def sagen(text):
        if fortschritt:
            fortschritt(text)
        hinweise.append(str(text))

    werkzeuge = mcp.als_werkzeugliste(verbindungen, sagen=sagen)
    if not werkzeuge:
        return list(vorab or []), []

    an_modell = [{"role": "system", "content": system}]
    an_modell += history_for_model(nachrichten, verlauf_anzahl)

    zusatz, entwuerfe = list(vorab or []), []
    letzte_frage = next((m.get("content") or "" for m in reversed(nachrichten)
                         if m.get("role") == "user"), "")
    for runde in range(max(1, WERKZEUG_RUNDEN)):
        try:
            try:
                a = client.chat.completions.create(
                    model=modell, messages=an_modell + zusatz,
                    tools=werkzeuge, tool_choice="auto",
                    timeout=TOOL_TIMEOUT)
            except Exception as e:
                # A dropped connection or a 500 of the gateway ("Server
                # disconnected") is often gone a moment later: once more.
                # A timeout is not tried again -- it would cost another
                # TOOL_TIMEOUT.
                if "timeout" in type(e).__name__.lower():
                    raise
                time.sleep(2)
                a = client.chat.completions.create(
                    model=modell, messages=an_modell + zusatz,
                    tools=werkzeuge, tool_choice="auto",
                    timeout=TOOL_TIMEOUT)
        except Exception as e:
            # Ein Modell, das mit Werkzeugen nicht umgehen kann, darf die
            # Antwort nicht verhindern. Dann eben ohne Nachschlagen --
            # aber das Modell erfaehrt es und sagt es, statt zu raten.
            sagen(f"Werkzeuge nicht nutzbar: {type(e).__name__}: {str(e)[:160]}")
            return zusatz, entwuerfe

        nachricht = a.choices[0].message if a.choices else None
        rufe = list(getattr(nachricht, "tool_calls", None) or [])
        if not rufe:
            rufe = _text_tool_calls(getattr(nachricht, "content", "") or "")
        if not rufe and runde == 0 and not vorab \
                and _ASKS_FOR_TOOLS.search(letzte_frage):
            # Asked about mail or the calendar and answered without a
            # tool: once more, this time a tool call is required.
            try:
                a = client.chat.completions.create(
                    model=modell, messages=an_modell + zusatz,
                    tools=werkzeuge, tool_choice="required",
                    timeout=TOOL_TIMEOUT)
                nachricht = a.choices[0].message if a.choices else None
                rufe = list(getattr(nachricht, "tool_calls", None) or []) \
                    or _text_tool_calls(getattr(nachricht, "content", "") or "")
            except Exception:
                rufe = []      # "required" not supported: go on without
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
            elif (mcp.braucht_bestaetigung(server, name, argumente)
                  # A built-in server names its own tools that need a
                  # person (workspace_notes.Tools.confirm).
                  or name in getattr(verbindungen[server], "confirm", ())):
                # NICHT ausfuehren. Der Entwurf geht an die Oberflaeche,
                # und das Modell erfaehrt ausdruecklich, dass nichts
                # verschickt wurde -- sonst schreibt es dem Nutzer, die
                # Nachricht sei unterwegs.
                #
                # A server may check the call first (pruefe_entwurf):
                # an incomplete one goes back to the model to correct,
                # instead of failing on the person's click.
                pruefe = getattr(verbindungen[server], "pruefe_entwurf", None)
                try:
                    vorschau = pruefe(name, argumente) if pruefe else None
                except Exception as e:
                    ergebnis = (f"NICHT als Entwurf angenommen: {e} "
                                f"Angaben korrigieren oder beim Nutzer "
                                f"nachfragen.")
                else:
                    entwurf = {"server": server, "werkzeug": name,
                               "argumente": argumente, "call_id": r.id}
                    if vorschau:
                        entwurf["vorschau"] = vorschau
                    entwuerfe.append(entwurf)
                    ergebnis = ("NICHT ausgefuehrt. Der Entwurf liegt dem "
                                "Nutzer zur Bestaetigung vor; erst sein Klick "
                                "fuehrt ihn aus. Sage ihm, dass ein Entwurf "
                                "bereitliegt -- nicht, dass es schon geschehen "
                                "ist." + (f" Entwurf: {vorschau}. Datum und "
                                          f"Wochentag genau so nennen."
                                          if vorschau else ""))
            else:
                sends = mcp.sendet(server, name)
                if sends:
                    argumente = mcp.mit_hinweis(server, argumente)
                try:
                    ergebnis = verbindungen[server].rufe(name, argumente)
                except Exception as e:
                    ergebnis = f"Fehler: {e}"
                    # A timeout after the server took the mail looks like
                    # a failure and is none. Look in the sent folder
                    # before telling anyone it did not go out.
                    check = getattr(verbindungen[server], "check_sent", None)
                    if sends and check:
                        try:
                            if check(name, argumente):
                                ergebnis = ("Gesendet. (Die Antwort des Servers "
                                            "kam nicht rechtzeitig; die Nachricht "
                                            "liegt im Ordner Gesendet.)")
                        except Exception:
                            pass

            zusatz.append({"role": "tool", "tool_call_id": r.id,
                           "content": (ergebnis or "")[:8000]})
    else:
        # Every round used and the model still calling: what it meant to
        # do next did not happen, and the answer has to say so.
        if zusatz and zusatz[-1].get("role") == "tool":
            hinweise.append(f"Grenze von {WERKZEUG_RUNDEN} Werkzeugrunden erreicht; "
                            f"weitere Schritte wurden nicht ausgefuehrt. Dem "
                            f"Nutzer sagen, was fehlt, und ihn bitten, es "
                            f"noch einmal zu verlangen.")

    return zusatz, entwuerfe


_WEBTREFFER = re.compile(
    r"^\[W(\d+)\] (.*?)\nAdresse: (\S+)\n(.*?)(?=\n\n\[W\d+\] |\Z)",
    re.S | re.M)


def webtreffer(zusatz, server):
    """Die Treffer der Websuche aus dem Werkzeugkreis, fuer die Quellen.

    [{nr, titel, adresse, text, anfrage}] -- je Adresse einmal. Gelesen
    wird das Ergebnis, das auch das Modell bekam (websuche.als_text),
    damit die Quellen zeigen, worauf die Antwort wirklich steht.
    """
    import mcp
    rufe = set()
    for m in zusatz or []:
        for r in m.get("tool_calls") or []:
            s, name = mcp.teile_namen(r["function"]["name"])
            if s in server and name == "web_suchen":
                rufe.add(r["id"])
    aus, gesehen = [], set()
    for m in zusatz or []:
        if m.get("role") != "tool" or m.get("tool_call_id") not in rufe:
            continue
        for t in webtreffer_aus_text(m.get("content") or ""):
            if t["adresse"] not in gesehen:
                gesehen.add(t["adresse"])
                aus.append(t)
    return aus


def webtreffer_aus_text(text):
    """Die Treffer eines Suchergebnisses (websuche.als_text)."""
    kopf = re.match(r'WEBSUCHE "(.*?)"', text or "")
    return [{"nr": f"W{nr}", "titel": titel.strip(), "adresse": adresse,
             "text": inhalt.strip(), "anfrage": kopf.group(1) if kopf else ""}
            for nr, titel, adresse, inhalt in _WEBTREFFER.findall(text or "")]


def antwort(client, modell, system, nachrichten, verlauf_anzahl=20,
            zusatz=()):
    """Erzeugt die Antwort und gibt sie stueckweise aus.

    Stueckweise, weil eine Antwort auf einem lokalen 27B-Modell leicht eine
    halbe Minute dauert -- am Stueck ist das eine halbe Minute ohne jedes
    Lebenszeichen.
    """
    an_modell = [{"role": "system", "content": system}]
    an_modell += history_for_model(nachrichten, verlauf_anzahl)
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
    gesammelt, herkunft = {}, {}
    for eintrag in treffer:
        meta = eintrag["meta"]
        schluessel = (meta.get("raum") or "", meta.get("file_name", "?"),
                      meta.get("page", "?"))
        gesammelt.setdefault(schluessel, []).append(eintrag["text"])
        # Woher der Text einer Seite stammt, wenn nicht aus ihrer
        # Textebene: "ocr" oder "sehmodell". Der Leser soll sehen, wie
        # verlaesslich eine Fundstelle ist.
        if meta.get("quelle"):
            herkunft.setdefault(schluessel, meta["quelle"])
    return [{"file": datei, "page": seite, "raum": raum, "texts": texte,
             "herkunft": herkunft.get((raum, datei, seite), "")}
            for (raum, datei, seite), texte in gesammelt.items()]


_CITATION = re.compile(r"\[([^\[\]]+)\]")
_CITED_PAGE = re.compile(
    r"^\s*(.+?)\s*,\s*(?:Seiten?|pages?|S\.|p\.)\s*([\d\s,\-\u2013und and]+?)\s*$",
    re.IGNORECASE)


def _cited_pages(answer):
    """{(file name, casefolded), page} pairs the answer cites as [file, page X]."""
    cited = set()
    for group in _CITATION.findall(answer or ""):
        for part in group.split(";"):
            m = _CITED_PAGE.match(part)
            if not m:
                continue
            name = m.group(1).strip().casefold()
            for a, b in re.findall(r"(\d+)(?:\s*[-\u2013]\s*(\d+))?", m.group(2)):
                first, last = int(a), int(b or a)
                for page in range(first, min(last, first + 50) + 1):
                    cited.add((name, page))
    return cited


def cited_sources(sources, answer, tools_used=False):
    """(cited, others): the sources the answer cites, and the rest.

    tools_used: an answer from a mailbox, the calendar or the web that
    cites no document has no document source -- then all are "others".

    The model gets every passage the search found; below the answer only
    those it actually cites belong first. A file name counts with or
    without its extension. When the answer cites none of them (no
    citations, or names the model changed), all stay cited -- an answer
    without any source would be worse than one with too many.
    """
    pages = _cited_pages(answer)
    if not pages:
        return ([], list(sources)) if tools_used else (list(sources), [])
    cited, others = [], []
    for s in sources:
        name = str(s.get("file", "")).casefold()
        stem = name.rsplit(".", 1)[0]
        try:
            page = int(s.get("page"))
        except (TypeError, ValueError):
            page = None
        hit = page is not None and ((name, page) in pages or (stem, page) in pages)
        (cited if hit else others).append(s)
    if not cited:
        return list(sources), []
    return cited, others


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
