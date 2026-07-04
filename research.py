"""
research.py — riset web & media sosial untuk ai-agent-v2 (gratis, tanpa API key).

- web_search()     : DuckDuckGo (endpoint 'lite', tanpa key)
- fetch_url()      : ambil & bersihkan teks satu halaman web
- reddit_search()  : Reddit JSON API (fallback ke DDG kalau IP diblokir)
- social_search()  : cari di X/Twitter, Reddit, LinkedIn, Facebook via filter site:

Catatan: X/LinkedIn/Facebook tidak punya API publik gratis, jadi risetnya lewat
hasil mesin pencari (site:domain). Reddit punya JSON API yang biasanya jalan dari
IP residensial (Termux/HP).
"""

from __future__ import annotations

import re
import httpx

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def _clean(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<.*?>", "", html)).strip()


async def web_search(query: str, n: int = 6) -> list[dict]:
    """Cari di DuckDuckGo, kembalikan [{title, url, snippet}]."""
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": UA}, follow_redirects=True) as c:
        r = await c.post("https://lite.duckduckgo.com/lite/", data={"q": query})
    html = r.text
    links = re.findall(
        r"<a rel=\"nofollow\" href=\"(http[^\"]+)\"[^>]*class=['\"]result-link['\"][^>]*>(.*?)</a>",
        html,
        re.S,
    )
    snippets = re.findall(r"<td class=['\"]result-snippet['\"]>(.*?)</td>", html, re.S)
    results = []
    for i, (url, title) in enumerate(links[:n]):
        results.append(
            {
                "title": _clean(title),
                "url": url,
                "snippet": _clean(snippets[i]) if i < len(snippets) else "",
            }
        )
    return results


async def fetch_url(url: str, max_chars: int = 5000) -> str:
    """Ambil isi teks sebuah halaman web (dibersihkan dari tag)."""
    async with httpx.AsyncClient(timeout=25, headers={"User-Agent": UA}, follow_redirects=True) as c:
        r = await c.get(url)
        r.raise_for_status()
    html = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", r.text)
    return _clean(html)[:max_chars]


async def reddit_search(query: str, n: int = 6) -> list[dict] | None:
    """Cari post Reddit via JSON API. Return None kalau diblokir (IP datacenter)."""
    headers = {"User-Agent": "ai-agent-v2/1.0 (crypto research bot)"}
    try:
        async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=True) as c:
            r = await c.get(
                "https://www.reddit.com/search.json",
                params={"q": query, "limit": n, "sort": "relevance", "t": "month"},
            )
            if r.status_code != 200:
                return None
            data = r.json()
    except Exception:  # noqa: BLE001
        return None
    out = []
    for ch in data.get("data", {}).get("children", []):
        d = ch.get("data", {})
        out.append(
            {
                "title": d.get("title"),
                "sub": d.get("subreddit_name_prefixed"),
                "ups": d.get("ups"),
                "comments": d.get("num_comments"),
                "url": "https://reddit.com" + (d.get("permalink") or ""),
                "text": (d.get("selftext") or "")[:300],
            }
        )
    return out


_SITE = {
    "reddit": "reddit.com",
    "linkedin": "linkedin.com",
    "facebook": "facebook.com",
}


async def social_search(platform: str, query: str, n: int = 6) -> list[dict]:
    """Cari di satu platform sosial lewat filter site: DuckDuckGo."""
    p = platform.lower()
    if p in ("x", "twitter"):
        q = f"{query} (site:x.com OR site:twitter.com OR site:nitter.net)"
    elif p in _SITE:
        q = f"site:{_SITE[p]} {query}"
    else:
        q = query
    return await web_search(q, n)
