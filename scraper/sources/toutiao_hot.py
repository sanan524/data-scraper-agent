"""今日头条热榜（带 HotValue 热度值，国内舆论风向标之一）。"""
from datetime import datetime, timedelta, timezone

import requests

from scraper.filters import is_relevant

URL = "https://www.toutiao.com/hot-event/hot-board/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
}

CN_TZ = timezone(timedelta(hours=8))


def fetch(limit: int = 30) -> list[dict]:
    resp = requests.get(URL, params={"origin": "toutiao_pc"}, headers=HEADERS, timeout=15)
    if resp.status_code != 200:
        print(f"  [头条热榜] HTTP {resp.status_code}")
        return []

    results: list[dict] = []

    for rank, item in enumerate((resp.json().get("data") or [])[:limit], start=1):
        title = (item.get("Title") or "").strip()
        if not title or not is_relevant(title):
            continue

        hot = item.get("HotValue")
        results.append(
            {
                "name": title[:300],
                "url": item.get("Url") or "",
                "source": "头条热榜",
                "date_found": datetime.now(CN_TZ).date().isoformat(),
                "hours_ago": 0.0,
                "heat": int(hot) if isinstance(hot, (int, float)) else None,
                "comments": None,
                "rank": rank,
            }
        )

    return results
