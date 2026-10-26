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
import sprache
from sprache import t as tx
import auth
import benutzer
import chats
import envcheck
import feedback
import geheim
import llm
import hintergrund
import keyword_index
import listenquellen
import mcp
import notzugang
import owncloud
import paths
import dateisperre
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
        st.caption(tx("ownCloud: ") + " · ".join(bericht["schritte"]))
    for f in bericht.get("fehler") or []:
        st.warning(tx("ownCloud: ") + f)
    if bericht.get("fehler"):
        st.caption(tx(f'{was} ist angelegt. ownCloud-Ablage später unter *ownCloud* einrichten.'))


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
        _vw = st.toggle(tx("Admin-Bereich"), value=False,
                        key="verwaltung_offen", disabled=_antwortet,
                        help=tx("Benutzer, Arbeitsbereiche, Sicherung, Prompts.")
                             + (tx(" -- gesperrt, solange eine Antwort läuft.")
                                if _antwortet else ""))
    if _vw:
        zahlen = _verwaltungsstand()["rueckmeldungen"]
        gesamt = sum(zahlen.values())
        if gesamt:
            with st.expander(tx(f'Rückmeldungen ({gesamt})')):
                st.caption(
                    tx(f"ohne Treffer: {zahlen['leer']} \u00b7 "
                    f"hat geholfen: {zahlen['daumen_hoch']} \u00b7 "
                    f"hat nicht geholfen: {zahlen['daumen_runter']}"))
                st.caption(tx("**Fragen ohne Treffer** -- Kandidaten für glossar.txt:"))
                leer = feedback.lese(grenze=15, art="leer")
                if leer:
                    st.code(chr(10).join(
                        f"{e['zeitpunkt'][:10]}  {e['frage'][:70]}"
                        for e in leer), language="text")
                else:
                    st.caption(tx("keine"))
                schlecht = feedback.lese(grenze=15, art="daumen_runter")
                if schlecht:
                    st.caption(tx("**Als nicht hilfreich gemeldet** -- falsche Treffer:"))
                    st.code(chr(10).join(
                        f"{e['zeitpunkt'][:10]}  {e['frage'][:70]}"
                        for e in schlecht), language="text")
                st.caption(tx("Vollständig in `data/feedback.jsonl`."))

                # Beiseitelegen statt loeschen: die Arbeitsliste soll leer
                # werden, nicht die Ueberlieferung. Was Nutzer nicht
                # gefunden haben, ist die einzige Quelle fuer die Frage, ob
                # der Bestand mit der Zeit besser wird.
                if st.button(tx("Liste abschließen"), use_container_width=True,
                             help=tx("Archiviert das Protokoll mit Datum und beginnt ein neues; nichts wird gelöscht.")):
                    ziel = feedback.archiviere()
                    if ziel:
                        st.success(tx(f"Abgelegt als `{os.path.basename(ziel)}`."))
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.info(tx("Nichts abzulegen."))

                # Herunterladen statt auf den Server steigen: die Liste
                # wird ausgewertet, nicht nur angesehen, und dafuer braucht
                # man sie vollstaendig.
                if os.path.exists(feedback.DATEI):
                    # Entschluesselt: auf der Platte liegt es
                    # verschluesselt, ausgewertet wird es im Klartext.
                    st.download_button(
                        tx("Protokoll herunterladen"), feedback.als_text(),
                        file_name="feedback.jsonl",
                        mime="application/x-ndjson",
                        use_container_width=True)

                alte = feedback.ablagen()
                if alte:
                    st.caption(tx("Früher abgelegt:"))
                    wahl = st.selectbox(tx("Ablage"), alte, label_visibility="collapsed", format_func=sprache.uebersetzt())
                    pfad = os.path.join(os.path.dirname(feedback.DATEI), wahl)
                    if os.path.exists(pfad):
                        with open(pfad, "rb") as f:
                            st.download_button(
                                tx(f"{wahl} herunterladen"), f.read(),
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
        st.caption(tx("**Zugänge**"))
    if _vw:
        with st.expander(tx("Benutzer")):
            _zustand = benutzer.zustand()
            _gesperrt = benutzer.ungueltige()

            if _zustand == benutzer.UNSIGNIERT:
                st.warning(
                    tx("Benutzerdatei ist noch nicht signiert – bis dahin gilt `ADMIN_USERS` aus der `.env`, und von Hand eingetragene Zugänge kommen herein."))
                if st.button(tx("Jetzt signieren"), use_container_width=True):
                    ok, meldung = benutzer.neu_signieren(
                        von=st.session_state["username"])
                    (st.success if ok else st.error)(meldung)
                    time.sleep(1)
                    st.rerun()
            elif _zustand == benutzer.MANIPULIERT:
                st.error(
                    tx("Benutzerdatei wurde außerhalb von LocaNoto geändert.")
                    + (tx(f" Gesperrt, Signatur ungültig: {', '.join(_gesperrt)}.") if _gesperrt else
                       tx(" Ein Eintrag fehlt oder ist hinzugekommen.")))

            # Kollidierende Kennungen: zwei Nutzer, ein persoenlicher
            # Raum. Beim Anlegen wird das jetzt abgewiesen -- ein
            # Bestand kann es aber schon enthalten.
            _konflikte = raeume.konflikte(benutzer.namen())
            if _konflikte:
                st.error(
                    tx("Diese Kennungen teilen sich einen persönlichen Arbeitsbereich und sehen gegenseitig ihre Unterlagen: ")
                    + "; ".join(
                        f"{', '.join(n)} -> {k}" for k, n in _konflikte)
                    + tx(". Eine der Kennungen umbenennen (neu anlegen, ")
                    + tx("Dokumente verschieben, alte löschen)."))

            for _n in benutzer.namen():
                _e = benutzer.eintrag(_n) or {}
                _marke = "" if _e.get("_gueltig", True) else "  GESPERRT"
                st.caption(f"**{_n}** · {_e.get('rolle', '?')}"
                           f"{_marke}")

            st.markdown("---")
            _wahl = st.selectbox(
                tx("Bearbeiten"), ["(neu anlegen)"] + benutzer.namen(),
                key="benutzer_wahl", format_func=sprache.uebersetzt())

            if _wahl == "(neu anlegen)":
                # In einem Formular, damit alle Felder MIT dem Klick
                # ankommen. Vorher hing der Knopf an "Passwort ausgefuellt"
                # aus dem vorigen Durchlauf: wer das Passwort tippte und
                # direkt klickte, traf einen noch gesperrten Knopf, und
                # der Klick verpuffte ohne Meldung.
                with st.form(
                        f"benutzer_neu_{_feldschluessel('benutzer_neu', 'runde')}"):
                    _name = st.text_input(
                        tx("Kennung"), key=_feldschluessel("benutzer_neu", "name"))
                    _rolle = st.selectbox(
                        tx("Rolle"), list(benutzer.ROLLEN),
                        index=list(benutzer.ROLLEN).index("nutzer"),
                        key=_feldschluessel("benutzer_neu", "rolle"),
                        help=tx("admin verwaltet alles; notzugang bestätigt nur den Notzugang eines Admins und gehört an jemanden, der kein Admin ist."), format_func=sprache.uebersetzt())
                    _pw1 = st.text_input(
                        tx(f'Passwort (mind. {benutzer.MIN_PASSWORT} Zeichen)'),
                        type="password",
                        key=_feldschluessel("benutzer_neu", "pw1"))
                    _pw2 = st.text_input(
                        tx("Passwort wiederholen"), type="password",
                        key=_feldschluessel("benutzer_neu", "pw2"))
                    _anlegen = st.form_submit_button(
                        tx("Benutzer anlegen"), use_container_width=True)
                if _anlegen:
                    if not (_name or "").strip() or not _pw1:
                        st.error(tx("Kennung und Passwort eintragen."))
                    elif _pw1 != _pw2:
                        st.error(tx("Eingaben stimmen nicht überein."))
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
                            with st.spinner(tx("Richte Ablage ein ...")):
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
                st.caption(tx(f"Angelegt: {_e.get('angelegt', 'unbekannt')} "
                           f"· von: {_e.get('von', 'unbekannt')}"))
                # Der Rueckfall geht ueber den NAMEN und nicht ueber eine
                # Zahl: als "notzugang" dazukam, waere aus dem frueheren
                # Index 1 ("nutzer") still die neue Rolle geworden.
                _neue_rolle = st.selectbox(
                    tx("Rolle"), list(benutzer.ROLLEN),
                    index=(list(benutzer.ROLLEN).index(_e.get("rolle"))
                           if _e.get("rolle") in benutzer.ROLLEN
                           else list(benutzer.ROLLEN).index("nutzer")),
                    key=f"benutzer_rolle_{_wahl}",
                    help=tx("admin verwaltet alles; notzugang bestätigt nur den Notzugang eines Admins und gehört an jemanden, der kein Admin ist."), format_func=sprache.uebersetzt())
                if _neue_rolle != _e.get("rolle"):
                    if st.button(tx("Rolle übernehmen"), use_container_width=True,
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
                # Formular aus demselben Grund wie beim Anlegen: die
                # Felder kommen mit dem Klick an, nicht einen Durchlauf
                # spaeter.
                with st.form(f"{_pwb}_{_feldschluessel(_pwb, 'runde')}"):
                    _pw1 = st.text_input(tx("Neues Passwort"), type="password",
                                         key=_feldschluessel(_pwb, "pw1"))
                    _pw2 = st.text_input(tx("Wiederholen"), type="password",
                                         key=_feldschluessel(_pwb, "pw2"))
                    _pw_setzen = st.form_submit_button(
                        tx("Passwort setzen"), use_container_width=True)
                if _pw_setzen:
                    if not _pw1:
                        st.error(tx("Bitte ein Passwort eintragen."))
                    elif _pw1 != _pw2:
                        st.error(tx("Eingaben stimmen nicht überein."))
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
                                with st.spinner(tx("Richte Ablage ein ...")):
                                    _b = owncloud.richte_nutzer_ein(
                                        _wahl, _pw1, _wahl)
                                _oc_bericht(_b, "Der Zugang")
                                if any("gab es schon" in _s for _s
                                       in _b.get("schritte") or []):
                                    # Das Konto bestand: das neue Passwort
                                    # gilt dort nur, wenn LocaNoto es
                                    # verwaltet. Sonst sagt die Meldung,
                                    # dass weiter das alte gilt.
                                    _ok_p, _m_p = owncloud.passwort_setzen(
                                        _wahl, _pw1)
                                    if _m_p:
                                        (st.info if _ok_p
                                         else st.warning)(_m_p)
                            _felder_leeren(_pwb, "pw1", "pw2")
                            time.sleep(3 if _b.get("fehler") else 1)
                            st.rerun()

                # Loeschen entfernt den Zugang, nicht die Daten. Chats und
                # der persoenliche Raum bleiben -- wer beides in einem Klick
                # zusammenlegt, loescht irgendwann mehr als gemeint.
                _sicher = st.checkbox(tx(f"'{_wahl}' wirklich löschen"),
                                      key=f"benutzer_x_{_wahl}")
                if st.button(tx("Benutzer löschen"), use_container_width=True,
                             disabled=not _sicher,
                             key=f"benutzer_del_{_wahl}"):
                    ok, meldung = benutzer.loesche(
                        _wahl, von=st.session_state["username"])
                    (st.success if ok else st.error)(meldung)
                    if ok:
                        # Was in LocaNoto geloescht wird, verschwindet auch
                        # in ownCloud -- das Konto, sofern LocaNoto es
                        # verwaltet. Ein fremdes bleibt, und das wird gesagt.
                        # Die persoenliche Anweisung gehoert zum Zugang
                        # und geht mit ihm.
                        prompts.anweisung_loeschen(_wahl)
                        _ok_k, _m_k = owncloud.konto_loeschen(_wahl)
                        if _m_k:
                            (st.info if _ok_k else st.warning)(_m_k)
                        time.sleep(3 if _m_k else 1)
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
                st.caption(tx(f"Protokoll: {_zeilen} Einträge, Kette in Ordnung."))
            else:
                st.error(tx(f'Protokoll ab Zeile {_zeilen} verändert oder eine Zeile fehlt.'))
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
        with st.expander(tx("Zugangstoken (Schnittstelle)")):
            st.caption(
                tx("Für Masseningest in **Allgemein** braucht es das Token eines Admins – sonst antwortet die Schnittstelle mit 403."))

            # ZUERST das frisch angelegte Token, falls eines aussteht.
            # Genau einmal zu zeigen heisst in Streamlit: den Wert einen
            # Lauf ueberdauern lassen und ihn wegwerfen, sobald jemand
            # bestaetigt hat, ihn zu haben.
            _frisch = st.session_state.get("_neues_token")
            if _frisch:
                st.success(tx("Angelegt. **Nur jetzt sichtbar** – Wert jetzt kopieren."))
                st.code(_frisch, language="text")
                if st.button(tx("Notiert"), key="token_weg",
                             use_container_width=True):
                    del st.session_state["_neues_token"]
                    st.rerun()
                st.markdown("---")

            _namen = benutzer.namen()
            if not _namen:
                st.caption(tx("Noch kein Benutzer angelegt."))
            else:
                # Im Formular, aus demselben Grund wie beim
                # Passwortaendern: ein Textfeld uebergibt seinen Inhalt
                # erst beim Verlassen, und ein Klick direkt nach dem
                # Tippen saehe sonst ein leeres Feld.
                _tk = "token_neu"
                with st.form(f"token_{_feldschluessel(_tk, 'runde')}"):
                    _t_wer = st.selectbox(
                        tx("Für wen"), _namen,
                        key=_feldschluessel(_tk, "wer"), format_func=sprache.uebersetzt())
                    _t_bez = st.text_input(
                        tx("Bezeichnung"), key=_feldschluessel(_tk, "bez"),
                        help=tx("Zweck, z. B. 'Masseneinlesen Laptop' → erscheint in der Liste unten."))
                    _t_tage = st.number_input(
                        tx("Gültig (Tage, 0 = unbegrenzt)"),
                        min_value=0, max_value=3650, value=0, step=30,
                        key=_feldschluessel(_tk, "tage"))
                    _t_ab = st.form_submit_button(
                        tx("Token anlegen"), use_container_width=True,
                        disabled=_antwortet)
                if _t_ab:
                    try:
                        st.session_state["_neues_token"] = auth.erzeuge(
                            _t_wer, _t_bez, int(_t_tage) or None)
                        _felder_leeren(_tk)
                        _leeren()
                        st.rerun()
                    except Exception as e:
                        st.error(tx(f"Nicht angelegt: {type(e).__name__}: {e}"))

            # --- die vorhandenen ---
            st.markdown("---")
            _tokens = auth.liste()
            if not _tokens:
                st.caption(tx("Keine Token angelegt."))
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
                    st.caption(tx(f"angelegt {_e.get('erstellt', '?')[:19]}"))
                with _z2:
                    if st.button("🗑️", key=f"token_weg_{_h[:12]}",
                                 help=tx("Widerrufen"), disabled=_antwortet):
                        _anzahl = auth.widerrufe(_h)
                        if _anzahl == 1:
                            st.info(tx("Widerrufen."))
                        else:
                            st.error(tx("Nicht widerrufen."))
                        _leeren()
                        time.sleep(1)
                        st.rerun()

        # --- POSTFAECHER ---
        #
        # Ein Werkzeugserver stellt dem Modell Funktionen bereit, die es
        # waehrend einer Antwort aufrufen kann. Eingerichtet wird hier
        # statt in einer Datei von Hand.
        with st.expander(tx("Postfächer (Werkzeugserver)")):
            _pf = mcp.lies_konfiguration()
            if not _pf:
                st.caption(tx("Kein Postfach eingerichtet."))
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
                        + (tx(f" · Postfach: {_a['postfach']}")
                           if _a.get("postfach") else "")
                        + tx(f" · Anmeldung: {mcp.anmeldeart(_name)}")
                        + ("" if not _a.get("automatisch") else
                           (tx(" · mit Hinweis") if mcp.hinweis_an(_name)
                            else tx(" · OHNE Hinweis"))))
                with _z2:
                    if st.button("🗑️", key=f"pf_weg_{_name}",
                                 help=tx("Entfernen"), disabled=_antwortet):
                        _ok, _m = mcp.entferne_postfach(_name)
                        (st.info if _ok else st.error)(_m)
                        _leeren()
                        time.sleep(1)
                        st.rerun()
                if st.button(tx("Werkzeuge abfragen"), key=f"pf_test_{_name}",
                             disabled=_antwortet):
                    _v = mcp.verbinde(
                        st.session_state.get("_postfach_koepfe"))
                    try:
                        _w = _v[_name].werkzeuge()
                        st.success(tx(f"{len(_w)} Werkzeuge"))
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
                st.markdown(tx("**Neues Postfach**"))
                st.caption(
                    tx("Für persönliche Postfächer genügt **ein Eintrag für alle**, z. B. `postfach` – jeder meldet sich unter „Meine Postfächer“ selbst an. Jedes Funktionspostfach (info@, service@ …) bekommt einen eigenen Eintrag."))
                _v_wahl = st.selectbox(
                    tx("Servertyp"), sorted(mcp.VORLAGEN),
                    format_func=sprache.uebersetzt(lambda v: mcp.VORLAGEN[v]["beschreibung"]),
                    key=_feldschluessel(_pk, "vorlage"))
                _v_name = st.text_input(
                    tx("Name"), key=_feldschluessel(_pk, "name"),
                    help=tx("Teil des Werkzeugnamens für das Modell, kurz und sprechend, z. B. 'postfach' oder 'info'."))
                _v_ziel = st.text_input(
                    tx("Adresse oder Befehl"), key=_feldschluessel(_pk, "ziel"),
                    help=tx("Exchange: Server wie `owa.firma.de` (`/EWS/Exchange.asmx` wird ergänzt, leer → automatisch); HTTP: Adresse; lokal: Startbefehl; Websuche: `http://websuche:8000/mcp`."))
                _v_pers = st.radio(
                    tx("Postfach"), ["persönlich", "Funktionspostfach"],
                    key=_feldschluessel(_pk, "pers"),
                    help=tx("Persönliche Postfächer antworten nie selbst – jede Nachricht wird vorgelegt."), format_func=sprache.uebersetzt())
                # Nur bei Exchange gefuellt. Ohne diese Adresse oeffnet
                # ein Funktionspostfach das Postfach dessen, der sich
                # gerade anmeldet -- deshalb weist lege_an() es ab.
                _v_adr = st.text_input(
                    tx("Postfachadresse (nur Exchange)"),
                    key=_feldschluessel(_pk, "adr"),
                    placeholder=tx("info@firma.de"),
                    help=tx("Funktionspostfach: Pflicht. Persönliche Postfächer: leer → jeder nutzt seine Anmeldeadresse."))
                st.caption(tx("Nur für Funktionspostfächer:"))
                _v_auto = st.checkbox(
                    tx("darf selbst antworten"),
                    key=_feldschluessel(_pk, "auto"))
                _v_hin = st.checkbox(
                    tx("Hinweis unter Autoantworten setzen"),
                    value=True, key=_feldschluessel(_pk, "hin"))
                _v_htext = st.text_input(
                    tx("Hinweistext"), key=_feldschluessel(_pk, "htext"),
                    placeholder=mcp.HINWEIS_VORGABE)
                _pf_ab = st.form_submit_button(
                    tx("Anlegen"), use_container_width=True, disabled=_antwortet)
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

        with st.expander(tx("Verschlüsselung")):
            st.caption(tx(f"Zustand: **{geheim.beschreibung()}**"))
            if not geheim.verfuegbar():
                st.error(
                    tx("Chats, Anhänge und Rückmeldungen liegen unverschlüsselt: Paket `cryptography` fehlt – `requirements.txt` prüfen und Image neu bauen."))
            else:
                st.caption(
                    tx("Verschlüsselt: Chats, Bilder, Rückmeldungen. Signiert: Benutzerdatei, Zugangstoken."))
                st.caption(
                    tx("**Nicht** verschlüsselt: der Dokumenttext in der Vektordatenbank – dafür den Datenträger verschlüsseln."))

            _offen_chats = chats.zaehle_klartext(st.session_state["username"])
            if _offen_chats:
                st.warning(tx(f'{_offen_chats} deiner Chatdateien noch unverschlüsselt – werden beim nächsten Öffnen verschlüsselt.'))

            _offen_fb = feedback.klartextzeilen()
            if _offen_fb:
                st.warning(tx(f'Rückmeldungsprotokoll: noch {_offen_fb} Zeilen im Klartext.'))
                if st.button(tx("Protokoll neu verschlüsseln"),
                             use_container_width=True):
                    ok, anzahl = feedback.neu_verschluesseln()
                    if ok:
                        st.success(tx(f"{anzahl} Zeilen neu geschrieben."))
                    else:
                        st.error(tx("Schreiben fehlgeschlagen."))
                    time.sleep(1)
                    st.rerun()

            # Die Grenze ausdruecklich nennen. Ein Verwalter, der glaubt,
            # die Verschluesselung schuetze auch gegen jemanden mit
            # Serverzugang, traegt eine falsche Auskunft weiter.
            st.caption(
                tx("Wer Dateizugriff auf `config/` hat, kann die Chats entschlüsseln – geschützt sind nur Sicherungen und kopierte Volumes."))

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
        with st.expander(tx("Notzugang") + _marke):
            st.caption(
                tx(f'Auch Admins kommen nicht in persönliche Arbeitsbereiche. Notzugang braucht **zwei Personen**: ein Admin beantragt, jemand mit Rolle *notzugang* bestätigt – gilt dann {notzugang.STUNDEN} Stunden, beide stehen im Protokoll.'))
            st.caption(tx(f"Stand: {notzugang.beschreibung()}"))

            # --- offene Zugaenge, fuer beide Seiten sichtbar ---
            if _offen:
                st.markdown(tx("**Gerade offen**"))
                for _z in _offen:
                    _rest = max(0, (_z["bis"] - int(time.time())) // 60)
                    st.warning(
                        tx(f"`{_z['raum']}` — {_z['von']}, bestätigt von "
                        f"{_z['durch']}, noch {_rest // 60} h {_rest % 60} min")
                        + (f"\n\n„{_z['grund']}\"" if _z.get("grund") else ""))
                    if st.button(tx("Jetzt schließen"),
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
                st.markdown(tx("**Anträge**"))
                if not _antraege:
                    st.caption(tx("Keine offenen Anträge."))
                for _a in _antraege:
                    st.info(tx(f"**{_a['von']}** möchte in `{_a['raum']}`")
                            + (f"\n\n„{_a['grund']}\"" if _a.get("grund")
                               else ""))
                    _s1, _s2 = st.columns(2)
                    with _s1:
                        if st.button(tx("Bestätigen"),
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
                        if st.button(tx("Ablehnen"),
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
                st.markdown(tx("**Zugang beantragen**"))
                if not notzugang.moeglich():
                    st.error(
                        tx("Niemand hat die Rolle *notzugang*. Vergib sie unter *Benutzer* an jemanden, der kein Admin ist."))
                else:
                    _fremde_privat = sorted(
                        k for k in raeume.liste() if raeume.ist_privat(k)
                        and k != raeume.privat_kennung(
                            st.session_state["username"]))
                    if not _fremde_privat:
                        st.caption(tx("Keine fremden persönlichen Arbeitsbereiche vorhanden."))
                    else:
                        _ziel = st.selectbox(tx("Arbeitsbereich"), _fremde_privat,
                                             key="nz_ziel", format_func=sprache.uebersetzt())
                        _grund = st.text_area(
                            tx("Grund"), key="nz_grund",
                            help=tx("Landet im Protokoll; die zweite Person entscheidet danach."))
                        if st.button(tx("Notzugang beantragen"),
                                     use_container_width=True):
                            _ok, _m = notzugang.beantrage(
                                _ziel, st.session_state["username"], _grund)
                            (st.success if _ok else st.error)(_m)
                            if _ok:
                                _leeren()
                                time.sleep(1)
                                st.rerun()

            st.caption(
                tx("**Grenze:** Wer Serverzugang hat, kann persönliche Arbeitsbereiche trotzdem lesen – der Notzugang schützt nur innerhalb von LocaNoto."))

    # --- RAEUME VERWALTEN ---
    #
    # Ein Raum ist eine Sammlung und eine Mitgliederliste. Die Sammlung
    # entsteht beim ersten Upload, nicht hier: ein Raum ohne Inhalt braucht
    # keine Sammlung, und eine leere anzulegen wuerde jede Suche mit einer
    # weiteren Abfrage belasten.
    if _vw:
        with st.expander(tx("Arbeitsbereiche")):
            _alle = raeume.liste()
            _bekannt = benutzer.namen()
            _mit_daten = {r: sml.count()
                          for r, sml in _alle_raum_sammlungen()}

            for _k, _e in sorted(_alle.items()):
                _m = _e.get("mitglieder") or []
                _wer = "alle" if "*" in _m else f"{len(_m)} Mitglieder"
                if _e.get("gruppe"):
                    _wer += f" + Gruppe {_e['gruppe']}"
                st.caption(tx(f"**{_e.get('bezeichnung') or _k}** · "
                           f"{_wer} · "
                           f"{_mit_daten.get(_k, 0):,} Abschnitte "
                           f"· `{_k}`"))

            st.markdown("---")
            _bearbeiten = st.selectbox(
                tx("Bearbeiten"), ["(neu anlegen)"] + sorted(_alle),
                format_func=sprache.uebersetzt(lambda n: (
                    n if n == "(neu anlegen)"
                    else (_alle.get(n, {}).get("bezeichnung") or n))),
                key="raum_bearbeiten")

            if _bearbeiten == "(neu anlegen)":
                _name = st.text_input(
                    tx("Bezeichnung"), key=_feldschluessel("raum_neu", "name"))
                _besch = st.text_input(
                    tx("Beschreibung (optional)"),
                    key=_feldschluessel("raum_neu", "besch"))
                _mitglieder = st.multiselect(
                    tx("Mitglieder"), _bekannt,
                    key=_feldschluessel("raum_neu", "mit"),
                    help=tx("Nur diese Nutzer sehen die Dokumente des Arbeitsbereichs."), format_func=sprache.uebersetzt())
                if st.button(tx("Arbeitsbereich anlegen"), use_container_width=True,
                             disabled=not _name.strip()):
                    ok, meldung = raeume.anlegen(_name, _name, _besch,
                                                 _mitglieder)
                    if ok:
                        st.success(tx(f"Arbeitsbereich '{_name}' angelegt."))
                        with st.spinner(tx("Richte Ablage ein ...")):
                            _b = owncloud.richte_raum_ein(meldung)
                        _oc_bericht(_b, "Der Raum")
                        refresh_document_index()
                        _felder_leeren("raum_neu", "name", "besch", "mit")
                        time.sleep(2 if _b.get("fehler") else 1)
                        st.rerun()
                    else:
                        st.error(tx(meldung))
            else:
                _e = _alle.get(_bearbeiten, {})
                _m = _e.get("mitglieder") or []
                if "*" in _m:
                    st.caption(tx("Für alle sichtbar – Mitgliederliste gilt hier nicht."))
                _name = st.text_input(tx("Bezeichnung"),
                                      value=_e.get("bezeichnung") or "",
                                      key=f"raum_b_{_bearbeiten}")
                _besch = st.text_input(tx("Beschreibung"),
                                       value=_e.get("beschreibung") or "",
                                       key=f"raum_d_{_bearbeiten}")
                # Ein persoenlicher Raum gehoert genau einem Nutzer.
                # Mitglieder hinzuzufuegen waere eine Hintertuer, und im
                # strengen Betrieb widerspricht sie dem Zweck.
                _ist_privat = raeume.ist_privat(_bearbeiten)
                if _ist_privat:
                    st.caption(
                        tx("Persönlicher Arbeitsbereich – nur sein Eigentümer sieht ihn.")
                        + (tx(" Als Ganzes löschbar unter *fremde persönliche Arbeitsbereiche*.") if raeume.PRIVAT_STRENG
                           else ""))
                    _neu_m = [x for x in _m if x != "*"]
                else:
                    _neu_m = st.multiselect(
                        tx("Mitglieder"),
                        sorted(set(_bekannt) | {x for x in _m if x != "*"}),
                        default=[x for x in _m if x != "*"],
                        key=f"raum_m_{_bearbeiten}",
                        disabled=("*" in _m), format_func=sprache.uebersetzt())
                    # "Fuer alle sichtbar" ist eine Vorgabe, keine
                    # Notwendigkeit. Wo der Grundsatz "nur was man wissen
                    # muss" gilt, bekommt auch der allgemeine Raum eine
                    # Liste.
                    if "*" in _m:
                        if st.button(tx("Mitgliederliste verwenden"),
                                     use_container_width=True,
                                     key=f"raum_zu_{_bearbeiten}",
                                     help=tx("Umstellen → nur eingetragene Nutzer sehen diesen Arbeitsbereich.")):
                            raeume.mitglieder_setzen(
                                _bearbeiten,
                                [st.session_state["username"]])
                            st.success(tx("Umgestellt. Jetzt Mitglieder "
                                       "eintragen."))
                            time.sleep(1)
                            st.rerun()
                    elif st.button(tx("Für alle öffnen"),
                                   use_container_width=True,
                                   key=f"raum_auf_{_bearbeiten}"):
                        raeume.fuer_alle_oeffnen(_bearbeiten)
                        st.success(tx("Für alle sichtbar."))
                        time.sleep(1)
                        st.rerun()
                # --- MITGLIEDSCHAFT AUS OWNCLOUD ---
                #
                # Vereinigung, nicht Ersetzung: ein Verwalter, den die
                # Firma nicht in der Abteilungsgruppe fuehrt, soll sich
                # nicht selbst aussperren, indem er eine Gruppe eintraegt.
                _gruppe_alt = str(_e.get("gruppe") or "")
                _web_alt = raeume.websuche_erlaubt(_bearbeiten)
                _web = _web_alt
                if not _ist_privat:
                    _web = st.checkbox(
                        tx("Websuche erlauben"),
                        value=_web_alt, key=f"raum_w_{_bearbeiten}",
                        help=tx("Haken setzen → Nutzer können hier im Chat die Websuche einschalten; Suchbegriffe gehen an Suchmaschinen."))
                _gruppe = st.text_input(
                    tx("ownCloud-Gruppe (optional)"), value=_gruppe_alt,
                    key=f"raum_g_{_bearbeiten}",
                    help=tx("Mitglieder der Gruppe kommen zu den obigen hinzu. Leer lassen → Mitglieder nur hier pflegen."))
                if _gruppe.strip():
                    _von_hand, _aus_gruppe = raeume.mitglieder_gesamt(
                        _bearbeiten)
                    _gueltig, _alter, _grund = raeume.stand_gueltig()
                    if not _gueltig:
                        st.warning(
                            tx(f'Gruppenstand ungültig ({_grund}) – Mitglieder dieser Gruppe kommen gerade nicht herein. Abgleich unter *Nachtragen und neu einlesen*.'))
                    else:
                        st.caption(
                            tx("Aus der Gruppe: ")
                            + (", ".join(_aus_gruppe) if _aus_gruppe
                               else tx("niemand"))
                            + (tx(f' -- Stand vor {_alter:.0f} min')
                               if _alter is not None else ""))
                        _unbekannt = [x for x in _aus_gruppe
                                      if x not in _bekannt]
                        if _unbekannt:
                            # Der Fall, in dem alles richtig aussieht und
                            # trotzdem niemand hereinkommt.
                            st.warning(
                                tx(f"Keine Benutzer, daher ohne Wirkung: {', '.join(_unbekannt)}"))

                # --- LISTENORDNER ---
                #
                # Hier und nicht in den allgemeinen Einstellungen: wer
                # einen Raum einrichtet, weiss in diesem Moment, wo
                # dessen Listen liegen. Muss er es sich fuer spaeter
                # merken, bleibt das Feld leer -- und die Listensuche
                # fuer diesen Raum entsteht nie.
                _lq_alt = listenquellen.pfad_von(_bearbeiten)
                _lq = st.text_input(
                    tx("Listenordner (xlsx, csv)"), value=_lq_alt,
                    key=f"raum_lq_{_bearbeiten}",
                    help=tx("Pfad im Container, z. B. /mnt/abteilungen/einkauf/listen; leer → keine Listen."))
                if listenquellen.WURZELN:
                    st.caption(tx("Erlaubt unterhalb von: ")
                               + ", ".join(f"`{w}`"
                                           for w in listenquellen.WURZELN))

                # --- DATENBANKZUGANG ---
                #
                # Ein Konto je Raum, mit den Rechten dieses Raums. Damit
                # kommt auch das Schema mit diesen Rechten, und das
                # Sprachmodell sieht nur Tabellen, die es lesen darf.
                _sqz = sqlquellen.zugang(_bearbeiten) or {}
                with st.expander(tx("Datenbankzugang"),
                                 expanded=False):
                    st.caption(
                        tx("Konto mit genau den Rechten dieses Arbeitsbereichs, am besten nur lesend. Leer → Zugang aus der Umgebung."))
                    _sq_b = st.text_input(tx("Benutzer"),
                                          value=_sqz.get("benutzer", ""),
                                          key=f"sqb_{_bearbeiten}")
                    _sq_p = st.text_input(
                        tx("Passwort"), value=_sqz.get("passwort", ""),
                        type="password", key=f"sqp_{_bearbeiten}")
                    _sq_d = st.text_input(
                        tx("Datenbank (leer = Vorgabe)"),
                        value=_sqz.get("datenbank", ""),
                        key=f"sqd_{_bearbeiten}")
                    st.caption(
                        tx("Das Passwort wird verschlüsselt gespeichert, ohne Installationsschlüssel gar nicht."))

                if st.button(tx("Speichern"), use_container_width=True,
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
                            st.error(tx(_m_lq))
                        else:
                            with st.spinner(tx("Lese Listen ein ...")):
                                _k, _f = tabellen.baue_katalog()
                            st.caption(tx(f"{len(_k['eintraege'])} Blätter im Katalog."))
                    raeume.beschriften(_bearbeiten, _name, _besch)
                    if "*" not in _m and not _ist_privat:
                        raeume.mitglieder_setzen(_bearbeiten, _neu_m)
                    if _gruppe.strip() != _gruppe_alt:
                        raeume.gruppe_setzen(_bearbeiten, _gruppe)
                    if _web != _web_alt:
                        raeume.websuche_setzen(_bearbeiten, _web)
                    st.success(tx("Gespeichert."))
                    # Die Freigabe zieht mit -- SETZEN, nicht ergaenzen.
                    # Ein Mitglied zu entfernen und die Freigabe stehen zu
                    # lassen waere die haeufigste Art, eine
                    # Rechteaenderung wirkungslos zu machen: die Suche
                    # fragt den Raum nicht mehr, die Dateien liegen aber
                    # weiter im ownCloud des Ausgeschiedenen.
                    with st.spinner(tx("Gleiche Freigaben ab ...")):
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
                        if st.button(tx("Arbeitsbereich entfernen"),
                                     use_container_width=True,
                                     key=f"raum_e_{_bearbeiten}",
                                     help=tx("Entfernt den Arbeitsbereich aus LocaNoto; die Dokumente bleiben.")):
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
                        if st.button(tx("Daten löschen"),
                                     use_container_width=True,
                                     disabled=not _sicher,
                                     key=f"raum_l_{_bearbeiten}"):
                            ok, meldung = store.loesche(
                                raeume.sammlung(_bearbeiten))
                            keyword_index.delete_document_by_raum(_bearbeiten)
                            (st.success if ok else st.error)(meldung)
                            # Auch der ownCloud-Ordner des Raums wird
                            # geleert, sonst holte der Abgleich alles
                            # zurueck. Der Inhalt liegt im Papierkorb.
                            _n_oc, _f_oc = owncloud.leere_raumordner(
                                _bearbeiten)
                            if _n_oc:
                                st.info(tx(f'{_n_oc} Einträge aus dem ownCloud-Ordner in den Papierkorb verschoben.'))
                            if _f_oc:
                                st.warning(tx("In ownCloud nicht gelöscht: ")
                                           + ", ".join(_f_oc[:5])
                                           + tx(" -- der nächste Abgleich holt es zurück."))
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
                    tx(f'Alte gemeinsame Sammlung enthält noch {_alt_zahl:,} Abschnitte, die nicht mehr durchsucht werden. Dokumente in einen Arbeitsbereich legen, neu einlesen, dann alte Sammlung unter *Arbeitsbereiche* leeren.'))

    # --- OWNCLOUD ---
    #
    # Ein Ordner in ownCloud wird auf einen Raum abgebildet. Damit liegen
    # die Dokumente dort, wo sie gepflegt werden, und die Rechte auf dem
    # Ordner sind die von ownCloud -- die Mitgliedschaft des Raums
    # entscheidet dann, wer die daraus gebauten Abschnitte sieht.
    if _vw:
        st.caption(tx("**Betrieb**"))
    if _vw:
        with st.expander(tx("ownCloud")):
            _ok, _meldung = _owncloud_stand()
            (st.success if _ok else st.warning)(_meldung)

            if not owncloud.eingerichtet():
                st.caption(
                    tx("In der `.env` eintragen: `OWNCLOUD_URL` (Wurzel, z. B. `https://cloud.firma.de`), `OWNCLOUD_USER`, `OWNCLOUD_PASSWORT` (bei Zwei-Faktor ein **App-Passwort**). Damit LocaNoto die Ablage selbst einrichtet, braucht `OWNCLOUD_ADMIN_USER` **Admin-Rechte** in ownCloud."))
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
                               + ("" if _r in _zu else tx(" *(Standard)*"))
                               + f" · {_stand}")
                st.caption(
                    tx(f'Ohne eigenen Eintrag gilt der Standardbaum unter `/{owncloud.WURZEL}/`; ein Eintrag von Hand geht vor.'))

                st.markdown("---")
                _raum_wahl = st.selectbox(
                    tx("Arbeitsbereich"), sorted(raeume.liste()),
                    format_func=sprache.uebersetzt(raeume.bezeichnung), key="oc_raum")
                _ordner = st.text_input(
                    tx("Ordner in ownCloud"), value=_zu.get(_raum_wahl, ""),
                    placeholder=tx("/Abteilungen/Einkauf/Handbücher"),
                    key=f"oc_ordner_{_raum_wahl}",
                    help=tx("Pfad ab dem Wurzelordner des Kontos; Unterordner → Sachgebiete."))
                _sp1, _sp2 = st.columns(2)
                with _sp1:
                    if st.button(tx("Zuordnung speichern"),
                                 use_container_width=True,
                                 disabled=not _ordner.strip()):
                        _zu[_raum_wahl] = _ordner.strip()
                        owncloud.setze_zuordnung(_zu)
                        st.success(tx("Gespeichert."))
                        time.sleep(1)
                        st.rerun()
                with _sp2:
                    if st.button(tx("Zuordnung entfernen"),
                                 use_container_width=True,
                                 disabled=_raum_wahl not in _zu,
                                 help=tx("Abgleich endet; geholte Dateien und ihre Abschnitte bleiben.")):
                        _zu.pop(_raum_wahl, None)
                        owncloud.setze_zuordnung(_zu)
                        st.success(tx("Entfernt."))
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
                st.markdown(tx("**Konten**"))
                _verw = owncloud.verwaltete_konten()
                _offen_k = [n for n in benutzer.namen()
                            if n not in _verw and not owncloud.geschuetzt(n)]
                st.caption(
                    tx(f'LocaNoto verwaltet {len(_verw)} ownCloud-Konten: Passwort und Löschung laufen mit dem Benutzer. Ältere Konten erst nach Übernahme, Dienst- und Admin-Konto nie.'))
                if _offen_k:
                    st.caption(tx("Nicht übernommen: ")
                               + ", ".join(_offen_k[:20])
                               + (" …" if len(_offen_k) > 20 else ""))
                    if st.button(tx("Konten übernehmen"),
                                 use_container_width=True,
                                 help=tx("Nur, wenn diese ownCloud-Konten allein LocaNoto gehören und sonst nirgends genutzt werden.")):
                        with st.spinner(tx("Frage ownCloud ab ...")):
                            _dazu, _aus = owncloud.konten_uebernehmen(_offen_k)
                        st.success(tx(f"{len(_dazu)} Konten übernommen."))
                        if _aus:
                            st.caption(tx("Nicht übernommen: ") + ", ".join(_aus))
                        time.sleep(2)
                        st.rerun()

                st.markdown("---")
                st.markdown(tx("**Ablage einrichten**"))
                st.caption(
                    tx(f'Legt unter `/{owncloud.WURZEL}/` je Arbeitsbereich einen Ordner an und teilt ihn mit den Mitgliedern. Wiederholbar, Vorhandenes bleibt.'))
                if st.button(tx("Alle einrichten"),
                             use_container_width=True):
                    _gut, _schlecht = 0, []
                    with st.spinner(tx("Richte ein ...")):
                        for _r in sorted(raeume.liste()):
                            _b = owncloud.richte_raum_ein(_r)
                            if _b.get("fehler"):
                                _schlecht.append(
                                    f"{_r}: {_b['fehler'][0]}")
                            else:
                                _gut += 1
                    st.success(tx(f'{_gut} Arbeitsbereiche eingerichtet.'))
                    for _f in _schlecht[:10]:
                        st.warning(tx(_f))
                    _leeren()

                _wer = st.selectbox(
                    tx("Einzelnen Zugang nachziehen"),
                    ["-"] + benutzer.namen(), key="oc_nutzer", format_func=sprache.uebersetzt())
                if _wer != "-" and st.button(
                        tx("Persönliche Ablage einrichten"),
                        use_container_width=True):
                    with st.spinner(tx("Richte ein ...")):
                        # Ohne Passwort: das Konto gibt es entweder schon,
                        # oder es wird beim Anlegen erzeugt. Hier ein
                        # Passwort zu erfinden waere ein zweites Geheimnis
                        # fuer denselben Menschen.
                        _b = owncloud.richte_nutzer_ein(_wer)
                    _oc_bericht(_b, "Der Zugang")
                    if not _b.get("fehler"):
                        st.success(tx(f"Ablage für '{_wer}' ist bereit."))

                # --- PRUEFEN ---
                #
                # Vor dem ersten Abgleich, und zwar nicht aus Vorsicht,
                # sondern weil eine falsch eingerichtete Zuordnung genau
                # wie "alles geloescht" aussieht: der Ordner ist leer,
                # also gilt jede bekannte Datei als entfallen. Danach sind
                # die Abschnitte weg.
                if _raum_wahl in _zu:
                    st.markdown("---")
                    if st.button(tx("Änderungen prüfen"),
                                 use_container_width=True,
                                 key=f"oc_pruef_{_raum_wahl}"):
                        try:
                            with st.spinner(tx("Frage ownCloud ab ...")):
                                _neu, _geae, _entf, _unv = owncloud.plane(
                                    _raum_wahl)
                            st.caption(tx(f"unverändert: {len(_unv)}"))
                            for _titel, _liste in (("neu", _neu),
                                                   ("geändert", _geae),
                                                   ("entfallen", _entf)):
                                if _liste:
                                    st.caption(f"**{_titel}: "
                                               f"{len(_liste)}**")
                                    st.code(chr(10).join(_liste[:30]),
                                            language="text")
                            if not (_neu or _geae or _entf):
                                st.info(tx("Nichts zu tun."))
                        except Exception as e:
                            st.error(tx(f"Abfrage fehlgeschlagen: {e}"))

                # --- MITGLIEDSCHAFTEN ---
                st.markdown("---")
                _gz = owncloud.gruppen_zuordnung()
                _gueltig, _alter, _grund = raeume.stand_gueltig()
                if _gz:
                    for _r, _g in sorted(_gz.items()):
                        _vh, _ag = raeume.mitglieder_gesamt(_r)
                        st.caption(tx(f"**{raeume.bezeichnung(_r)}** "
                                   f"· Gruppe `{_g}` · "
                                   f"{len(_ag)} aus der Gruppe, "
                                   f"{len(_vh)} von Hand"))
                    if _gueltig:
                        st.caption(tx("Gruppenstand: ")
                                   + (tx(f"{_alter:.0f} Minuten alt")
                                      if _alter is not None
                                      else tx("unbekannt")))
                    else:
                        st.warning(tx(f'Gruppenstand ungültig: {_grund}. Bis zum nächsten Abgleich gelten nur von Hand eingetragene Mitglieder.'))
                    if st.button(tx("Mitgliedschaften abgleichen"),
                                 use_container_width=True):
                        with st.spinner(tx("Frage ownCloud ab ...")):
                            _b = owncloud.gruppen_abgleich()
                        (st.success if _b["geschrieben"]
                         else st.warning)(_b["meldung"])
                        for _f in _b["fehler"]:
                            st.error(tx(f"Gruppe '{_f['gruppe']}': "
                                     f"{_f['grund']}"))
                        time.sleep(1)
                        st.rerun()
                else:
                    st.caption(
                        tx("Noch keine ownCloud-Gruppe eingetragen; das geht unter *Arbeitsbereiche*. Die Gruppenabfrage braucht ein Admin-Konto (`OWNCLOUD_ADMIN_USER`)."))

                st.caption(
                    tx("Abgleich starten unter *Nachtragen und neu einlesen* → „Aus ownCloud abgleichen“. Dauerbetrieb per Zeitplan: `docker compose exec -T locanoto_bot python abgleich.py`"))

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
        with st.expander(tx("Sicherung der Vektordatenbank")):
            _abzuege = _verwaltungsstand()["abzuege"]
            st.caption(tx(f"Ablage: `{sicherung.ORDNER}`")
                       + (tx(f' · {sicherung.BEHALTEN} Abzüge bleiben')
                          if sicherung.BEHALTEN else
                          tx(" · alle Abzüge bleiben")))

            if not _abzuege:
                st.warning(
                    tx("Noch kein Abzug – bei Verlust der Vektordatenbank müsste alles stundenlang neu eingelesen werden."))
            else:
                st.code(chr(10).join(
                    f"{_n:<22} {_gr / 1e6:9.1f} MB  "
                    f"{_st.get('abschnitte', '?'):>8} Abschnitte  "
                    f"{len(_st.get('raeume') or {})} Räume"
                    + ("   UNVOLLSTÄNDIG" if _unvollstaendig(_st) else "")
                    for _n, _p, _gr, _st in _abzuege), language="text")
                if any(_unvollstaendig(_st) for _n, _p, _gr, _st in _abzuege):
                    st.warning(
                        tx("Ein Abzug ist unvollständig, nicht alle Arbeitsbereiche waren lesbar. Neuen Abzug ziehen; der letzte vollständige bleibt."))

            _laeuft = hintergrund.laeuft("sicherung")
            if _laeuft:
                st.caption(tx("Abzug läuft."))
                st.code(hintergrund.protokoll("sicherung", 6) or "...",
                        language="text")
            elif st.button(tx("Jetzt sichern"), use_container_width=True,
                           help=tx("Läuft im Hintergrund weiter, auch wenn die Seite neu lädt.")):
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
                    tx("Abzug einspielen"), [_n for _n, _p, _g, _s in _abzuege],
                    key="sich_wahl", format_func=sprache.uebersetzt())
                _st = dict(_abzuege[[_n for _n, _p, _g, _s
                                     in _abzuege].index(_wahl)][3])
                st.caption(
                    tx(f"{_st.get('abschnitte', '?')} Abschnitte in ")
                    + ", ".join(sorted((_st.get('raeume') or {}))))
                if _unvollstaendig(_st):
                    _fehlten = ", ".join(
                        _f.get("raum", "?") for _f in (_st.get("fehler") or [])
                    ) or "unbekannt"
                    st.error(
                        tx(f'Abzug unvollständig – nicht gelesene Arbeitsbereiche: {_fehlten}. Eingespielt wird nur der Rest; nimm lieber einen neueren vollständigen Abzug.'))
                _sicher = st.checkbox(
                    tx("Vorhandene Abschnitte überschreiben"),
                    key="sich_ok")
                if st.button(tx("Einspielen"), use_container_width=True,
                             disabled=not _sicher):
                    with st.spinner(tx("Spiele ein ...")):
                        _b = sicherung.hole_zurueck(_wahl)
                    for _r, _n2 in sorted(_b["raeume"].items()):
                        st.caption(tx(f"{_r}: {_n2} Abschnitte"))
                    for _f in _b["fehler"]:
                        st.error(tx(str(_f)))
                    if not _b["fehler"]:
                        st.success(tx("Eingespielt. Stichwortindex baut sich beim nächsten Start neu auf."))
                    refresh_document_index()

            st.caption(
                tx("Der Abzug enthält Abschnitte, Metadaten **und Vektoren** – Einspielen braucht kein Modell. Der Schlüssel ist **nicht** enthalten; bewahre ihn getrennt auf."))

    # --- SICHERHEITSLAGE ---
    #
    # Verschluesselung, die man nicht nachsehen kann, ist eine
    # Behauptung. Hier steht, was tatsaechlich gilt -- einschliesslich
    # dessen, was sie NICHT leistet. Ein offener Punkt heisst nicht
    # "kaputt", sondern "hier ist die Zusage schwaecher, als sie
    # aussieht".
    if _vw:
        st.caption(tx("**Lage**"))
    if _vw:
        _lage = sicherheit.lage()
        _offen = [n for n, _ok, _t in _lage if not _ok]
        with st.expander(tx(f'Sicherheitslage ({len(_lage) - len(_offen)}/{len(_lage)})')):
            for _name, _ok, _text in _lage:
                st.markdown(("✅ " if _ok else "⚠️ ") + f"**{_name}**")
                st.caption(tx(_text))
            st.caption(
                tx("Die letzten drei Punkte lassen sich nur eingrenzen: mit verschlüsseltem Datenträger und wenigen Personen mit Serverzugang."))

    # --- SPEICHERORTE ---
    #
    # Wo welcher Zustand liegt, auf einem Bildschirm. Bei einer Frage nach
    # der Datenhaltung ist "schau in die docker-compose.yaml und in fuenf
    # Module" keine Antwort.
    if _vw:
        with st.expander(tx("Speicherorte")):
            for _name, _pfad, _gesetzt in paths.wurzeln():
                st.caption(f"**{_name}** · `{_pfad}` · "
                           + (tx("von außen gesetzt") if _gesetzt
                              else tx("Standard neben dem Code")))

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
                    tx("Der Abgleich legt die Arbeitskopie aus ownCloud unter `dokumente` ab. Von Hand abgelegte Dateien werden eingelesen, erscheinen aber nie in ownCloud."))

            _modus = _verwaltungsstand()["journal"]
            if _modus.lower() != "wal":
                # Der stille Rueckfall. PRAGMA journal_mode=WAL schlaegt
                # nicht fehl, wenn das Dateisystem es nicht kann -- SQLite
                # bleibt beim alten Modus und sagt nichts. Genau das
                # passiert auf einem Netzlaufwerk.
                st.error(
                    tx(f'Stichwortindex läuft im Journalmodus `{_modus}` statt `wal` (meist Netzlaufwerk). `LOCANOTO_INDEX` auf ein containerlokales Verzeichnis setzen.'))
            else:
                st.caption(tx(f"Stichwortindex: Journalmodus `{_modus}`."))

            st.caption(
                tx("Vektordatenbank und Stichwortindex nicht auf Netzspeicher (NFS, SMB) legen."))

    if _vw:
        st.caption(tx("**Inhalte**"))
    if _vw:
        with st.expander(tx("Glossar")):
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
                tx("Eine Zuordnung je Zeile, # = Kommentar."),
                value=inhalt, height=320, key="glossar_text")

            wirksam = pipeline.glossar()
            st.caption(tx(f"Wirksam: {len(wirksam.splitlines()) if wirksam else 0} "
                       f"Zuordnungen \u00b7 `{os.path.relpath(pfad, paths.BASE_DIR)}`"))

            if st.button(tx("Glossar speichern"), use_container_width=True):
                try:
                    # Erst daneben schreiben, dann umbenennen: bricht der
                    # Vorgang ab, steht die alte Datei noch vollstaendig da.
                    dateisperre.schreibe_atomar(paths.GLOSSAR_FILE, neu)
                    st.success(tx("Gespeichert. Wirkt ab der nächsten Frage."))
                    time.sleep(1)
                    st.rerun()
                except OSError as e:
                    st.error(tx(f'Speichern fehlgeschlagen: {e}'))

    # --- VOREINSTELLUNGEN VERWALTEN ---
    #
    # Angelegt werden sie von Verwaltern, ausgewaehlt von allen. Eine
    # Voreinstellung buendelt, was zusammengehoert -- wer das jedes Mal von
    # Hand umstellt, macht es entweder selten oder falsch.
    if _vw:
        with st.expander(tx("Voreinstellungen")):
            vorhanden = presets.namen()
            bearbeiten = st.selectbox(
                tx("Bearbeiten"), ["(neu anlegen)"] + vorhanden,
                format_func=sprache.uebersetzt(lambda n: (n if n == "(neu anlegen)"
                                       else presets.lese(n)["bezeichnung"])),
                key="preset_bearbeiten")
            neu = bearbeiten == "(neu anlegen)"
            werte = presets.lese(None if neu else bearbeiten)

            bez = st.text_input(tx("Bezeichnung"), value="" if neu
                                else werte["bezeichnung"],
                                key=f"pb_{bearbeiten}")
            beschr = st.text_input(tx("Beschreibung"), value=werte["beschreibung"],
                                   key=f"pd_{bearbeiten}",
                                   help=tx("Zeile unter der Auswahl."))
            _mod_liste = [""] + llm.chat_modelle()
            modell = st.selectbox(
                tx("Chat-Modell"), _mod_liste,
                index=(_mod_liste.index(werte["chat_modell"])
                       if werte["chat_modell"] in _mod_liste else 0),
                format_func=sprache.uebersetzt(lambda m: m or tx("(Vorgabe)")),
                key=f"pm_{bearbeiten}",
                help=tx("Auswahl aus CHAT_MODELLE; leer → CHAT_MODEL."))
            k = st.number_input(tx("Relevante Abschnitte"), min_value=0,
                                max_value=30, value=int(werte["top_k"] or 0),
                                key=f"pk_{bearbeiten}",
                                help=tx("0 = Vorgabe aus TOP_K."))
            bereiche = st.multiselect(
                tx("Listenbereiche"), options=tabellen.bereiche(_eintraege),
                default=[b for b in werte["listen_bereiche"]
                         if b in tabellen.bereiche(_eintraege)],
                key=f"pl_{bearbeiten}",
                help=tx("Unterordner im Listenordner (TABELLEN_PFAD). Leer → alle."), format_func=sprache.uebersetzt()) if _eintraege else []

            links, rechts = st.columns(2)
            with links:
                if st.button(tx("Speichern"), key=f"psp_{bearbeiten}",
                             use_container_width=True):
                    ok, meldung = presets.speichern(bez, {
                        "bezeichnung": bez, "beschreibung": beschr,
                        "chat_modell": modell, "top_k": int(k),
                        "listen_bereiche": bereiche})
                    if ok:
                        st.success(tx(f"Gespeichert als `{meldung}`."))
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(tx(meldung))
            with rechts:
                if st.button(tx("Entfernen"), key=f"pdl_{bearbeiten}",
                             disabled=neu, use_container_width=True):
                    if presets.loesche(bearbeiten):
                        st.success(tx("Entfernt."))
                        time.sleep(1)
                        st.rerun()

            st.caption(tx("Eigene Prompts und Glossar für eine Voreinstellung: unter “Prompts” auswählen."))

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
        with st.expander(tx("Prompts")):
            namen = prompts.verfuegbar()
            if not namen:
                st.caption(tx("Keine Vorlagen gefunden."))
            else:
                # Fuer wen gilt die Fassung: fuer die ganze Installation
                # oder nur fuer eine Voreinstellung? Genau hier bekommt ein
                # Buendel seine eigene Sprache -- fuer Bedienhandbuecher ist
                # "welche Maske, welches Feld" die richtige zweite Sonde,
                # fuer Regelwerke "welcher Anhang, welche Tabelle".
                geltung = st.selectbox(
                    tx("Gilt für"), ["Alle"] + presets.namen(),
                    format_func=sprache.uebersetzt(lambda n: (n if n == "Alle"
                                           else presets.lese(n)["bezeichnung"])),
                    key="prompt_geltung")
                fuer = None if geltung == "Alle" else geltung

                gewaehlt = st.selectbox(
                    tx("Vorlage"), namen,
                    format_func=sprache.uebersetzt(lambda n: f"{prompts.VORLAGEN[n]['titel']} ({n})"))
                angaben = prompts.VORLAGEN[gewaehlt]
                st.caption(tx(angaben["zweck"]))

                inhalt, herkunft = prompts.lese(gewaehlt, fuer)
                text = st.text_area(
                    tx("Platzhalter: ") + ", ".join(
                        list(angaben["pflicht"]) + list(angaben["optional"])),
                    value=inhalt, height=340,
                    key=f"prompt_{gewaehlt}_{fuer}")

                st.caption(tx({
                    "preset": "Eigene Fassung dieser Voreinstellung",
                    "eigen": "Bearbeitete Fassung aus `config/`",
                    "vorlage": "Mitgelieferte Vorlage",
                }[herkunft]))

                links, rechts = st.columns(2)
                with links:
                    if st.button(tx("Speichern"), key=f"sp_{gewaehlt}_{fuer}",
                                 use_container_width=True):
                        ok, meldung = prompts.speichern(gewaehlt, text, fuer)
                        if ok:
                            st.success(tx(meldung))
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(tx(meldung))
                with rechts:
                    # Zuruecksetzen entfernt nur die Fassung dieser Stufe.
                    # Darunter gilt dann wieder, was ohnehin gelten wuerde.
                    eigene_stufe = (herkunft == "preset" if fuer
                                    else herkunft == "eigen")
                    if st.button(tx("Zurücksetzen"), key=f"zr_{gewaehlt}_{fuer}",
                                 disabled=not eigene_stufe,
                                 use_container_width=True):
                        if prompts.zuruecksetzen(gewaehlt, fuer):
                            st.success(tx("Zurückgesetzt."))
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
            with st.expander(tx(f'Konfiguration ({len(fehlend) + len(abweichend) + len(unbekannt)})')):
                if abweichend:
                    st.caption(tx("**Abweichend von der Vorlage** -- gewollt oder übersehen:"))
                    st.code(chr(10).join(abweichend), language="text")
                if fehlend:
                    st.caption(tx("**Nicht in der eigenen .env** -- es gilt der Standard aus dem Code:"))
                    st.code(chr(10).join(fehlend), language="text")
                if unbekannt:
                    st.caption(tx("**Nur in der eigenen .env** -- veraltet oder aus der Vorlage verschwunden:"))
                    st.code(chr(10).join(unbekannt), language="text")
