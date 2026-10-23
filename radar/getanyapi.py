"""Optional X source: AnyAPI (getanyapi.com), used for ① x instead of AIsa when
GETANYAPI_API_KEY is set. twitter.user_posts is $0.00045 an account on the cheapest lane.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import UA

BASE = os.environ.get("GETANYAPI_BASE_URL", "https://api.getanyapi.com") + "/v1/run/"
TIMEOUT = 90
WORKERS = 6


SPENT = [0]         # micro-USD billed by AnyAPI this process, for the report's cost line
_LOCK = threading.Lock()


class AnyApiError(RuntimeError):
    pass


def key() -> str:
    return os.environ.get("GETANYAPI_API_KEY", "").strip()


def run(sku: str, body: dict) -> tuple[dict, int]:
    """One call. Returns (output, cost in micro-USD)."""
    req = urllib.request.Request(BASE + sku, data=json.dumps(body).encode(), method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key()}", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            data = json.load(res)
    except urllib.error.HTTPError as exc:
        raise AnyApiError(f"HTTP {exc.code}: {' '.join(exc.read().decode('utf-8', 'replace').split())[:200]}") from exc
    except (OSError, ValueError) as exc:
        raise AnyApiError(f"{type(exc).__name__}: {exc}") from exc
    cost = round(float(data.get("costUsd") or 0) * 1_000_000)
    with _LOCK:
        SPENT[0] += cost
    return data.get("output") or {}, cost


def user_posts(handles: list[str]) -> tuple[dict[str, list[dict]], int, list[str]]:
    """Recent posts per handle, in the shape sources.x_new reads: {handle: [{text, likes,
    url, created}]}. A handle that failed is left out and its error returned."""
    def one(h: str):
        for attempt in range(2):    # one retry: a few accounts fail now and then and answer the second time
            try:
                out, cost = run("twitter.user_posts", {"handle": h})
                break
            except AnyApiError as exc:
                if attempt:
                    return h, None, 0, f"@{h}: {exc}"
        posts = [{"text": tw.get("text") or "", "likes": int(tw.get("likes") or 0), "url": tw.get("url", ""),
                  "created": datetime.fromtimestamp(tw["createdUtc"], timezone.utc) if tw.get("createdUtc") else None}
                 for tw in ((out.get("data") or {}).get("tweets") or [])]
        return h, posts, cost, None

    data, cost, errors = {}, 0, []
    with ThreadPoolExecutor(WORKERS) as pool:
        for h, posts, c, err in pool.map(one, handles):
            cost += c
            if err:
                errors.append(err)
            else:
                data[h] = posts
    return data, cost, errors


def tweet_search(query: str, query_type: str = "Top") -> tuple[list[dict], int]:
    """X advanced search, one page. Posts as {text, likes, by, url}."""
    out, cost = run("twitter.search", {"query": query, "queryType": query_type})
    return [{"text": tw.get("text") or "", "likes": int(tw.get("likeCount") or 0),
             "by": tw.get("authorUsername") or "?", "url": tw.get("url", "")}
            for tw in ((out.get("data") or {}).get("items") or [])], cost


def search_volume(keywords: list[str], location: int, language: str = "en") -> tuple[dict[str, dict], int]:
    """{keyword: {"volume", "month"}} from Google Ads, one call (up to 1,000 keywords, $0.108)."""
    kws = [k for k in keywords if 3 <= len(k) <= 80]
    if not kws:
        return {}, 0
    out, cost = run("seo.search_volume", {"keywords": kws, "location": location, "language": language})
    res = {}
    for r in (out.get("data") or {}).get("keywords") or []:
        ms = r.get("monthlySearches") or []
        last = max(ms, key=lambda m: (m.get("year", 0), m.get("month", 0))) if ms else None
        res[r["keyword"]] = {"volume": int(r.get("searchVolume") or 0),
                             "month": f"{last['year']}-{last['month']:02d}" if last else ""}
    return res, cost


def trends(keywords: list[str], timeframe: str = "3m", geo: str = "worldwide") -> tuple[list[list[tuple]], int]:
    """Google Trends interest over time: one [(day, value)] per keyword, in order, on one
    shared scale. Too little interest comes back as empty series, not an error."""
    out, cost = run("google.trends", {"keywords": keywords, "timeframe": timeframe, "geo": geo})
    by_kw = {s.get("keyword"): s.get("points") or [] for s in (out.get("data") or {}).get("series") or []}
    series = []
    for i, k in enumerate(keywords):
        pts = by_kw.get(k)
        if pts is None:     # fall back to position when the echo differs in case or spacing
            all_s = (out.get("data") or {}).get("series") or []
            pts = (all_s[i].get("points") or []) if i < len(all_s) else []
        series.append([(datetime.fromtimestamp(p["startUtc"], timezone.utc).date(), int(p.get("value") or 0)) for p in pts])
    return series, cost
