"""基于规则的快速预过滤，跑在 AI 之前，省 Gemini 额度。"""
from pathlib import Path

import yaml

_ROOT = Path(__file__).parent.parent
_config = None


def _cfg() -> dict:
    global _config
    if _config is None:
        _config = yaml.safe_load((_ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    return _config


def filters() -> dict:
    return _cfg().get("filters") or {}


def is_relevant(text: str) -> bool:
    """命中 blocked 一律丢弃；配了 required 则必须命中其中之一。"""
    cfg = filters()
    low = (text or "").lower()

    if any(k.lower() in low for k in cfg.get("blocked_keywords") or []):
        return False

    required = [k.lower() for k in cfg.get("required_keywords") or []]
    if required and not any(k in low for k in required):
        return False

    return True
