"""The local time of the installation, and a calendar for the model.

A container runs in UTC unless told otherwise, and a language model has
no clock at all. Both showed: appointments landed an hour off, and an
invitation for a Tuesday was announced as a Friday. Every place that
needs "today" or a weekday takes it from here:

    zone()            the time zone (TIMEZONE, default Europe/Berlin)
    now() / today()   in that zone
    calendar_block()  today, the time, and the weekdays of the weeks
                      around it -- part of every system prompt, so the
                      model reads weekdays instead of computing them
    weekday(d)        "Di" / "Tue" for a date
"""
import datetime
import os

try:
    import zoneinfo
except ImportError:          # Python < 3.9
    zoneinfo = None

DEFAULT_ZONE = "Europe/Berlin"

WEEKDAYS = {"de": ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
                   "Samstag", "Sonntag"),
            "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                   "Saturday", "Sunday")}
SHORT = {"de": ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"),
         "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")}

# Weeks shown before and after the current one.
WEEKS_BEFORE = 1
WEEKS_AFTER = 5


def zone_name():
    return (os.getenv("TIMEZONE") or DEFAULT_ZONE).strip()


def zone():
    """A tzinfo for TIMEZONE; UTC if the name is unknown."""
    if zoneinfo is None:
        return datetime.timezone.utc
    try:
        return zoneinfo.ZoneInfo(zone_name())
    except Exception:
        try:
            return zoneinfo.ZoneInfo(DEFAULT_ZONE)
        except Exception:
            return datetime.timezone.utc


def as_utc(value):
    """An aware time as a plain datetime in UTC.

    Exchange hands out EWSDateTime, whose astimezone() refuses
    datetime.timezone.utc ("must be of type EWSTimeZone"). Going through
    the timestamp works for every aware datetime.
    """
    return datetime.datetime.fromtimestamp(value.timestamp(), datetime.timezone.utc)


def now():
    return datetime.datetime.now(zone())


def today():
    return now().date()


def weekday(day, lang="de"):
    return SHORT.get(lang, SHORT["de"])[day.weekday()]


def calendar_block(lang="de", at=None):
    """Today, the time and a day table, as a block for the system prompt."""
    at = at or now()
    day = at.date()
    long_names = WEEKDAYS.get(lang, WEEKDAYS["de"])
    short = SHORT.get(lang, SHORT["de"])
    monday = day - datetime.timedelta(days=day.weekday())
    first = monday - datetime.timedelta(weeks=WEEKS_BEFORE)
    lines = []
    for w in range(WEEKS_BEFORE + 1 + WEEKS_AFTER):
        start = first + datetime.timedelta(weeks=w)
        week = start.isocalendar()[1]
        cells = []
        for d in range(7):
            x = start + datetime.timedelta(days=d)
            cell = f"{short[d]} {x:%d.%m.%Y}"
            cells.append(f"[{cell}]" if x == day else cell)
        label = "KW" if lang == "de" else "Week"
        lines.append(f"{label} {week:02d}: " + " | ".join(cells))
    if lang == "de":
        head = (f"Heute ist {long_names[day.weekday()]}, der {day:%d.%m.%Y}, "
                f"{at:%H:%M} Uhr ({zone_name()}). Wochentage nicht selbst "
                f"ausrechnen, sondern aus dieser Tabelle ablesen "
                f"(heute in eckigen Klammern):")
    else:
        head = (f"Today is {long_names[day.weekday()]}, {day:%Y-%m-%d}, "
                f"{at:%H:%M} ({zone_name()}). Do not compute weekdays; read "
                f"them from this table (today in brackets):")
    return "<kalender>\n" + head + "\n" + "\n".join(lines) + "\n</kalender>\n"
