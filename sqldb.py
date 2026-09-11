"""Lesender Zugriff auf eine SQL-Server-Datenbank fuer Text-to-SQL.

Das Sprachmodell formuliert die Abfrage selbst. Es bekommt dafuer das Schema,
das dieses Modul aus der Datenbank ausliest (INFORMATION_SCHEMA) -- die
Struktur muss also nicht gepflegt werden und bleibt automatisch aktuell.

Sicherheit
----------
Eine vom Modell erzeugte Abfrage ist nicht vertrauenswuerdig. Sie kann auf
einem Missverstaendnis beruhen oder auf einer Anweisung, die jemand in ein
Dokument geschrieben hat. Deshalb greifen drei voneinander unabhaengige
Schranken:

1. Das Datenbankkonto sollte nur Leserechte besitzen (db_datareader). Das ist
   die einzige Schranke, die auch dann haelt, wenn die anderen versagen, und
   sie laesst sich nur auf dem Server setzen -- nicht hier.
2. pruefe_abfrage() laesst ausschliesslich eine einzelne SELECT- oder
   WITH-Anweisung durch und lehnt alles andere ab.
3. Zeilenzahl und Laufzeit sind begrenzt, damit eine unbedachte Abfrage die
   Datenbank nicht belastet.
"""
import os
import re

import paths
import sqlpruefung

# --- KONFIGURATION ---
SQL_SERVER = os.getenv("SQL_SERVER", "").strip()
SQL_USER = os.getenv("SQL_USER", "").strip()
SQL_PASS = os.getenv("SQL_PASS", "")
SQL_DB = os.getenv("SQL_DB", "").strip()

# Port der Datenbank. Weicht vom Standard ab, wenn die Verbindung ueber
# einen Weiterleiter laeuft -- etwa den VPN-Beiwagen, der den Port des
# Kundennetzes im eigenen Netz anbietet.
SQL_PORT = paths.env_int("SQL_PORT", 1433)

# Optional: nur diese Tabellen an das Modell geben. Kommagetrennt, ohne
# Angabe wird das gesamte Schema uebermittelt.
SQL_TABLES = [t.strip() for t in os.getenv("SQL_TABLES", "").split(",") if t.strip()]

# Freitext-Hinweis zum Fachgebiet, der mit dem Schema an das Modell geht.
# Spalten- und Tabellennamen allein sagen nicht, welche Tabelle den aktuellen
# Stand fuehrt und welche Altdaten enthaelt, oder was ein Statuscode bedeutet.
# Genau daran scheitern erzeugte Abfragen am haeufigsten.
SQL_HINWEIS = os.getenv("SQL_HINWEIS", "").strip()

SQL_TIMEOUT = paths.env_int("SQL_TIMEOUT", 20)
SQL_MAX_ROWS = paths.env_int("SQL_MAX_ROWS", 200)

# Obergrenze fuer die Schemabeschreibung im Prompt. Ein grosses Schema wuerde
# sonst den Kontext fuellen, der fuer die Dokumente gebraucht wird.
SQL_SCHEMA_MAX_CHARS = paths.env_int("SQL_SCHEMA_MAX_CHARS", 12000)

MARKER_KEINE_ABFRAGE = "KEINE_ABFRAGE"


# --- EIN ZUGANG JE RAUM ---
#
# Die Werte aus der Umgebung sind ab hier die VORGABE, nicht mehr die
# Wahrheit. Ein Raum kann ein eigenes Datenbankkonto mitbringen
# (sqlquellen.py); dann gelten dessen Angaben, und was es nicht
# mitbringt -- meist Server, Port und Datenbank -- kommt weiter aus
# der Umgebung.
#
# Warum das mehr ist als Bequemlichkeit: mit dem Konto des Raums kommt
# auch das SCHEMA mit dessen Rechten. Das Sprachmodell sieht dann nur
# Tabellen, die dieses Konto lesen darf, und kann gar keine Abfrage
# auf etwas formulieren, das ohnehin verweigert wuerde.


def _wert(zugang, feld, vorgabe):
    if zugang and zugang.get(feld) not in (None, ""):
        return zugang[feld]
    return vorgabe


def ist_konfiguriert(zugang=None):
    """True, wenn alle vier Verbindungsangaben zusammenkommen."""
    return all([_wert(zugang, "server", SQL_SERVER),
                _wert(zugang, "benutzer", SQL_USER),
                _wert(zugang, "passwort", SQL_PASS),
                _wert(zugang, "datenbank", SQL_DB)])


# --- PRUEFUNG DER ERZEUGTEN ABFRAGE ---
#
# Die Regeln stehen in sqlpruefung.py, weil sie nicht nur fuer den
# SQL-Server gelten: eingelesene Tabellendateien werden mit derselben
# Kette geprueft. Zwei Kopien eines Sicherheitsfilters waeren die Art von
# Verdopplung, bei der eine Haelfte irgendwann nachgezogen wird und die
# andere nicht.
bereinige = sqlpruefung.bereinige
pruefe_abfrage = sqlpruefung.pruefe_abfrage
als_tabelle = sqlpruefung.als_tabelle


def begrenze_zeilen(sql, max_rows=None):
    """Setzt ein TOP, falls die Abfrage keines hat."""
    return sqlpruefung.begrenze_zeilen(sql, max_rows or SQL_MAX_ROWS, "tsql")


# --- VERBINDUNG ---

def _verbinde(zugang=None):
    import pymssql  # bewusst lokal: ohne SQL-Nutzung wird das Paket nie geladen
    return pymssql.connect(
        server=_wert(zugang, "server", SQL_SERVER),
        port=int(_wert(zugang, "port", SQL_PORT) or SQL_PORT),
        user=_wert(zugang, "benutzer", SQL_USER),
        password=_wert(zugang, "passwort", SQL_PASS),
        database=_wert(zugang, "datenbank", SQL_DB),
        timeout=SQL_TIMEOUT, login_timeout=SQL_TIMEOUT,
        as_dict=False,
    )


def lade_schema(zugang=None):
    """Liest Tabellen und Spalten aus INFORMATION_SCHEMA.

    Rueckgabe: Text in der Form
        schema.tabelle(spalte typ, spalte typ, ...)
    Eine Zeile je Tabelle -- kompakt genug fuer den Prompt und fuer ein
    Sprachmodell gut lesbar.
    """
    if not ist_konfiguriert(zugang):
        return ""

    sql = """
        SELECT c.TABLE_SCHEMA, c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS c
        JOIN INFORMATION_SCHEMA.TABLES t
          ON t.TABLE_SCHEMA = c.TABLE_SCHEMA AND t.TABLE_NAME = c.TABLE_NAME
        WHERE t.TABLE_TYPE IN ('BASE TABLE', 'VIEW')
        ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION
    """

    con = _verbinde(zugang)
    try:
        cur = con.cursor()
        cur.execute(sql)
        zeilen = cur.fetchall()
    finally:
        con.close()

    tabellen = {}
    for schema, tabelle, spalte, typ in zeilen:
        voll = f"{schema}.{tabelle}"
        if SQL_TABLES and tabelle not in SQL_TABLES and voll not in SQL_TABLES:
            continue
        tabellen.setdefault(voll, []).append(f"{spalte} {typ}")

    teile = [f"{name}({', '.join(spalten)})" for name, spalten in tabellen.items()]
    text = "\n".join(teile)

    if len(text) > SQL_SCHEMA_MAX_CHARS:
        gekuerzt, laenge = [], 0
        for t in teile:
            if laenge + len(t) + 1 > SQL_SCHEMA_MAX_CHARS:
                break
            gekuerzt.append(t)
            laenge += len(t) + 1
        text = "\n".join(gekuerzt) + (
            f"\n-- gekuerzt, {len(teile) - len(gekuerzt)} weitere Tabellen nicht "
            "aufgefuehrt. Mit SQL_TABLES eingrenzen.")
    return text


def formuliere(client, modell, frage, schema, verlauf="", zeitlimit=None):
    """Laesst das Sprachmodell eine Abfrage zu der Frage formulieren.

    Rueckgabe: die bereinigte Abfrage, oder "" wenn das Modell die Frage
    nicht durch die Datenbank beantwortbar sieht. Die Vorlage steht in
    sql_prompt.txt -- wie system_prompt.txt und search_prompt.txt, damit
    sich die Formulierung ohne Codeaenderung anpassen laesst.

    Geprueft wird hier nichts. Das macht pruefe_abfrage() in fuehre_aus(),
    und zwar unabhaengig davon, wer die Abfrage erzeugt hat.
    """
    with open(paths.resolve_prompt("sql_prompt.txt"),
              "r", encoding="utf-8") as f:
        vorlage = f.read()

    hinweis = ("Hinweise zum Fachgebiet:\n" + SQL_HINWEIS + "\n"
               if SQL_HINWEIS else "")
    prompt = (vorlage
              .replace("{SCHEMA}", schema)
              .replace("{HINWEIS}", hinweis)
              .replace("{HISTORY}", verlauf)
              .replace("{FRAGE}", frage)
              .replace("{MARKER}", MARKER_KEINE_ABFRAGE))

    roh = (client.chat.completions.create(
        model=modell,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        timeout=zeitlimit if zeitlimit is not None else SQL_TIMEOUT,
    ).choices[0].message.content or "")

    if MARKER_KEINE_ABFRAGE in roh.upper():
        return ""
    return bereinige(roh)


def fuehre_aus(sql, max_rows=None, zugang=None):
    """Fuehrt eine gepruefte Abfrage aus.

    Rueckgabe: (spalten, zeilen). Loest ValueError aus, wenn die Pruefung
    fehlschlaegt -- die Abfrage erreicht die Datenbank dann nicht.
    """
    ok, grund = pruefe_abfrage(sql)
    if not ok:
        raise ValueError(f"Abfrage abgelehnt: {grund}")

    sql = begrenze_zeilen(sql, max_rows)
    max_rows = max_rows or SQL_MAX_ROWS

    con = _verbinde(zugang)
    try:
        cur = con.cursor()
        cur.execute(sql)
        spalten = [d[0] for d in (cur.description or [])]
        zeilen = cur.fetchmany(max_rows)
    finally:
        con.close()
    return spalten, list(zeilen)
