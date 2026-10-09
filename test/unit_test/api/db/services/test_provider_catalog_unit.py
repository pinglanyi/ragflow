"""A model's region selects its endpoint, not an obsolete model catalog."""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[5]


@pytest.mark.parametrize("region", ["default", "intl"])
def test_siliconflow_models_resolve_from_unified_catalog_in_both_regions(region):
    source = ast.parse((ROOT / "api/db/joint_services/tenant_model_service.py").read_text(encoding="utf-8"))
    fn = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == "_lookup_factory_llm_info")
    model = {"llm_name": "Qwen/Qwen3-Embedding-0.6B", "model_type": "embedding"}
    ns = {"settings": SimpleNamespace(FACTORY_LLM_INFOS=[{"name": "SILICONFLOW", "llm": [model]},
                                                       {"name": "siliconflow_intl", "llm": []}])}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "actual-catalog", "exec"), ns)  # noqa: S102 - trusted repository function
    assert ns["_lookup_factory_llm_info"]("SILICONFLOW", model["llm_name"], {"region": region}) == model
