"""
gemini.py — pemanggil Gemini via REST API (pakai httpx, tanpa SDK berat).

Kenapa REST, bukan google-generativeai?
- SDK resmi menarik cryptography + grpcio + protobuf yang butuh kompilasi Rust,
  dan itu gagal di Termux (Android). REST cukup pakai httpx (pure-Python).

Format contents mengikuti REST Gemini:
  [{"role": "user"|"model", "parts": [{"text": "..."}]}]
"""

from __future__ import annotations

import httpx

BASE = "https://generativelanguage.googleapis.com/v1beta"


async def generate(
    api_key: str,
    model: str,
    contents: list[dict],
    system_prompt: str | None = None,
    timeout: float = 90.0,
) -> str:
    """Panggil generateContent dan kembalikan teks jawaban."""
    url = f"{BASE}/models/{model}:generateContent"
    payload: dict = {"contents": contents}
    if system_prompt:
        payload["system_instruction"] = {"parts": [{"text": system_prompt}]}

    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(url, params={"key": api_key}, json=payload)

    if r.status_code != 200:
        # Coba ambil pesan error dari body
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
        if block:
            return f"(Jawaban diblokir oleh filter Gemini: {block})"
        return "(Tidak ada jawaban dari model.)"

    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    return text or "(Jawaban kosong.)"


def user_msg(text: str) -> dict:
    return {"role": "user", "parts": [{"text": text}]}


def model_msg(text: str) -> dict:
    return {"role": "model", "parts": [{"text": text}]}
