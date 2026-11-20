"""Hacker News 源 —— 走官方 Algolia 公开 API，不需要任何 key。

方法：REST API（search_by_date）
文档：https://hn.algolia.com/api
"""
from datetime import datetime, timezone

import requests

from scraper.filters import is_relevant

API = "https://hn.algolia.com/api/v1/search_by_date"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; research-bot/1.0)",
}


def fetch(queries: list[str], hits_per_page: int = 30) -> list[dict]:
    """按 query 逐个抓，返回统一 schema 的条目列表。"""
    results: list[dict] = []

    for query in queries:
        resp = requests.get(
            API,
            params={
                "query": query,
                "tags": "story",
                "hitsPerPage": min(hits_per_page, 100),
            },
            headers=HEADERS,
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"  [HN] query={query!r} -> HTTP {resp.status_code}")
            continue

        for hit in resp.json().get("hits", []):
            title = (hit.get("title") or "").strip()
            if not title or not is_relevant(title):
                continue
            results.append(_normalise(hit, query))

        # 别把 HN 打爆
        import time

        time.sleep(1)

    return results


def _normalise(hit: dict, query: str) -> dict:
    object_id = hit.get("objectID", "")
    return {
        "name": (hit.get("title") or "")[:300],
        "url": hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}",
        "source": "Hacker News",
        "date_found": (hit.get("created_at") or datetime.now(timezone.utc).isoformat())[:10],
        "points": hit.get("points"),
        "_query": query,
    }
