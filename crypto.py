"""
crypto.py — sumber data crypto realtime & on-chain untuk ai-agent-v2.

API yang dipakai (semuanya GRATIS, tanpa API key):
- CoinGecko   : harga realtime, market cap, perubahan 24 jam
- DexScreener : data pair DEX (harga, likuiditas, volume, umur token, txns) + token baru
- RugCheck    : analisa risiko rug + sebaran holder (anti-whale) untuk token Solana

Semua fungsi async, memakai httpx (sudah ikut terinstall bareng python-telegram-bot).
"""

from __future__ import annotations

import time
from typing import Any

import httpx

CG_BASE = "https://api.coingecko.com/api/v3"
DEX_BASE = "https://api.dexscreener.com"
RUG_BASE = "https://api.rugcheck.xyz/v1"

_HEADERS = {"User-Agent": "ai-agent-v2/1.0 (+https://github.com/sixdevilxd)"}


async def _get_json(url: str, params: dict | None = None, timeout: float = 25.0) -> Any:
    async with httpx.AsyncClient(timeout=timeout, headers=_HEADERS, follow_redirects=True) as c:
        r = await c.get(url, params=params)
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Helper format
# ---------------------------------------------------------------------------
def fmt_usd(x: Any) -> str:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "-"
    if x == 0:
        return "$0"
    if abs(x) >= 1:
        return f"${x:,.2f}"
    # harga sangat kecil (meme coin)
    return f"${x:,.10f}".rstrip("0").rstrip(".")


def fmt_big(x: Any) -> str:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "-"
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(x) >= div:
            return f"${x/div:.2f}{unit}"
    return f"${x:,.0f}"


def fmt_age(ms: Any) -> str:
    try:
        secs = time.time() - float(ms) / 1000.0
    except (TypeError, ValueError):
        return "-"
    if secs < 3600:
        return f"{int(secs//60)} menit"
    if secs < 86400:
        return f"{secs/3600:.1f} jam"
    return f"{secs/86400:.1f} hari"


# ---------------------------------------------------------------------------
# CoinGecko — harga realtime
# ---------------------------------------------------------------------------
async def get_price(query: str) -> dict | None:
    """Cari coin di CoinGecko lalu ambil harga realtime + market cap."""
    search = await _get_json(f"{CG_BASE}/search", {"query": query})
    coins = search.get("coins") or []
    if not coins:
        return None
    coin = coins[0]
    coin_id = coin["id"]
    data = await _get_json(
        f"{CG_BASE}/simple/price",
        {
            "ids": coin_id,
            "vs_currencies": "usd",
            "include_market_cap": "true",
            "include_24hr_vol": "true",
            "include_24hr_change": "true",
        },
    )
    d = data.get(coin_id, {})
    return {
        "id": coin_id,
        "name": coin.get("name"),
        "symbol": (coin.get("symbol") or "").upper(),
        "rank": coin.get("market_cap_rank"),
        "price": d.get("usd"),
        "market_cap": d.get("usd_market_cap"),
        "vol24": d.get("usd_24h_vol"),
        "change24": d.get("usd_24h_change"),
    }


# ---------------------------------------------------------------------------
# DexScreener — data pair & token baru
# ---------------------------------------------------------------------------
async def dex_token(address: str) -> dict | None:
    """Ambil pair terbaik (likuiditas tertinggi) untuk sebuah token address."""
    data = await _get_json(f"{DEX_BASE}/latest/dex/tokens/{address}")
    pairs = data.get("pairs") or []
    if not pairs:
        return None
    best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd", 0) or 0)
    return best


async def new_meme_tokens(limit: int = 8) -> list[dict]:
    """Token yang baru muncul profilnya di DexScreener (kandidat meme coin baru)."""
    data = await _get_json(f"{DEX_BASE}/token-profiles/latest/v1")
    items = data if isinstance(data, list) else data.get("data", [])
    out = []
    for it in items[:limit]:
        out.append(
            {
                "chain": it.get("chainId"),
                "address": it.get("tokenAddress"),
                "description": (it.get("description") or "").strip(),
                "url": it.get("url"),
            }
        )
    return out


# ---------------------------------------------------------------------------
# RugCheck — risiko rug + sebaran holder (anti-whale) untuk Solana
# ---------------------------------------------------------------------------
async def rugcheck(mint: str) -> dict | None:
    """Laporan RugCheck untuk token Solana (mint address)."""
    try:
        return await _get_json(f"{RUG_BASE}/tokens/{mint}/report")
    except httpx.HTTPStatusError:
        return None


def summarize_rug(report: dict) -> dict:
    """Ringkas laporan RugCheck jadi metrik penting + anti-whale."""
    if not report:
        return {}
    risks = report.get("risks") or []
    top = report.get("topHolders") or []
    # Sebaran holder (abaikan LP/pool yang ditandai)
    holders = [h for h in top if not h.get("insider", False)]
    top1 = holders[0]["pct"] if holders and "pct" in holders[0] else None
    top10 = sum(float(h.get("pct", 0) or 0) for h in top[:10])
    token = report.get("token") or {}
    markets = report.get("markets") or []
    lp_locked = None
    if markets:
        lp = markets[0].get("lp") or {}
        lp_locked = lp.get("lpLockedPct")
    return {
        "score": report.get("score_normalised", report.get("score")),
        "risks": [
            {"name": r.get("name"), "level": r.get("level"), "desc": r.get("description")}
            for r in risks
        ],
        "mint_authority": token.get("mintAuthority"),
        "freeze_authority": token.get("freezeAuthority"),
        "total_holders": report.get("totalHolders"),
        "top1_pct": top1,
        "top10_pct": round(top10, 2) if top10 else None,
        "lp_locked_pct": lp_locked,
        "top_holders": [
            {"pct": round(float(h.get("pct", 0) or 0), 2), "insider": h.get("insider", False)}
            for h in top[:5]
        ],
    }


# ---------------------------------------------------------------------------
# Kumpulkan semua fakta untuk Deep Research Pro
# ---------------------------------------------------------------------------
async def deep_research_facts(address: str) -> dict:
    """Gabungkan data DexScreener + RugCheck untuk satu token."""
    facts: dict = {"address": address}
    pair = await dex_token(address)
    if pair:
        facts["dex"] = {
            "name": (pair.get("baseToken") or {}).get("name"),
            "symbol": (pair.get("baseToken") or {}).get("symbol"),
            "chain": pair.get("chainId"),
            "dex": pair.get("dexId"),
            "price_usd": pair.get("priceUsd"),
            "change": pair.get("priceChange") or {},
            "volume": pair.get("volume") or {},
            "liquidity_usd": (pair.get("liquidity") or {}).get("usd"),
            "fdv": pair.get("fdv"),
            "market_cap": pair.get("marketCap"),
            "age": fmt_age(pair.get("pairCreatedAt")),
            "txns": pair.get("txns") or {},
            "url": pair.get("url"),
        }
    # RugCheck hanya relevan untuk Solana
    chain = (facts.get("dex") or {}).get("chain", "")
    if chain in ("solana", "") :
        report = await rugcheck(address)
        if report:
            facts["rug"] = summarize_rug(report)
    return facts


# ---------------------------------------------------------------------------
# New pairs scanner — GeckoTerminal (GMGN diblokir Cloudflare untuk bot)
# ---------------------------------------------------------------------------
GECKO = "https://api.geckoterminal.com/api/v2"


async def new_pairs(network: str = "solana", limit: int = 12) -> list[dict]:
    """Ambil pool/pair yang baru dibuat di sebuah chain (default Solana)."""
    data = await _get_json(f"{GECKO}/networks/{network}/new_pools", {"page": 1})
    out = []
    for d in (data.get("data") or [])[:limit]:
        a = d.get("attributes") or {}
        rel = d.get("relationships") or {}
        bt = (((rel.get("base_token") or {}).get("data") or {}).get("id") or "")
        addr = bt.split("_", 1)[1] if "_" in bt else None
        vol = a.get("volume_usd") or {}
        out.append(
            {
                "id": d.get("id"),
                "name": a.get("name"),
                "address": addr,
                "pool": a.get("address"),
                "created_at": a.get("pool_created_at"),
                "price": a.get("base_token_price_usd"),
                "fdv": a.get("fdv_usd"),
                "liq": a.get("reserve_in_usd"),
                "vol_m5": vol.get("m5"),
                "url": f"https://www.geckoterminal.com/{network}/pools/{a.get('address')}",
            }
        )
    return out
