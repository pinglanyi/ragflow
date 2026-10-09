"""Legacy provider suffixes must resolve only an unambiguous owned model."""

# ruff: noqa: S102 -- execute trusted repository functions without server imports
import ast
import enum
from pathlib import Path
from types import SimpleNamespace

import pytest


def resolver(models):
    source = Path(__file__).resolve().parents[5] / "api/db/joint_services/tenant_model_service.py"
    names = {"split_model_name", "resolve_model_config", "_resolve_legacy_model_config"}
    nodes = [n for n in ast.parse(source.read_text(encoding="utf-8")).body if isinstance(n, ast.FunctionDef) and n.name in names]

    def missing(*args):
        raise LookupError("missing model")

    def by_id(tenant, kind, ref):
        if ref == "valid-id":
            return {"model_id": ref}
        model = next((m for m in models if m.id == ref), None)
        if not model or getattr(model, "status", "active") != "active" or getattr(model, "model_type", kind) != kind:
            raise LookupError("Model unavailable")
        return {"model_id": ref}

    ns = {
        "enum": enum,
        "get_model_config_by_id": by_id,
        "get_model_config_from_provider_instance": missing,
        "TenantModelProviderService": SimpleNamespace(get_by_tenant_id_and_provider_name=lambda tenant, provider: SimpleNamespace(id="owned", provider_name=provider) if tenant == "owner" else None),
        "TenantModelInstanceService": SimpleNamespace(get_all_by_provider_id=lambda provider: [SimpleNamespace(id=inst, status="1") for inst in {m.instance_id for m in models}]),
        "TenantModelService": SimpleNamespace(
            get_by_provider_id_and_instance_id_and_model_name=lambda provider, inst, name: next(
                (m for m in models if m.instance_id == inst and m.model_name == name), None
            ),
            get_by_provider_id_and_instance_id_and_model_type_and_model_name=lambda provider, inst, kind, name: next((m for m in models if m.instance_id == inst and m.model_name == name), None)
        ),
        "ActiveStatusEnum": SimpleNamespace(ACTIVE=SimpleNamespace(value="1")),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), ns)
    return ns["resolve_model_config"]


def test_suffix_binding_resolves_same_model_without_changing_embedding():
    model = SimpleNamespace(id="model-1", instance_id="inst", model_name="qwen3-emb-0_6b")
    assert resolver([model])("owner", "embedding", "qwen3-emb-0_6b___VLLM@default@VLLM") == {"model_id": "model-1"}


@pytest.mark.parametrize(
    "tenant,ref",
    [
        ("other", "qwen3-emb-0_6b___VLLM@default@VLLM"),
        ("owner", "qwen3-emb-0_6b___Other@default@VLLM"),
        ("owner", "missing___VLLM@default@VLLM"),
        ("owner", "qwen3-emb-0_6b___VLLM@explicit@VLLM"),
    ],
)
def test_suffix_binding_rejects_other_scope_or_model(tenant, ref):
    model = SimpleNamespace(id="model-1", instance_id="inst", model_name="qwen3-emb-0_6b")
    with pytest.raises(LookupError):
        resolver([model])(tenant, "embedding", ref)


def test_model_id_wins_over_suffix_recovery():
    assert resolver([])("owner", "embedding", "valid-id") == {"model_id": "valid-id"}


def test_suffix_binding_rejects_ambiguous_instances():
    models = [SimpleNamespace(id=f"model-{index}", instance_id=f"instance-{index}", model_name="qwen3-emb-0_6b") for index in range(2)]
    with pytest.raises(LookupError, match="unique"):
        resolver(models)("owner", "embedding", "qwen3-emb-0_6b___VLLM@default@VLLM")


def test_suffix_binding_does_not_replace_existing_rejected_model():
    models = [
        SimpleNamespace(id="old-disabled", instance_id="inst", model_name="qwen3-emb-0_6b___VLLM", status="inactive"),
        SimpleNamespace(id="bare-active", instance_id="inst", model_name="qwen3-emb-0_6b"),
    ]
    with pytest.raises(LookupError):
        resolver(models)("owner", "embedding", "qwen3-emb-0_6b___VLLM@default@VLLM")


def test_suffix_binding_preserves_existing_active_original_after_instance_rename():
    models = [
        SimpleNamespace(id="original", instance_id="renamed", model_name="qwen3-emb-0_6b___VLLM"),
        SimpleNamespace(id="bare", instance_id="renamed", model_name="qwen3-emb-0_6b"),
    ]
    assert resolver(models)("owner", "embedding", "qwen3-emb-0_6b___VLLM@default@VLLM") == {"model_id": "original"}


def test_suffix_binding_rejects_original_with_wrong_type():
    models = [SimpleNamespace(id="original", instance_id="renamed", model_name="qwen3-emb-0_6b___VLLM", model_type="chat")]
    with pytest.raises(LookupError):
        resolver(models)("owner", "embedding", "qwen3-emb-0_6b___VLLM@default@VLLM")


def test_suffix_binding_rejects_ambiguous_originals():
    models = [SimpleNamespace(id=f"original-{i}", instance_id=f"inst-{i}", model_name="qwen3-emb-0_6b___VLLM") for i in range(2)]
    with pytest.raises(LookupError):
        resolver(models)("owner", "embedding", "qwen3-emb-0_6b___VLLM@default@VLLM")
