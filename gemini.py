"""
gemini.py — pemanggil Gemini via REST API (httpx), dengan dukungan function calling.

Kenapa REST, bukan google-generativeai?
- SDK resmi menarik cryptography + grpcio + protobuf yang butuh kompilasi Rust,
  dan itu gagal di Termux (Android). REST cukup pakai httpx (pure-Python).

Format contents mengikuti REST Gemini:
  [{"role": "user"|"model", "parts": [{"text": "..."}]}]
Function calling:
  - kirim payload["tools"] = [{"function_declarations": [...]}]
  - respons bisa berisi part {"functionCall": {"name","args"}}
  - balas dengan part {"functionResponse": {"name","response"}}
"""

from __future__ import annotations

import httpx

BASE = "https://generativelanguage.googleapis.com/v1beta"


async def call(
    api_key: str,
    model: str,
    contents: list[dict],
    system_prompt: str | None = None,
    tools: list[dict] | None = None,
    timeout: float = 90.0,
) -> dict:
    """Panggil generateContent, kembalikan CONTENT kandidat (role+parts)."""
    url = f"{BASE}/models/{model}:generateContent"
    payload: dict = {"contents": contents}
    if system_prompt:
        payload["system_instruction"] = {"parts": [{"text": system_prompt}]}
    if tools:
        payload["tools"] = tools

    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(url, params={"key": api_key}, json=payload)

    if r.status_code != 200:
        try:
            err = r.json().get("error", {}).get("message", r.text)
        except Exception:  # noqa: BLE001
            err = r.text
        raise RuntimeError(f"Gemini API {r.status_code}: {err}")

    data = r.json()
    candidates = data.get("candidates") or []
    if not candidates:
        feedback = data.get("promptFeedback", {})
        block = feedback.get("blockReason")
        msg = f"(Jawaban diblokir: {block})" if block else "(Tidak ada jawaban.)"
        return {"role": "model", "parts": [{"text": msg}]}
    return candidates[0].get("content") or {"role": "model", "parts": [{"text": "(kosong)"}]}


async def generate(
    api_key: str,
    model: str,
    contents: list[dict],
    system_prompt: str | None = None,
    timeout: float = 90.0,
) -> str:
    """Versi sederhana: kembalikan teks saja (tanpa tools)."""
    content = await call(api_key, model, contents, system_prompt, timeout=timeout)
    return extract_text(content) or "(Jawaban kosong.)"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def extract_text(content: dict) -> str:
    return "".join(p.get("text", "") for p in content.get("parts", []) if "text" in p).strip()


def extract_calls(content: dict) -> list[dict]:
    return [p["functionCall"] for p in content.get("parts", []) if "functionCall" in p]


def user_msg(text: str) -> dict:
    return {"role": "user", "parts": [{"text": text}]}


def model_msg(text: str) -> dict:
    return {"role": "model", "parts": [{"text": text}]}


def function_response(name: str, result) -> dict:
    """Bungkus hasil eksekusi tool sebagai functionResponse part."""
    if not isinstance(result, dict):
        result = {"result": result}
    return {"functionResponse": {"name": name, "response": result}}
