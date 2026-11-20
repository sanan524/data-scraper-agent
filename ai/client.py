"""Gemini REST 客户端：思考预算归零 + 429/5xx 自动降级到更省额度的模型。"""
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

TIMEOUT = 120      # 3.x flash 偶尔要 30~60 秒，60 秒会把整批丢掉
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
        parsed = _call_once(m, api_key, prompt, m)
        if parsed:
            return parsed

    return {}


def _call_once(model: str, api_key: str, prompt: str, label: str):
    """返回 dict 表示成功；None 表示这个模型不可用（调用方负责换模型）。

    只在「超时」时重试同一个模型（网络抖动），429/503 直接换下一个，
    否则会把免费额度浪费在同一个模型的重复请求上。
    """
    for allow_thinking_cfg in (True, False):
        generation = {
            "responseMimeType": "application/json",
            "temperature": 0.3,
            "maxOutputTokens": 4096,
        }
        if allow_thinking_cfg:
            # 关掉"思考"，否则输出预算被推理吃掉，JSON 容易被截断
            # 部分 lite 模型不认这个字段（400），所以下面会去掉了再试一次
            generation["thinkingConfig"] = {"thinkingBudget": 0}

        payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": generation}

        for attempt in (1, 2):
            try:
                resp = requests.post(
                    ENDPOINT.format(model=model),
                    params={"key": api_key},
                    json=payload,
                    timeout=TIMEOUT,
                )
            except requests.Timeout:
                if attempt == 1:
                    print(f"  [AI] {label} 超时（{TIMEOUT}s），重试")
                    continue
                print(f"  [AI] {label} 连续超时，换模型")
                return None
            except requests.RequestException as e:
                print(f"  [AI] {label} 请求失败: {e}")
                return None

            if resp.status_code == 200:
                parsed = _parse(resp)
                if parsed:
                    return parsed
                print(f"  [AI] {label} 返回内容无法解析为 JSON，换下一个模型")
                return None

            if resp.status_code == 400 and allow_thinking_cfg:
                # 该模型不认 thinkingConfig，去掉再试
                break

            if resp.status_code in RETRYABLE:
                print(f"  [AI] {label} -> HTTP {resp.status_code}，换模型")
                return None

            print(f"  [AI] {label} -> HTTP {resp.status_code}: {resp.text[:200]}")
            return None

    return None


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
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, KeyError, IndexError, AttributeError):
        snippet = resp.text[:200] if resp is not None else ""
        print(f"  [AI] 解析失败，原始返回: {snippet}")
        return {}
