"""Exercise the real agent entry with real context and a tool-capable fake model."""

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import test_harness_wiring as wiring

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "rag/advanced_rag/harness"


class EntryTests(unittest.TestCase):
    def setUp(self):
        fixture = wiring.WiringTests()
        fixture.setUp()
        self.ns = fixture.ns
        spec = importlib.util.spec_from_file_location("agent_entry_types", HARNESS / "types.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self.addCleanup(sys.modules.pop, spec.name)
        self.types = module
        self.ns.update(ClaimTarget=module.ClaimTarget, ExecutionStrategy=module.ExecutionStrategy, RESEARCH_AGENT_PROMPT="{claim_description}", RESEARCH_AGENT_TEXT_PROMPT="{claim_description}")
        wiring.load(HARNESS / "agent.py", self.ns)

    def run_entry(self, chunks):
        observed = {}

        class Model:
            is_tools = True

            def bind_tools(self, session, schemas):
                observed["schemas"] = schemas

            async def async_chat(self, system, history, config):
                observed["history"] = history
                return "report"

        tools = SimpleNamespace(kbinfos={"chunks": chunks}, chat_mdl=Model())
        pipeline = self.ns["Pipeline"](tools)
        claim = self.types.ClaimTarget("claim", "Find exceptions")
        context = self.types.OrchestratorContext("q", [claim], "high")
        asyncio.run(self.ns["research_agent_loop"](claim, tools, pipeline, context, self.ns["THINKING_MODES"]["high"], {}))
        return observed

    def test_real_empty_context_does_not_hide_navigation_with_existing_pool(self):
        observed = self.run_entry([{"chunk_id": "source", "doc_id": "doc", "content_with_weight": "MLLM evidence"}])
        names = {d["function"]["name"] for d in observed["schemas"]}
        self.assertIn("inspector_request_adjacent", names)
        self.assertIn("inspector_read_document", names)
        self.assertIn("source", str(observed["history"]))
        self.assertIn("evidence_index", str(observed["history"]))

    def test_empty_start_can_search_then_navigate_in_same_native_binding(self):
        observed = self.run_entry([])
        names = {d["function"]["name"] for d in observed["schemas"]}
        self.assertIn("hybrid_search", names)
        self.assertIn("inspector_request_adjacent", names)

    def test_text_agent_sees_seed_and_rejects_unseen_reference(self):
        observed = {}

        class Model:
            is_tools = False

            async def async_chat(self, system, history, config):
                observed["history"] = history
                return '<tool_call>{"name":"generate_report","arguments":{"report":"done","evidence_ids":[99]}}</tool_call>'

        tools = SimpleNamespace(kbinfos={"chunks": [{"chunk_id": "source", "content_with_weight": "MLLM"}]}, chat_mdl=Model())
        claim = self.types.ClaimTarget("claim", "Find exceptions")
        ctx = self.types.OrchestratorContext("q", [claim], "high")
        result = asyncio.run(self.ns["research_agent_loop"](claim, tools, self.ns["Pipeline"](tools), ctx, self.ns["THINKING_MODES"]["high"], {}))
        self.assertIn("source", str(observed["history"]))
        self.assertIn("evidence_index", str(observed["history"]))
        self.assertEqual(result["evidence_ids"], [0])


if __name__ == "__main__":
    unittest.main()
