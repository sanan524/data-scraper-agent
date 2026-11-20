"""回填：把库里 AI Score 为空的历史行补上分数与摘要。

用法：
    python enrich_existing.py            # 最多补 50 条
    python enrich_existing.py --limit 10
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent
load_dotenv(_ROOT / ".env")

from ai.memory import build_preference_prompt, load_feedback  # noqa: E402
from ai.pipeline import analyse_batch  # noqa: E402
from storage.notion_sync import missing_ai_rows, update_ai_fields  # noqa: E402


def main() -> None:
    limit = 50
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    if not os.environ.get("GEMINI_API_KEY", "").strip():
        print("ERROR: GEMINI_API_KEY 未设置")
        sys.exit(1)

    db_id = os.environ.get("NOTION_DATABASE_ID", "").strip()
    if not db_id:
        print("ERROR: NOTION_DATABASE_ID 未设置")
        sys.exit(1)

    rows = missing_ai_rows(db_id, limit=limit)
    print(f"待回填: {len(rows)} 条")
    if not rows:
        return

    context_path = _ROOT / "profile" / "context.md"
    context = context_path.read_text(encoding="utf-8") if context_path.exists() else ""
    preference = build_preference_prompt(load_feedback())

    enriched = analyse_batch(rows, context=context, preference_prompt=preference)

    updated = 0
    for item in enriched:
        page_id = item.get("_page_id")
        if not page_id or item.get("ai_score") is None:
            continue
        if update_ai_fields(
            page_id,
            int(item["ai_score"]),
            str(item.get("ai_summary", "")),
            str(item.get("ai_notes", "")),
        ):
            updated += 1

    print(f"已回填 {updated} 条")


if __name__ == "__main__":
    main()
