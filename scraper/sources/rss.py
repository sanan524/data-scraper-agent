"""通用 RSS 源：config.yaml 里列几行，就能抓几家中文媒体。

带 pubDate，所以能真正做「48 小时以内」过滤。
"""
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

from scraper.filters import is_relevant

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
}

CN_TZ = timezone(timedelta(hours=8))


def fetch(feeds: list[dict]) -> list[dict]:
    """feeds: [{"name": "IT之家", "url": "...", "limit": 20}, ...]"""
    results: list[dict] = []
    now = datetime.now(timezone.utc)

    for feed in feeds:
        name = feed.get("name") or "RSS"
        url = feed.get("url") or ""
        limit = int(feed.get("limit", 20))
        if not url:
            continue

        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code != 200:
                print(f"  [{name}] HTTP {resp.status_code}")
                continue
            root = ET.fromstring(resp.content)
            items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
        except (requests.RequestException, ET.ParseError) as e:
            print(f"  [{name}] 抓取失败: {e}")
            continue

        kept = 0
        for rank, it in enumerate(items, start=1):
            if kept >= limit:
                break

            title = (it.findtext("title") or it.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            if not title or not is_relevant(title):
                continue

            link = (it.findtext("link") or "").strip()
            if not link:
                link_el = it.find("{http://www.w3.org/2005/Atom}link")
                if link_el is not None:
                    link = link_el.get("href", "")

            raw_date = (it.findtext("pubDate") or it.findtext("{http://www.w3.org/2005/Atom}updated") or "").strip()
            published = _parse_date(raw_date)
            hours_ago = round((now - published).total_seconds() / 3600, 1) if published else None

            results.append(
                {
                    "name": title[:300],
                    "url": link,
                    "source": name,
                    "date_found": (published.astimezone(CN_TZ).date().isoformat() if published else datetime.now(CN_TZ).date().isoformat()),
                    "hours_ago": hours_ago,
                    "heat": None,
                    "comments": None,
                    "rank": rank,
                }
            )
            kept += 1

        print(f"  [{name}] {kept}/{len(items)} 条")

    return results


def _parse_date(raw: str):
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
