"""Lightweight web search fallback using DuckDuckGo HTML results."""

from __future__ import annotations

import html
import re
from hashlib import sha1
from typing import Any, Dict, List
from urllib.parse import urlparse

import httpx

from app.config.settings import settings
from app.search.query_expansion import empty_retrieval_stats


_RESULT_PATTERN = re.compile(
    r'<a rel="nofollow" class="result__a" href="(?P<url>[^"]+)".*?>(?P<title>.*?)</a>.*?'
    r'(?:<a class="result__snippet"[^>]*>(?P<snippet_link>.*?)</a>|'
    r'<div class="result__snippet">(?P<snippet_div>.*?)</div>)',
    re.S,
)
_TAG_PATTERN = re.compile(r"<[^>]+>")


def _clean_html(value: str) -> str:
    text = html.unescape(_TAG_PATTERN.sub(" ", value or ""))
    return re.sub(r"\s+", " ", text).strip()


class WebSearch:
    """Fallback web search used when the local knowledge base has no evidence."""

    search_url = "https://html.duckduckgo.com/html/"

    async def search_with_metadata(
        self,
        query: str,
        *,
        max_results: int | None = None,
    ) -> Dict[str, Any]:
        clean_query = (query or "").strip()
        if not clean_query or not settings.search.web_search_enabled:
            return self._empty_result()

        limit = max(1, min(max_results or settings.search.web_search_top_k, 8))
        timeout_seconds = max(5, settings.search.web_search_timeout_seconds)

        try:
            async with httpx.AsyncClient(
                timeout=timeout_seconds,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/135.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            ) as client:
                response = await client.post(self.search_url, data={"q": clean_query})
                response.raise_for_status()
        except Exception as exc:
            print(f"[WebSearch] DuckDuckGo request failed: {exc}")
            return self._empty_result()

        items = self._parse_results(response.text, limit=limit)
        if not items:
            return self._empty_result()

        sources = [
            {
                "id": f"web:{sha1(item['url'].encode('utf-8')).hexdigest()[:16]}",
                "source_type": "web",
                "label": "网络搜索",
                "title": item["title"],
                "content": item["snippet"],
                "document_name": item["domain"],
                "url": item["url"],
            }
            for item in items
        ]
        stats = empty_retrieval_stats()
        stats["web_hits"] = len(items)
        stats["evidence_total"] = len(sources)
        stats["knowledge_backed"] = len(sources) > 0

        return {
            "items": items,
            "context": self.format_context(items),
            "stats": stats,
            "sources": sources,
            "has_evidence": bool(sources),
        }

    def _parse_results(self, html_text: str, *, limit: int) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        seen_urls: set[str] = set()

        for match in _RESULT_PATTERN.finditer(html_text):
            url = html.unescape((match.group("url") or "").strip())
            title = _clean_html(match.group("title") or "")
            snippet = _clean_html(
                match.group("snippet_link") or match.group("snippet_div") or ""
            )
            if not url or not title or url in seen_urls:
                continue
            if url.startswith("/") or "duckduckgo.com" in url:
                continue

            seen_urls.add(url)
            results.append(
                {
                    "title": title[:160],
                    "url": url,
                    "domain": urlparse(url).netloc or "网页",
                    "snippet": snippet[:320],
                }
            )
            if len(results) >= limit:
                break

        return results

    def format_context(self, items: List[Dict[str, str]]) -> str:
        if not items:
            return "未检索到相关网页结果。"

        parts = ["## 联网搜索结果"]
        for index, item in enumerate(items, start=1):
            snippet = item.get("snippet") or "未提供摘要。"
            parts.append(
                f"[{index}] {item['title']}（来源：{item['domain']}）\n"
                f"链接：{item['url']}\n"
                f"摘要：{snippet}"
            )
        return "\n\n---\n\n".join(parts)

    def _empty_result(self) -> Dict[str, Any]:
        stats = empty_retrieval_stats()
        stats["web_hits"] = 0
        return {
            "items": [],
            "context": "未检索到相关网页结果。",
            "stats": stats,
            "sources": [],
            "has_evidence": False,
        }
