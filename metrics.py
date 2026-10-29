"""Counters in the Prometheus text format, for /metrics.

    locanoto_llm_calls_total{task}            calls to the model endpoints
    locanoto_llm_errors_total{task}
    locanoto_llm_rate_limited_total{task}     answers 429/503
    locanoto_llm_waited_seconds_total{task}   time spent waiting them out
    locanoto_llm_seconds_total{task}          time in model calls
    locanoto_llm_in_flight{task}              calls running right now
    locanoto_http_requests_total{route,status}
    locanoto_http_seconds_total{route}
    locanoto_jobs{name,state}                 (with DATABASE_URL)

Per process: Prometheus scrapes every pod and adds them up. No user names,
no questions, no file names -- only counts per task and route.
"""
import threading

import database
import llm

_http = {}
_lock = threading.Lock()


def record_request(route, status, seconds):
    with _lock:
        n = _http.setdefault((route, status), [0, 0.0])
        n[0] += 1
        n[1] += seconds


def _label(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"')


def render():
    lines = []

    def metric(name, kind, help_, rows):
        lines.append(f"# HELP {name} {help_}")
        lines.append(f"# TYPE {name} {kind}")
        for labels, value in rows:
            inner = ",".join(f'{k}="{_label(v)}"' for k, v in labels.items())
            lines.append(f"{name}{{{inner}}} {value}")

    stats = {t: dict(s) for t, s in llm.STATS.items()}
    for key, kind, help_ in (
            ("calls", "counter", "Calls to model endpoints."),
            ("errors", "counter", "Failed model calls."),
            ("rate_limited", "counter", "Answers 429/503 from model endpoints."),
            ("waited_seconds", "counter", "Seconds spent waiting out rate limits."),
            ("seconds", "counter", "Seconds spent in model calls."),
            ("in_flight", "gauge", "Model calls running now.")):
        suffix = "" if kind == "gauge" else "_total"
        metric(f"locanoto_llm_{key}{suffix}", kind, help_,
               [({"task": t}, s[key]) for t, s in sorted(stats.items())])
    with _lock:
        http = dict(_http)
    metric("locanoto_http_requests_total", "counter", "HTTP requests.",
           [({"route": r, "status": s}, n[0])
            for (r, s), n in sorted(http.items())])
    by_route = {}
    for (r, _s), n in http.items():
        by_route[r] = by_route.get(r, 0.0) + n[1]
    metric("locanoto_http_seconds_total", "counter",
           "Seconds spent answering HTTP requests.",
           [({"route": r}, round(v, 3)) for r, v in sorted(by_route.items())])
    if database.active():
        try:
            rows = database.connect().execute(
                "SELECT name, state, count(*) FROM job GROUP BY 1, 2").fetchall()
            metric("locanoto_jobs", "gauge", "Background jobs by state.",
                   [({"name": n, "state": s}, c) for n, s, c in rows])
        except Exception:
            pass
    return "\n".join(lines) + "\n"
