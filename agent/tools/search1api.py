# Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0

from agent.tools.base import ToolBase, ToolMeta, ToolParamBase
from rag.prompts.generator import kb_prompt
from rag.utils.search1api_conn import Search1API
from rag.utils.web_evidence import normalize_web_evidence


class Search1APISearchParam(ToolParamBase):
    def __init__(self):
        self.meta: ToolMeta = {
            "name": "search1api_search",
            "description": "Search web pages or news with Search1API. Use focused keywords and a service suited to the question.",
            "parameters": {
                "query": {"type": "string", "description": "Search keywords", "default": "{sys.query}", "required": True},
                "channel": {"type": "string", "description": "Web or news search; omit to use node configuration", "enum": ["general", "news"], "default": "general", "required": False},
                "search_service": {
                    "type": "string",
                    "description": "Search service, e.g. google, github or arxiv for general; google or reuters for news. Omit to use node configuration.",
                    "default": "google",
                    "required": False,
                },
                "time_range": {"type": "string", "description": "Result recency", "enum": ["any", "day", "week", "month", "year"], "default": "any", "required": False},
                "max_results": {"type": "integer", "description": "1–50 results; omit to use node Top N", "default": None, "required": False},
            },
        }
        super().__init__()
        self.api_key = ""
        self.top_n = 10
        self.outputs = {"formalized_content": {"value": "", "type": "string"}, "json": {"value": [], "type": "Array<Object>"}}

    def check(self):
        if self.channel not in {"general", "news"}:
            raise ValueError("Search1API channel must be general or news")
        if isinstance(self.top_n, bool) or not isinstance(self.top_n, int) or not 1 <= self.top_n <= 50:
            raise ValueError("Search1API Top N must be an integer from 1 to 50")

    def get_input_form(self):
        return {
            "query": {"name": "Query", "type": "line"},
            "channel": {"name": "Channel", "type": "options", "value": self.channel, "options": ["general", "news"]},
            "time_range": {"name": "Time range", "type": "options", "value": "any", "options": ["any", "day", "week", "month", "year"]},
        }


class Search1APISearch(ToolBase):
    component_name = "Search1APISearch"

    def _invoke(self, **kwargs):
        if self.check_if_canceled("Search1API search"):
            return
        self.set_output("_ERROR", "")
        self.set_output("json", [])
        self.set_output("formalized_content", "")
        query = kwargs.get("query", self._param.query)
        if not query or not str(query).strip():
            return ""
        try:
            channel = str(kwargs.get("channel") or self._param.channel).strip().lower()
            service = str(kwargs.get("search_service") or "").strip().lower()
            if not service:
                service = str(self._param.search_service or "").strip().lower()
                if service not in Search1API.services_for(channel):
                    service = ""
            time_range = str(kwargs.get("time_range") or self._param.time_range or "any").strip().lower()
            try:
                count = int(kwargs.get("max_results"))
            except (ValueError, TypeError):
                count = self._param.top_n
            results = Search1API(self._param.api_key).search_results(str(query), channel=channel, search_service=service, time_range=time_range, max_results=count)
            if self.check_if_canceled("Search1API search"):
                return
            chunks = []
            for result in results:
                content = str(result.get("content") or "").strip() or str(result.get("snippet") or "").strip()
                if not content:
                    continue
                chunks.append({"content_with_weight": content[:10000], "docnm_kwd": str(result.get("title") or ""), "url": str(result.get("link") or ""), "similarity": 1.0})
            evidence = normalize_web_evidence({"chunks": chunks, "doc_aggs": []})
            for chunk in evidence["chunks"]:
                chunk["content"] = chunk["content_with_weight"]
            self._canvas.add_reference(evidence["chunks"], evidence["doc_aggs"])
            self.set_output("formalized_content", "\n".join(kb_prompt(evidence, 200000, True)))
            self.set_output("json", results)
            return self.output("formalized_content")
        except (ValueError, TypeError) as error:
            self.set_output("_ERROR", str(error))
            return {"_ERROR": str(error)}

    def thoughts(self):
        return "Searching web pages with Search1API."


class Search1APICrawlParam(ToolParamBase):
    def __init__(self):
        self.meta: ToolMeta = {
            "name": "search1api_crawl",
            "description": "Read one web page with Search1API and return its title, content and metadata.",
            "parameters": {"url": {"type": "string", "description": "Absolute HTTP or HTTPS URL to read", "default": "", "required": True}},
        }
        super().__init__()
        self.api_key = ""
        self.outputs = {"json": {"value": {}, "type": "object"}}

    def check(self):
        pass

    def get_input_form(self):
        return {"url": {"name": "URL", "type": "line"}}


class Search1APICrawl(ToolBase):
    component_name = "Search1APICrawl"

    def _invoke(self, **kwargs):
        if self.check_if_canceled("Search1API crawl"):
            return
        self.set_output("_ERROR", "")
        self.set_output("json", {})
        try:
            page = Search1API(self._param.api_key).crawl(kwargs.get("url") or self._param.url)
            if self.check_if_canceled("Search1API crawl"):
                return
            self.set_output("json", page)
            return page
        except (ValueError, TypeError) as error:
            self.set_output("_ERROR", str(error))
            return {"_ERROR": str(error)}

    def thoughts(self):
        return "Reading a web page with Search1API."
