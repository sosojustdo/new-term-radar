"""Signal ⑩: who already earns, and who just started paying for attention (weekly, GoAnyAPI).

- Portfolios: a site that earns from ads names its AdSense publisher ID in its ads.txt, and GoAnyAPI
  lists the other domains that use the same ID (3 credits each way). One proven tool site leads
  to the rest of its owner's sites, each a niche someone already makes money in: one AI tools
  directory's ID also ran a coloring-page site and a song-meaning site. The sites asked about are
  the tool sites already on page one for the day's terms worth acting on (strongest first), then
  the paying products of ⑥
  and ⑧, at most `portfolio_sites`. Brand-new sites rarely show an AdSense ID yet: on 2026-10-15
  ⑥'s and ⑧'s twelve gave none.
- New advertisers: who runs Google ads for each of `ad_terms` (Ads Transparency, 4 credits a
  term). An advertiser not seen before on a term has just decided the term is worth money.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from . import goanyapi, sellers, snap
from .i18n import t


def sisters(domain: str) -> tuple[str, list[str], int]:
    """(publisher ID, the other domains on it, cost); ("", [], cost) when the site shows no AdSense ID."""
    data, cost = goanyapi.call("adsense", domain=domain)
    ids = (data.get("publisherIds") or {}).get("direct") or []
    if not ids:
        return "", [], cost
    more, spent = goanyapi.call("adsense", pubId=ids[0])
    return ids[0], [d for d in more.get("domains") or [] if d.lower() != domain.lower()], cost + spent


def is_network(others: list[str], c: dict) -> bool:
    """One ID on more than `max_sisters` sites is a media group or an ad network, not a person's sites
    (2026-10-15: tomshardware.com's ID held 34 Future plc titles, spiceworks.com's hundreds of wikis and papers)."""
    return len(others) > c["max_sisters"]


def portfolios(c: dict, sites: list[str], seen: dict[str, str], today: str) -> tuple[list[dict], int, list[str]]:
    rows, cost, errors = [], 0, []
    for site in list(dict.fromkeys(sites))[:c["portfolio_sites"]]:
        try:
            pub, others, spent = sisters(site)
        except goanyapi.GoAnyError as exc:
            errors.append(f"adsense {site}: {exc}")
            continue
        cost += spent
        if is_network(others, c):
            errors.append(f"adsense {site}: {pub} is on {len(others)} sites, a network")
            continue
        fresh = [d for d in others if f"pub:{d}" not in seen]
        for d in fresh:
            seen[f"pub:{d}"] = today
        if fresh:
            rows.append({"site": site, "pub": pub, "sisters": fresh})
    return rows, cost, errors


def new_advertisers(c: dict, seen: dict[str, str], today: str) -> tuple[list[dict], int, list[str]]:
    rows, cost, errors = [], 0, []
    for term in c["ad_terms"]:
        try:
            names, spent = goanyapi.advertisers(term)
        except goanyapi.GoAnyError as exc:
            errors.append(f"ads {term}: {exc}")
            continue
        cost += spent
        first = not any(k.startswith(f"ad:{term}:") for k in seen)
        fresh = [n for n in names if f"ad:{term}:{n.lower()}" not in seen]
        for n in fresh:
            seen[f"ad:{term}:{n.lower()}"] = today
        if fresh and not first:
            rows.append({"term": term, "advertisers": fresh})
    return rows, cost, errors


def money(cfg: dict, state: Path, sites: list[str], today: date | None = None) -> dict:
    """`sites`: the paying products' domains of this week's ⑥ and ⑧."""
    c = cfg["money"]
    today_s = (today or date.today()).isoformat()
    if not goanyapi.key():
        return {"no_key": True, "portfolios": [], "advertisers": [], "terms": [], "errors": [], "cost_micros": 0}
    path = state / "money.json.gz"
    seen: dict[str, str] = snap.load(path) or {}
    folios, cost, errors = portfolios(c, sites, seen, today_s)
    ads, spent, failed = new_advertisers(c, seen, today_s)
    snap.save(path, seen)
    terms = [{"term": sellers.term_of(d, ""), "recent": 1, "about": (f"https://{d}/", ""),
              "examples": [t("money_sister_ex", site=r["site"], pub=r["pub"])], "note": t("note_sister", site=r["site"])}
             for r in folios for d in r["sisters"]]
    terms += [{"term": n.lower(), "recent": 1, "examples": [t("money_ad_ex", term=r["term"])], "note": t("note_advertiser", term=r["term"])}
              for r in ads for n in r["advertisers"] if "." not in n]       # a company name, not a bare domain
    return {"portfolios": folios, "advertisers": ads, "terms": terms, "errors": errors + failed, "cost_micros": cost + spent}
