"""批量 AI 分析：一次调用喂多条，避免打爆免费额度。"""
import json
from pathlib import Path

import yaml

from ai.client import generate

_ROOT = Path(__file__).parent.parent


def analyse_batch(items: list[dict], context: str = "", preference_prompt: str = "") -> list[dict]:
    """返回带 ai_score / ai_summary / ai_notes 的条目列表。"""
    config = yaml.safe_load((_ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    ai_cfg = config.get("ai") or {}

    model = ai_cfg.get("model", "gemini-2.5-flash")
    rate_limit = float(ai_cfg.get("rate_limit_seconds", 7.0))
    min_score = int(ai_cfg.get("min_score", 0) or 0)
    batch_size = max(1, int(ai_cfg.get("batch_size", 5) or 5))

    batches = [items[i : i + batch_size] for i in range(0, len(items), batch_size)]
    print(f"  [AI] {len(items)} items → {len(batches)} API calls")

    enriched: list[dict] = []
    for i, batch in enumerate(batches):
        print(f"  [AI] Batch {i + 1}/{len(batches)}...")
        prompt = _build_prompt(batch, context, preference_prompt, config)
        result = generate(prompt, model=model, rate_limit=rate_limit)

        analyses = result.get("analyses", []) if isinstance(result, dict) else []
        for j, item in enumerate(batch):
            ai = analyses[j] if j < len(analyses) and isinstance(analyses[j], dict) else {}
            if not ai:
                enriched.append(item)
                continue

            score = max(0, min(100, int(ai.get("score", 0) or 0)))
            if min_score and score < min_score:
                continue

            enriched.append(
                {
                    **item,
                    "ai_score": score,
                    "ai_summary": str(ai.get("summary", ""))[:2000],
                    "ai_notes": str(ai.get("notes", ""))[:2000],
                }
            )

    return enriched


def _build_prompt(batch: list[dict], context: str, preference_prompt: str, config: dict) -> str:
    priorities = config.get("priorities") or []
    items_text = "\n\n".join(
        f"Item {i + 1}: {json.dumps({k: v for k, v in item.items() if not str(k).startswith('_')}, ensure_ascii=False)}"
        for i, item in enumerate(batch)
    )

    return f"""Analyse these {len(batch)} items and return a JSON object.

# Items
{items_text}

# User Context
{context[:800] if context else "Not provided"}

# User Priorities
{chr(10).join(f"- {p}" for p in priorities)}

{preference_prompt}

# Instructions
Return: {{"analyses": [{{"score": <0-100>, "summary": "<2 sentences>", "notes": "<why this matches or doesn't>"}} for each item in order]}}
Be concise. Score 90+=excellent match, 70-89=good, 50-69=ok, <50=weak."""
