"""Gemini REST 客户端，带 429 自动降级到更省额度的模型。"""
import json
import os
import time

import requests

# 从高额度到低额度排列：前一个被打爆就换下一个
MODEL_FALLBACK = [
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.5-flash",
    "gemini-flash-lite-latest",
]

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
            if resp.status_code in (429, 404):
                # 429 = 额度打爆；404 = 该模型在当前 key 下不可用
                print(f"  [AI] {m} -> HTTP {resp.status_code}，降级")
                time.sleep(1)
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
