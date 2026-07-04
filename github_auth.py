"""
github_auth.py — hubungkan akun GitHub ke bot Telegram lewat OAuth Device Flow.

Kenapa Device Flow?
- Cocok untuk bot/CLI: user cukup buka link GitHub & masukkan kode, TANPA
  paste token ke chat, dan TANPA perlu web server / callback URL.
- Hanya butuh CLIENT_ID (public), tidak butuh client secret.

Setup (sekali saja):
  1. Buat OAuth App di https://github.com/settings/developers
     -> "New OAuth App". Homepage URL bebas (mis. https://github.com/username).
     Authorization callback URL boleh diisi sembarang (device flow tidak memakainya).
  2. Di halaman app, aktifkan "Enable Device Flow".
  3. Salin Client ID, taruh di .env: GITHUB_CLIENT_ID=...

Token per Telegram user disimpan di gh_tokens.json (JANGAN di-commit; sudah di .gitignore).
"""

from __future__ import annotations

import os
import json
import time
import asyncio

import httpx

DEVICE_CODE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
API = "https://api.github.com"

TOKENS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gh_tokens.json")
DEFAULT_SCOPE = "repo read:user"


# ---------------------------------------------------------------------------
# Penyimpanan token (lokal, per Telegram user_id)
# ---------------------------------------------------------------------------
def _load() -> dict:
    if os.path.exists(TOKENS_FILE):
        try:
            with open(TOKENS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save(data: dict) -> None:
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    try:
        os.chmod(TOKENS_FILE, 0o600)  # hanya owner yang bisa baca
    except OSError:
        pass


def get_token(user_id: int | str) -> str | None:
    return _load().get(str(user_id))


def set_token(user_id: int | str, token: str) -> None:
    data = _load()
    data[str(user_id)] = token
    _save(data)


def remove_token(user_id: int | str) -> bool:
    data = _load()
    existed = data.pop(str(user_id), None) is not None
    _save(data)
    return existed


# ---------------------------------------------------------------------------
# OAuth Device Flow
# ---------------------------------------------------------------------------
async def start_device_flow(client_id: str, scope: str = DEFAULT_SCOPE) -> dict:
    """Minta device_code + user_code ke GitHub."""
    async with httpx.AsyncClient(timeout=20, headers={"Accept": "application/json"}) as c:
        r = await c.post(DEVICE_CODE_URL, data={"client_id": client_id, "scope": scope})
        r.raise_for_status()
        return r.json()


async def poll_for_token(client_id: str, device_code: str, interval: int, expires_in: int) -> dict:
    """Poll GitHub sampai user mengizinkan (atau timeout)."""
    deadline = time.time() + expires_in
    wait = max(interval, 5)
    async with httpx.AsyncClient(timeout=20, headers={"Accept": "application/json"}) as c:
        while time.time() < deadline:
            await asyncio.sleep(wait)
            r = await c.post(
                TOKEN_URL,
                data={
                    "client_id": client_id,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
            j = r.json()
            if j.get("access_token"):
                return {"ok": True, "token": j["access_token"]}
            err = j.get("error")
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                wait += int(j.get("interval", 5))
                continue
            if err in ("expired_token", "access_denied", "unsupported_grant_type"):
                return {"ok": False, "error": err}
            # error lain
            return {"ok": False, "error": err or "unknown"}
    return {"ok": False, "error": "timeout"}


async def get_github_user(token: str) -> dict:
    async with httpx.AsyncClient(
        timeout=20,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    ) as c:
        r = await c.get(f"{API}/user")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Aksi GitHub (pakai token user yang sudah /login)
# ---------------------------------------------------------------------------
import base64  # noqa: E402


async def _gh(token: str, method: str, path: str, json_body: dict | None = None, params: dict | None = None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "ai-agent-v2",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as c:
        r = await c.request(method, f"{API}{path}", json=json_body, params=params)
    if r.status_code >= 400:
        try:
            msg = r.json().get("message", r.text)
        except Exception:  # noqa: BLE001
            msg = r.text
        raise RuntimeError(f"GitHub {r.status_code}: {str(msg)[:200]}")
    return r.json() if r.text.strip() else {}


async def list_repos(token: str, limit: int = 30) -> list[dict]:
    data = await _gh(token, "GET", "/user/repos", params={"per_page": limit, "sort": "updated"})
    return [
        {
            "full_name": r.get("full_name"),
            "private": r.get("private"),
            "description": r.get("description"),
            "url": r.get("html_url"),
            "default_branch": r.get("default_branch"),
        }
        for r in (data if isinstance(data, list) else [])
    ]


async def read_file(token: str, owner: str, repo: str, path: str, ref: str | None = None) -> dict:
    params = {"ref": ref} if ref else None
    data = await _gh(token, "GET", f"/repos/{owner}/{repo}/contents/{path}", params=params)
    content = data.get("content", "")
    if data.get("encoding") == "base64" and content:
        try:
            content = base64.b64decode(content).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            content = "(gagal decode)"
    return {"path": data.get("path"), "sha": data.get("sha"), "content": content[:8000]}


async def commit_file(
    token: str, owner: str, repo: str, path: str, content: str, message: str, branch: str | None = None
) -> dict:
    """Buat atau update file (satu commit + push). Otomatis handle sha untuk update."""
    sha = None
    try:
        cur = await _gh(
            token, "GET", f"/repos/{owner}/{repo}/contents/{path}",
            params={"ref": branch} if branch else None,
        )
        sha = cur.get("sha")
    except RuntimeError:
        sha = None  # file belum ada -> buat baru
    body: dict = {"message": message, "content": base64.b64encode(content.encode()).decode()}
    if branch:
        body["branch"] = branch
    if sha:
        body["sha"] = sha
    data = await _gh(token, "PUT", f"/repos/{owner}/{repo}/contents/{path}", json_body=body)
    commit = data.get("commit") or {}
    return {"ok": True, "commit_url": commit.get("html_url"), "sha": commit.get("sha")}


async def create_repo(token: str, name: str, description: str = "", private: bool = False, auto_init: bool = True) -> dict:
    body = {"name": name, "description": description, "private": private, "auto_init": auto_init}
    data = await _gh(token, "POST", "/user/repos", json_body=body)
    return {"full_name": data.get("full_name"), "url": data.get("html_url"), "default_branch": data.get("default_branch")}
