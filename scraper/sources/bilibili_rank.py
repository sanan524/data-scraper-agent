"""B 站排行榜 —— 唯一能拿到**真实评论数**的源（stat.reply）。

需要带 Referer，否则会 403。
"""
import time
from datetime import datetime, timedelta, timezone

import requests

from scraper.filters import is_relevant

URL = "https://api.bilibili.com/x/web-interface/ranking/v2"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
}

CN_TZ = timezone(timedelta(hours=8))


def fetch(limit: int = 30) -> list[dict]:
    resp = requests.get(URL, params={"rid": 0, "type": "all"}, headers=HEADERS, timeout=20)
    if resp.status_code != 200:
        print(f"  [B站排行榜] HTTP {resp.status_code}")
        return []

    payload = resp.json()
    if payload.get("code") != 0:
        print(f"  [B站排行榜] code={payload.get('code')} {payload.get('message')}")
        return []

    now = time.time()
    results: list[dict] = []

    for rank, v in enumerate((payload.get("data") or {}).get("list") or [], start=1):
        if rank > limit:
            break

        title = (v.get("title") or "").strip()
        if not title or not is_relevant(title):
            continue

        pub = v.get("pubdate") or 0
        hours_ago = round((now - pub) / 3600, 1) if pub else None
        stat = v.get("stat") or {}

        results.append(
            {
                "name": title[:300],
                "url": f"https://www.bilibili.com/video/{v.get('bvid', '')}",
                "source": "B站排行榜",
                "date_found": datetime.fromtimestamp(pub, CN_TZ).date().isoformat() if pub else datetime.now(CN_TZ).date().isoformat(),
                "hours_ago": hours_ago,
                "heat": stat.get("view"),
                "comments": stat.get("reply"),      # 真实评论数
                "rank": rank,
            }
        )

    return results
