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
    priority_text = "\n".join(f"- {p}" for p in priorities)

    return f"""你在为一位中文自媒体作者筛选选题素材。分析下面 {len(batch)} 条内容，返回 JSON。

# Items
hours_ago = 发布距今多少小时；heat = 平台热度值；comments = 评论数；rank = 榜单排名（越小越热）
{items_text}

# 作者情况
{context[:800] if context else "未提供"}

# 作者的优先级
{priority_text}

{preference_prompt}

# 评分规则（严格执行，不要客气）
1. 只留中文内容。纯英文、纯海外且与国内无关的 → score ≤ 20。
2. 海外内容只有在明确影响国内（政策监管、产业链、大厂动作、资本、普通人生活）时才可到 70+。
3. 时效：hours_ago ≤ 24 → 可给 85+；≤ 48 → 最高 80；48–72 → 最高 45；> 72 → ≤ 35。
4. 热度：comments ≥ 1000、或 heat 很高、或 rank ≤ 10，才可能是高分。评论多 = 大众真的在讨论。
5. 只有小圈子知道的不算热点：行业内部消息、极客向技术细节、小众产品发布 → ≤ 50。
6. 素材价值：能撑起一条短视频/公众号选题（有冲突、有情绪、有观点可讲）加分。

# 输出格式
Return: {{"analyses": [{{"score": <0-100>, "summary": "<中文，40 字以内讲清这条是什么>", "notes": "<中文，30 字以内说为什么>"}} for each item in order]}}
输出务必精简，不要解释，不要 markdown。"""
