from __future__ import annotations

import argparse
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
    "source": "SEC Staff Report on Equity and Options Market Structure Conditions in Early 2021",
    "source_url": "https://www.sec.gov/files/staff-report-equity-options-market-struction-conditions-early-2021.pdf",
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
        symbols[symbol] = {
            "price": market.get("price"),
            "price_change_5d_pct": market.get("price_change_5d_pct"),
            "volume_ratio_20d": market.get("volume_ratio_20d"),
            "short_percent_float": market.get("short_percent_float"),
            "score": score.get("score"),
            "confidence": score.get("confidence"),
            "social_mentions": {
                source: (payload or {}).get("mention_count")
                for source, payload in (data.get("social") or {}).items()
            },
        }
    return {"generated_at_utc": snapshot["generated_at_utc"], "symbols": symbols}


def build_snapshot(window_hours: int) -> dict[str, Any]:
    snapshot = {
        "generated_at_utc": iso_z(utc_now()),
        "window_hours": window_hours,
        "baseline": BASELINE,
        "symbols": {},
        "meta": {
            "runtime": "github-pages-actions",
            "repo": "tudoryoon/-spce-data",
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

