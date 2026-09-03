"""Pruefung und Aufbereitung erzeugter SQL-Abfragen.

Eine vom Sprachmodell erzeugte Abfrage ist nicht vertrauenswuerdig. Sie kann
auf einem Missverstaendnis beruhen oder auf einer Anweisung, die jemand in
ein Dokument geschrieben hat. Was hier steht, ist die Schranke, die in
beiden Faellen greift -- unabhaengig davon, ob die Abfrage gegen einen
SQL-Server oder gegen eine eingelesene Tabellendatei laeuft.

Bewusst ein eigenes Modul: eine zweite Kopie dieser Regeln waere die Art
von Verdopplung, bei der eine Haelfte irgendwann nachgezogen wird und die
andere nicht.
"""
import re

# Anweisungen, die Daten oder Struktur veraendern, sowie alles, was den
# Server zu etwas anderem als Lesen bewegen kann.
_VERBOTEN = re.compile(
    r"\b("
    r"INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|RENAME|"
    r"GRANT|REVOKE|DENY|BACKUP|RESTORE|SHUTDOWN|RECONFIGURE|"
    r"EXEC|EXECUTE|OPENROWSET|OPENQUERY|OPENDATASOURCE|BULK|"
    r"WAITFOR|KILL|ATTACH|DETACH|PRAGMA|VACUUM"
    r")\b", re.IGNORECASE)

# Erweiterte und System-Prozeduren.
_VERBOTEN_PRAEFIX = re.compile(r"\b(xp_|sp_configure|sys\.sp_)", re.IGNORECASE)

# INTO ausserhalb von "INSERT INTO" erzeugt eine Tabelle (SELECT ... INTO x).
_SELECT_INTO = re.compile(r"\bINTO\b", re.IGNORECASE)


def _ohne_kommentare(sql):
    """Entfernt Kommentare, damit sie keine Schluesselwoerter verbergen."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def _ohne_zeichenketten(sql):
    """Ersetzt Zeichenketten, damit Wortmarken darin nicht anschlagen.

    'DROP' als Suchbegriff in einer WHERE-Bedingung ist zulaessig und darf
    die Pruefung nicht ausloesen.
    """
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def bereinige(sql):
    """Loest die Abfrage aus einem moeglichen Markdown-Block heraus."""
    if not sql:
        return ""
    sql = sql.strip()
    m = re.search(r"```(?:sql)?\s*(.+?)```", sql, flags=re.S | re.I)
    if m:
        sql = m.group(1)
    # Denk-Bloecke von Reasoning-Modellen
    sql = re.sub(r"<think>.*?</think>", " ", sql, flags=re.S | re.I)
    sql = re.sub(r"<think>.*", " ", sql, flags=re.S | re.I)
    return sql.strip().rstrip(";").strip()


def pruefe_abfrage(sql):
    """(True, "") wenn die Abfrage ausgefuehrt werden darf, sonst (False, Grund)."""
    if not sql or not sql.strip():
        return False, "leere Abfrage"

    # Kommentare werden nicht durchgelassen. Ein erzeugtes SELECT braucht
    # keine, und ihre Auswertung ist heikel: manche Dialekte erlauben
    # verschachtelte Blockkommentare. Wo diese Pruefung und die Datenbank
    # unterschiedlich erkennen, wo ein Kommentar endet, entsteht genau die
    # Luecke, die eine angehaengte zweite Anweisung braucht.
    if "--" in sql or "/*" in sql:
        return False, "Kommentare sind nicht zulaessig"

    kern = _ohne_zeichenketten(_ohne_kommentare(sql))

    # Genau eine Anweisung. Ein Semikolon mit Text danach deutet auf einen
    # angehaengten zweiten Befehl.
    if ";" in kern.strip().rstrip(";"):
        return False, "mehrere Anweisungen"

    if not re.match(r"(SELECT|WITH)\b", kern.lstrip(), re.IGNORECASE):
        return False, "beginnt nicht mit SELECT oder WITH"

    treffer = _VERBOTEN.search(kern)
    if treffer:
        return False, f"unzulaessiges Schluesselwort: {treffer.group(1).upper()}"

    treffer = _VERBOTEN_PRAEFIX.search(kern)
    if treffer:
        return False, f"unzulaessiger Aufruf: {treffer.group(1)}"

    if _SELECT_INTO.search(kern):
        return False, "SELECT ... INTO erzeugt eine Tabelle"

    return True, ""


def begrenze_zeilen(sql, max_rows, dialekt="tsql"):
    """Setzt eine Obergrenze, falls die Abfrage keine hat.

    Ohne Begrenzung koennte eine versehentlich weit gefasste Abfrage
    Millionen Zeilen zurueckliefern. T-SQL schreibt TOP an den Anfang,
    SQLite haengt LIMIT an -- deshalb der Dialekt.
    """
    if dialekt == "sqlite":
        if re.search(r"\bLIMIT\s+\d+", sql, re.IGNORECASE):
            return sql
        return f"{sql} LIMIT {max_rows}"

    if re.search(r"\bTOP\s*\(?\s*\d+", sql, re.IGNORECASE):
        return sql
    if re.search(r"\bOFFSET\b.*\bFETCH\b", sql, re.IGNORECASE | re.S):
        return sql
    # Nur beim ersten SELECT einsetzen; bei WITH bleibt die Abfrage
    # unberuehrt, dort sitzt das aeussere SELECT nicht am Anfang.
    if re.match(r"\s*SELECT\b", sql, re.IGNORECASE):
        return re.sub(r"(?i)^(\s*SELECT\s+)(DISTINCT\s+)?",
                      lambda m: f"{m.group(1)}{m.group(2) or ''}TOP {max_rows} ",
                      sql, count=1)
    return sql


def als_tabelle(spalten, zeilen, max_zeilen=50):
    """Formatiert ein Ergebnis als Markdown-Tabelle fuer den LLM-Kontext."""
    if not spalten:
        return "(kein Ergebnis)"
    if not zeilen:
        return "(Abfrage lieferte keine Zeilen)"

    aus = ["| " + " | ".join(str(s) for s in spalten) + " |",
           "|" + "|".join("---" for _ in spalten) + "|"]
    for zeile in zeilen[:max_zeilen]:
        werte = ["" if w is None else str(w).replace("\n", " ").replace("|", "\\|")
                 for w in zeile]
        aus.append("| " + " | ".join(werte) + " |")
    if len(zeilen) > max_zeilen:
        # Als eigene Zeile unter der Tabelle, nicht als Tabellenzeile: eine
        # Zeile mit zwei Zellen in einer Tabelle mit zwoelf Spalten ist
        # kaputtes Markdown. Und der Hinweis muss sagen, dass das Ergebnis
        # unvollstaendig ist -- sonst gibt das Modell die ersten Zeilen als
        # die vollstaendige Auskunft aus.
        aus.append("")
        aus.append(f"(Unvollstaendig: {len(zeilen)} Zeilen gefunden, "
                   f"{max_zeilen} davon dargestellt. Die Abfrage war zu weit "
                   f"gefasst -- diese Aufstellung ist keine vollstaendige "
                   f"Antwort.)")
    return "\n".join(aus)
