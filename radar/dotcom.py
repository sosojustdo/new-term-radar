"""Is the exact-match .com still free? For the prioritized rows, a free RDAP lookup.

RDAP is the registry's own answer (Verisign runs .com), free and keyless: 200 = registered,
with its registration date; 404 = not registered. Not registered is not the same as for sale
at the usual price: registrars hold some names back or sell them as premium, so check at a
registrar before counting on it. A phrase of several words is looked up joined and
hyphenated ("synthid detector": synthiddetector.com, synthid-detector.com). Names come first,
up to `max_rows` rows a run; a phrase that is not plain ASCII is left out.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from . import UA

RDAP = "https://rdap.verisign.com/com/v1/domain/"
TIMEOUT = 15
LABEL_MAX = 63


def names(phrase: str) -> list[str]:
    """The .com names a phrase reads as: joined, then hyphenated when it has several words."""
    if not phrase.isascii():
        return []
    words = re.findall(r"[a-z0-9]+", phrase.lower())
    out = ["".join(words), "-".join(words)] if len(words) > 1 else words
    return [f"{w}.com" for w in out if 1 <= len(w) <= LABEL_MAX]


def _get(url: str) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rdap+json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            return res.status, json.load(res)
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def lookup(domain: str) -> dict:
    """{"domain", "taken", "registered"}; raises on any answer but 200 and 404."""
    status, body = _get(RDAP + domain)
    if status == 404:
        return {"domain": domain, "taken": False}
    if status != 200:
        raise RuntimeError(f"RDAP answered {status}")
    reg = next((e.get("eventDate", "")[:10] for e in body.get("events") or [] if e.get("eventAction") == "registration"), None)
    return {"domain": domain, "taken": True, "registered": reg}


def assess(rows: list[dict], cfg: dict) -> tuple[int, list[str]]:
    """Adds `dot_com` = [{"domain", "taken", "registered"}] to the prioritized rows. (cost, errors)"""
    c = cfg.get("dot_com") or {}
    if not c.get("enabled") or not rows:
        return 0, []
    errors = []
    for r in sorted(rows, key=lambda r: r.get("kind") != "name")[:c["max_rows"]]:
        found = []
        for domain in names(r["phrase"]):
            try:
                found.append(lookup(domain))
            except (RuntimeError, OSError, ValueError) as exc:
                errors.append(f"{domain} (.com): {exc}")
        if found:
            r["dot_com"] = found
    return 0, errors
