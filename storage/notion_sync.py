"""Notion 存储层：去重、写入、读取用户反馈、回填 AI 字段。

note: 固定走 2022-06-28（notion-client 2.2.1 的默认版本），
属性名与建库时完全一致，不要改中文。
"""
import os

from notion_client import Client
from notion_client.errors import APIResponseError

_client = None

# 建库时定下的属性名，代码里靠它们定位
P_NAME = "Name"
P_URL = "URL"
P_SOURCE = "Source"
P_DATE = "Date Found"
P_STATUS = "Status"
P_SCORE = "AI Score"
P_SUMMARY = "Summary"
P_NOTES = "Notes"
P_HEAT = "Heat"
P_COMMENTS = "Comments"
P_BATCH = "批次"
P_RUN_AT = "抓取时间"

REQUIRED_PROPERTIES = {
    P_NAME: "title",
    P_URL: "url",
    P_SOURCE: "select",
    P_DATE: "date",
    P_STATUS: "select",
    P_SCORE: "number",
    P_SUMMARY: "rich_text",
    P_NOTES: "rich_text",
    P_HEAT: "number",
    P_COMMENTS: "number",
    P_BATCH: "select",
    P_RUN_AT: "date",
}


def get_client() -> Client:
    global _client
    if _client is None:
        token = os.environ.get("NOTION_TOKEN", "").strip()
        if not token:
            raise RuntimeError("NOTION_TOKEN 未设置")
        _client = Client(auth=token)
    return _client


def _iter_pages(db_id: str, **kwargs):
    """按 100 条一页翻完整个库。"""
    cursor = None
    while True:
        resp = get_client().databases.query(
            database_id=db_id,
            page_size=100,
            **(dict(start_cursor=cursor) if cursor else {}),
            **kwargs,
        )
        for page in resp.get("results", []):
            yield page
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")


def get_existing_urls(db_id: str) -> set[str]:
    """已入库的 URL 集合，用于去重（这是不产生重复行的唯一依据）。"""
    seen: set[str] = set()
    for page in _iter_pages(db_id):
        url = (page.get("properties", {}).get(P_URL, {}) or {}).get("url") or ""
        if url:
            seen.add(url)
    return seen


def push_item(db_id: str, item: dict) -> bool:
    """写入一条。失败打印原因并返回 False，不抛异常（单条失败不该拖垮整轮）。"""
    props = {
        P_NAME: {"title": [{"text": {"content": (item.get("name") or "")[:100]}}]},
        P_URL: {"url": item.get("url") or None},
        P_SOURCE: {"select": {"name": item.get("source") or "Unknown"}},
        P_DATE: {"date": {"start": item.get("date_found")}},
        P_STATUS: {"select": {"name": "New"}},
    }

    if item.get("ai_score") is not None:
        props[P_SCORE] = {"number": int(item["ai_score"])}
    if item.get("heat") is not None:
        props[P_HEAT] = {"number": int(item["heat"])}
    if item.get("comments") is not None:
        props[P_COMMENTS] = {"number": int(item["comments"])}
    # 这批是哪次抓的：批次用来看"一次热榜的横截面"，抓取时间用来排序/过滤
    if item.get("batch"):
        props[P_BATCH] = {"select": {"name": str(item["batch"])}}
    if item.get("run_at"):
        props[P_RUN_AT] = {"date": {"start": str(item["run_at"])}}
    if item.get("ai_summary"):
        props[P_SUMMARY] = {"rich_text": [{"text": {"content": str(item["ai_summary"])[:2000]}}]}
    if item.get("ai_notes"):
        props[P_NOTES] = {"rich_text": [{"text": {"content": str(item["ai_notes"])[:2000]}}]}

    try:
        get_client().pages.create(parent={"database_id": db_id}, properties=props)
        return True
    except APIResponseError as e:
        print(f"[notion] 写入失败: {e}")
        return False


def sync(db_id: str, items: list[dict]) -> tuple[int, int]:
    """批量入库，返回 (新增, 跳过)。"""
    existing = get_existing_urls(db_id)
    added = skipped = 0

    for item in items:
        url = item.get("url") or ""
        if not url or url in existing:
            skipped += 1
            continue
        if push_item(db_id, item):
            added += 1
            existing.add(url)
        else:
            skipped += 1

    return added, skipped


def fetch_feedback_rows(db_id: str, positive: list[str], negative: list[str]) -> dict:
    """把库里被标成 Saved/Skip 的条目捞出来，喂给 memory 做偏好学习。"""
    fb = {"positive": [], "negative": []}

    for page in _iter_pages(db_id):
        props = page.get("properties", {})
        status = ((props.get(P_STATUS) or {}).get("select") or {}).get("name") or ""
        title = "".join(
            t.get("plain_text", "")
            for t in ((props.get(P_NAME) or {}).get("title") or [])
        ).strip()

        if not title:
            continue
        if status in positive:
            fb["positive"].append(title[:200])
        elif status in negative:
            fb["negative"].append(title[:200])

    return fb


def update_ai_fields(page_id: str, score: int, summary: str, notes: str) -> bool:
    try:
        get_client().pages.update(
            page_id=page_id,
            properties={
                P_SCORE: {"number": int(score)},
                P_SUMMARY: {"rich_text": [{"text": {"content": summary[:2000]}}]},
                P_NOTES: {"rich_text": [{"text": {"content": notes[:2000]}}]},
            },
        )
        return True
    except APIResponseError as e:
        print(f"[notion] 更新失败 {page_id}: {e}")
        return False


def missing_ai_rows(db_id: str, limit: int = 50) -> list[dict]:
    """AI Score 为空的行，供 enrich_existing.py 回填。"""
    rows: list[dict] = []
    cursor = None

    while len(rows) < limit:
        resp = get_client().databases.query(
            database_id=db_id,
            page_size=min(100, limit - len(rows)),
            filter={"property": P_SCORE, "number": {"is_empty": True}},
            **(dict(start_cursor=cursor) if cursor else {}),
        )
        for page in resp.get("results", []):
            props = page.get("properties", {})
            rows.append(
                {
                    "_page_id": page["id"],
                    "name": "".join(
                        t.get("plain_text", "")
                        for t in ((props.get(P_NAME) or {}).get("title") or [])
                    ),
                    "url": (props.get(P_URL) or {}).get("url"),
                    "source": ((props.get(P_SOURCE) or {}).get("select") or {}).get("name"),
                    "date_found": ((props.get(P_DATE) or {}).get("date") or {}).get("start"),
                }
            )
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")

    return rows[:limit]
