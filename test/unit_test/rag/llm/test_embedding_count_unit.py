"""Response cardinality must be checked before vectors can be misaligned."""

import ast
import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[4]


def method(path, owner, name, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner)
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)  # noqa: S102 - trusted local method
    return namespace[name]


@pytest.mark.parametrize("actual", [0, 1, 3])
def test_bundle_rejects_wrong_count_before_returning_partial_vectors(actual):
    encode = method("api/db/services/llm_service.py", "LLMBundle", "encode", {"logging": logging, "num_tokens_from_string": len, "truncate": lambda text, length: text[:length]})
    bundle = SimpleNamespace(langfuse=None, max_length=100, model_config={"llm_name": "test", "llm_factory": "test"}, mdl=SimpleNamespace(encode=lambda texts: (np.ones((actual, 3)), 4)))
    with pytest.raises(ValueError, match="embedding count"):
        encode(bundle, ["one", "two"])


def test_bundle_keeps_valid_vectors_and_empty_input_placeholder():
    seen = []
    vectors = np.array([[1, 2], [3, 4]])
    encode = method("api/db/services/llm_service.py", "LLMBundle", "encode", {"logging": logging, "num_tokens_from_string": len, "truncate": lambda text, length: text[:length]})
    bundle = SimpleNamespace(langfuse=None, max_length=100, model_config={"llm_name": "test", "llm_factory": "test"}, mdl=SimpleNamespace(encode=lambda texts: (seen.extend(texts) or vectors, 7)))
    result, tokens = encode(bundle, ["one", " "])
    assert result is vectors and tokens == 7
    assert seen == ["one", "None"]


def test_provider_batch_count_cannot_compensate_between_batches():
    class ModelException(Exception):
        pass

    class EmbeddingError(ModelException):
        pass

    namespace = {"np": np, "ModelException": ModelException, "EmbeddingError": EmbeddingError, "logger": logging.getLogger(__name__)}
    encode = method("rag/llm/embedding_model.py", "Base", "_batched_encode", namespace)
    calls = []

    def provider(batch):
        calls.append(batch)
        return [[1, 2]], 1

    with pytest.raises(EmbeddingError, match="embedding count"):
        encode(object(), ["a", "b", "c"], provider, batch_size=2)
    assert len(calls) == 1
