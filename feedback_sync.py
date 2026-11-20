"""把 Notion 里的 Saved / Skip 决策同步到 data/feedback.json。

正常轮次里 scraper/main.py 会自动做这一步，
这个脚本只是让你想单独刷新偏好时手动跑：
    python feedback_sync.py
"""
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

_ROOT = Path(__file__).parent
load_dotenv(_ROOT / ".env")

from ai.memory import save_feedback  # noqa: E402
from storage.notion_sync import fetch_feedback_rows  # noqa: E402


def main() -> None:
    db_id = os.environ.get("NOTION_DATABASE_ID", "").strip()
    if not db_id:
        print("ERROR: NOTION_DATABASE_ID 未设置")
        sys.exit(1)

    config = yaml.safe_load((_ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    fb_cfg = config.get("feedback") or {}

    fb = fetch_feedback_rows(
        db_id,
        fb_cfg.get("positive_statuses") or [],
        fb_cfg.get("negative_statuses") or [],
    )
    save_feedback(fb)
    print(f"feedback.json 已更新: +{len(fb['positive'])} / -{len(fb['negative'])}")


if __name__ == "__main__":
    main()
