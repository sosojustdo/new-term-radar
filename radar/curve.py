"""The year behind a keyword: twelve months of Google Ads searches, as a curve and a word.

The volume lookup the keyword table already makes (usecases.volumes) carries each phrase's
monthly searches for the last twelve months, so this costs nothing. The newest month runs one
to two months behind today. Google Ads rounds small volumes into buckets (10, 20, 30, 40, 50,
70, 90, ...), so a phrase whose best month stays under MIN_PEAK gets the curve and no word:
its changes would be rounding.

- since: when the first three months are each under a tenth of the peak, the term is new
  within the year; `since` is the first month at a tenth of the peak. It goes with a word below.
- spiked: the peak lies two or more months before the newest month, is twice the median month
  or more, and the newest month is at half of it or less: a burst already past its top.
- falling: down to 60% of the peak or less since a peak two or more months back, or the last
  three months at 0.7x the three before or less.
- rising: the last three months at 1.3x the three before or more.
- steady otherwise.

`c3` and `c6` are the newest month against three and six months before it, in percent.
Measured on 2026-10-20: "claude skills" read spiked (90,500 in 2026-03, 18,100 in 2026-09),
"best claude skills" new since 2026-01 and falling (3,600 at its top, 1,900 now).
"""
from __future__ import annotations

from statistics import mean, median

MIN_PEAK = 50
BARS = "▁▂▃▄▅▆▇█"
MIN_MONTHS = 7


def spark(values: list[int]) -> str:
    """One bar a month, on the curve's own scale from zero."""
    top = max(values, default=0)
    if top <= 0:
        return ""
    return "".join(BARS[round(v / top * (len(BARS) - 1))] for v in values)


def change(new: int, old: int) -> int | None:
    return round((new / old - 1) * 100) if old else None


def _trend(v: list[int], months: list[str]) -> dict:
    peak = max(v)
    top = len(v) - 1 - v[::-1].index(peak)          # the latest month at the peak
    past = top <= len(v) - 3
    if past and peak >= 2 * median(v) and v[-1] <= peak * 0.5:
        return {"label": "spiked", "peak": months[top], "from_peak": change(v[-1], peak)}
    last, before = mean(v[-3:]), mean(v[-6:-3])
    if (past and v[-1] <= peak * 0.6) or last <= 0.7 * before:
        return {"label": "falling"}
    return {"label": "rising" if last >= 1.3 * before and last > 0 else "steady"}


def shape(months: list[list]) -> dict | None:
    """{"label", "spark", "c3", "c6", "first", "last", "since"?, ...} from [[YYYY-MM, searches], ...], oldest first."""
    if len(months) < MIN_MONTHS:
        return None
    names, v = [m for m, _ in months], [int(x or 0) for _, x in months]
    out = {"spark": spark(v), "first": names[0], "last": names[-1], "c3": change(v[-1], v[-4]), "c6": change(v[-1], v[-7])}
    peak = max(v)
    if peak < MIN_PEAK:
        return dict(out, label="thin")
    if max(v[:3]) < peak * 0.1:
        out["since"] = names[next(i for i, x in enumerate(v) if x >= peak * 0.1)]
    return {**out, **_trend(v, names)}


def assess(rows: list[dict], cfg: dict) -> None:
    """Adds `year` to each row that carries monthly searches."""
    if not cfg.get("year_curve", {}).get("enabled"):
        return
    for r in rows:
        if r.get("months"):
            r["year"] = shape(r["months"])
