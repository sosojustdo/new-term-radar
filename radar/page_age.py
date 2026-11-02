"""How old the sites on page one are (0.6, recorded only): whether new sites get onto it.

A page one where sites registered in the last half year rank is open to a new site, whatever its difficulty says;
one held by sites years old is not, for now. For each row the radar reads page one for (competition.py), each
result's domain is dated by its registration, asked of RDAP, the registries' public record (rdap.org, one request
every RDAP_GAP seconds, a failure asked once more, kept DAYS_KEPT days; a registry with no RDAP record leaves the
domain undated). And the readings of a name are compared: the results that entered the top 10 since the reading
before, up to SINCE_MAX days back.

Recorded in report.json as each row's `page_age`, not shown and not used in any decision until later rankings show
it says something. Free: RDAP asks nothing for it.
"""
from __future__ import annotations

import http.client
import json
import threading
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from . import UA, snap

RDAP = "https://rdap.org/domain/"
RDAP_GAP = 0.5          # seconds between RDAP requests: a burst is refused
RETRY_PAUSE = 5
TIMEOUT = 25
DAYS_KEPT = 30          # a registration day does not change
YOUNG_DAYS = 183
SINCE_MAX = 7           # an earlier reading this many days back at most is compared
TWO_LABEL = {"co.uk", "org.uk", "com.au", "com.br", "co.jp", "com.cn", "co.in", "com.tw", "com.hk", "co.kr", "com.mx",
             "com.sg", "co.nz", "co.za", "com.tr", "co.id", "com.vn", "com.my", "com.ph"}
_spacing = threading.Lock()
_last = [0.0]


def registrable(domain: str) -> str:
    """docs.example.co.uk -> example.co.uk: the name a registry knows."""
    labels = domain.lower().removeprefix("www.").split(".")
    return ".".join(labels[-3:] if ".".join(labels[-2:]) in TWO_LABEL else labels[-2:])


def ask(domain: str) -> tuple[str, str]:
    """(day, "ok"); ("", "none") when the registry keeps no record; ("", "failed") when no answer came, twice."""
    req = urllib.request.Request(RDAP + domain, headers={"User-Agent": UA, "Accept": "application/rdap+json"})
    for attempt in range(2):
        with _spacing:                       # held while waiting: the requests leave one at a time
            time.sleep(max(0.0, _last[0] + RDAP_GAP - time.monotonic()))
            _last[0] = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
                events = json.load(res).get("events") or []
            day = next(((e.get("eventDate") or "")[:10] for e in events if e.get("eventAction") == "registration"), "")
            return (day, "ok") if day else ("", "none")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return "", "none"
        except (OSError, ValueError, http.client.HTTPException):
            pass
        if not attempt:
            time.sleep(RETRY_PAUSE)
    return "", "failed"


def registered(domains: list[str], state: Path, today: date) -> dict[str, str]:
    """{domain: registration day or ""}, from state/registered.json.gz when asked in the last DAYS_KEPT days."""
    path = state / "registered.json.gz"
    held: dict[str, dict] = snap.load(path) or {}
    out = {}
    for d in dict.fromkeys(domains):
        got = held.get(d)
        if not got or (today - date.fromisoformat(got["asked"])).days > DAYS_KEPT:
            day, status = ask(d)
            if status == "failed":
                out[d] = ""
                continue
            held[d] = got = {"day": day, "asked": today.isoformat()}
        out[d] = got["day"]
    snap.save(path, held)
    return out


def ages(results: list[dict], born: dict[str, str], today: date) -> dict:
    """{"dated", "young", "young_sites": [{"domain", "registered", "position"}], "newest"} for one page one."""
    rows = [(r, born.get(registrable(r["domain"])) or "") for r in results]
    dated = [(r, d) for r, d in rows if d]
    young = [{"domain": r["domain"], "registered": d, "position": r.get("position")} for r, d in dated
             if (today - date.fromisoformat(d)).days <= YOUNG_DAYS]
    return {"dated": len(dated), "young": len(young), "young_sites": young,
            "newest": max((d for _, d in dated), default="")}


def entered(phrase: str, urls: list[str], held: dict, today: date) -> dict:
    """{"since", "urls"}: the results not in the reading of `phrase` before, when that is SINCE_MAX days back at most;
    updates `held` with this reading."""
    before = held.get(phrase)
    held[phrase] = {"day": today.isoformat(), "urls": urls}
    if not before or before["day"] == today.isoformat() or (today - date.fromisoformat(before["day"])).days > SINCE_MAX:
        return {"since": "", "urls": []}
    return {"since": before["day"], "urls": [u for u in urls if u not in set(before["urls"])]}


def record(rows: list[dict], pages: dict[str, dict], state: Path, today: date | None = None) -> None:
    """Sets each row's `page_age` for the rows whose page one was read: ages() and entered()."""
    today = today or date.today()
    read = [r for r in rows if pages.get(r["phrase"])]
    if not read:
        return
    born = registered([registrable(x["domain"]) for r in read for x in pages[r["phrase"]]["results"] if x["domain"]],
                      state, today)
    path = state / "page_one.json.gz"
    held: dict[str, dict] = snap.load(path) or {}
    for r in read:
        results = pages[r["phrase"]]["results"]
        r["page_age"] = {**ages(results, born, today), "entered": entered(r["phrase"], [x["url"] for x in results], held, today)}
    snap.save(path, held)
