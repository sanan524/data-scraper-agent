"""百度热搜（国内实时热榜，公开接口，无需 key）。

方法：REST API
"""
import requests

from datetime import datetime, timedelta, timezone

from scraper.filters import is_relevant

URL = "https://top.baidu.com/api/board"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
}

CN_TZ = timezone(timedelta(hours=8))


def fetch(limit: int = 30) -> list[dict]:
    resp = requests.get(
        URL,
        params={"platform": "wise", "tab": "realtime"},
        headers=HEADERS,
        timeout=15,
    )
    if resp.status_code != 200:
        print(f"  [百度热搜] HTTP {resp.status_code}")
        return []

    results: list[dict] = []
    rank = 0

    for card in (resp.json().get("data") or {}).get("cards") or []:
        for block in card.get("content") or []:
            for item in block.get("content") or []:
                word = (item.get("word") or "").strip()
                if not word or not is_relevant(word):
                    continue

                rank += 1
                if rank > limit:
                    return results

                results.append(
                    {
                        "name": word[:300],
                        "url": item.get("url") or f"https://www.baidu.com/s?wd={word}",
                        "source": "百度热搜",
                        "date_found": datetime.now(CN_TZ).date().isoformat(),
                        "hours_ago": 0.0,          # 实时榜，热度正在发生
                        "heat": None,              # 百度这个接口不返回热度值，用排名代替
                        "comments": None,
                        "rank": rank,
                    }
                )

    return results
