"""协调器：抓取 → 去重 → 时效过滤 → 反馈同步 → AI 打分 → 入库。

用法：
    python -m scraper.main
    python -m scraper.main --dry-run     # 不写入，只打印会入库什么
"""
import os
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:  # Windows 控制台默认 GBK，中文/符号会崩，强制 UTF-8
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import yaml
from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env")

from scraper.sources import baidu_hot, bilibili_rank, hackernews, rss, toutiao_hot  # noqa: E402
from storage.notion_sync import fetch_feedback_rows, get_existing_urls, sync  # noqa: E402


def load_config() -> dict:
    return yaml.safe_load((_ROOT / "config.yaml").read_text(encoding="utf-8")) or {}


def ai_enabled(config: dict) -> bool:
    cfg = config.get("ai") or {}
    return bool(os.environ.get("GEMINI_API_KEY", "").strip()) and bool(cfg.get("enabled", True))


def collect(config: dict) -> list[dict]:
    """按 config.sources 逐个源抓，单源失败不影响其它源。"""
    src = config.get("sources") or {}
    items: list[dict] = []

    simple = (
        ("百度热搜", baidu_hot, "baidu_hot"),
        ("头条热榜", toutiao_hot, "toutiao_hot"),
        ("B站排行榜", bilibili_rank, "bilibili_rank"),
    )
    for label, module, key in simple:
        cfg = src.get(key) or {}
        if not cfg.get("enabled", True):
            continue
        try:
            got = module.fetch(int(cfg.get("limit", 30)))
            print(f"[{label}] {len(got)} items")
            items.extend(got)
        except Exception as e:
            print(f"[{label}] FAILED: {e}")

    rss_cfg = src.get("rss") or {}
    if rss_cfg.get("enabled", True):
        try:
            got = rss.fetch(rss_cfg.get("feeds") or [])
            print(f"[RSS] {len(got)} items")
            items.extend(got)
        except Exception as e:
            print(f"[RSS] FAILED: {e}")

    hn = src.get("hackernews") or {}
    if hn.get("enabled", False):
        try:
            got = hackernews.fetch(hn.get("queries") or [], int(hn.get("hits_per_page", 30)))
            print(f"[Hacker News] {len(got)} items")
            items.extend(got)
        except Exception as e:
            print(f"[Hacker News] FAILED: {e}")

    return items


def dedupe(items: list[dict]) -> list[dict]:
    seen_url: set[str] = set()
    seen_name: set[str] = set()
    out: list[dict] = []

    for item in items:
        url = (item.get("url") or "").strip()
        name = (item.get("name") or "").strip()
        # 同一条热点在多平台上榜 → 只留第一条（多平台同时出现本身就是热度信号，
        # 后面 AI 会按第一条的 rank/heat 打分）
        if name and name in seen_name:
            continue
        if url and url in seen_url:
            continue
        if name:
            seen_name.add(name)
        if url:
            seen_url.add(url)
        out.append(item)

    return out


def apply_recency(items: list[dict], max_age_hours: float) -> list[dict]:
    fresh, dropped = [], 0
    for item in items:
        hours = item.get("hours_ago")
        if hours is not None and hours > max_age_hours:
            dropped += 1
            continue
        fresh.append(item)
    if dropped:
        print(f"[时效] 丢弃 {dropped} 条超过 {max_age_hours:g} 小时的内容")
    return fresh


def pick_mixed(items: list[dict], cap: int) -> list[dict]:
    """按来源轮流取，保证一轮里各家都有，而不是被第一个源占满。"""
    buckets: dict[str, list[dict]] = {}
    for it in items:
        buckets.setdefault(it.get("source") or "未知", []).append(it)

    order = list(buckets.keys())
    out: list[dict] = []
    i = 0
    while len(out) < cap and any(buckets[s] for s in order):
        src = order[i % len(order)]
        if buckets[src]:
            out.append(buckets[src].pop(0))
        i += 1
    return out


def main() -> None:
    config = load_config()

    db_id = os.environ.get("NOTION_DATABASE_ID", "").strip()
    if not db_id:
        print("ERROR: NOTION_DATABASE_ID not set")
        sys.exit(1)
    if not os.environ.get("NOTION_TOKEN", "").strip():
        print("ERROR: NOTION_TOKEN not set")
        sys.exit(1)

    # 1) 抓
    items = collect(config)

    # 2) 去重（同标题/同链接只留一条）
    items = dedupe(items)
    print(f"Unique items in this run: {len(items)}")

    # 3) 时效硬过滤
    max_age = float((config.get("filters") or {}).get("max_age_hours", 48) or 48)
    items = apply_recency(items, max_age)

    # 4) 跟库里已有的对比，省掉 AI 额度
    try:
        existing = get_existing_urls(db_id)
        fresh = [i for i in items if (i.get("url") or "") not in existing]
        print(f"Already in Notion: {len(items) - len(fresh)} | New: {len(fresh)}")
    except Exception as e:
        print(f"[notion] 读取已有 URL 失败，跳过预去重: {e}")
        fresh = items

    # 5) 单轮上限：按来源轮流取，避免被第一个源占满
    cap = int((config.get("filters") or {}).get("max_items", 20) or 20)
    if len(fresh) > cap:
        fresh = pick_mixed(fresh, cap)
        print(f"[cap] 本轮取 {len(fresh)} 条（各来源轮流，config.filters.max_items={cap}）")

    if not fresh:
        print("Nothing new. Done.")
        return

    # 6) 反馈学习 + AI 打分
    if ai_enabled(config):
        from ai.memory import build_preference_prompt, load_feedback, save_feedback
        from ai.pipeline import analyse_batch

        fb_cfg = config.get("feedback") or {}
        try:
            fb = fetch_feedback_rows(
                db_id,
                fb_cfg.get("positive_statuses") or [],
                fb_cfg.get("negative_statuses") or [],
            )
            save_feedback(fb)
            print(f"[AI] 反馈样本: +{len(fb['positive'])} / -{len(fb['negative'])}")
        except Exception as e:
            print(f"[AI] 读取反馈失败，用本地缓存: {e}")
            fb = load_feedback()

        preference = build_preference_prompt(fb)
        context_path = _ROOT / "profile" / "context.md"
        context = context_path.read_text(encoding="utf-8") if context_path.exists() else ""

        fresh = analyse_batch(fresh, context=context, preference_prompt=preference)
    else:
        print("[AI] Skipped — GEMINI_API_KEY not set or ai.enabled=false")

    # 7) 入库
    if "--dry-run" in sys.argv:
        print(f"[dry-run] 不写入。本来会入库 {len(fresh)} 条：")
        for item in fresh[:8]:
            score = item.get("ai_score")
            tag = f"[{score}]" if score is not None else "[--]"
            print(f"  {tag} ({item.get('source')}) {item.get('name', '')[:70]}")
        if len(fresh) > 8:
            print(f"  … 还有 {len(fresh) - 8} 条")
        return

    added, skipped = sync(db_id, fresh)
    print(f"Done — {added} new, {skipped} skipped")


if __name__ == "__main__":
    main()
