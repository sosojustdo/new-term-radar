"""Signal ④ (optional): queries your own site got impressions for, for the first time.

Search Console, fresh data (about a day behind instead of three; the numbers are revised
later, which is fine for spotting). A query is new when it has impressions in the last
RECENT days and none in the BEFORE days ahead of them.

Set in config.json:

    "gsc": {"site": "sc-domain:example.com", "token_file": "gsc_token.json"}

`token_file` is a Google "authorized user" JSON holding client_id, client_secret and
refresh_token for the scope webmasters.readonly (what google-auth's
Credentials.to_json() writes; see the README). It is read from the config's directory,
or from the environment variable GSC_TOKEN_JSON when the file is missing (for CI).
Queries that use search operators (quotes, site:, -word) are dropped: those are tools
probing the results, not people.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import date, timedelta

from . import UA

LAG_DAYS = 1
RECENT, BEFORE = 3, 60
MIN_IMPRESSIONS = 5
TOP = 30
ROW_LIMIT = 25000
_OPERATOR = re.compile(r'"|\b(site|inurl|intitle|intext|filetype):|(^|\s)-\w|\*|\bOR\b')


def _token(cfg: dict) -> str:
    path = cfg["_dir"] / cfg["gsc"].get("token_file", "gsc_token.json")
    raw = path.read_text() if path.exists() else os.environ.get("GSC_TOKEN_JSON", "")
    if not raw:
        raise RuntimeError(f"no Search Console token: {path.name} or GSC_TOKEN_JSON")
    tok = json.loads(raw)
    body = urllib.parse.urlencode({"client_id": tok["client_id"], "client_secret": tok["client_secret"],
                                   "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"}).encode()
    req = urllib.request.Request(tok.get("token_uri") or "https://oauth2.googleapis.com/token", data=body,
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.load(res)["access_token"]


def _query(access: str, site: str, start: date, end: date, dimensions: list[str], fresh: bool,
           filters: list[dict] | None = None) -> list[dict]:
    body = {"startDate": str(start), "endDate": str(end), "dimensions": dimensions, "rowLimit": ROW_LIMIT}
    if fresh:
        body["dataState"] = "all"
    if filters:
        body["dimensionFilterGroups"] = [{"filters": filters}]
    url = f"https://www.googleapis.com/webmasters/v3/sites/{urllib.parse.quote(site, safe='')}/searchAnalytics/query"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {access}", "Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as res:
        rows = json.load(res).get("rows", [])
    return [{**dict(zip(dimensions, r["keys"])), "impressions": int(r["impressions"]), "clicks": int(r["clicks"]),
             "position": round(float(r.get("position") or 0), 1)}
            for r in rows if not _OPERATOR.search(r["keys"][0])]


def _re2(text: str) -> str:
    """A literal for Search Console's RE2 filter (Python's re.escape also escapes spaces, which RE2 refuses)."""
    return re.sub(r"([\\.^$|?*+()\[\]{}])", r"\\\1", text)


def positions(cfg: dict, phrases: list[str], today: date, days: int = 28) -> dict[str, dict]:
    """{query: {"position", "impressions", "clicks", "page"}} for these exact queries over the last
    `days` days, all countries and devices, in one call. A query on several of your pages is
    read on the one with the most impressions; impressions and clicks are the query's total."""
    access = _token(cfg)
    end = today - timedelta(days=LAG_DAYS)
    expr = "^(" + "|".join(_re2(p.lower()) for p in phrases) + ")$"
    rows = _query(access, cfg["gsc"]["site"], end - timedelta(days=days - 1), end, ["query", "page"], True,
                  [{"dimension": "query", "operator": "includingRegex", "expression": expr}])
    out: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: -r["impressions"]):
        q = out.setdefault(r["query"].lower(), {"position": r["position"], "page": r["page"], "impressions": 0, "clicks": 0})
        q["impressions"] += r["impressions"]
        q["clicks"] += r["clicks"]
    return out


def fresh_queries(recent: list[dict], before: list[dict]) -> list[dict]:
    """Queries in `recent` (query, page rows) that `before` never saw, summed per query."""
    seen = {r["query"] for r in before}
    fresh: dict[str, dict] = {}
    for r in recent:
        if r["query"] in seen:
            continue
        f = fresh.setdefault(r["query"], {"query": r["query"], "impressions": 0, "clicks": 0, "page": r["page"]})
        f["impressions"] += r["impressions"]
        f["clicks"] += r["clicks"]
    return sorted(fresh.values(), key=lambda f: -f["impressions"])


def gsc_new(cfg: dict) -> dict:
    site = cfg["gsc"].get("site")
    if not site:
        return {"off": True}
    access = _token(cfg)
    end = date.today() - timedelta(days=LAG_DAYS)
    start = end - timedelta(days=RECENT - 1)
    recent = _query(access, site, start, end, ["query", "page"], fresh=True)
    before = _query(access, site, start - timedelta(days=BEFORE), start - timedelta(days=1), ["query"], fresh=False)
    fresh = fresh_queries(recent, before)
    return {"window": f"{start}..{end}", "total_new": len(fresh), "min_impressions": MIN_IMPRESSIONS,
            "queries": [f for f in fresh if f["impressions"] >= MIN_IMPRESSIONS][:TOP]}
