"""Der Verwaltungsbereich der Seitenleiste.

Herausgeloest aus app.py, das mit 4.300 Zeilen zu gross geworden war --
davon 1.385 fuer diesen Bereich. Die Trennung ist die inhaltlich
richtige: was NUTZER tun gegen was VERWALTER einstellen.

DIE SCHNITTSTELLE IST ABSICHTLICH SICHTBAR. Zwoelf Namen kommen aus
app.py, und sie stehen einzeln in der Signatur statt in einem
Sammelobjekt. Wer einen zwoelften braucht, muss ihn hinschreiben --
und merkt dabei, dass er die Kopplung vergroessert.

Die Namen tragen ihren fuehrenden Unterstrich weiter, obwohl sie damit
als Parameter unueblich aussehen. Der Grund ist der Umzug selbst: so
konnte der Block WOERTLICH herueberwandern, ohne dass eine einzige
Zeile umgeschrieben werden musste. Eine Verschiebung ohne Umbenennung
kann nichts uebersehen -- und genau das war bei 1.385 Zeilen die
einzige Art, es sicher zu tun.

Gezeichnet wird in die Seitenleiste, weil der Aufruf dort steht:
Streamlit richtet sich nach dem Ort des Aufrufs, nicht nach dem der
Funktion.
"""

import os
import time
import streamlit as st
import auth
import benutzer
import chats
import envcheck
import feedback
import geheim
import hintergrund
import keyword_index
import listenquellen
import mcp
import notzugang
import owncloud
import paths
import pipeline
import presets
import prompts
import raeume
import sicherheit
import sicherung
import sqlquellen
import store
import tabellen


def _oc_bericht(bericht, was):
    """Zeigt, was in ownCloud geschehen ist -- und was nicht.

    Nie als Fehlschlag des Ganzen: der Nutzer beziehungsweise der Raum ist
    in LocaNoto zu diesem Zeitpunkt schon angelegt, und ein nicht
    erreichbares ownCloud darf das nicht rueckgaengig machen. Was fehlt,
    steht hier und laesst sich mit "Ablage einrichten" nachholen -- der
    Ablauf ist wiederholbar.
    """
    if not owncloud.eingerichtet():
        return
    if bericht.get("schritte"):
        st.caption("ownCloud: " + " · ".join(bericht["schritte"]))
    for f in bericht.get("fehler") or []:
        st.warning("ownCloud: " + f)
    if bericht.get("fehler"):
        st.caption(f"{was} ist in LocaNoto angelegt. Die Ablage in ownCloud "
                   f"laesst sich unter *ownCloud* nachholen.")


def _unvollstaendig(stand):
    """Fehlte diesem Abzug beim Sichern ein Raum?

    Aeltere Abzuege haben die Angabe 'vollstaendig' nicht -- ihr Fehlen
    heisst nicht "unvollstaendig", sondern "damals nicht vermerkt". Also
    zaehlt hier nur ein ausdruecklich vermerkter Fehlschlag.
    """
    return bool(stand.get("fehler")) or stand.get("vollstaendig") is False


@st.cache_data(ttl=60, show_spinner=False)
def _owncloud_stand():
    """Erreichbarkeit von ownCloud -- eine Anfrage ueber das Netz.

    Sie stand bisher im Aufbau der Seitenleiste und lief damit bei jedem
    Klick. Ist ownCloud langsam oder nicht erreichbar, wartete die ganze
    Oberflaeche darauf.
    """
    if not owncloud.eingerichtet():
        return False, owncloud.beschreibung()
    return owncloud.pruefe()


def zeichne(*, is_admin,
            refresh_document_index,
            aktives_preset,
            _antwortet,
            _eintraege,
            _leeren,
            _feldschluessel,
            _felder_leeren,
            _verwaltungsstand,
            _alle_raum_sammlungen,
            _loeschfreigabe, _p):
    """Zeichnet den Verwaltungsbereich in die Seitenleiste.

    Die Parameter sind die gemessene Kopplung an app.py --
    siehe den Kopf dieser Datei.
    """
    _vw = False
    if is_admin():
        st.markdown("---")
        _vw = st.toggle("\U0001f6e0\ufe0f Verwaltung", value=False,
                        key="verwaltung_offen", disabled=_antwortet,
                        help="Benutzer, Raeume, Sicherung, Prompts und "
                             "alles Weitere zum Einrichten."
                             + (" -- gesperrt, solange eine Antwort laeuft."
                                if _antwortet else ""))
    if _vw:
        zahlen = _verwaltungsstand()["rueckmeldungen"]
        gesamt = sum(zahlen.values())
        if gesamt:
            with st.expander(f"\U0001f4dd Rueckmeldungen ({gesamt})"):
                st.caption(
                    f"ohne Treffer: {zahlen['leer']} \u00b7 "
                    f"hat geholfen: {zahlen['daumen_hoch']} \u00b7 "
                    f"hat nicht geholfen: {zahlen['daumen_runter']}")
                st.caption("**Fragen ohne Treffer** -- Kandidaten fuer "
                           "glossar.txt:")
                leer = feedback.lese(grenze=15, art="leer")
                if leer:
                    st.code(chr(10).join(
                        f"{e['zeitpunkt'][:10]}  {e['frage'][:70]}"
                        for e in leer), language="text")
                else:
                    st.caption("keine")
                schlecht = feedback.lese(grenze=15, art="daumen_runter")
                if schlecht:
                    st.caption("**Als nicht hilfreich gemeldet** -- Treffer "
                               "kamen, aber die falschen:")
                    st.code(chr(10).join(
                        f"{e['zeitpunkt'][:10]}  {e['frage'][:70]}"
                        for e in schlecht), language="text")
                st.caption("Vollstaendig in `data/feedback.jsonl`.")

                # Beiseitelegen statt loeschen: die Arbeitsliste soll leer
                # werden, nicht die Ueberlieferung. Was Nutzer nicht
                # gefunden haben, ist die einzige Quelle fuer die Frage, ob
                # der Bestand mit der Zeit besser wird.
                if st.button("Liste abschliessen", use_container_width=True,
                             help="Legt das Protokoll unter einem Datum ab "
                                  "und beginnt ein neues. Es wird nichts "
                                  "geloescht."):
                    ziel = feedback.archiviere()
                    if ziel:
                        st.success(f"Abgelegt als `{os.path.basename(ziel)}`.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.info("Nichts abzulegen.")

                # Herunterladen statt auf den Server steigen: die Liste
                # wird ausgewertet, nicht nur angesehen, und dafuer braucht
                # man sie vollstaendig.
                if os.path.exists(feedback.DATEI):
                    # Entschluesselt: auf der Platte liegt es
                    # verschluesselt, ausgewertet wird es im Klartext.
                    st.download_button(
                        "Protokoll herunterladen", feedback.als_text(),
                        file_name="feedback.jsonl",
                        mime="application/x-ndjson",
                        use_container_width=True)

                alte = feedback.ablagen()
                if alte:
                    st.caption("Frueher abgelegt:")
                    wahl = st.selectbox("Ablage", alte, label_visibility="collapsed")
                    pfad = os.path.join(os.path.dirname(feedback.DATEI), wahl)
                    if os.path.exists(pfad):
                        with open(pfad, "rb") as f:
                            st.download_button(
                                f"{wahl} herunterladen", f.read(),
                                file_name=wahl, mime="application/x-ndjson",
                                use_container_width=True)

    # --- GLOSSAR ---
    #
    # Bearbeitbar im Browser, weil es laufend gepflegt wird: die Eintraege
    # entstehen aus den Fragen, die nichts gefunden haben, und wer sie
    # nachtraegt sitzt nicht am Server. Die Datei liegt unter config/ und
    # ist damit eingehaengt -- die Aenderung wirkt bei der naechsten Frage,
    # ohne Rebuild und ohne Neustart.
    # --- BENUTZER VERWALTEN ---
    #
    # Vorher gab es das nur im Terminal, und dort ohne jede Nachfrage: wer
    # create_user.py starten konnte, legte sich einen Zugang an. Jetzt
    # verlangt das Skript die Anmeldung eines Verwalters -- und derselbe
    # Vorgang steht hier, weil ein Verwalter dafuer nicht auf den Server
    # steigen sollte.
    if _vw:
        st.caption("**Zugaenge**")
    if _vw:
        with st.expander("👥 Benutzer verwalten"):
            _zustand = benutzer.zustand()
            _gesperrt = benutzer.ungueltige()

            if _zustand == benutzer.UNSIGNIERT:
                st.warning(
                    "Die Benutzerdatei stammt aus der Zeit vor den "
                    "Signaturen. Bis sie signiert ist, gilt weiter "
                    "`ADMIN_USERS` aus der `.env`, und ein von Hand "
                    "eingetragener Zugang käme herein.")
                if st.button("Jetzt signieren", use_container_width=True):
                    ok, meldung = benutzer.neu_signieren(
                        von=st.session_state["username"])
                    (st.success if ok else st.error)(meldung)
                    time.sleep(1)
                    st.rerun()
            elif _zustand == benutzer.MANIPULIERT:
                st.error(
                    "Die Benutzerdatei wurde außerhalb der Anwendung "
                    "geändert."
                    + (f" Gesperrt, weil ohne gültige Signatur: "
                       f"{', '.join(_gesperrt)}." if _gesperrt else
                       " Es fehlt oder es kam ein Eintrag hinzu."))

            # Kollidierende Kennungen: zwei Nutzer, ein persoenlicher
            # Raum. Beim Anlegen wird das jetzt abgewiesen -- ein
            # Bestand kann es aber schon enthalten.
            _konflikte = raeume.konflikte(benutzer.namen())
            if _konflikte:
                st.error(
                    "Diese Kennungen teilen sich einen persoenlichen Raum "
                    "und sehen damit die Unterlagen des jeweils anderen: "
                    + "; ".join(
                        f"{', '.join(n)} -> {k}" for k, n in _konflikte)
                    + ". Eine der Kennungen umbenennen (neu anlegen, "
                    + "Dokumente verschieben, alte loeschen).")

            for _n in benutzer.namen():
                _e = benutzer.eintrag(_n) or {}
                _marke = "" if _e.get("_gueltig", True) else "  GESPERRT"
                st.caption(f"**{_n}** · {_e.get('rolle', '?')}"
                           f"{_marke}")

            st.markdown("---")
            _wahl = st.selectbox(
                "Bearbeiten", ["(neu anlegen)"] + benutzer.namen(),
                key="benutzer_wahl")

            if _wahl == "(neu anlegen)":
                _name = st.text_input(
                    "Kennung", key=_feldschluessel("benutzer_neu", "name"))
                _rolle = st.selectbox(
                    "Rolle", list(benutzer.ROLLEN),
                    index=list(benutzer.ROLLEN).index("nutzer"),
                    key=_feldschluessel("benutzer_neu", "rolle"),
                    help="admin verwaltet Nutzer, Räume und den gemeinsamen Bestand. notzugang darf NICHTS davon — die Rolle bestätigt nur den Notzugang eines Verwalters zu einem persönlichen Raum, und gehört deshalb an jemanden, der kein Verwalter ist.")
                _pw1 = st.text_input(
                    f"Passwort (mindestens {benutzer.MIN_PASSWORT} Zeichen)",
                    type="password",
                    key=_feldschluessel("benutzer_neu", "pw1"))
                _pw2 = st.text_input(
                    "Passwort wiederholen", type="password",
                    key=_feldschluessel("benutzer_neu", "pw2"))
                if st.button("Benutzer anlegen", use_container_width=True,
                             disabled=not (_name.strip() and _pw1)):
                    if _pw1 != _pw2:
                        st.error("Die Eingaben stimmen nicht überein.")
                    else:
                        ok, meldung = benutzer.anlege(
                            _name, _pw1, _rolle,
                            von=st.session_state["username"])
                        (st.success if ok else st.error)(meldung)
                        if ok:
                            # ownCloud zieht mit: Konto, persoenlicher
                            # Ordner, Freigabe nur an ihn, dazu der
                            # gemeinsame Ordner. Der Nutzer muss dort
                            # nichts einrichten -- das ist der Sinn von
                            # "eingebettet".
                            with st.spinner("Richte die Ablage ein ..."):
                                _b = owncloud.richte_nutzer_ein(
                                    _name, _pw1, _name)
                            _oc_bericht(_b, "Der Zugang")
                            _leeren()
                            _felder_leeren("benutzer_neu", "name", "rolle",
                                           "pw1", "pw2")
                            time.sleep(2 if _b.get("fehler") else 1)
                            st.rerun()
            else:
                _e = benutzer.eintrag(_wahl) or {}
                st.caption(f"Angelegt: {_e.get('angelegt', 'unbekannt')} "
                           f"· von: {_e.get('von', 'unbekannt')}")
                # Der Rueckfall geht ueber den NAMEN und nicht ueber eine
                # Zahl: als "notzugang" dazukam, waere aus dem frueheren
                # Index 1 ("nutzer") still die neue Rolle geworden.
                _neue_rolle = st.selectbox(
                    "Rolle", list(benutzer.ROLLEN),
                    index=(list(benutzer.ROLLEN).index(_e.get("rolle"))
                           if _e.get("rolle") in benutzer.ROLLEN
                           else list(benutzer.ROLLEN).index("nutzer")),
                    key=f"benutzer_rolle_{_wahl}",
                    help="admin verwaltet Nutzer, Räume und den gemeinsamen Bestand. notzugang darf NICHTS davon — die Rolle bestätigt nur den Notzugang eines Verwalters zu einem persönlichen Raum, und gehört deshalb an jemanden, der kein Verwalter ist.")
                if _neue_rolle != _e.get("rolle"):
                    if st.button("Rolle übernehmen", use_container_width=True,
                                 key=f"benutzer_rs_{_wahl}"):
                        ok, meldung = benutzer.rolle_setzen(
                            _wahl, _neue_rolle,
                            von=st.session_state["username"])
                        (st.success if ok else st.error)(meldung)
                        time.sleep(1)
                        st.rerun()

                # Der Bereich traegt die Kennung: sonst teilten sich
                # zwei Benutzer eine Runde, und das Umschalten auf den
                # naechsten leerte das Feld des vorigen mit.
                _pwb = f"benutzer_pw_{_wahl}"
                _pw1 = st.text_input("Neues Passwort", type="password",
                                     key=_feldschluessel(_pwb, "pw1"))
                _pw2 = st.text_input("Wiederholen", type="password",
                                     key=_feldschluessel(_pwb, "pw2"))
                if st.button("Passwort setzen", use_container_width=True,
                             disabled=not _pw1, key=f"benutzer_pws_{_wahl}"):
                    if _pw1 != _pw2:
                        st.error("Die Eingaben stimmen nicht überein.")
                    else:
                        ok, meldung = benutzer.passwort_setzen(
                            _wahl, _pw1, von=st.session_state["username"])
                        (st.success if ok else st.error)(meldung)
                        if ok:
                            # --- DIE ABLAGE NACHZIEHEN ---
                            #
                            # Beim Anlegen entsteht das ownCloud-Konto
                            # mit. Wer aus einer Migration kommt, hat
                            # keins -- dort kamen nur bcrypt-Hashes mit,
                            # und daraus laesst sich keines erzeugen.
                            # Hier liegt wieder ein Klartextpasswort vor,
                            # also ist das der Moment.
                            #
                            # Ein VORHANDENES Konto bleibt unangetastet:
                            # LocaNoto wird oft auf ein Haus gesetzt, in
                            # dem es die Leute in ownCloud laengst gibt.
                            # Ihnen von hier aus das Passwort ihres
                            # Firmenkontos zu ueberschreiben waere ein
                            # Uebergriff -- und einer, der sie aus allem
                            # aussperrt, was sonst daran haengt.
                            _b = {}
                            if owncloud.eingerichtet():
                                with st.spinner("Richte die Ablage ein ..."):
                                    _b = owncloud.richte_nutzer_ein(
                                        _wahl, _pw1, _wahl)
                                _oc_bericht(_b, "Der Zugang")
                                if any("gab es schon" in _s for _s
                                       in _b.get("schritte") or []):
                                    # Sonst glaubt der Verwalter, die
                                    # beiden Passwoerter seien jetzt
                                    # gleich. Sie sind es nicht.
                                    st.info("Das ownCloud-Konto gab es "
                                            "bereits. Sein Passwort wurde "
                                            "NICHT geaendert -- dort gilt "
                                            "weiter das alte.")
                            _felder_leeren(_pwb, "pw1", "pw2")
                            time.sleep(3 if _b.get("fehler") else 1)
                            st.rerun()

                # Loeschen entfernt den Zugang, nicht die Daten. Chats und
                # der persoenliche Raum bleiben -- wer beides in einem Klick
                # zusammenlegt, loescht irgendwann mehr als gemeint.
                _sicher = st.checkbox(f"'{_wahl}' wirklich löschen",
                                      key=f"benutzer_x_{_wahl}")
                if st.button("Benutzer löschen", use_container_width=True,
                             disabled=not _sicher,
                             key=f"benutzer_del_{_wahl}"):
                    ok, meldung = benutzer.loesche(
                        _wahl, von=st.session_state["username"])
                    (st.success if ok else st.error)(meldung)
                    if ok:
                        time.sleep(1)
                        st.rerun()

            # --- PROTOKOLL ---
            #
            # Verkettet: jeder Eintrag traegt den Hash des vorherigen. Eine
            # entfernte Zeile bricht die Kette, und die Pruefung sagt, an
            # welcher Stelle. Das verhindert nichts -- es macht ein
            # Aufraeumen im Nachhinein sichtbar.
            st.markdown("---")
            _kette_ok, _zeilen = benutzer.protokoll_pruefen()
            if _kette_ok:
                st.caption(f"Protokoll: {_zeilen} Einträge, Kette in Ordnung.")
            else:
                st.error(f"Das Protokoll ist ab Zeile {_zeilen} verändert "
                         f"oder es fehlt eine Zeile.")
            _log = benutzer.protokoll(letzte=20)
            if _log:
                st.code(chr(10).join(
                    f"{e.get('zeit', '?')}  {e.get('aktion', ''):<12} "
                    f"{e.get('ziel', ''):<16} von={e.get('von', '')} "
                    f"{e.get('hinweis', '')}".rstrip()
                    for e in reversed(_log)), language="text")

    # --- VERSCHLUESSELUNG ---
    #
    # Was verschluesselt ist, was nicht, und warum. Steht in der
    # Oberflaeche, weil ein Zustand, den man nur im Quelltext nachlesen
    # kann, bei einer Datenschutzfrage nicht hilft.
    if _vw:
        # --- ZUGANGSTOKEN ---
        #
        # Die Mechanik lag fertig in auth.py und wurde nur von
        # create_token.py im Terminal benutzt. Wer ein Token fuer die
        # Schnittstelle brauchte, musste an eine Konsole im Pod -- fuer
        # eine Aufgabe, die dem Verwalter gehoert, ein Umweg.
        with st.expander("🎫 Zugangstoken für die Schnittstelle"):
            st.caption(
                "Ein Token weist einen Nutzer aus. Was er darf, steht in "
                "der signierten Benutzerdatei — nicht im Token. Für einen "
                "Masseningest in den **allgemeinen Raum** braucht es "
                "deshalb das Token eines Verwalters; mit dem eines "
                "gewöhnlichen Nutzers antwortet die Schnittstelle dort "
                "mit 403.")

            # ZUERST das frisch angelegte Token, falls eines aussteht.
            # Genau einmal zu zeigen heisst in Streamlit: den Wert einen
            # Lauf ueberdauern lassen und ihn wegwerfen, sobald jemand
            # bestaetigt hat, ihn zu haben.
            _frisch = st.session_state.get("_neues_token")
            if _frisch:
                st.success("Angelegt. **Dieser Wert erscheint nur "
                           "dieses eine Mal** — gespeichert ist nur sein "
                           "Hashwert.")
                st.code(_frisch, language="text")
                if st.button("Habe ich notiert", key="token_weg",
                             use_container_width=True):
                    del st.session_state["_neues_token"]
                    st.rerun()
                st.markdown("---")

            _namen = benutzer.namen()
            if not _namen:
                st.caption("Noch kein Benutzer angelegt.")
            else:
                # Im Formular, aus demselben Grund wie beim
                # Passwortaendern: ein Textfeld uebergibt seinen Inhalt
                # erst beim Verlassen, und ein Klick direkt nach dem
                # Tippen saehe sonst ein leeres Feld.
                _tk = "token_neu"
                with st.form(f"token_{_feldschluessel(_tk, 'runde')}"):
                    _t_wer = st.selectbox(
                        "Für wen", _namen,
                        key=_feldschluessel(_tk, "wer"))
                    _t_bez = st.text_input(
                        "Bezeichnung", key=_feldschluessel(_tk, "bez"),
                        help="Wofür es gedacht ist, etwa "
                             "'Masseningest Laptop'. Erscheint in der "
                             "Liste unten.")
                    _t_tage = st.number_input(
                        "Gültig für Tage (0 = unbegrenzt)",
                        min_value=0, max_value=3650, value=0, step=30,
                        key=_feldschluessel(_tk, "tage"))
                    _t_ab = st.form_submit_button(
                        "Token anlegen", use_container_width=True,
                        disabled=_antwortet)
                if _t_ab:
                    try:
                        st.session_state["_neues_token"] = auth.erzeuge(
                            _t_wer, _t_bez, int(_t_tage) or None)
                        _felder_leeren(_tk)
                        _leeren()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Nicht angelegt: {type(e).__name__}: {e}")

            # --- die vorhandenen ---
            st.markdown("---")
            _tokens = auth.liste()
            if not _tokens:
                st.caption("Keine Token angelegt.")
            for _h, _e in _tokens:
                _bis = _e.get("gueltig_bis")
                _zusatz = _e.get("bezeichnung") or "ohne Bezeichnung"
                if _bis:
                    _zusatz += f" · bis {_bis[:10]}"
                if not _e.get("gueltig", True):
                    # Ohne gueltige Signatur: von Hand eingetragen oder
                    # veraendert. Es gilt nicht -- und wird genau deshalb
                    # gezeigt, statt verschwiegen.
                    _zusatz += " · **UNGÜLTIG**"
                _z1, _z2 = st.columns([4, 1])
                with _z1:
                    st.markdown(
                        f"`{_h[:8]}` · **{_e.get('benutzer', '?')}** · "
                        f"{_zusatz}")
                    st.caption(f"angelegt {_e.get('erstellt', '?')[:19]}")
                with _z2:
                    if st.button("🗑️", key=f"token_weg_{_h[:12]}",
                                 help="Widerrufen", disabled=_antwortet):
                        _anzahl = auth.widerrufe(_h)
                        if _anzahl == 1:
                            st.info("Widerrufen.")
                        else:
                            st.error("Nicht widerrufen.")
                        _leeren()
                        time.sleep(1)
                        st.rerun()

        # --- POSTFAECHER ---
        #
        # Ein Werkzeugserver stellt dem Modell Funktionen bereit, die es
        # waehrend einer Antwort aufrufen kann. Eingerichtet wird hier
        # statt in einer Datei von Hand.
        with st.expander("📬 Postfächer (Werkzeugserver)"):
            _pf = mcp.lies_konfiguration()
            if not _pf:
                st.caption("Kein Postfach eingerichtet. Ohne eines bleibt "
                           "der Werkzeugkreis aus — keine Werkzeugliste, "
                           "kein zusätzlicher Modellaufruf.")
            for _name, _a in sorted(_pf.items()):
                _art = "persönlich" if _a.get("persoenlich") else "Funktion"
                _wie = ("antwortet selbständig" if _a.get("automatisch")
                        else "legt Entwürfe vor")
                _z1, _z2 = st.columns([4, 1])
                with _z1:
                    st.markdown(f"**{_name}** · {_art} · {_wie}")
                    # Bei Exchange darf die Adresse fehlen -- dann sucht
                    # exchangelib den Server. Das steht hier, damit eine
                    # leere Zeile nicht nach einem Einrichtungsfehler
                    # aussieht.
                    _ziel = (_a.get("url")
                             or " ".join(_a.get("befehl") or [])
                             or ("Server wird gesucht"
                                 if _a.get("transport") == "exchange" else "—"))
                    st.caption(
                        f"{_ziel}"
                        + (f" · Postfach: {_a['postfach']}"
                           if _a.get("postfach") else "")
                        + f" · Anmeldung: {mcp.anmeldeart(_name)}"
                        + ("" if not _a.get("automatisch") else
                           (" · mit Hinweis" if mcp.hinweis_an(_name)
                            else " · OHNE Hinweis")))
                with _z2:
                    if st.button("🗑️", key=f"pf_weg_{_name}",
                                 help="Entfernen", disabled=_antwortet):
                        _ok, _m = mcp.entferne_postfach(_name)
                        (st.info if _ok else st.error)(_m)
                        _leeren()
                        time.sleep(1)
                        st.rerun()
                if st.button("Werkzeuge abfragen", key=f"pf_test_{_name}",
                             disabled=_antwortet):
                    _v = mcp.verbinde(
                        st.session_state.get("_postfach_koepfe"))
                    try:
                        _w = _v[_name].werkzeuge()
                        st.success(f"{len(_w)} Werkzeuge")
                        for _x in _w:
                            _marke = ("**[SENDET]**"
                                      if mcp.sendet(_name, _x.get("name"))
                                      else "[liest]")
                            st.markdown(f"- {_marke} `{_x.get('name')}` — "
                                        f"{_x.get('beschreibung', '')[:90]}")
                    except Exception as e:
                        st.error(f"{type(e).__name__}: {e}")
                    finally:
                        for _vv in _v.values():
                            try:
                                _vv.schliesse()
                            except Exception:
                                pass
                st.markdown("---")

            # --- anlegen ---
            _pk = "postfach_neu"
            with st.form(f"postfach_{_feldschluessel(_pk, 'runde')}"):
                st.markdown("**Neues Postfach**")
                _v_wahl = st.selectbox(
                    "Art des Servers", sorted(mcp.VORLAGEN),
                    format_func=lambda v: mcp.VORLAGEN[v]["beschreibung"],
                    key=_feldschluessel(_pk, "vorlage"))
                _v_name = st.text_input(
                    "Name", key=_feldschluessel(_pk, "name"),
                    help="Erscheint im Werkzeugnamen, den das Modell sieht. "
                         "Kurz und sprechend, etwa 'info' oder 'markus'.")
                _v_ziel = st.text_input(
                    "Adresse oder Befehl", key=_feldschluessel(_pk, "ziel"),
                    help="Bei Exchange der Server, etwa `owa.firma.de` — "
                         "den Pfad `/EWS/Exchange.asmx` ergänzt LocaNoto. "
                         "Leer lassen sucht den Server selbst. Bei HTTP die "
                         "Adresse des Servers, bei einem lokalen Prozess "
                         "der Startbefehl.")
                _v_pers = st.radio(
                    "Postfach", ["persönlich", "Funktionspostfach"],
                    key=_feldschluessel(_pk, "pers"),
                    help="Ein persönliches Postfach antwortet nie "
                         "selbständig — jede Nachricht wird vorgelegt.")
                # Nur bei Exchange gefuellt. Ohne diese Adresse oeffnet
                # ein Funktionspostfach das Postfach dessen, der sich
                # gerade anmeldet -- deshalb weist lege_an() es ab.
                _v_adr = st.text_input(
                    "Mailadresse des Postfachs (nur Exchange)",
                    key=_feldschluessel(_pk, "adr"),
                    placeholder="info@firma.de",
                    help="Bei einem Funktionspostfach Pflicht. Bei einem "
                         "persönlichen Postfach leer lassen — dann gilt "
                         "die Adresse, mit der sich der Nutzer anmeldet. "
                         "Jeder meldet sich mit seinen eigenen Daten an; "
                         "Exchange entscheidet, wer hineindarf.")
                st.caption("Nur für Funktionspostfächer:")
                _v_auto = st.checkbox(
                    "darf selbständig antworten",
                    key=_feldschluessel(_pk, "auto"))
                _v_hin = st.checkbox(
                    "Hinweis unter automatische Antworten setzen",
                    value=True, key=_feldschluessel(_pk, "hin"))
                _v_htext = st.text_input(
                    "Text des Hinweises", key=_feldschluessel(_pk, "htext"),
                    placeholder=mcp.HINWEIS_VORGABE)
                _pf_ab = st.form_submit_button(
                    "Anlegen", use_container_width=True, disabled=_antwortet)
            if _pf_ab:
                _pers = _v_pers == "persönlich"
                _ok, _m = mcp.lege_an(
                    _v_name, _v_wahl, _v_ziel, persoenlich=_pers,
                    postfach=((_v_adr or "").strip() or None),
                    automatisch=bool(_v_auto),
                    hinweis_anhaengen=bool(_v_hin),
                    hinweis=(_v_htext or None))
                (st.success if _ok else st.error)(_m)
                if _ok:
                    _felder_leeren(_pk)
                    _leeren()
                    time.sleep(1)
                    st.rerun()

        with st.expander("🔐 Verschlüsselung"):
            st.caption(f"Zustand: **{geheim.beschreibung()}**")
            if not geheim.verfuegbar():
                st.error(
                    "Chats, Anhänge und Rückmeldungen liegen im Klartext. "
                    "Ohne das Paket `cryptography` im Image kann nicht "
                    "verschlüsselt werden — `requirements.txt` prüfen und "
                    "neu bauen.")
            else:
                st.caption(
                    "Verschlüsselt: Chatverläufe samt Titeln, angehängte "
                    "Bilder, das Rückmeldungsprotokoll. Signiert: "
                    "Benutzerdatei und Zugangstoken, je Eintrag einzeln.")
                st.caption(
                    "**Nicht** verschlüsselt: der Text der Dokumente in der "
                    "Vektordatenbank. Er muss durchsuchbar bleiben und liegt "
                    "neben dem Vektor. Dafür ist die Verschlüsselung des "
                    "Datenträgers zuständig.")

            _offen_chats = chats.zaehle_klartext(st.session_state["username"])
            if _offen_chats:
                st.warning(f"{_offen_chats} eigene Chatdateien noch im "
                           f"Klartext. Sie werden beim nächsten Öffnen "
                           f"übernommen.")

            _offen_fb = feedback.klartextzeilen()
            if _offen_fb:
                st.warning(f"Im Rückmeldungsprotokoll stehen {_offen_fb} "
                           f"Zeilen noch im Klartext.")
                if st.button("Protokoll neu verschlüsseln",
                             use_container_width=True):
                    ok, anzahl = feedback.neu_verschluesseln()
                    if ok:
                        st.success(f"{anzahl} Zeilen neu geschrieben.")
                    else:
                        st.error("Konnte nicht geschrieben werden.")
                    time.sleep(1)
                    st.rerun()

            # Die Grenze ausdruecklich nennen. Ein Verwalter, der glaubt,
            # die Verschluesselung schuetze auch gegen jemanden mit
            # Serverzugang, traegt eine falsche Auskunft weiter.
            st.caption(
                "Der Schlüssel gehört der Installation, nicht dem Nutzer: "
                "ein Passwortwechsel lässt die Chats lesbar, und wer "
                "Dateizugriff auf `config/` hat, kann entschlüsseln. Das "
                "schützt gegen eine abgeflossene Sicherung oder ein "
                "kopiertes Volume, nicht gegen Serverzugang.")

    # --- NOTZUGANG ---
    #
    # Sichtbar fuer Verwalter UND fuer Traeger der Rolle, aber mit
    # verschiedenen Knoepfen: der eine beantragt, der andere bestaetigt.
    # Offene Zugaenge sieht jeder von beiden -- eine Kontrolle, von der nur
    # der weiss, der sie hat, kontrolliert nichts.
    _kann_bestaetigen = benutzer.hat_rolle(
        st.session_state["username"], "notzugang")
    if is_admin() or _kann_bestaetigen:
        _antraege = notzugang.antraege()
        _offen = notzugang.offene()
        _marke = ""
        if _kann_bestaetigen and _antraege:
            _marke = f" — {len(_antraege)} zu bestätigen"
        elif _offen:
            _marke = f" — {len(_offen)} offen"
        with st.expander("🔓 Notzugang" + _marke):
            st.caption(
                "Ein persönlicher Raum ist auch für Verwalter zu. Ist "
                "sein Besitzer nicht mehr erreichbar, führt der Weg "
                "hinein über **zwei Personen**: ein Verwalter beantragt, "
                "ein Träger der Rolle *notzugang* bestätigt. Danach gilt "
                f"er {notzugang.STUNDEN} Stunden. Beide Namen stehen im "
                "Protokoll.")
            st.caption(f"Stand: {notzugang.beschreibung()}")

            # --- offene Zugaenge, fuer beide Seiten sichtbar ---
            if _offen:
                st.markdown("**Gerade offen**")
                for _z in _offen:
                    _rest = max(0, (_z["bis"] - int(time.time())) // 60)
                    st.warning(
                        f"`{_z['raum']}` — {_z['von']}, bestätigt von "
                        f"{_z['durch']}, noch {_rest // 60} h {_rest % 60} min"
                        + (f"\n\n„{_z['grund']}\"" if _z.get("grund") else ""))
                    if st.button("Jetzt schließen",
                                 key=f"nzs_{_z['raum']}_{_z['von']}",
                                 use_container_width=True):
                        _ok, _m = notzugang.schliesse(
                            _z["raum"], _z["von"],
                            durch=st.session_state["username"])
                        (st.success if _ok else st.error)(_m)
                        _leeren()
                        time.sleep(1)
                        st.rerun()

            # --- bestaetigen ---
            if _kann_bestaetigen:
                st.markdown("---")
                st.markdown("**Anträge**")
                if not _antraege:
                    st.caption("Keine offenen Anträge.")
                for _a in _antraege:
                    st.info(f"**{_a['von']}** möchte in `{_a['raum']}`"
                            + (f"\n\n„{_a['grund']}\"" if _a.get("grund")
                               else ""))
                    _s1, _s2 = st.columns(2)
                    with _s1:
                        if st.button("Bestätigen",
                                     key=f"nzb_{_a['raum']}_{_a['von']}",
                                     use_container_width=True):
                            _ok, _m = notzugang.bestaetige(
                                _a["raum"], _a["von"],
                                st.session_state["username"])
                            (st.success if _ok else st.error)(_m)
                            _leeren()
                            time.sleep(1)
                            st.rerun()
                    with _s2:
                        if st.button("Ablehnen",
                                     key=f"nza_{_a['raum']}_{_a['von']}",
                                     use_container_width=True):
                            _ok, _m = notzugang.lehne_ab(
                                _a["raum"], _a["von"],
                                st.session_state["username"])
                            (st.info if _ok else st.error)(_m)
                            _leeren()
                            time.sleep(1)
                            st.rerun()

            # --- beantragen ---
            if is_admin():
                st.markdown("---")
                st.markdown("**Zugang beantragen**")
                if not notzugang.moeglich():
                    st.error(
                        "Niemand trägt die Rolle *notzugang*. Ohne eine "
                        "zweite Person lässt sich kein Notzugang "
                        "bestätigen — das ist der Sinn der Sache. Vergib "
                        "die Rolle unter *Benutzer verwalten*, und zwar "
                        "an jemanden, der KEIN Verwalter ist.")
                else:
                    _fremde_privat = sorted(
                        k for k in raeume.liste() if raeume.ist_privat(k)
                        and k != raeume.privat_kennung(
                            st.session_state["username"]))
                    if not _fremde_privat:
                        st.caption("Es gibt keine fremden persönlichen "
                                   "Räume.")
                    else:
                        _ziel = st.selectbox("Raum", _fremde_privat,
                                             key="nz_ziel")
                        _grund = st.text_area(
                            "Grund", key="nz_grund",
                            help="Steht im Protokoll und ist das, was die "
                                 "zweite Person beurteilt.")
                        if st.button("Notzugang beantragen",
                                     use_container_width=True):
                            _ok, _m = notzugang.beantrage(
                                _ziel, st.session_state["username"], _grund)
                            (st.success if _ok else st.error)(_m)
                            if _ok:
                                _leeren()
                                time.sleep(1)
                                st.rerun()

            st.caption(
                "**Die ehrliche Grenze:** das ist eine Kontrolle in der "
                "Anwendung. Wer Serverzugang hat, liest die Sammlung eines "
                "persönlichen Raums, ohne diese Freigabe zu beachten — die "
                "Abschnitte liegen dort im Klartext, weil sie durchsuchbar "
                "sein müssen. Der Notzugang schützt gegen den Verwalter, "
                "der im Alltag klickt, nicht gegen den, der sich einloggt.")

    # --- RAEUME VERWALTEN ---
    #
    # Ein Raum ist eine Sammlung und eine Mitgliederliste. Die Sammlung
    # entsteht beim ersten Upload, nicht hier: ein Raum ohne Inhalt braucht
    # keine Sammlung, und eine leere anzulegen wuerde jede Suche mit einer
    # weiteren Abfrage belasten.
    if _vw:
        with st.expander("🚪 Räume verwalten"):
            _alle = raeume.liste()
            _bekannt = benutzer.namen()
            _mit_daten = {r: sml.count()
                          for r, sml in _alle_raum_sammlungen()}

            for _k, _e in sorted(_alle.items()):
                _m = _e.get("mitglieder") or []
                _wer = "alle" if "*" in _m else f"{len(_m)} Mitglieder"
                if _e.get("gruppe"):
                    _wer += f" + Gruppe {_e['gruppe']}"
                st.caption(f"**{_e.get('bezeichnung') or _k}** · "
                           f"{_wer} · "
                           f"{_mit_daten.get(_k, 0):,} Abschnitte "
                           f"· `{_k}`")

            st.markdown("---")
            _bearbeiten = st.selectbox(
                "Bearbeiten", ["(neu anlegen)"] + sorted(_alle),
                format_func=lambda n: (
                    n if n == "(neu anlegen)"
                    else (_alle.get(n, {}).get("bezeichnung") or n)),
                key="raum_bearbeiten")

            if _bearbeiten == "(neu anlegen)":
                _name = st.text_input(
                    "Bezeichnung", key=_feldschluessel("raum_neu", "name"))
                _besch = st.text_input(
                    "Beschreibung (optional)",
                    key=_feldschluessel("raum_neu", "besch"))
                _mitglieder = st.multiselect(
                    "Mitglieder", _bekannt,
                    key=_feldschluessel("raum_neu", "mit"),
                    help="Nur diese Nutzer sehen die Dokumente des Raums.")
                if st.button("Raum anlegen", use_container_width=True,
                             disabled=not _name.strip()):
                    ok, meldung = raeume.anlegen(_name, _name, _besch,
                                                 _mitglieder)
                    if ok:
                        st.success(f"Raum '{_name}' angelegt.")
                        with st.spinner("Richte die Ablage ein ..."):
                            _b = owncloud.richte_raum_ein(meldung)
                        _oc_bericht(_b, "Der Raum")
                        refresh_document_index()
                        _felder_leeren("raum_neu", "name", "besch", "mit")
                        time.sleep(2 if _b.get("fehler") else 1)
                        st.rerun()
                    else:
                        st.error(meldung)
            else:
                _e = _alle.get(_bearbeiten, {})
                _m = _e.get("mitglieder") or []
                if "*" in _m:
                    st.caption("Dieser Raum ist für alle sichtbar. Eine "
                               "Mitgliederliste gilt hier nicht.")
                _name = st.text_input("Bezeichnung",
                                      value=_e.get("bezeichnung") or "",
                                      key=f"raum_b_{_bearbeiten}")
                _besch = st.text_input("Beschreibung",
                                       value=_e.get("beschreibung") or "",
                                       key=f"raum_d_{_bearbeiten}")
                # Ein persoenlicher Raum gehoert genau einem Nutzer.
                # Mitglieder hinzuzufuegen waere eine Hintertuer, und im
                # strengen Betrieb widerspricht sie dem Zweck.
                _ist_privat = raeume.ist_privat(_bearbeiten)
                if _ist_privat:
                    st.caption(
                        "Persönlicher Raum – nur sein Eigentümer sieht "
                        "ihn. Eine Mitgliederliste gibt es hier nicht."
                        + (" Löschbar als Ganzes unter *fremde "
                           "persönliche Räume*." if raeume.PRIVAT_STRENG
                           else ""))
                    _neu_m = [x for x in _m if x != "*"]
                else:
                    _neu_m = st.multiselect(
                        "Mitglieder",
                        sorted(set(_bekannt) | {x for x in _m if x != "*"}),
                        default=[x for x in _m if x != "*"],
                        key=f"raum_m_{_bearbeiten}",
                        disabled=("*" in _m))
                    # "Fuer alle sichtbar" ist eine Vorgabe, keine
                    # Notwendigkeit. Wo der Grundsatz "nur was man wissen
                    # muss" gilt, bekommt auch der allgemeine Raum eine
                    # Liste.
                    if "*" in _m:
                        if st.button("Auf eine Mitgliederliste umstellen",
                                     use_container_width=True,
                                     key=f"raum_zu_{_bearbeiten}",
                                     help="Danach sehen nur noch die "
                                          "eingetragenen Nutzer diesen "
                                          "Raum."):
                            raeume.mitglieder_setzen(
                                _bearbeiten,
                                [st.session_state["username"]])
                            st.success("Umgestellt. Jetzt Mitglieder "
                                       "eintragen.")
                            time.sleep(1)
                            st.rerun()
                    elif st.button("Wieder für alle öffnen",
                                   use_container_width=True,
                                   key=f"raum_auf_{_bearbeiten}"):
                        raeume.fuer_alle_oeffnen(_bearbeiten)
                        st.success("Für alle sichtbar.")
                        time.sleep(1)
                        st.rerun()
                # --- MITGLIEDSCHAFT AUS OWNCLOUD ---
                #
                # Vereinigung, nicht Ersetzung: ein Verwalter, den die
                # Firma nicht in der Abteilungsgruppe fuehrt, soll sich
                # nicht selbst aussperren, indem er eine Gruppe eintraegt.
                _gruppe_alt = str(_e.get("gruppe") or "")
                _gruppe = st.text_input(
                    "ownCloud-Gruppe (optional)", value=_gruppe_alt,
                    key=f"raum_g_{_bearbeiten}",
                    help="Ihre Mitglieder kommen zu den oben "
                         "eingetragenen hinzu. Leer lassen, um die "
                         "Mitgliedschaft nur hier zu pflegen.")
                if _gruppe.strip():
                    _von_hand, _aus_gruppe = raeume.mitglieder_gesamt(
                        _bearbeiten)
                    _gueltig, _alter, _grund = raeume.stand_gueltig()
                    if not _gueltig:
                        st.warning(
                            f"Der Gruppenstand gilt nicht ({_grund}) -- "
                            f"die Mitglieder dieser Gruppe kommen gerade "
                            f"NICHT herein. Der Abgleich laeuft unter "
                            f"*Nachtragen und neu einlesen*.")
                    else:
                        st.caption(
                            "Aus der Gruppe: "
                            + (", ".join(_aus_gruppe) if _aus_gruppe
                               else "niemand")
                            + (f" -- Stand {_alter:.0f} min alt"
                               if _alter is not None else ""))
                        _unbekannt = [x for x in _aus_gruppe
                                      if x not in _bekannt]
                        if _unbekannt:
                            # Der Fall, in dem alles richtig aussieht und
                            # trotzdem niemand hereinkommt.
                            st.warning(
                                f"Nicht als Benutzer angelegt und damit "
                                f"wirkungslos: {', '.join(_unbekannt)}")

                # --- LISTENORDNER ---
                #
                # Hier und nicht in den allgemeinen Einstellungen: wer
                # einen Raum einrichtet, weiss in diesem Moment, wo
                # dessen Listen liegen. Muss er es sich fuer spaeter
                # merken, bleibt das Feld leer -- und die Listensuche
                # fuer diesen Raum entsteht nie.
                _lq_alt = listenquellen.pfad_von(_bearbeiten)
                _lq = st.text_input(
                    "Listenordner (xlsx, csv)", value=_lq_alt,
                    key=f"raum_lq_{_bearbeiten}",
                    help="Vollstaendiger Pfad, wie er im Container gilt "
                         "-- etwa /mnt/abteilungen/einkauf/listen. Die "
                         "Dateien bleiben, wo sie sind; niemand muss sie "
                         "ein zweites Mal ablegen. Leer = keine Listen "
                         "fuer diesen Raum.")
                if listenquellen.WURZELN:
                    st.caption("Erlaubt unterhalb von: "
                               + ", ".join(f"`{w}`"
                                           for w in listenquellen.WURZELN))

                # --- DATENBANKZUGANG ---
                #
                # Ein Konto je Raum, mit den Rechten dieses Raums. Damit
                # kommt auch das Schema mit diesen Rechten, und das
                # Sprachmodell sieht nur Tabellen, die es lesen darf.
                _sqz = sqlquellen.zugang(_bearbeiten) or {}
                with st.expander("Datenbankzugang dieses Raums",
                                 expanded=False):
                    st.caption(
                        "Ein Konto mit genau den Rechten, die dieser "
                        "Raum haben soll -- idealerweise nur lesend. "
                        "Leer = der Raum benutzt den Zugang aus der "
                        "Umgebung.")
                    _sq_b = st.text_input("Benutzer",
                                          value=_sqz.get("benutzer", ""),
                                          key=f"sqb_{_bearbeiten}")
                    _sq_p = st.text_input(
                        "Passwort", value=_sqz.get("passwort", ""),
                        type="password", key=f"sqp_{_bearbeiten}")
                    _sq_d = st.text_input(
                        "Datenbank (leer = Vorgabe)",
                        value=_sqz.get("datenbank", ""),
                        key=f"sqd_{_bearbeiten}")
                    st.caption(
                        "Das Passwort wird mit dem Schluessel dieses "
                        "Raums verschluesselt abgelegt. Ohne "
                        "Installationsschluessel wird es gar nicht "
                        "gespeichert.")

                if st.button("Speichern", use_container_width=True,
                             key=f"raum_s_{_bearbeiten}"):
                    if (_sq_b != _sqz.get("benutzer", "")
                            or _sq_p != _sqz.get("passwort", "")
                            or _sq_d != _sqz.get("datenbank", "")):
                        _ok_sq, _m_sq = sqlquellen.setze(
                            _bearbeiten,
                            {"benutzer": _sq_b, "passwort": _sq_p,
                             "datenbank": _sq_d},
                            benutzer=st.session_state.get("username", "?"),
                            ist_verwalter=True)
                        (st.success if _ok_sq else st.error)(_m_sq)
                    if _lq.strip() != _lq_alt:
                        _ok_lq, _m_lq = listenquellen.setze_raum(
                            _bearbeiten, _lq,
                            benutzer=st.session_state.get("username", "?"),
                            ist_verwalter=True)
                        if not _ok_lq:
                            st.error(_m_lq)
                        else:
                            with st.spinner("Lese die Listen ein ..."):
                                _k, _f = tabellen.baue_katalog()
                            st.caption(f"{len(_k['eintraege'])} Blaetter "
                                       f"im Katalog.")
                    raeume.beschriften(_bearbeiten, _name, _besch)
                    if "*" not in _m and not _ist_privat:
                        raeume.mitglieder_setzen(_bearbeiten, _neu_m)
                    if _gruppe.strip() != _gruppe_alt:
                        raeume.gruppe_setzen(_bearbeiten, _gruppe)
                    st.success("Gespeichert.")
                    # Die Freigabe zieht mit -- SETZEN, nicht ergaenzen.
                    # Ein Mitglied zu entfernen und die Freigabe stehen zu
                    # lassen waere die haeufigste Art, eine
                    # Rechteaenderung wirkungslos zu machen: die Suche
                    # fragt den Raum nicht mehr, die Dateien liegen aber
                    # weiter im ownCloud des Ausgeschiedenen.
                    with st.spinner("Ziehe die Freigaben nach ..."):
                        _b = owncloud.richte_raum_ein(_bearbeiten)
                    _oc_bericht(_b, "Der Raum")
                    refresh_document_index()
                    time.sleep(2 if _b.get("fehler") else 1)
                    st.rerun()

                # Entfernen und Loeschen sind zwei Dinge. Das erste nimmt
                # den Raum aus der Verwaltung und laesst die Daten liegen,
                # das zweite loescht sie. Ein Knopf fuer beides waere ein
                # Knopf, den man einmal zu oft drueckt.
                if _bearbeiten != raeume.ALLGEMEIN:
                    st.markdown("---")
                    _sp1, _sp2 = st.columns(2)
                    with _sp1:
                        if st.button("Raum entfernen",
                                     use_container_width=True,
                                     key=f"raum_e_{_bearbeiten}",
                                     help="Nimmt den Raum aus der "
                                          "Verwaltung. Die Dokumente "
                                          "bleiben erhalten."):
                            ok, meldung = raeume.entfernen(_bearbeiten)
                            (st.success if ok else st.error)(meldung)
                            refresh_document_index()
                            time.sleep(1)
                            st.rerun()
                    with _sp2:
                        _zahl = _mit_daten.get(_bearbeiten, 0)
                        # Derselbe Mechanismus wie im strengen
                        # Betrieb. Hier haengt der Haken zwar am Raum
                        # und bleibt beim Wechsel nicht stehen -- aber
                        # zwei verschiedene Freigaben fuer denselben
                        # Vorgang sind eine zu viel: die schwaechere
                        # wird zur Gewohnheit, und die Gewohnheit
                        # traegt man zur staerkeren hinueber.
                        _sicher = _loeschfreigabe(
                            _bearbeiten, _zahl, f"raum_x_{_bearbeiten}")
                        if st.button("Daten löschen",
                                     use_container_width=True,
                                     disabled=not _sicher,
                                     key=f"raum_l_{_bearbeiten}"):
                            ok, meldung = store.loesche(
                                raeume.sammlung(_bearbeiten))
                            keyword_index.delete_document_by_raum(_bearbeiten)
                            (st.success if ok else st.error)(meldung)
                            refresh_document_index()
                            time.sleep(1)
                            st.rerun()

            # --- ALTBESTAND ---
            #
            # Eine Installation von vor den Raeumen hat ihre Abschnitte noch
            # in der gemeinsamen Sammlung. Der Hinweis steht hier, damit man
            # es sieht, ohne ins Protokoll zu schauen.
            try:
                _alt_zahl = store.collection(anlegen=False).count()
            except Exception:
                _alt_zahl = 0
            if _alt_zahl:
                st.markdown("---")
                st.warning(
                    f"In der alten, gemeinsamen Sammlung liegen noch "
                    f"{_alt_zahl:,} Abschnitte. Sie werden nicht mehr "
                    f"durchsucht — die Suche fragt nur Raumsammlungen. "
                    f"Die Dokumente in den gewünschten Raum legen und neu "
                    f"einlesen; die alte Sammlung lässt sich danach unter "
                    f"*Räume verwalten* leeren.")

    # --- OWNCLOUD ---
    #
    # Ein Ordner in ownCloud wird auf einen Raum abgebildet. Damit liegen
    # die Dokumente dort, wo sie gepflegt werden, und die Rechte auf dem
    # Ordner sind die von ownCloud -- die Mitgliedschaft des Raums
    # entscheidet dann, wer die daraus gebauten Abschnitte sieht.
    if _vw:
        st.caption("**Betrieb**")
    if _vw:
        with st.expander("☁️ ownCloud"):
            _ok, _meldung = _owncloud_stand()
            (st.success if _ok else st.warning)(_meldung)

            if not owncloud.eingerichtet():
                st.caption(
                    "Einzurichten in der `.env`: `OWNCLOUD_URL` (die Wurzel, "
                    "etwa `https://cloud.firma.de`), `OWNCLOUD_USER` und "
                    "`OWNCLOUD_PASSWORT`. Bei aktiver Zwei-Faktor-Anmeldung "
                    "braucht es ein **App-Passwort**, nicht das "
                    "Anmeldepasswort. Für das reine Holen von Dateien "
                    "genügt Lesezugriff. Damit LocaNoto die Ablage selbst "
                    "einrichtet — Konten anlegen, Ordner erzeugen, "
                    "freigeben —, braucht `OWNCLOUD_ADMIN_USER` in "
                    "ownCloud **Verwalterrechte**. Das ist viel Macht in "
                    "einem Dienstkonto; wer sie nicht geben will, richtet "
                    "Konten und Ordner dort von Hand ein und trägt hier "
                    "nur die Zuordnung ein.")
            else:
                _zu = owncloud.zuordnung()
                _wirksam = owncloud.zuordnung_wirksam()
                for _r, _o in sorted(_wirksam.items()):
                    _b = owncloud.letzter_bericht(_r)
                    _stand = (f"{_b['dateien']} Dateien, zuletzt "
                              f"{(_b['zuletzt'] or '?')[:16]}"
                              if _b else "noch nicht abgeglichen")
                    st.caption(f"**{raeume.bezeichnung(_r)}** "
                               f"· `{_o}`"
                               + ("" if _r in _zu else " *(Standard)*")
                               + f" · {_stand}")
                st.caption(
                    "Ohne eigenen Eintrag gilt der Standardbaum unter "
                    f"`/{owncloud.WURZEL}/`. Eine Zuordnung von Hand "
                    "geht vor — für Bestände, die seit Jahren woanders "
                    "liegen.")

                st.markdown("---")
                _raum_wahl = st.selectbox(
                    "Raum", sorted(raeume.liste()),
                    format_func=raeume.bezeichnung, key="oc_raum")
                _ordner = st.text_input(
                    "Ordner in ownCloud", value=_zu.get(_raum_wahl, ""),
                    placeholder="/Abteilungen/Einkauf/Handbücher",
                    key=f"oc_ordner_{_raum_wahl}",
                    help="Pfad relativ zum Wurzelverzeichnis des "
                         "angemeldeten Kontos. Unterordner werden zu "
                         "Sachgebieten.")
                _sp1, _sp2 = st.columns(2)
                with _sp1:
                    if st.button("Zuordnung speichern",
                                 use_container_width=True,
                                 disabled=not _ordner.strip()):
                        _zu[_raum_wahl] = _ordner.strip()
                        owncloud.setze_zuordnung(_zu)
                        st.success("Gespeichert.")
                        time.sleep(1)
                        st.rerun()
                with _sp2:
                    if st.button("Zuordnung entfernen",
                                 use_container_width=True,
                                 disabled=_raum_wahl not in _zu,
                                 help="Der Raum wird nicht mehr "
                                      "abgeglichen. Bereits geholte "
                                      "Dateien und ihre Abschnitte "
                                      "bleiben."):
                        _zu.pop(_raum_wahl, None)
                        owncloud.setze_zuordnung(_zu)
                        st.success("Entfernt.")
                        time.sleep(1)
                        st.rerun()

            # --- ABLAGE EINRICHTEN ---
            #
            # Nachholen, was beim Anlegen nicht ging -- weil ownCloud
            # gerade nicht erreichbar war, oder weil die Installation
            # aelter ist als diese Anbindung. Der Ablauf ist wiederholbar:
            # vorhandene Ordner bleiben, Freigaben werden auf den Soll-
            # Stand gebracht, nicht ergaenzt.
            if owncloud.eingerichtet():
                st.markdown("---")
                st.markdown("**Ablage einrichten**")
                st.caption(
                    f"Legt unter `/{owncloud.WURZEL}/` je Raum einen Ordner "
                    f"an und teilt ihn mit seinen Mitgliedern — den "
                    f"gemeinsamen mit allen (nur lesend, schreiben dürfen "
                    f"Verwalter), einen persönlichen nur mit seinem "
                    f"Besitzer. Wiederholbar: was schon steht, bleibt.")
                if st.button("Für alle Räume einrichten",
                             use_container_width=True):
                    _gut, _schlecht = 0, []
                    with st.spinner("Richte ein ..."):
                        for _r in sorted(raeume.liste()):
                            _b = owncloud.richte_raum_ein(_r)
                            if _b.get("fehler"):
                                _schlecht.append(
                                    f"{_r}: {_b['fehler'][0]}")
                            else:
                                _gut += 1
                    st.success(f"{_gut} Räume eingerichtet.")
                    for _f in _schlecht[:10]:
                        st.warning(_f)
                    _leeren()

                _wer = st.selectbox(
                    "Einzelnen Zugang nachziehen",
                    ["-"] + benutzer.namen(), key="oc_nutzer")
                if _wer != "-" and st.button(
                        "Persönliche Ablage einrichten",
                        use_container_width=True):
                    with st.spinner("Richte ein ..."):
                        # Ohne Passwort: das Konto gibt es entweder schon,
                        # oder es wird beim Anlegen erzeugt. Hier ein
                        # Passwort zu erfinden waere ein zweites Geheimnis
                        # fuer denselben Menschen.
                        _b = owncloud.richte_nutzer_ein(_wer)
                    _oc_bericht(_b, "Der Zugang")
                    if not _b.get("fehler"):
                        st.success(f"Ablage für '{_wer}' steht.")

                # --- PRUEFEN ---
                #
                # Vor dem ersten Abgleich, und zwar nicht aus Vorsicht,
                # sondern weil eine falsch eingerichtete Zuordnung genau
                # wie "alles geloescht" aussieht: der Ordner ist leer,
                # also gilt jede bekannte Datei als entfallen. Danach sind
                # die Abschnitte weg.
                if _raum_wahl in _zu:
                    st.markdown("---")
                    if st.button("Änderungen prüfen",
                                 use_container_width=True,
                                 key=f"oc_pruef_{_raum_wahl}"):
                        try:
                            with st.spinner("Frage ownCloud ab ..."):
                                _neu, _geae, _entf, _unv = owncloud.plane(
                                    _raum_wahl)
                            st.caption(f"unverändert: {len(_unv)}")
                            for _titel, _liste in (("neu", _neu),
                                                   ("geändert", _geae),
                                                   ("entfallen", _entf)):
                                if _liste:
                                    st.caption(f"**{_titel}: "
                                               f"{len(_liste)}**")
                                    st.code(chr(10).join(_liste[:30]),
                                            language="text")
                            if not (_neu or _geae or _entf):
                                st.info("Nichts zu tun.")
                        except Exception as e:
                            st.error(f"Abfrage fehlgeschlagen: {e}")

                # --- MITGLIEDSCHAFTEN ---
                st.markdown("---")
                _gz = owncloud.gruppen_zuordnung()
                _gueltig, _alter, _grund = raeume.stand_gueltig()
                if _gz:
                    for _r, _g in sorted(_gz.items()):
                        _vh, _ag = raeume.mitglieder_gesamt(_r)
                        st.caption(f"**{raeume.bezeichnung(_r)}** "
                                   f"· Gruppe `{_g}` · "
                                   f"{len(_ag)} aus der Gruppe, "
                                   f"{len(_vh)} von Hand")
                    if _gueltig:
                        st.caption("Gruppenstand: "
                                   + (f"{_alter:.0f} Minuten alt"
                                      if _alter is not None
                                      else "unbekannt"))
                    else:
                        st.warning(f"Gruppenstand gilt nicht: {_grund}. "
                                   f"Bis zum nächsten Abgleich wirken "
                                   f"nur die von Hand eingetragenen "
                                   f"Mitglieder.")
                    if st.button("Mitgliedschaften jetzt nachziehen",
                                 use_container_width=True):
                        with st.spinner("Frage ownCloud ab ..."):
                            _b = owncloud.gruppen_abgleich()
                        (st.success if _b["geschrieben"]
                         else st.warning)(_b["meldung"])
                        for _f in _b["fehler"]:
                            st.error(f"Gruppe '{_f['gruppe']}': "
                                     f"{_f['grund']}")
                        time.sleep(1)
                        st.rerun()
                else:
                    st.caption(
                        "Noch keine Raumgruppe eingetragen. Sie gehört "
                        "in den Raum selbst — unter *Räume "
                        "verwalten*, Feld ownCloud-Gruppe. Die "
                        "Gruppenabfrage braucht in ownCloud ein Konto mit "
                        "Verwalterrechten (`OWNCLOUD_ADMIN_USER`); "
                        "für die Dateien genügt Lesen.")

                st.caption(
                    "Der eigentliche Abgleich läuft abgekoppelt — unter "
                    "*Nachtragen und neu einlesen*, Eintrag „Aus ownCloud "
                    "abgleichen“. Er holt neue und geänderte Dateien, "
                    "entfernt die Abschnitte entfallener und liest "
                    "anschließend ein. Für den Dauerbetrieb gehört das in "
                    "einen Zeitplan auf dem Server: "
                    "`docker compose exec -T locanoto_bot python "
                    "abgleich.py`")

    # --- SICHERUNG DER VEKTORDATENBANK ---
    #
    # Der einzige Zustand, der nicht ableitbar ist und trotzdem nicht auf
    # den Netzspeicher gehoert: SQLite plus binaere Indexdateien. Deshalb
    # der laufende Bestand auf lokalem oder Blockspeicher und ein Abzug
    # davon auf dem persistenten Speicher.
    #
    # Gelesen wird ueber die Schnittstelle, nicht als Dateikopie: eine
    # Kopie mitten in einem Schreibvorgang ist ein Abzug, der sich nicht
    # zurueckholen laesst -- und das zeigt sich erst beim Zurueckholen.
    if _vw:
        with st.expander("🗃️ Sicherung der Vektordatenbank"):
            _abzuege = _verwaltungsstand()["abzuege"]
            st.caption(f"Ablage: `{sicherung.ORDNER}`"
                       + (f" · es werden "
                          f"{sicherung.BEHALTEN} Abzüge behalten"
                          if sicherung.BEHALTEN else
                          " · alle Abzüge werden behalten"))

            if not _abzuege:
                st.warning(
                    "Noch kein Abzug. Ohne einen wäre der Verlust der "
                    "Vektordatenbank ein vollständiges Neueinlesen — "
                    "Stunden Modellzeit für ein Ergebnis, das schon "
                    "vorlag.")
            else:
                st.code(chr(10).join(
                    f"{_n:<22} {_gr / 1e6:9.1f} MB  "
                    f"{_st.get('abschnitte', '?'):>8} Abschnitte  "
                    f"{len(_st.get('raeume') or {})} Räume"
                    + ("   UNVOLLSTÄNDIG" if _unvollstaendig(_st) else "")
                    for _n, _p, _gr, _st in _abzuege), language="text")
                if any(_unvollstaendig(_st) for _n, _p, _gr, _st in _abzuege):
                    st.warning(
                        "Bei einem Abzug ließen sich nicht alle Räume "
                        "lesen. Er ist von außen nicht von einem "
                        "vollständigen zu unterscheiden — deshalb steht es "
                        "hier. Ein neuer Abzug behebt es; der letzte "
                        "vollständige wird nicht weggeräumt.")

            _laeuft = hintergrund.laeuft("sicherung")
            if _laeuft:
                st.caption("Ein Abzug läuft gerade.")
                st.code(hintergrund.protokoll("sicherung", 6) or "...",
                        language="text")
            elif st.button("Jetzt sichern", use_container_width=True,
                           help="Läuft abgekoppelt weiter, auch wenn die "
                                "Oberfläche neu lädt."):
                _ok, _meldung = hintergrund.starte("sicherung")
                (st.success if _ok else st.error)(_meldung)
                time.sleep(1)
                st.rerun()

            # --- ZURUECKHOLEN ---
            #
            # Bewusst mit Haken und in einem eigenen Schritt: ein Abzug
            # ueberschreibt vorhandene Abschnitte. Wer ihn einspielt, weil
            # er die Liste sehen wollte, verliert Arbeit.
            if _abzuege:
                st.markdown("---")
                _wahl = st.selectbox(
                    "Abzug einspielen", [_n for _n, _p, _g, _s in _abzuege],
                    key="sich_wahl")
                _st = dict(_abzuege[[_n for _n, _p, _g, _s
                                     in _abzuege].index(_wahl)][3])
                st.caption(
                    f"{_st.get('abschnitte', '?')} Abschnitte in "
                    + ", ".join(sorted((_st.get('raeume') or {}))))
                if _unvollstaendig(_st):
                    _fehlten = ", ".join(
                        _f.get("raum", "?") for _f in (_st.get("fehler") or [])
                    ) or "unbekannt"
                    st.error(
                        f"Dieser Abzug ist unvollständig — beim Sichern "
                        f"ließen sich diese Räume nicht lesen: {_fehlten}. "
                        f"Eingespielt wird nur, was er hat. Gibt es einen "
                        f"neueren vollständigen, nimm den.")
                _sicher = st.checkbox(
                    "Vorhandene Abschnitte dürfen überschrieben werden",
                    key="sich_ok")
                if st.button("Einspielen", use_container_width=True,
                             disabled=not _sicher):
                    with st.spinner("Spiele ein — das dauert länger als "
                                    "das Sichern, weil der Suchindex neu "
                                    "gebaut wird ..."):
                        _b = sicherung.hole_zurueck(_wahl)
                    for _r, _n2 in sorted(_b["raeume"].items()):
                        st.caption(f"{_r}: {_n2} Abschnitte")
                    for _f in _b["fehler"]:
                        st.error(str(_f))
                    if not _b["fehler"]:
                        st.success("Eingespielt. Der Stichwortindex baut "
                                   "sich beim nächsten Start neu auf.")
                    refresh_document_index()

            st.caption(
                "Der Abzug enthält Abschnitte, Metadaten **und die "
                "Vektoren** — ein Einspielen braucht kein Modell und "
                "keinen Endpunkt. Gemessen: 20.500 Abschnitte in 2,6 s "
                "(112 MB), Einspielen 29 s. Hochgerechnet auf 324.000 "
                "Abschnitte: rund 40 s und 1,8 GB, Einspielen etwa acht "
                "Minuten. Der Schlüssel geht **nicht** mit in den Abzug — "
                "er gehört in eine andere Aufbewahrung als die Daten, die "
                "er lesbar macht.")

    # --- SICHERHEITSLAGE ---
    #
    # Verschluesselung, die man nicht nachsehen kann, ist eine
    # Behauptung. Hier steht, was tatsaechlich gilt -- einschliesslich
    # dessen, was sie NICHT leistet. Ein offener Punkt heisst nicht
    # "kaputt", sondern "hier ist die Zusage schwaecher, als sie
    # aussieht".
    if _vw:
        st.caption("**Lage**")
    if _vw:
        _lage = sicherheit.lage()
        _offen = [n for n, _ok, _t in _lage if not _ok]
        with st.expander(f"\U0001f512 Sicherheitslage "
                         f"({len(_lage) - len(_offen)}/{len(_lage)})"):
            for _name, _ok, _text in _lage:
                st.markdown(("✅ " if _ok else "⚠️ ") + f"**{_name}**")
                st.caption(_text)
            st.caption(
                "Die letzten drei Punkte lassen sich nicht schließen, "
                "sondern nur eingrenzen: Vektoren müssen vergleichbar "
                "bleiben, und wer den laufenden Prozess hat, hat den "
                "Klartext. Dagegen hilft ein verschlüsselter Datenträger "
                "und wenige Menschen mit Serverzugang.")

    # --- SPEICHERORTE ---
    #
    # Wo welcher Zustand liegt, auf einem Bildschirm. Bei einer Frage nach
    # der Datenhaltung ist "schau in die docker-compose.yaml und in fuenf
    # Module" keine Antwort.
    if _vw:
        with st.expander("💾 Speicherorte"):
            for _name, _pfad, _gesetzt in paths.wurzeln():
                st.caption(f"**{_name}** · `{_pfad}` · "
                           + ("von außen gesetzt" if _gesetzt
                              else "Standard neben dem Code"))

            st.markdown("---")
            # BEI EINGERICHTETEM OWNCLOUD IST DAS KEINE QUELLE.
            #
            # Gemeldet als "es laeuft immer noch alles im alten
            # Ablagesystem". Es laeuft nichts Altes: der Abgleich HOLT
            # die Dateien aus ownCloud hierher, und der Ingest liest
            # ausschliesslich von der Platte. Dateien hier sind das Bild
            # eines funktionierenden Abgleichs, nicht sein Gegenteil.
            #
            # "Werden gepflegt" stimmte dann aber nicht mehr: gepflegt
            # wird in ownCloud, hier steht die Kopie.
            _mit_cloud = owncloud.eingerichtet()
            _klassen = {
                "quelle": ("Quellen — Arbeitskopie; gepflegt wird in "
                           "ownCloud" if _mit_cloud else
                           "Quellen — werden gepflegt, nur gelesen"),
                "nutzerdaten": "Nutzerdaten — müssen den Container "
                               "überleben",
                "konfiguration": "Konfiguration — getrennt aufzubewahren",
                "index": "Ableitbar — gehört auf die lokale Platte",
            }
            _bestand = _verwaltungsstand()["bestand"]
            for _klasse, _beschriftung in _klassen.items():
                st.caption(f"**{_beschriftung}**")
                _zeilen = [z for z in _bestand if z[1] == _klasse]
                st.code(chr(10).join(
                    f"{_b:<26} {_gr / 1e6:9.2f} MB {_n:>6} Dateien  {_p}"
                    for _b, _k, _p, _gr, _n in _zeilen), language="text")

            if _mit_cloud:
                st.caption(
                    "Der Abgleich legt unter `dokumente` ab, was in "
                    "ownCloud steht — der Ingest liest nur von der "
                    "Platte, nie über das Netz. Dateien hier sind also "
                    "kein alter Ablageweg, sondern die Arbeitskopie. "
                    "Was von Hand hierher gelegt wird, bleibt liegen und "
                    "wird eingelesen, taucht in ownCloud aber nie auf — "
                    "und ist damit für alle anderen unsichtbar.")

            _modus = _verwaltungsstand()["journal"]
            if _modus.lower() != "wal":
                # Der stille Rueckfall. PRAGMA journal_mode=WAL schlaegt
                # nicht fehl, wenn das Dateisystem es nicht kann -- SQLite
                # bleibt beim alten Modus und sagt nichts. Genau das
                # passiert auf einem Netzlaufwerk.
                st.error(
                    f"Der Stichwortindex läuft im Journalmodus `{_modus}` "
                    f"statt `wal`. Das heißt fast immer: er liegt auf "
                    f"einem Netzlaufwerk, wo SQLite den WAL-Betrieb nicht "
                    f"aufsetzen kann. Setze `LOCANOTO_INDEX` auf ein "
                    f"containerlokales Verzeichnis — der Index baut sich "
                    f"dort in Sekunden neu auf.")
            else:
                st.caption(f"Stichwortindex: Journalmodus `{_modus}`.")

            st.caption(
                "Ableitbares gehört nicht auf den Netzspeicher: "
                "Vektordatenbank und Stichwortindex sind SQLite-Dateien, "
                "und der WAL-Betrieb braucht gemeinsamen Speicher im "
                "selben Dateisystem — über NFS oder SMB gibt es den nicht, "
                "und die Dateisperren sind unzuverlässig. Der Verlust "
                "kostet nichts: der Stichwortindex baut sich mit rund "
                "18.600 Abschnitten je Sekunde neu auf.")

    if _vw:
        st.caption("**Inhalte**")
    if _vw:
        with st.expander("\U0001f5e3\ufe0f Glossar bearbeiten"):
            pfad = paths.resolve_glossar()
            try:
                with open(pfad, "r", encoding="utf-8") as f:
                    inhalt = f.read()
            except OSError:
                # Noch nicht angelegt: mit der Vorlage beginnen, damit die
                # Hinweise zur Pflege gleich dabeistehen.
                vorlage = os.path.join(paths.BASE_DIR, "glossar.example.txt")
                try:
                    with open(vorlage, "r", encoding="utf-8") as f:
                        inhalt = f.read()
                except OSError:
                    inhalt = ""

            neu = st.text_area(
                "Je Zeile eine Zuordnung. Zeilen mit # sind Erlaeuterungen "
                "und kommen nicht in den Prompt.",
                value=inhalt, height=320, key="glossar_text")

            wirksam = pipeline.glossar()
            st.caption(f"Wirksam: {len(wirksam.splitlines()) if wirksam else 0} "
                       f"Zuordnungen \u00b7 `{os.path.relpath(pfad, paths.BASE_DIR)}`")

            if st.button("Glossar speichern", use_container_width=True):
                try:
                    os.makedirs(os.path.dirname(paths.GLOSSAR_FILE),
                                exist_ok=True)
                    # Erst daneben schreiben, dann umbenennen: bricht der
                    # Vorgang ab, steht die alte Datei noch vollstaendig da.
                    vorlaeufig = paths.GLOSSAR_FILE + ".neu"
                    with open(vorlaeufig, "w", encoding="utf-8",
                              newline="\n") as f:
                        f.write(neu)
                    os.replace(vorlaeufig, paths.GLOSSAR_FILE)
                    st.success("Gespeichert. Wirkt ab der naechsten Frage.")
                    time.sleep(1)
                    st.rerun()
                except OSError as e:
                    st.error(f"Konnte nicht gespeichert werden: {e}")

    # --- VOREINSTELLUNGEN VERWALTEN ---
    #
    # Angelegt werden sie von Verwaltern, ausgewaehlt von allen. Eine
    # Voreinstellung buendelt, was zusammengehoert -- wer das jedes Mal von
    # Hand umstellt, macht es entweder selten oder falsch.
    if _vw:
        with st.expander("🎛️ Voreinstellungen verwalten"):
            vorhanden = presets.namen()
            bearbeiten = st.selectbox(
                "Bearbeiten", ["(neu anlegen)"] + vorhanden,
                format_func=lambda n: (n if n == "(neu anlegen)"
                                       else presets.lese(n)["bezeichnung"]),
                key="preset_bearbeiten")
            neu = bearbeiten == "(neu anlegen)"
            werte = presets.lese(None if neu else bearbeiten)

            bez = st.text_input("Bezeichnung", value="" if neu
                                else werte["bezeichnung"],
                                key=f"pb_{bearbeiten}")
            beschr = st.text_input("Beschreibung", value=werte["beschreibung"],
                                   key=f"pd_{bearbeiten}",
                                   help="Eine Zeile, die unter der Auswahl "
                                        "steht.")
            modell = st.text_input(
                "Chat-Modell", value=werte["chat_modell"],
                key=f"pm_{bearbeiten}",
                help="Leer = das Modell aus der .env. Der Name muss dem "
                     "eingetragenen Endpunkt bekannt sein.")
            k = st.number_input("Relevante Abschnitte", min_value=0,
                                max_value=30, value=int(werte["top_k"] or 0),
                                key=f"pk_{bearbeiten}",
                                help="0 = Vorgabe aus TOP_K.")
            bereiche = st.multiselect(
                "Listenbereiche", options=tabellen.bereiche(_eintraege),
                default=[b for b in werte["listen_bereiche"]
                         if b in tabellen.bereiche(_eintraege)],
                key=f"pl_{bearbeiten}",
                help="Unterordner des Listenordners. Leer = alle. Der "
                     "Wurzelordner selbst steht in der .env "
                     "(TABELLEN_PFAD).") if _eintraege else []

            links, rechts = st.columns(2)
            with links:
                if st.button("Speichern", key=f"psp_{bearbeiten}",
                             use_container_width=True):
                    ok, meldung = presets.speichern(bez, {
                        "bezeichnung": bez, "beschreibung": beschr,
                        "chat_modell": modell, "top_k": int(k),
                        "listen_bereiche": bereiche})
                    if ok:
                        st.success(f"Gespeichert als `{meldung}`.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(meldung)
            with rechts:
                if st.button("Entfernen", key=f"pdl_{bearbeiten}",
                             disabled=neu, use_container_width=True):
                    if presets.loesche(bearbeiten):
                        st.success("Entfernt.")
                        time.sleep(1)
                        st.rerun()

            st.caption("Eigene Prompts und ein eigenes Glossar bekommt eine "
                       "Voreinstellung ueber die Auswahl unter "
                       "\u201cPrompts bearbeiten\u201d.")

    # --- PROMPT-VORLAGEN ---
    #
    # Sie bestimmen, wonach gesucht und wie geantwortet wird -- also genau
    # das, was man im Betrieb nachschaerft. Bearbeitbar zu machen kostet
    # wenig; sie im Image zu lassen kostet fuer jede Formulierung einen
    # Rebuild.
    #
    # Nur fuer Verwalter: eine unglueckliche Formulierung wirkt auf jede
    # Antwort, die danach gegeben wird.
    if _vw:
        with st.expander("📜 Prompts bearbeiten"):
            namen = prompts.verfuegbar()
            if not namen:
                st.caption("Keine Vorlagen gefunden.")
            else:
                # Fuer wen gilt die Fassung: fuer die ganze Installation
                # oder nur fuer eine Voreinstellung? Genau hier bekommt ein
                # Buendel seine eigene Sprache -- fuer Bedienhandbuecher ist
                # "welche Maske, welches Feld" die richtige zweite Sonde,
                # fuer Regelwerke "welcher Anhang, welche Tabelle".
                geltung = st.selectbox(
                    "Gilt fuer", ["Alle"] + presets.namen(),
                    format_func=lambda n: (n if n == "Alle"
                                           else presets.lese(n)["bezeichnung"]),
                    key="prompt_geltung")
                fuer = None if geltung == "Alle" else geltung

                gewaehlt = st.selectbox(
                    "Vorlage", namen,
                    format_func=lambda n: f"{prompts.VORLAGEN[n]['titel']} ({n})")
                angaben = prompts.VORLAGEN[gewaehlt]
                st.caption(angaben["zweck"])

                inhalt, herkunft = prompts.lese(gewaehlt, fuer)
                text = st.text_area(
                    "Platzhalter: " + ", ".join(
                        list(angaben["pflicht"]) + list(angaben["optional"])),
                    value=inhalt, height=340,
                    key=f"prompt_{gewaehlt}_{fuer}")

                st.caption({
                    "preset": "Eigene Fassung dieser Voreinstellung",
                    "eigen": "Bearbeitete Fassung aus `config/`",
                    "vorlage": "Mitgelieferte Vorlage",
                }[herkunft])

                links, rechts = st.columns(2)
                with links:
                    if st.button("Speichern", key=f"sp_{gewaehlt}_{fuer}",
                                 use_container_width=True):
                        ok, meldung = prompts.speichern(gewaehlt, text, fuer)
                        if ok:
                            st.success(meldung)
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(meldung)
                with rechts:
                    # Zuruecksetzen entfernt nur die Fassung dieser Stufe.
                    # Darunter gilt dann wieder, was ohnehin gelten wuerde.
                    eigene_stufe = (herkunft == "preset" if fuer
                                    else herkunft == "eigen")
                    if st.button("Zuruecksetzen", key=f"zr_{gewaehlt}_{fuer}",
                                 disabled=not eigene_stufe,
                                 use_container_width=True):
                        if prompts.zuruecksetzen(gewaehlt, fuer):
                            st.success("Zurueckgesetzt.")
                            time.sleep(1)
                            st.rerun()

    # --- KONFIGURATION GEGEN DIE VORLAGE ---
    #
    # .env steht in der .gitignore, ein git pull fasst sie also nie an.
    # Kommt mit einem Update eine Einstellung dazu oder aendert sich ein
    # empfohlener Wert, bleibt die eigene .env, wie sie war -- und ein dort
    # eingetragener Wert schlaegt immer den Standard im Code. Genau so ist
    # eine Obergrenze ueber mehrere Updates hinweg auf einem Wert
    # stehengeblieben, der zu Ausfaellen beim Vektorisieren gefuehrt hat.
    #
    # Angezeigt werden nur Namen, nie Werte; Namen, die auf ein Geheimnis
    # hindeuten, werden gar nicht erst verglichen.
    if _vw:
        try:
            fehlend, abweichend, unbekannt = envcheck.vergleiche()
        except Exception:
            fehlend, abweichend, unbekannt = [], [], []
        if fehlend or abweichend or unbekannt:
            with st.expander(f"⚙️ Konfiguration ({len(fehlend) + len(abweichend) + len(unbekannt)})"):
                if abweichend:
                    st.caption("**Abweichend von der Vorlage** -- gewollt oder "
                               "beim letzten Update uebersehen:")
                    st.code(chr(10).join(abweichend), language="text")
                if fehlend:
                    st.caption("**Nicht in der eigenen .env** -- es greift der "
                               "Standard aus dem Code:")
                    st.code(chr(10).join(fehlend), language="text")
                if unbekannt:
                    st.caption("**Nur in der eigenen .env** -- veraltet, oder "
                               "die Vorlage hat den Eintrag verloren:")
                    st.code(chr(10).join(unbekannt), language="text")
