"""从用户在 Notion 里的决策（Saved/Skip…）反推出打分偏好。"""
import json
from pathlib import Path

_ROOT = Path(__file__).parent.parent
FEEDBACK_PATH = _ROOT / "data" / "feedback.json"


def load_feedback() -> dict:
    if FEEDBACK_PATH.exists():
        try:
            data = json.loads(FEEDBACK_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("positive", [])
                data.setdefault("negative", [])
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"positive": [], "negative": []}


def save_feedback(fb: dict) -> None:
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    FEEDBACK_PATH.write_text(
        json.dumps(fb, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def build_preference_prompt(feedback: dict, max_examples: int = 15) -> str:
    """把反馈历史变成 prompt 里的一段加权说明。"""
    lines = []

    if feedback.get("positive"):
        lines.append("# Items the user LIKED (positive signal):")
        for e in feedback["positive"][-max_examples:]:
            lines.append(f"- {e}")

    if feedback.get("negative"):
        lines.append("\n# Items the user SKIPPED/REJECTED (negative signal):")
        for e in feedback["negative"][-max_examples:]:
            lines.append(f"- {e}")

    if lines:
        lines.append("\nUse these patterns to bias scoring on new items.")

    return "\n".join(lines)
