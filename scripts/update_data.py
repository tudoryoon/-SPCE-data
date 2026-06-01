from __future__ import annotations

import argparse
import html as html_lib
import json
import math
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT / "public"
DATA_DIR = PUBLIC_DIR / "data"
LATEST_PATH = DATA_DIR / "latest.json"
HISTORY_PATH = DATA_DIR / "history.json"

USER_AGENT = "spce-data-monitor/0.1"
REDDIT_TOKEN: tuple[str, float] | None = None

BASELINE = {
    "name": "GME January 2021",
    "short_percent_float": 122.97,
    "short_percent_shares_outstanding": 109.26,
    "short_notional_to_market_cap_pct": 109.26,
    "source": "SEC Staff Report on Equity and Options Market Structure Conditions in Early 2021",
    "source_url": "https://www.sec.gov/files/staff-report-equity-options-market-struction-conditions-early-2021.pdf",
    "short_market_cap_note": "Short notional / market cap is approximated as shares sold short / shares outstanding when measured at the same share price. SEC staff reported GME short interest exceeded shares outstanding in January 2021, with a cited 109.26% high on December 31, 2020; SEC also reported 122.97% of float in January 2021.",
}

GME_2021_SOCIAL_BENCHMARK = {
    "window": "2021-01-20 to 2021-01-27",
    "reddit_mentions": 82000,
    "tweets": 1582000,
    "youtube_videos": 1465,
    "source": "Sprout Social social-listening recap",
    "source_url": "https://sproutsocial.com/insights/gamestop-stock-social-media/",
    "note": "External social-listening benchmark, not the same methodology as the current ApeWisdom 24h WSB ranking.",
}

SYMBOLS = {
    "SPCE": {
        "company": "Virgin Galactic",
        "aliases": ["Virgin Galactic", "Virgin Galactic Holdings"],
        "subreddits": [
            "wallstreetbets",
            "stocks",
            "investing",
            "Shortsqueeze",
            "ShortSqueezeJuice",
            "SPCE",
            "VirginGalactic",
            "smallstreetbets",
            "TheRaceTo1Million",
        ],
    },
    "GME": {
        "company": "GameStop",
        "aliases": ["GameStop", "Gamestop"],
        "subreddits": [
            "wallstreetbets",
            "Superstonk",
            "GME",
            "stocks",
            "investing",
            "Shortsqueeze",
            "smallstreetbets",
        ],
    },
}

SOCIAL_THRESHOLDS_24H = {
    "reddit": 500.0,
    "x": 20000.0,
    "youtube": 50.0,
}

WSB_TOP_LIMIT = 15
WSB_SAMPLE_PAGES = 4
MOST_SHORTED_SOURCE_URL = "https://stockanalysis.com/list/most-shorted-stocks/"
HIGH_SHORT_FLOAT_THRESHOLD_PCT = 10.0
TICKER_DENYLIST = {
    "A",
    "AI",
    "ALL",
    "ARE",
    "BE",
    "BIG",
    "CEO",
    "CFO",
    "DD",
    "EPS",
    "ETF",
    "FOR",
    "GDP",
    "GO",
    "IMO",
    "IPO",
    "IRS",
    "IT",
    "LOL",
    "NEW",
    "NOW",
    "ON",
    "ONE",
    "OR",
    "PE",
    "PM",
    "RH",
    "SEC",
    "TA",
    "THE",
    "USA",
    "YOLO",
}
BULLISH_TERMS = [
    "buy",
    "bought",
    "buying",
    "calls",
    "call",
    "long",
    "moon",
    "rocket",
    "squeeze",
    "short squeeze",
    "gamma squeeze",
    "breakout",
    "undervalued",
    "oversold",
    "bullish",
    "rip",
    "ripping",
    "runup",
    "pump",
    "loaded",
    "holding",
    "hold",
    "diamond",
    "tendies",
]
BEARISH_TERMS = [
    "puts",
    "put",
    "shorting",
    "shorted",
    "sell",
    "selling",
    "dump",
    "dumping",
    "overpriced",
    "overvalued",
    "bearish",
    "rug",
    "crash",
    "bankruptcy",
    "dilution",
    "diluting",
    "scam",
    "fraud",
    "bagholder",
    "bagholders",
    "dead",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def http_get_json(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 25,
) -> tuple[dict[str, Any] | None, str | None]:
    merged_headers = {
        "Accept": "application/json",
        "User-Agent": os.environ.get("REDDIT_USER_AGENT") or USER_AGENT,
    }
    if headers:
        merged_headers.update(headers)
    try:
        response = requests.get(url, params=params, headers=merged_headers, timeout=timeout)
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "2"))
            time.sleep(min(retry_after, 10))
            response = requests.get(url, params=params, headers=merged_headers, timeout=timeout)
        if not response.ok:
            return None, f"HTTP {response.status_code}: {response.text[:220]}"
        return response.json(), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def http_post_json(
    url: str,
    body: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> tuple[list[dict[str, Any]] | dict[str, Any] | None, str | None]:
    merged_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": os.environ.get("REDDIT_USER_AGENT") or USER_AGENT,
    }
    if headers:
        merged_headers.update(headers)
    try:
        response = requests.post(url, headers=merged_headers, json=body, timeout=timeout)
        if response.status_code == 204:
            return [], None
        if not response.ok:
            return None, f"HTTP {response.status_code}: {response.text[:220]}"
        return response.json(), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def reddit_headers() -> tuple[dict[str, str] | None, str | None]:
    global REDDIT_TOKEN
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None, "Missing REDDIT_CLIENT_ID or REDDIT_CLIENT_SECRET"
    now = time.time()
    if REDDIT_TOKEN and REDDIT_TOKEN[1] > now + 60:
        return {"Authorization": f"Bearer {REDDIT_TOKEN[0]}"}, None
    try:
        response = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": os.environ.get("REDDIT_USER_AGENT") or USER_AGENT},
            timeout=25,
        )
        if not response.ok:
            return None, f"Reddit OAuth HTTP {response.status_code}: {response.text[:220]}"
        payload = response.json()
        REDDIT_TOKEN = (payload["access_token"], now + int(payload.get("expires_in") or 3600))
        return {"Authorization": f"Bearer {REDDIT_TOKEN[0]}"}, None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def parse_percent_text(value: str) -> float | None:
    cleaned = re.sub(r"[^0-9.+-]", "", value or "")
    return safe_float(cleaned)


def clean_cell_html(value: str) -> str:
    value = re.sub(r"<!--.*?-->", "", value, flags=re.DOTALL)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", html_lib.unescape(value)).strip()


def percent_value(value: Any) -> float | None:
    number = safe_float(value)
    if number is None:
        return None
    return number * 100 if abs(number) <= 1 else number


def pct_change(values: list[float], periods: int) -> float | None:
    if len(values) <= periods:
        return None
    latest = values[-1]
    prior = values[-1 - periods]
    if prior == 0:
        return None
    return (latest / prior - 1) * 100


def ratio(numerator: Any, denominator: Any) -> float | None:
    num = safe_float(numerator)
    den = safe_float(denominator)
    if num is None or den in (None, 0):
        return None
    return num / den


def bounded_score(value: float | None, high: float) -> float | None:
    if value is None:
        return None
    return max(0.0, min(100.0, value / high * 100.0))


def top_share(counter: Counter[str]) -> tuple[str | None, float | None]:
    total = sum(counter.values())
    if total <= 0:
        return None, None
    key, count = counter.most_common(1)[0]
    return key, count / total


def symbol_query(symbol: str, config: dict[str, Any]) -> str:
    aliases = config.get("aliases") or []
    parts = [f'"${symbol}"', symbol]
    parts.extend(f'"{alias}"' for alias in aliases[:2])
    return " OR ".join(parts)


def mention_pattern(symbol: str, aliases: list[str]) -> re.Pattern[str]:
    terms = [rf"(?<![A-Za-z0-9])\$?{re.escape(symbol)}(?![A-Za-z0-9])"]
    terms.extend(re.escape(alias) for alias in aliases)
    return re.compile("|".join(terms), re.IGNORECASE)


def collect_finra_short_interest(symbol: str) -> dict[str, Any]:
    start_date = (utc_now() - timedelta(days=370)).date().isoformat()
    body = {
        "limit": 60,
        "compareFilters": [
            {"compareType": "EQUAL", "fieldName": "symbolCode", "fieldValue": symbol},
            {"compareType": "GREATER", "fieldName": "settlementDate", "fieldValue": start_date},
        ],
        "fields": [
            "settlementDate",
            "symbolCode",
            "issueName",
            "marketClassCode",
            "currentShortPositionQuantity",
            "previousShortPositionQuantity",
            "changePreviousNumber",
            "changePercent",
            "averageDailyVolumeQuantity",
            "daysToCoverQuantity",
            "revisionFlag",
            "stockSplitFlag",
        ],
    }
    payload, err = http_post_json("https://api.finra.org/data/group/OTCMarket/name/ConsolidatedShortInterest", body)
    if err:
        return {"status": "error", "note": err, "history": []}
    rows = []
    for item in payload or []:
        rows.append(
            {
                "settlement_date": item.get("settlementDate"),
                "shares_short": safe_float(item.get("currentShortPositionQuantity")),
                "previous_shares_short": safe_float(item.get("previousShortPositionQuantity")),
                "change_shares": safe_float(item.get("changePreviousNumber")),
                "change_percent": safe_float(item.get("changePercent")),
                "average_daily_volume": safe_float(item.get("averageDailyVolumeQuantity")),
                "days_to_cover": safe_float(item.get("daysToCoverQuantity")),
                "market_class": item.get("marketClassCode"),
                "revision_flag": item.get("revisionFlag"),
                "stock_split_flag": item.get("stockSplitFlag"),
            }
        )
    rows = sorted([row for row in rows if row.get("settlement_date")], key=lambda row: row["settlement_date"])
    latest = rows[-1] if rows else None
    return {
        "status": "ok" if rows else "empty",
        "note": "",
        "source": "FINRA Consolidated Short Interest",
        "source_url": "https://api.finra.org/data/group/OTCMarket/name/ConsolidatedShortInterest",
        "latest": latest,
        "history": rows[-26:],
    }


def collect_gme_2021_case() -> dict[str, Any]:
    series = []
    status = "ok"
    note = ""
    try:
        import yfinance as yf

        hist = yf.Ticker("GME").history(start="2020-04-01", end="2021-02-16", interval="1d", auto_adjust=False)
        if hist is not None and not hist.empty:
            for index, (dt, row) in enumerate(hist.iterrows()):
                close = safe_float(row.get("Close"))
                volume = safe_float(row.get("Volume"))
                if close is None:
                    continue
                series.append(
                    {
                        "date": dt.strftime("%Y-%m-%d"),
                        "close": close,
                        "volume": volume,
                        "normalized": None,
                    }
                )
        else:
            status = "empty"
            note = "No GME price history returned by yfinance."
    except Exception as exc:  # noqa: BLE001
        status = "error"
        note = str(exc)

    start = series[0] if series else None
    base = min(series, key=lambda item: item.get("close") or float("inf")) if series else None
    if base and base.get("close") not in (None, 0):
        for item in series:
            item["normalized"] = item["close"] / base["close"] if item.get("close") is not None else None
    peak = max(series, key=lambda item: item.get("close") or 0) if series else None
    peak_return_pct = None
    if peak and base and base.get("close") not in (None, 0):
        peak_return_pct = (peak["close"] / base["close"] - 1) * 100

    milestones = [
        {"date": "2020-08-31", "label": "Ryan Cohen stake disclosed"},
        {"date": "2021-01-11", "label": "Ryan Cohen board catalyst"},
        {"date": "2021-01-22", "label": "Retail/WSB acceleration"},
        {"date": "2021-01-27", "label": "Social volume peak week"},
        {"date": "2021-01-28", "label": "Broker restrictions / volatility peak"},
    ]
    if base:
        milestones.insert(0, {"date": base["date"], "label": "COVID-era closing low"})

    return {
        "status": status,
        "note": note,
        "price_source": "yfinance GME daily close, split-adjusted by Yahoo where applicable; normalized to the COVID-era closing low in this window",
        "window": "2020-04-01 to 2021-02-15",
        "start": start,
        "base": base,
        "peak": peak,
        "peak_return_pct": peak_return_pct,
        "jan_2021_gain_pct": 1625,
        "jan_2021_gain_source": "CNBC recap of January 2021 GME move",
        "jan_2021_gain_source_url": "https://www.cnbc.com/2021/01/30/gamestop-reddit-and-robinhood-a-full-recap-of-the-historic-retail-trading-mania-on-wall-street.html",
        "short_interest_peak_percent_float": BASELINE["short_percent_float"],
        "short_interest_peak_percent_shares_outstanding": BASELINE["short_percent_shares_outstanding"],
        "short_notional_to_market_cap_pct": BASELINE["short_notional_to_market_cap_pct"],
        "short_market_cap_note": BASELINE["short_market_cap_note"],
        "short_interest_source": BASELINE["source_url"],
        "sec_volume_note": "SEC staff described Jan. 13-29, 2021 average GME trading volume as roughly 100 million shares per day, more than 1,400% above the 2020 average.",
        "social_benchmark": GME_2021_SOCIAL_BENCHMARK,
        "series": series,
        "milestones": milestones,
        "methodology_note": "Price is normalized to GME's COVID-era closing low in this window. The historical social benchmark is not directly comparable to the current ApeWisdom WSB 24h count; it shows order-of-magnitude attention during the GME event.",
    }


def collect_most_shorted_stocks() -> dict[str, Any]:
    try:
        response = requests.get(
            MOST_SHORTED_SOURCE_URL,
            headers={
                "Accept": "text/html",
                "User-Agent": os.environ.get("REDDIT_USER_AGENT") or USER_AGENT,
            },
            timeout=30,
        )
        if not response.ok:
            return {
                "status": "error",
                "note": f"HTTP {response.status_code}: {response.text[:160]}",
                "items": [],
            }
        html_text = response.text
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "note": str(exc), "items": []}

    items: list[dict[str, Any]] = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, flags=re.DOTALL | re.IGNORECASE):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.DOTALL | re.IGNORECASE)
        if len(cells) < 7:
            continue
        rank = safe_float(clean_cell_html(cells[0]))
        symbol = clean_cell_html(cells[1]).upper()
        company = clean_cell_html(cells[2])
        short_float = parse_percent_text(clean_cell_html(cells[3]))
        price = safe_float(clean_cell_html(cells[4]).replace(",", ""))
        change_pct = parse_percent_text(clean_cell_html(cells[5]))
        market_cap = clean_cell_html(cells[6])
        if not symbol or short_float is None:
            continue
        items.append(
            {
                "rank": int(rank) if rank is not None else len(items) + 1,
                "symbol": symbol,
                "company": company,
                "short_percent_float": short_float,
                "price": price,
                "change_pct": change_pct,
                "market_cap": market_cap,
            }
        )

    items = sorted(items, key=lambda item: item.get("rank") or 9999)
    return {
        "status": "ok" if items else "empty",
        "note": "" if items else "No rows parsed from StockAnalysis most-shorted list.",
        "source": "StockAnalysis Most Shorted Stocks",
        "source_url": MOST_SHORTED_SOURCE_URL,
        "universe": "Top 100 stocks by short percent of float from StockAnalysis.",
        "items": items[:100],
    }


def collect_short_exposure_context(spce_market: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    detail = spce_market.get("short_deep_dive") or {}
    short_float_pct = safe_float(detail.get("short_percent_float")) or safe_float(spce_market.get("short_percent_float"))
    short_mcap_pct = safe_float(detail.get("short_notional_to_market_cap_pct"))
    top_data = collect_most_shorted_stocks()
    top_items = top_data.get("items") or []
    top_observed = top_items[0] if top_items else None
    top100_cutoff = top_items[-1].get("short_percent_float") if len(top_items) >= 100 else None
    spce_entry = next((item for item in top_items if item.get("symbol") == "SPCE"), None)
    rank = spce_entry.get("rank") if spce_entry else None
    above_count = None
    if short_float_pct is not None and top_items:
        above_count = sum(1 for item in top_items if safe_float(item.get("short_percent_float")) is not None and item["short_percent_float"] > short_float_pct)
    top100_cutoff_ratio = None
    if short_float_pct is not None and top100_cutoff not in (None, 0):
        top100_cutoff_ratio = short_float_pct / top100_cutoff * 100
    high_threshold_multiple = None
    if short_float_pct is not None:
        high_threshold_multiple = short_float_pct / HIGH_SHORT_FLOAT_THRESHOLD_PCT

    if rank:
        classification = "Top-100 extreme short-float bucket."
    elif short_float_pct is not None and top100_cutoff is not None and short_float_pct < top100_cutoff:
        classification = "High short interest, but below the current top-100 extreme short-float bucket."
    elif short_float_pct is not None and short_float_pct >= HIGH_SHORT_FLOAT_THRESHOLD_PCT:
        classification = "High short interest versus the common 10% short-float threshold."
    else:
        classification = "Not high versus the common 10% short-float threshold."

    return {
        "status": top_data.get("status"),
        "note": top_data.get("note"),
        "generated_at_utc": iso_z(utc_now()),
        "spce": {
            "short_percent_float": short_float_pct,
            "short_notional_to_market_cap_pct": short_mcap_pct,
            "shares_short": detail.get("shares_short"),
            "market_cap": detail.get("market_cap"),
            "short_notional": detail.get("short_notional"),
            "settlement_date": detail.get("official_settlement_date"),
            "rank_in_top100_short_float": rank,
            "top100_count_above_spce": above_count,
            "top100_cutoff_ratio_pct": top100_cutoff_ratio,
            "high_threshold_multiple": high_threshold_multiple,
            "classification": classification,
        },
        "benchmarks": {
            "high_short_float_threshold_pct": HIGH_SHORT_FLOAT_THRESHOLD_PCT,
            "top_observed_short_float_pct": top_observed.get("short_percent_float") if top_observed else None,
            "top_observed_symbol": top_observed.get("symbol") if top_observed else None,
            "top100_cutoff_short_float_pct": top100_cutoff,
            "gme_2021_short_float_pct": baseline.get("short_percent_float"),
            "gme_2021_short_market_cap_proxy_pct": baseline.get("short_notional_to_market_cap_pct"),
        },
        "top_short_float": top_items[:12],
        "source": top_data.get("source"),
        "source_url": top_data.get("source_url"),
        "methodology": "SPCE short / market cap uses FINRA shares short divided by shares outstanding proxy. External high-short list uses short percent of float, so it is directional context rather than the same denominator.",
    }


def collect_finra_short_volume(symbol: str) -> dict[str, Any]:
    start_date = (utc_now() - timedelta(days=45)).date().isoformat()
    body = {
        "limit": 500,
        "compareFilters": [
            {
                "compareType": "EQUAL",
                "fieldName": "securitiesInformationProcessorSymbolIdentifier",
                "fieldValue": symbol,
            },
            {"compareType": "GREATER", "fieldName": "tradeReportDate", "fieldValue": start_date},
        ],
        "fields": [
            "tradeReportDate",
            "securitiesInformationProcessorSymbolIdentifier",
            "shortParQuantity",
            "shortExemptParQuantity",
            "totalParQuantity",
            "marketCode",
            "reportingFacilityCode",
        ],
    }
    payload, err = http_post_json("https://api.finra.org/data/group/OTCMarket/name/regShoDaily", body)
    if err:
        return {"status": "error", "note": err, "history": []}

    grouped: dict[str, dict[str, Any]] = {}
    for item in payload or []:
        date = item.get("tradeReportDate")
        if not date:
            continue
        bucket = grouped.setdefault(
            date,
            {
                "trade_date": date,
                "short_volume": 0.0,
                "short_exempt_volume": 0.0,
                "total_volume": 0.0,
                "facilities": set(),
            },
        )
        bucket["short_volume"] += safe_float(item.get("shortParQuantity")) or 0.0
        bucket["short_exempt_volume"] += safe_float(item.get("shortExemptParQuantity")) or 0.0
        bucket["total_volume"] += safe_float(item.get("totalParQuantity")) or 0.0
        if item.get("reportingFacilityCode"):
            bucket["facilities"].add(item.get("reportingFacilityCode"))

    rows = []
    for row in grouped.values():
        row["short_volume_ratio"] = ratio(row["short_volume"], row["total_volume"])
        row["short_exempt_ratio"] = ratio(row["short_exempt_volume"], row["total_volume"])
        row["facilities"] = sorted(row["facilities"])
        rows.append(row)
    rows = sorted(rows, key=lambda row: row["trade_date"])
    latest = rows[-1] if rows else None
    last_five = rows[-5:]
    ratios = [row["short_volume_ratio"] for row in last_five if row.get("short_volume_ratio") is not None]
    avg_ratio_5d = sum(ratios) / len(ratios) if ratios else None
    return {
        "status": "ok" if rows else "empty",
        "note": "",
        "source": "FINRA Reg SHO Daily Short Sale Volume",
        "source_url": "https://api.finra.org/data/group/OTCMarket/name/regShoDaily",
        "latest": latest,
        "average_short_volume_ratio_5d": avg_ratio_5d,
        "history": rows[-30:],
    }


def enrich_short_deep_dive(market: dict[str, Any]) -> None:
    finra_interest = market.get("finra_short_interest") or {}
    finra_volume = market.get("finra_short_volume") or {}
    latest_interest = finra_interest.get("latest") or {}
    latest_volume = finra_volume.get("latest") or {}

    official_shares_short = safe_float(latest_interest.get("shares_short"))
    shares_short = official_shares_short if official_shares_short is not None else safe_float(market.get("shares_short"))
    price = safe_float(market.get("price"))
    float_shares = safe_float(market.get("float_shares"))
    shares_outstanding = safe_float(market.get("shares_outstanding"))
    market_cap = safe_float(market.get("market_cap"))
    if market_cap in (None, 0) and price is not None and shares_outstanding not in (None, 0):
        market_cap = price * shares_outstanding
    short_notional = shares_short * price if shares_short is not None and price is not None else None

    short_percent_float_calc = None
    if shares_short is not None and float_shares not in (None, 0):
        short_percent_float_calc = shares_short / float_shares * 100

    short_percent_shares_outstanding = None
    if shares_short is not None and shares_outstanding not in (None, 0):
        short_percent_shares_outstanding = shares_short / shares_outstanding * 100

    short_notional_to_market_cap_pct = None
    if short_notional is not None and market_cap not in (None, 0):
        short_notional_to_market_cap_pct = short_notional / market_cap * 100

    market["short_deep_dive"] = {
        "shares_short": shares_short,
        "shares_short_source": "FINRA" if official_shares_short is not None else "yfinance",
        "short_notional": short_notional,
        "short_percent_float": short_percent_float_calc or safe_float(market.get("short_percent_float")),
        "short_percent_shares_outstanding": short_percent_shares_outstanding,
        "short_notional_to_market_cap_pct": short_notional_to_market_cap_pct,
        "reported_short_percent_float": safe_float(market.get("short_percent_float")),
        "float_shares": float_shares,
        "shares_outstanding": shares_outstanding,
        "market_cap": market_cap,
        "official_settlement_date": latest_interest.get("settlement_date"),
        "official_days_to_cover": safe_float(latest_interest.get("days_to_cover")),
        "official_average_daily_volume": safe_float(latest_interest.get("average_daily_volume")),
        "short_interest_change_shares": safe_float(latest_interest.get("change_shares")),
        "short_interest_change_percent": safe_float(latest_interest.get("change_percent")),
        "daily_short_volume_date": latest_volume.get("trade_date"),
        "daily_short_volume": safe_float(latest_volume.get("short_volume")),
        "daily_total_reported_volume": safe_float(latest_volume.get("total_volume")),
        "daily_short_volume_ratio": safe_float(latest_volume.get("short_volume_ratio")),
        "daily_short_exempt_volume": safe_float(latest_volume.get("short_exempt_volume")),
        "daily_short_exempt_ratio": safe_float(latest_volume.get("short_exempt_ratio")),
        "average_short_volume_ratio_5d": safe_float(finra_volume.get("average_short_volume_ratio_5d")),
        "caveat": "Short Interest Shares is the open short-position stock reported on FINRA settlement dates. Daily Short Sale Volume Ratio is same-day reported short-sale flow, not accumulated open short interest. Short / Market Cap is short shares times price divided by market cap.",
    }


def collect_market(symbol: str) -> dict[str, Any]:
    try:
        import yfinance as yf
    except Exception as exc:  # noqa: BLE001
        return {"status": "skipped", "note": f"Missing yfinance: {exc}"}

    result: dict[str, Any] = {"status": "ok", "note": ""}
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="3mo", interval="1d", auto_adjust=False)
        if hist is not None and not hist.empty:
            closes = [safe_float(value) for value in hist["Close"].dropna().tolist()]
            closes = [value for value in closes if value is not None]
            volumes = [safe_float(value) for value in hist["Volume"].dropna().tolist()]
            volumes = [value for value in volumes if value is not None]
            if closes:
                result["price"] = closes[-1]
                result["price_change_5d_pct"] = pct_change(closes, 5)
                result["price_change_20d_pct"] = pct_change(closes, 20)
            if volumes:
                avg20 = sum(volumes[-20:]) / min(len(volumes), 20)
                result["volume"] = volumes[-1]
                result["volume_avg_20d"] = avg20
                result["volume_ratio_20d"] = volumes[-1] / avg20 if avg20 else None

        info = ticker.get_info() if hasattr(ticker, "get_info") else ticker.info
        result.update(
            {
                "short_percent_float": percent_value(info.get("shortPercentOfFloat")),
                "shares_short": safe_float(info.get("sharesShort")),
                "short_ratio": safe_float(info.get("shortRatio")),
                "float_shares": safe_float(info.get("floatShares")),
                "shares_outstanding": safe_float(info.get("sharesOutstanding")),
                "market_cap": safe_float(info.get("marketCap")),
                "average_volume": safe_float(info.get("averageVolume")),
                "beta": safe_float(info.get("beta")),
            }
        )
        result["finra_short_interest"] = collect_finra_short_interest(symbol)
        result["finra_short_volume"] = collect_finra_short_volume(symbol)
        enrich_short_deep_dive(result)
    except Exception as exc:  # noqa: BLE001
        result["status"] = "error"
        result["note"] = str(exc)
    return result


def collect_reddit(symbol: str, window_hours: int) -> dict[str, Any]:
    config = SYMBOLS[symbol]
    headers, auth_error = reddit_headers()
    if headers is None:
        return {"status": "skipped", "note": auth_error, "mention_count": None}

    start_ts = (utc_now() - timedelta(hours=window_hours)).timestamp()
    query = symbol_query(symbol, config)
    pattern = mention_pattern(symbol, config.get("aliases", []))
    subreddits: list[str | None] = [None] + config["subreddits"]
    posts: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    for subreddit in subreddits:
        url = "https://oauth.reddit.com/search" if subreddit is None else f"https://oauth.reddit.com/r/{subreddit}/search"
        params = {
            "q": query,
            "sort": "new",
            "t": "day" if window_hours <= 24 else "week",
            "limit": 100,
            "raw_json": 1,
        }
        if subreddit:
            params["restrict_sr"] = 1
        payload, err = http_get_json(url, params=params, headers=headers)
        if err:
            errors.append(f"{subreddit or 'global'}: {err}")
            continue
        for child in (((payload or {}).get("data") or {}).get("children") or []):
            data = child.get("data") or {}
            created = float(data.get("created_utc") or 0)
            if created < start_ts:
                continue
            text = f"{data.get('title') or ''}\n{data.get('selftext') or ''}"
            if not pattern.search(text):
                continue
            post_id = data.get("id")
            if post_id:
                posts[post_id] = {
                    "id": post_id,
                    "title": data.get("title"),
                    "author": data.get("author"),
                    "subreddit": data.get("subreddit"),
                    "score": data.get("score") or 0,
                    "comments": data.get("num_comments") or 0,
                    "url": "https://www.reddit.com" + (data.get("permalink") or ""),
                }
        time.sleep(0.15)

    authors = Counter(post.get("author") or "unknown" for post in posts.values())
    communities = Counter(post.get("subreddit") or "unknown" for post in posts.values())
    top_author, top_author_share = top_share(authors)
    top_community, top_community_share = top_share(communities)
    engagement = sum(int(post["score"]) + int(post["comments"]) for post in posts.values())

    return {
        "status": "ok" if not errors else "partial",
        "note": "; ".join(errors[:3]),
        "mention_count": len(posts),
        "unique_authors": len(authors),
        "top_author": top_author,
        "top_author_share": top_author_share,
        "top_community": top_community,
        "top_community_share": top_community_share,
        "engagement_sum": engagement,
        "sample": sorted(posts.values(), key=lambda item: item["score"] + item["comments"], reverse=True)[:8],
    }


def collect_x(symbol: str, window_hours: int) -> dict[str, Any]:
    bearer = os.environ.get("X_BEARER_TOKEN")
    if not bearer:
        return {"status": "skipped", "note": "Missing X_BEARER_TOKEN", "mention_count": None}

    config = SYMBOLS[symbol]
    start = utc_now() - timedelta(hours=min(window_hours, 24 * 7))
    query = f'(${symbol} OR "{config["company"]}") -is:retweet'
    headers = {"Authorization": f"Bearer {bearer}"}

    counts_payload, counts_err = http_get_json(
        "https://api.x.com/2/tweets/counts/recent",
        params={
            "query": query,
            "start_time": iso_z(start),
            "end_time": iso_z(utc_now()),
            "granularity": "hour",
            "search_count.fields": "start,end,tweet_count",
        },
        headers=headers,
    )
    tweets_payload, tweets_err = http_get_json(
        "https://api.x.com/2/tweets/search/recent",
        params={
            "query": query,
            "start_time": iso_z(start),
            "max_results": 100,
            "tweet.fields": "created_at,public_metrics,author_id,lang",
            "expansions": "author_id",
            "user.fields": "username,name,public_metrics",
        },
        headers=headers,
    )

    counts = (counts_payload or {}).get("data") or []
    mention_count = sum(int(item.get("tweet_count") or 0) for item in counts)
    users = {
        user.get("id"): user.get("username") or user.get("name") or user.get("id")
        for user in (((tweets_payload or {}).get("includes") or {}).get("users") or [])
    }
    authors = Counter()
    engagement = 0
    sample = []
    for item in (tweets_payload or {}).get("data") or []:
        author = users.get(item.get("author_id"), item.get("author_id") or "unknown")
        authors[author] += 1
        metrics = item.get("public_metrics") or {}
        engagement += sum(int(metrics.get(field) or 0) for field in ["retweet_count", "reply_count", "like_count", "quote_count"])
        if len(sample) < 8:
            sample.append(
                {
                    "id": item.get("id"),
                    "author": author,
                    "created_at": item.get("created_at"),
                    "engagement": sum(int(metrics.get(field) or 0) for field in ["retweet_count", "reply_count", "like_count", "quote_count"]),
                }
            )
    top_author, top_author_share = top_share(authors)
    errors = [error for error in [counts_err, tweets_err] if error]
    return {
        "status": "ok" if not errors else "partial",
        "note": "; ".join(errors[:2]),
        "query": query,
        "mention_count": mention_count,
        "unique_authors": len(authors) if authors else None,
        "top_author": top_author,
        "top_author_share": top_author_share,
        "engagement_sum": engagement,
        "hourly": counts,
        "sample": sample,
    }


def collect_youtube(symbol: str, window_hours: int) -> dict[str, Any]:
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        return {"status": "skipped", "note": "Missing YOUTUBE_API_KEY", "mention_count": None}

    config = SYMBOLS[symbol]
    start = utc_now() - timedelta(hours=window_hours)
    query = f'${symbol} OR "{config["company"]}"'
    payload, err = http_get_json(
        "https://www.googleapis.com/youtube/v3/search",
        params={
            "key": api_key,
            "part": "snippet",
            "type": "video",
            "q": query,
            "order": "date",
            "publishedAfter": iso_z(start),
            "maxResults": 50,
        },
    )
    if err:
        return {"status": "error", "note": err, "mention_count": None}

    videos: dict[str, dict[str, Any]] = {}
    for item in (payload or {}).get("items") or []:
        video_id = ((item.get("id") or {}).get("videoId"))
        snippet = item.get("snippet") or {}
        if not video_id:
            continue
        videos[video_id] = {
            "id": video_id,
            "title": snippet.get("title"),
            "channel": snippet.get("channelTitle"),
            "published_at": snippet.get("publishedAt"),
            "url": f"https://www.youtube.com/watch?v={video_id}",
        }

    if videos:
        stats_payload, stats_err = http_get_json(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "key": api_key,
                "part": "statistics",
                "id": ",".join(videos.keys()),
            },
        )
        if stats_err:
            err = stats_err
        else:
            for item in (stats_payload or {}).get("items") or []:
                if item.get("id") in videos:
                    videos[item["id"]]["statistics"] = item.get("statistics") or {}

    channels = Counter(video.get("channel") or "unknown" for video in videos.values())
    top_channel, top_channel_share = top_share(channels)
    engagement = 0
    for video in videos.values():
        stats = video.get("statistics") or {}
        engagement += int(stats.get("viewCount") or 0)
        engagement += int(stats.get("likeCount") or 0)
        engagement += int(stats.get("commentCount") or 0)

    return {
        "status": "ok" if not err else "partial",
        "note": err or "",
        "query": query,
        "mention_count": len(videos),
        "raw_total": ((payload or {}).get("pageInfo") or {}).get("totalResults"),
        "unique_authors": len(channels),
        "top_author": top_channel,
        "top_author_share": top_channel_share,
        "engagement_sum": engagement,
        "sample": list(videos.values())[:8],
    }


def count_terms(text: str, terms: list[str]) -> int:
    lowered = text.lower()
    count = 0
    for term in terms:
        if " " in term:
            count += lowered.count(term)
        else:
            count += len(re.findall(rf"\b{re.escape(term)}\b", lowered))
    return count


def classify_sentiment(text: str) -> str:
    bullish = count_terms(text, BULLISH_TERMS)
    bearish = count_terms(text, BEARISH_TERMS)
    if bullish - bearish >= 1:
        return "positive"
    if bearish - bullish >= 1:
        return "negative"
    return "neutral"


def extract_tickers(text: str, allowed: set[str]) -> set[str]:
    cashtags = {
        match.group(1).upper()
        for match in re.finditer(r"(?<![A-Za-z0-9])\$([A-Za-z]{1,5})(?![A-Za-z0-9])", text)
    }
    uppercase_tokens = {
        match.group(0)
        for match in re.finditer(r"(?<![A-Za-z0-9$])([A-Z]{2,5})(?![A-Za-z0-9])", text)
    }
    tickers = (cashtags | uppercase_tokens) & allowed
    return {ticker for ticker in tickers if ticker not in TICKER_DENYLIST or ticker in cashtags}


def fetch_apewisdom_wsb(limit: int = WSB_TOP_LIMIT) -> tuple[list[dict[str, Any]], str | None]:
    payload, err = http_get_json("https://apewisdom.io/api/v1.0/filter/wallstreetbets")
    if err:
        return [], err
    rows = []
    for item in ((payload or {}).get("results") or [])[:limit]:
        rows.append(
            {
                "rank": int(item.get("rank") or 0),
                "ticker": str(item.get("ticker") or "").upper(),
                "name": item.get("name"),
                "mentions": int(item.get("mentions") or 0),
                "upvotes": int(item.get("upvotes") or 0),
                "rank_24h_ago": int(item.get("rank_24h_ago") or 0) if item.get("rank_24h_ago") not in (None, "") else None,
                "mentions_24h_ago": int(item.get("mentions_24h_ago") or 0) if item.get("mentions_24h_ago") not in (None, "") else None,
            }
        )
    return rows, None


def reddit_listing_items(path: str, headers: dict[str, str], window_hours: int, pages: int) -> tuple[list[dict[str, Any]], list[str]]:
    start_ts = (utc_now() - timedelta(hours=window_hours)).timestamp()
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    after = None
    for _page in range(pages):
        params: dict[str, Any] = {"limit": 100, "raw_json": 1}
        if after:
            params["after"] = after
        payload, err = http_get_json(f"https://oauth.reddit.com/r/wallstreetbets/{path}", params=params, headers=headers)
        if err:
            errors.append(f"{path}: {err}")
            break
        children = (((payload or {}).get("data") or {}).get("children") or [])
        oldest_seen = None
        for child in children:
            data = child.get("data") or {}
            created = float(data.get("created_utc") or 0)
            if oldest_seen is None or created < oldest_seen:
                oldest_seen = created
            if created < start_ts:
                continue
            if path == "comments":
                text = f"{data.get('link_title') or ''}\n{data.get('body') or ''}"
                permalink = data.get("permalink") or ""
            else:
                text = f"{data.get('title') or ''}\n{data.get('selftext') or ''}"
                permalink = data.get("permalink") or ""
            items.append(
                {
                    "id": data.get("id"),
                    "author": data.get("author") or "unknown",
                    "created_utc": created,
                    "text": text,
                    "score": int(data.get("score") or 0),
                    "permalink": "https://www.reddit.com" + permalink,
                }
            )
        after = ((payload or {}).get("data") or {}).get("after")
        if not after or (oldest_seen is not None and oldest_seen < start_ts):
            break
        time.sleep(0.15)
    return items, errors


def collect_wsb_trending(window_hours: int) -> dict[str, Any]:
    ape_rows, ape_error = fetch_apewisdom_wsb(WSB_TOP_LIMIT)
    allowed = {row["ticker"] for row in ape_rows if row.get("ticker")}
    sentiment_counts: dict[str, Counter[str]] = {ticker: Counter() for ticker in allowed}
    mention_keys: set[tuple[str, str, str]] = set()
    sample_total = 0
    errors: list[str] = []
    sentiment_source = "apewisdom_mentions_only"

    headers, auth_error = reddit_headers()
    if headers and allowed:
        sentiment_source = "reddit_oauth_bow_sample"
        for path in ["new", "comments"]:
            items, item_errors = reddit_listing_items(path, headers, window_hours, WSB_SAMPLE_PAGES)
            errors.extend(item_errors)
            for item in items:
                tickers = extract_tickers(item["text"], allowed)
                if not tickers:
                    continue
                label = classify_sentiment(item["text"])
                hour_bucket = datetime.fromtimestamp(item["created_utc"], timezone.utc).strftime("%Y%m%d%H")
                for ticker in tickers:
                    key = (item["author"], ticker, hour_bucket)
                    if key in mention_keys:
                        continue
                    mention_keys.add(key)
                    sentiment_counts[ticker][label] += 1
                    sample_total += 1
    elif auth_error:
        errors.append(auth_error)

    rows = []
    for row in ape_rows:
        ticker = row["ticker"]
        total = int(row.get("mentions") or 0)
        counts = sentiment_counts.get(ticker, Counter())
        sample_mentions = sum(counts.values())
        if sample_mentions:
            positive = round(total * counts["positive"] / sample_mentions)
            negative = round(total * counts["negative"] / sample_mentions)
            neutral = max(0, total - positive - negative)
        else:
            positive = 0
            negative = 0
            neutral = total
        rows.append(
            {
                **row,
                "positive": positive,
                "negative": negative,
                "neutral": neutral,
                "net_sentiment": (positive - negative) / total if total else None,
                "sample_mentions": sample_mentions,
            }
        )

    return {
        "status": "ok" if ape_rows and not errors else ("partial" if ape_rows else "error"),
        "note": "; ".join(errors[:4]) if errors else "",
        "source": "ApeWisdom wallstreetbets ranking + local Reddit BoW sentiment split",
        "source_url": "https://apewisdom.io/api/v1.0/filter/wallstreetbets",
        "methodology": "Rank by 24h r/wallstreetbets mention volume. Sentiment split uses a local rules-based bag-of-words classifier on recent WSB posts/comments when Reddit OAuth credentials are available; otherwise mentions are shown as neutral.",
        "window_hours": 24,
        "sentiment_source": sentiment_source,
        "sample_mentions": sample_total,
        "items": rows,
        "error": ape_error,
    }


def score_symbol(symbol_data: dict[str, Any], window_hours: int) -> dict[str, Any]:
    market = symbol_data.get("market") or {}
    social = symbol_data.get("social") or {}
    short_pct = safe_float(market.get("short_percent_float"))
    volume_ratio = safe_float(market.get("volume_ratio_20d"))
    price_change_5d = safe_float(market.get("price_change_5d_pct"))

    social_scores: list[float] = []
    for source, threshold_24h in SOCIAL_THRESHOLDS_24H.items():
        count = safe_float((social.get(source) or {}).get("mention_count"))
        if count is None:
            continue
        threshold = threshold_24h * (window_hours / 24)
        source_score = bounded_score(count, threshold)
        if source_score is not None:
            social_scores.append(source_score)
    social_heat = sum(social_scores) / len(social_scores) if social_scores else None

    leader_shares = [
        safe_float((social.get(source) or {}).get("top_author_share"))
        for source in ["reddit", "x", "youtube"]
    ]
    leader_shares = [value for value in leader_shares if value is not None]
    leader_concentration = max(leader_shares) if leader_shares else None

    components = {
        "short_pressure": bounded_score(short_pct, BASELINE["short_percent_float"]),
        "volume_pressure": bounded_score(volume_ratio, 20.0),
        "price_momentum": bounded_score(max(price_change_5d or 0.0, 0.0), 150.0),
        "social_heat": social_heat,
        "leader_concentration": bounded_score(leader_concentration, 0.35),
    }
    weights = {
        "short_pressure": 0.30,
        "volume_pressure": 0.20,
        "price_momentum": 0.15,
        "social_heat": 0.25,
        "leader_concentration": 0.10,
    }
    available = sum(weights[key] for key, value in components.items() if value is not None)
    weighted = sum(weights[key] * value for key, value in components.items() if value is not None)
    score = weighted / available if available else None
    confidence = available / sum(weights.values())
    return {
        "score": score,
        "confidence": confidence,
        "components": components,
        "label": score_label(score),
        "verdict_ko": verdict(score, components),
    }


def score_label(score: float | None) -> str:
    if score is None:
        return "insufficient data"
    if score >= 75:
        return "high similarity"
    if score >= 45:
        return "partial similarity"
    return "low similarity"


def verdict(score: float | None, components: dict[str, float | None]) -> str:
    if score is None:
        return "데이터가 아직 부족합니다."
    if score >= 75:
        head = "GME 2021과 닮은 압력이 강합니다."
    elif score >= 45:
        head = "일부 밈/숏스퀴즈 특징은 있지만 GME 2021급은 아닙니다."
    else:
        head = "현재는 GME 2021과의 구조적 유사성이 낮습니다."
    reasons = []
    if (components.get("short_pressure") or 0) < 40:
        reasons.append("숏 압력이 GME 2021의 극단적 기준에는 못 미침")
    if (components.get("social_heat") or 0) < 40:
        reasons.append("소셜 결집 신호가 아직 제한적")
    if (components.get("leader_concentration") or 0) < 40:
        reasons.append("명확한 단일 인플루언서 집중도 약함")
    return head if not reasons else f"{head} {'; '.join(reasons)}."


def load_history() -> list[dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    try:
        payload = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else []
    except Exception:
        return []


def slim_history_item(snapshot: dict[str, Any]) -> dict[str, Any]:
    symbols = {}
    for symbol, data in snapshot["symbols"].items():
        market = data.get("market") or {}
        score = data.get("score") or {}
        short_deep_dive = market.get("short_deep_dive") or {}
        symbols[symbol] = {
            "price": market.get("price"),
            "price_change_5d_pct": market.get("price_change_5d_pct"),
            "volume_ratio_20d": market.get("volume_ratio_20d"),
            "short_percent_float": market.get("short_percent_float"),
            "official_short_percent_float": short_deep_dive.get("short_percent_float"),
            "official_shares_short": short_deep_dive.get("shares_short"),
            "official_days_to_cover": short_deep_dive.get("official_days_to_cover"),
            "short_volume_ratio": short_deep_dive.get("daily_short_volume_ratio"),
            "score": score.get("score"),
            "confidence": score.get("confidence"),
            "social_mentions": {
                source: (payload or {}).get("mention_count")
                for source, payload in (data.get("social") or {}).items()
            },
        }
    wsb_spce = next(
        (item for item in ((snapshot.get("wsb_trending") or {}).get("items") or []) if item.get("ticker") == "SPCE"),
        {},
    )
    return {
        "generated_at_utc": snapshot["generated_at_utc"],
        "symbols": symbols,
        "wsb": {
            "spce_mentions": wsb_spce.get("mentions"),
            "spce_rank": wsb_spce.get("rank"),
            "spce_net_sentiment": wsb_spce.get("net_sentiment"),
        },
    }


def build_snapshot(window_hours: int) -> dict[str, Any]:
    snapshot = {
        "generated_at_utc": iso_z(utc_now()),
        "window_hours": window_hours,
        "baseline": BASELINE,
        "gme_2021_case": collect_gme_2021_case(),
        "symbols": {},
        "wsb_trending": collect_wsb_trending(window_hours),
        "meta": {
            "runtime": "github-pages-actions",
            "repo": "tudoryoon/-SPCE-data",
            "disclaimer": "Research automation only. Not investment advice.",
        },
    }
    for symbol in SYMBOLS:
        data = {
            "profile": {
                "symbol": symbol,
                "company": SYMBOLS[symbol]["company"],
                "aliases": SYMBOLS[symbol]["aliases"],
            },
            "market": collect_market(symbol),
            "social": {
                "reddit": collect_reddit(symbol, window_hours),
                "x": collect_x(symbol, window_hours),
                "youtube": collect_youtube(symbol, window_hours),
            },
        }
        data["score"] = score_symbol(data, window_hours)
        snapshot["symbols"][symbol] = data
    snapshot["short_exposure_context"] = collect_short_exposure_context(
        snapshot["symbols"]["SPCE"]["market"],
        snapshot["baseline"],
    )
    snapshot["comparison"] = {
        "target": "SPCE",
        "baseline": "GME",
        "headline": snapshot["symbols"]["SPCE"]["score"]["verdict_ko"],
    }
    return snapshot


def write_snapshot(snapshot: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    history = load_history()
    history.append(slim_history_item(snapshot))
    history = history[-500:]
    LATEST_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Update SPCE/GME monitor data.")
    parser.add_argument("--window-hours", type=int, default=24)
    args = parser.parse_args()
    load_dotenv()
    snapshot = build_snapshot(args.window_hours)
    write_snapshot(snapshot)
    print(json.dumps({"generated_at_utc": snapshot["generated_at_utc"], "comparison": snapshot["comparison"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
