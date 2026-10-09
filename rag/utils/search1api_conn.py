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

import requests

from common.http_client import DEFAULT_TIMEOUT
from rag.nlp import rag_tokenizer
from rag.utils.web_evidence import normalize_web_evidence

logger = logging.getLogger(__name__)
SEARCH1API_SEARCH_URL = "https://api.search1api.com/search"


class Search1API:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str) -> list[dict[str, Any]]:
        try:
            response = requests.post(
                SEARCH1API_SEARCH_URL,
                headers={"Accept": "application/json", "Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
                json={"query": query, "max_results": 6},
                timeout=DEFAULT_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise TypeError("Search1API response must be an object")
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
