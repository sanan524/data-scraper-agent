"""一次性自检：确认 .env 齐全、Notion 库的 8 个属性名与类型都对得上。

用法：
    python setup.py
"""
import os
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:  # Windows 控制台默认 GBK，中文/符号会崩，强制 UTF-8
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv

_ROOT = Path(__file__).parent
load_dotenv(_ROOT / ".env")

from notion_client.errors import APIResponseError  # noqa: E402
from storage.notion_sync import REQUIRED_PROPERTIES, get_client  # noqa: E402


def main() -> int:
    ok = True

    # 1) env
    for key in ("NOTION_TOKEN", "NOTION_DATABASE_ID"):
        val = os.environ.get(key, "").strip()
        if val:
            print(f"[env] {key} = {val[:12]}… ({len(val)} chars)")
        else:
            print(f"[env] {key} 缺失")
            ok = False

    gemini = os.environ.get("GEMINI_API_KEY", "").strip()
    print(f"[env] GEMINI_API_KEY = {'已设置' if gemini else '未设置（AI 会被跳过，抓取仍可用）'}")

    if not ok:
        return 1

    # 2) 库连接 + 属性核对
    db_id = os.environ["NOTION_DATABASE_ID"].strip()
    try:
        db = get_client().databases.retrieve(database_id=db_id)
    except APIResponseError as e:
        print(f"[notion] 打不开库 {db_id}: {e}")
        print("        → 检查 DATABASE_ID 是否正确、库是否已 Connect 给这个 integration")
        return 1

    title = "".join(t.get("plain_text", "") for t in db.get("title") or [])
    print(f"[notion] 库可访问：《{title}》")

    props = db.get("properties", {})
    for name, expected in REQUIRED_PROPERTIES.items():
        actual = (props.get(name) or {}).get("type")
        if actual == expected:
            print(f"  [OK] {name:<12} {actual}")
        else:
            print(f"  [NG] {name:<12} 期望 {expected}，实际 {actual or '缺失'}")
            ok = False

    extra = set(props) - set(REQUIRED_PROPERTIES)
    if extra:
        print(f"  · 额外属性（不影响）: {', '.join(sorted(extra))}")

    print("\n结果：" + ("全部通过，可以 python -m scraper.main" if ok else "有问题，先按上面修"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
