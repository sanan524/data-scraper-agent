"""Gemini REST 客户端，带 429 自动降级到更省额度的模型。"""
import json
import os
import time

import requests

# 从高能力到低额度排列：前一个不可用就换下一个
# 注意：gemini-2.x 系列对新建的 key 已全部下线（404 "no longer available to new users"）
MODEL_FALLBACK = [
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
]

# 这些状态码说明"这个模型现在不行"，换下一个；其它状态码直接放弃
RETRYABLE = (404, 429, 500, 503)

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_last_call = 0.0


def generate(prompt: str, model: str = "", rate_limit: float = 7.0) -> dict:
    """调用 Gemini，返回解析后的 JSON 对象；任何失败都返回 {}。"""
    global _last_call

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return {}

    elapsed = time.time() - _last_call
    if elapsed < rate_limit:
        time.sleep(rate_limit - elapsed)

    models = [model] + [m for m in MODEL_FALLBACK if m != model] if model else MODEL_FALLBACK
    _last_call = time.time()

    for m in models:
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.3,
                "maxOutputTokens": 4096,
            },
        }
        try:
            resp = requests.post(
                ENDPOINT.format(model=m),
                params={"key": api_key},
                json=payload,
                timeout=60,
            )
            if resp.status_code == 200:
                return _parse(resp)
            if resp.status_code in RETRYABLE:
                # 404 = 模型下线；429 = 额度打爆；503 = 高峰期
                print(f"  [AI] {m} -> HTTP {resp.status_code}，降级")
                time.sleep(2)
                continue
            print(f"  [AI] {m} -> HTTP {resp.status_code}: {resp.text[:200]}")
            return {}
        except requests.RequestException as e:
            print(f"  [AI] {m} 请求失败: {e}")
            return {}

    return {}


def _parse(resp: requests.Response) -> dict:
    try:
        text = (
            resp.json()
            .get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
            .strip()
        )
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(text)
    except (json.JSONDecodeError, KeyError, IndexError):
        return {}
