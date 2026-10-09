import ast
import json
import logging
import os
from copy import deepcopy
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[4]


def load_classes(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    nodes = [n for n in tree.body if getattr(n, "name", None) in names or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in n.targets)]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, "exec"), namespace)  # noqa: S102 - execute trusted local definitions without optional SDKs
    return namespace


def test_opper_registered_and_routes_openai_gateway():
    ns = load_classes("rag/llm/__init__.py", {"SupportedLiteLLMProvider", "FACTORY_DEFAULT_BASE_URL", "LITELLM_PROVIDER_PREFIX"}, {"StrEnum": StrEnum})
    assert ns["FACTORY_DEFAULT_BASE_URL"].get("Opper") == "https://api.opper.ai/v3/compat"
    assert ns["LITELLM_PROVIDER_PREFIX"].get("Opper") == "openai/"
    source = ast.parse((ROOT / "rag/llm/chat_model.py").read_text(encoding="utf-8"))
    cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == "LiteLLMBase")
    factories = ast.literal_eval(cls.body[0].value)
    assert "Opper" in factories


@pytest.mark.parametrize("file,name,parent", [("embedding_model.py", "OpperEmbed", "OpenAIEmbed"), ("cv_model.py", "OpperCV", "GptV4"), ("model_meta.py", "Opper", "OpenAIAPICompatible")])
def test_opper_drivers_preserve_compat_path(file, name, parent):
    class Parent:
        def __init__(self, *args, **kwargs):
            self.args, self.kwargs = args, kwargs
            self.base_url = args[1] if len(args) > 1 else kwargs.get("base_url")

    ns = load_classes("rag/llm/" + file, {name}, {parent: Parent, "ClassVar": ClassVar})
    assert name in ns
    obj = ns[name]("test-key", "test-model") if name != "Opper" else ns[name]("test-key")
    assert obj._FACTORY_NAME == "Opper"
    if name == "Opper":
        assert obj._get_model_list_url() == "https://api.opper.ai/v3/compat/models"
    else:
        assert obj.kwargs["base_url"] == "https://api.opper.ai/v3/compat"


@pytest.mark.parametrize("provider,filename", [("Opper", "opper.json"), ("SILICONFLOW", "siliconflow.json")])
def test_python_catalog_exposes_every_upstream_model_type(provider, filename):
    factories = json.loads((ROOT / "conf/llm_factories.json").read_text(encoding="utf-8"))["factory_llm_infos"]
    factory = next((f for f in factories if f["name"] == provider), None)
    assert factory is not None
    catalog = json.loads((ROOT / "conf/models" / filename).read_text(encoding="utf-8"))
    registered = {
        (m["llm_name"], {"image2text": "vision", "speech2text": "asr"}.get(kind, kind))
        for m in factory["llm"]
        for kind in (m["model_type"] if isinstance(m["model_type"], list) else [m["model_type"]])
    }
    for model in catalog["models"]:
        for kind in model["model_types"]:
            assert (model["name"], "vision" if kind == "ocr" else kind) in registered


def test_opper_builds_real_litellm_request_with_gateway_base():
    ns = load_classes("rag/llm/__init__.py", {"SupportedLiteLLMProvider", "FACTORY_DEFAULT_BASE_URL", "LITELLM_PROVIDER_PREFIX"}, {"StrEnum": StrEnum})
    ns.update(
        deepcopy=deepcopy,
        os=os,
        json=json,
        JSONDecodeError=json.JSONDecodeError,
        logger=logging.getLogger(__name__),
        current_llm_user=lambda: None,
        _apply_model_family_policies=lambda model, **kw: (kw["gen_conf"], {}),
    )
    load_classes("rag/llm/chat_model.py", {"_move_litellm_provider_body_fields"}, ns)
    tree = ast.parse((ROOT / "rag/llm/chat_model.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "LiteLLMBase")
    cls.bases = []
    cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in {"__init__", "_is_dashscope_family_provider", "_targets_openai_compatible_endpoint", "_construct_completion_args"}]
    exec(compile(ast.Module(body=[cls], type_ignores=[]), "chat_model", "exec"), ns)  # noqa: S102 - execute trusted local definitions without optional SDKs
    chat = ns["LiteLLMBase"]("secret", "claude-sonnet-4-6", provider="Opper")
    args = chat._construct_completion_args([{"role": "user", "content": "hello"}], stream=False, tools=False)
    assert args["model"] == "openai/claude-sonnet-4-6"
    assert args["api_base"] == "https://api.opper.ai/v3/compat"
    assert args["api_key"] == "secret"


def test_opper_embedding_uses_openai_embedding_request():
    from types import SimpleNamespace
    from urllib.parse import urlparse

    class Client:
        def __init__(self, **kwargs):
            self.base_url = kwargs["base_url"]
            self.embeddings = SimpleNamespace(create=self.create)

        def create(self, **kwargs):
            self.sent = kwargs
            return SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.2, 0.8])])

    ns = {
        "Base": object,
        "OpenAI": Client,
        "ensure_v1": lambda url: url,
        "urlparse": urlparse,
        "openai_user_kwargs": dict,
        "_sorted_by_index": lambda data: sorted(data, key=lambda d: d.index),
        "total_token_count_from_response": lambda r: 2,
    }
    ns = load_classes("rag/llm/embedding_model.py", {"OpenAIEmbed", "OpperEmbed"}, ns)
    model = ns["OpperEmbed"]("secret", "text-embedding-3-small")
    vectors, tokens = model._call(["hello"])
    assert model.client.base_url == "https://api.opper.ai/v3/compat"
    assert model.client.sent == {"input": ["hello"], "model": "text-embedding-3-small", "encoding_format": "float"}
    assert vectors == [[0.2, 0.8]] and tokens == 2


def test_siliconflow_asr_is_registered_with_compatible_endpoint():
    class Parent:
        def __init__(self, key, model_name, **kwargs):
            self.base_url = kwargs["base_url"]

    ns = load_classes("rag/llm/sequence2txt_model.py", {"SiliconFlowSeq2txt"}, {"GPTSeq2txt": Parent})
    assert "SiliconFlowSeq2txt" in ns
    model = ns["SiliconFlowSeq2txt"]("secret", "FunAudioLLM/SenseVoiceSmall")
    assert model._FACTORY_NAME == "SILICONFLOW"
    assert model.base_url == "https://api.siliconflow.cn/v1"


def test_siliconflow_unified_catalog_preserves_international_models():
    factories = json.loads((ROOT / "conf/llm_factories.json").read_text(encoding="utf-8"))["factory_llm_infos"]
    domestic = next(f for f in factories if f["name"] == "SILICONFLOW")
    international = next(f for f in factories if f["name"] == "siliconflow_intl")
    assert {m["llm_name"] for m in international["llm"]} <= {m["llm_name"] for m in domestic["llm"]}


def test_siliconflow_does_not_offer_unimplemented_pdf_ocr_driver():
    factories = json.loads((ROOT / "conf/llm_factories.json").read_text(encoding="utf-8"))["factory_llm_infos"]
    factory = next(f for f in factories if f["name"] == "SILICONFLOW")
    for m in factory["llm"]:
        types = m["model_type"] if isinstance(m["model_type"], list) else [m["model_type"]]
        assert "ocr" not in types


def test_opper_discovery_keeps_catalog_capabilities():
    from typing import ClassVar

    class Parent:
        def __init__(self, *a, **kw):
            pass

        def _format_model_list(self, data):
            return [{"name": m["id"], "model_types": ["chat"], "max_tokens": 8192, "features": []} for m in data["data"]]

    ns = load_classes("rag/llm/model_meta.py", {"Opper"}, {"OpenAIAPICompatible": Parent, "ClassVar": ClassVar})
    models = ns["Opper"]("secret")._format_model_list({"data": [{"id": "gpt-5.5"}, {"id": "text-embedding-3-small"}]})
    assert models[0]["model_types"] == ["chat", "vision"]
    assert models[0]["max_tokens"] == 1050000
    assert models[0]["features"] == ["is_tools"]
    assert models[1]["model_types"] == ["embedding"]
    assert models[1]["max_tokens"] == 8191


def test_python_catalog_uses_upstream_context_limits():
    factories = json.loads((ROOT / "conf/llm_factories.json").read_text(encoding="utf-8"))["factory_llm_infos"]
    factory = next(f for f in factories if f["name"] == "SILICONFLOW")
    entries = {m["llm_name"]: m for m in factory["llm"]}
    catalog = json.loads((ROOT / "conf/models/siliconflow.json").read_text(encoding="utf-8"))
    for model in catalog["models"]:
        limit = model.get("context_length", model.get("max_tokens"))
        if limit:
            assert entries[model["name"]]["max_tokens"] == limit
