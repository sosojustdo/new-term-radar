"""What AI assistants recommend for a job people ask for (⑦), and which sites they cite.

For the ⑦ rows that have Google searches, up to `max_rows`, this asks each engine of `engines`
the job as a question (`prompt`, "What is the best tool to {job}?") and keeps who the answer
names and which sites it cites:

- chatgpt: the answer ChatGPT's own interface gives, with its web search (DataForSEO's LLM
  scraper): the brands it names (`brand_entities`, as written in the answer) and its sources;
- google: Google's AI Mode for the same question: it has no brand list, so the names are the
  bold ones that open its list items ("- **[Knowt AI PowerPoint Summarizer](…)** : …"), which is
  how it writes up the tools it recommends; and the sites its answer references. The names its
  references go by are not used: they include "Reddit".

An answer that names no tool is a gap a new tool can fill in AI search; the cited sites are the
pages AI search reads for the job, the ones to be listed on or compared against. One of your
sites (`yours.domains`, or the Search Console property) among them is marked. About $0.004 an
answer for either engine (October 2026); off by default: set `"enabled": true` to pay for it.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from . import aisa, yours

PATHS = {"chatgpt": "ai_optimization/chat_gpt/llm_scraper/live/advanced",
         "google": "serp/google/ai_mode/live/advanced"}
KEPT = 8
WORKERS = 3          # answers asked at once; each takes 10 to 60 seconds


def _host(domain: str | None) -> str:
    return re.sub(r"^www\.", "", (domain or "").lower())


def _unique(values) -> list[str]:
    return list(dict.fromkeys(v for v in values if v))[:KEPT]


def read_chatgpt(result: dict) -> dict:
    """Names as the answer writes them (the entity's title can be a category: "AI assistant" for ChatGPT)."""
    names = (re.sub(r"[*_`\[\]\\]", "", b.get("markdown") or b.get("title") or "").strip() for b in result.get("brand_entities") or [])
    return {"names": _unique(names), "sites": _unique(_host(s.get("domain")) for s in result.get("sources") or [])}


LISTED = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\*\*(.+?)\*\*", re.M)
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def listed_names(markdown: str) -> list[str]:
    """The bold names that open an answer's list items, links and code marks taken off."""
    return [LINK.sub(r"\1", m).strip(" :`") for m in LISTED.findall(markdown or "")]


def read_google(result: dict) -> dict:
    refs, names = [], []
    for item in result.get("items") or []:
        refs += item.get("references") or []
        names += listed_names(item.get("markdown") or "")
        for element in item.get("items") or []:
            refs += element.get("references") or []
    return {"names": _unique(names), "sites": _unique(_host(r.get("domain")) for r in refs)}


READ = {"chatgpt": read_chatgpt, "google": read_google}


def _ask(job: str, engine: str, c: dict) -> tuple[str, str, dict | None, int, str | None]:
    task = {"keyword": c["prompt"].format(job=job), "location_code": c["location_code"], "language_code": c["language_code"]}
    try:
        result, cost = aisa.rest(PATHS[engine], task)
    except aisa.AisaError as exc:
        return job, engine, None, 0, f"{job} ({engine}): {exc}"
    return job, engine, READ[engine](result), cost, None


def assess(rows: list[dict], cfg: dict) -> tuple[int, list[str]]:
    """Adds `ai` = {"prompt", "by": {engine: {"names", "sites"}}, "yours"} to the first `max_rows` rows. (cost, errors)"""
    c = cfg.get("ai_answers") or {}
    if not c.get("enabled") or not rows:
        return 0, []
    engines = [e for e in c["engines"] if e in PATHS]
    errors = [f"unknown engine: {e}" for e in c["engines"] if e not in PATHS]
    picked = {r["phrase"]: r for r in rows[:c["max_rows"]]}
    mine, cost = yours.own_domains(cfg), 0
    with ThreadPoolExecutor(WORKERS) as pool:
        for job, engine, got, spent, error in pool.map(lambda p: _ask(*p, c), [(j, e) for j in picked for e in engines]):
            cost += spent
            if error:
                errors.append(error)
                continue
            ai = picked[job].setdefault("ai", {"prompt": c["prompt"].format(job=job), "by": {}, "yours": False})
            ai["by"][engine] = got
            ai["yours"] |= any(yours.is_mine(s, mine) for s in got["sites"]) if mine else False
    return cost, errors
