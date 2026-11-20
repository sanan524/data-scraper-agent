"""协调器：抓取 → 去重 → 反馈同步 → AI 打分 → 入库。

用法：
    python -m scraper.main
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

from scraper.sources import hackernews  # noqa: E402
from storage.notion_sync import fetch_feedback_rows, get_existing_urls, sync  # noqa: E402


def load_config() -> dict:
    return yaml.safe_load((_ROOT / "config.yaml").read_text(encoding="utf-8")) or {}


def ai_enabled(config: dict) -> bool:
    cfg = config.get("ai") or {}
    return bool(os.environ.get("GEMINI_API_KEY", "").strip()) and bool(cfg.get("enabled", True))


def collect(config: dict) -> list[dict]:
    items: list[dict] = []

    hn = (config.get("sources") or {}).get("hackernews") or {}
    if hn.get("enabled", True):
        try:
            got = hackernews.fetch(
                hn.get("queries") or [],
                int(hn.get("hits_per_page", 30)),
            )
            print(f"[Hacker News] {len(got)} items")
            items.extend(got)
        except Exception as e:  # 单源失败不影响其它源
            print(f"[Hacker News] FAILED: {e}")

    return items


def dedupe(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        url = item.get("url") or ""
        if url and url not in seen:
            seen.add(url)
            out.append(item)
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

    # 2) 批内去重
    items = dedupe(items)
    print(f"Unique items in this run: {len(items)}")

    # 3) 跟库里已有的对比，省掉 AI 额度
    try:
        existing = get_existing_urls(db_id)
        fresh = [i for i in items if (i.get("url") or "") not in existing]
        print(f"Already in Notion: {len(items) - len(fresh)} | New: {len(fresh)}")
    except Exception as e:
        print(f"[notion] 读取已有 URL 失败，跳过预去重: {e}")
        fresh = items

    # 4) 单轮上限，防止额度被打爆
    cap = int((config.get("filters") or {}).get("max_items", 20) or 20)
    if len(fresh) > cap:
        print(f"[cap] 本轮只处理前 {cap} 条（config.filters.max_items）")
        fresh = fresh[:cap]

    if not fresh:
        print("Nothing new. Done.")
        return

    # 5) 反馈学习
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

    # 6) 入库
    if "--dry-run" in sys.argv:
        print(f"[dry-run] 不写入。本来会入库 {len(fresh)} 条：")
        for item in fresh[:5]:
            score = item.get("ai_score")
            tag = f"[{score}]" if score is not None else "[--]"
            print(f"  {tag} {item.get('name', '')[:80]}")
        if len(fresh) > 5:
            print(f"  … 还有 {len(fresh) - 5} 条")
        return

    added, skipped = sync(db_id, fresh)
    print(f"Done — {added} new, {skipped} skipped")


if __name__ == "__main__":
    main()
