#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

import logging
from typing import Any
from urllib.parse import urlsplit

import requests

from common.http_client import DEFAULT_TIMEOUT
from rag.nlp import rag_tokenizer
from rag.utils.web_evidence import normalize_web_evidence

logger = logging.getLogger(__name__)
SEARCH1API_SEARCH_URL = "https://api.search1api.com/search"


class Search1API:
    @staticmethod
    def services_for(channel: str) -> set[str]:
        return {
            "general": {"google", "bing", "bingcn", "duckduckgo", "yahoo", "yandex", "youtube", "x", "reddit", "github", "arxiv", "wechat", "bilibili", "imdb", "wikipedia", "baidu", "360", "quark"},
            "news": {"google", "bing", "duckduckgo", "yahoo", "hackernews", "reuters"},
        }.get(channel, set())

    def __init__(self, api_key: str):
        self.api_key = api_key

    def _request(self, endpoint: str, payload: dict, timeout=DEFAULT_TIMEOUT) -> dict:
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise ValueError("Search1API api_key is required")
        try:
            response = requests.post(
                f"https://api.search1api.com/{endpoint}",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key.strip()}",
                    "User-Agent": "RAGFlow search1api-integration/infiniflow-ragflow",
                },
                json=payload,
                timeout=timeout,
                allow_redirects=False,
            )
            if 300 <= getattr(response, "status_code", 200) < 400:
                raise ValueError("Search1API redirects are not supported")
            response.raise_for_status()
            data = response.json()
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else "unknown"
            raise ValueError(f"Search1API upstream returned HTTP {status}") from None
        except (requests.RequestException, TypeError, ValueError):
            raise ValueError("Search1API request or response failed") from None
        if not isinstance(data, dict):
            raise TypeError("Search1API response must be an object")
        return data

    def search_results(self, query: str, *, channel="general", search_service="", time_range="any", max_results=10) -> list[dict]:
        if channel not in {"general", "news"} or (search_service and search_service not in self.services_for(channel)):
            raise ValueError("Search1API channel or search_service is not supported")
        if time_range not in {"any", "day", "week", "month", "year"}:
            raise ValueError("Search1API time_range is not supported")
        count = min(max(int(max_results), 1), 50)
        payload = {"query": query, "max_results": count}
        if search_service:
            payload["search_service"] = search_service
        if time_range != "any":
            payload["time_range"] = time_range
        data = self._request("news" if channel == "news" else "search", payload)
        results = data.get("results", [])
        if not isinstance(results, list):
            raise TypeError("Search1API results must be an array")
        return [item for item in results if isinstance(item, dict)][:count]

    def crawl(self, url: str) -> dict:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("Search1API crawl URL is required")
        url = url.strip()
        try:
            parsed = urlsplit(url)
            valid = parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password and (parsed.port is None or parsed.port > 0)
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Search1API crawl requires an absolute HTTP(S) URL without credentials")
        data = self._request("crawl", {"url": url}, timeout=60)
        results = data.get("results")
        if not isinstance(results, dict):
            raise TypeError("Search1API crawl response must contain a page object")
        return results

    def search(self, query: str) -> list[dict[str, Any]]:
        try:
            data = self._request("search", {"query": query, "max_results": 6})
            results = data.get("results", [])
            if not isinstance(results, list):
                raise TypeError("Search1API results must be an array")
            hits = []
            for result in results:
                if not isinstance(result, dict):
                    continue
                content = result.get("snippet")
                url = result.get("link")
                if not isinstance(content, str) or not content.strip() or not isinstance(url, str) or not url.strip():
                    continue
                hits.append({"content": content.strip(), "url": url.strip(), "title": str(result.get("title") or "")})
                if len(hits) >= 6:
                    break
            return hits
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else "unknown"
            logger.error("Search1API search failed: HTTP %s", status)
        except (requests.RequestException, TypeError, ValueError) as error:
            logger.error("Search1API search failed: %s", type(error).__name__)
        return []

    def retrieve_chunks(self, question: str) -> dict[str, list]:
        chunks, doc_aggs = [], []
        for result in self.search(question):
            chunk_id = "search1api-" + result["url"]
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "doc_id": chunk_id,
                    "content_ltks": rag_tokenizer.tokenize(result["content"]),
                    "content_with_weight": result["content"],
                    "docnm_kwd": result["title"],
                    "kb_id": [],
                    "important_kwd": [],
                    "image_id": "",
                    "similarity": 1.0,
                    "vector_similarity": 1.0,
                    "term_similarity": 0,
                    "vector": [],
                    "positions": [],
                    "url": result["url"],
                }
            )
            doc_aggs.append({"doc_name": result["title"], "doc_id": chunk_id, "count": 1, "url": result["url"]})
        return normalize_web_evidence({"chunks": chunks, "doc_aggs": doc_aggs})
