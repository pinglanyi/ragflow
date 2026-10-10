import ast
import logging
from pathlib import Path
from unittest.mock import Mock

import pytest


def storage(bucket=None, prefix=None):
    source = Path(__file__).resolve().parents[4] / "rag/utils/oss_conn.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RAGFlowOSS")
    cls.decorator_list = []
    cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in ("_resolve_path", "copy", "move")]
    namespace = {"logging": logging}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(source), "exec"), namespace)  # noqa: S102 - execute trusted repository definitions in an isolated test scope
    instance = namespace["RAGFlowOSS"]()
    instance.bucket, instance.prefix_path, instance.conn = bucket, prefix, Mock()
    return instance


@pytest.mark.parametrize("bucket,prefix", [(None, None), ("shared", "中文 prefix")])
def test_copy_preserves_raw_keys_for_sdk_encoding(bucket, prefix):
    oss = storage(bucket, prefix)
    key = "文档/a b+%2F?.pdf"
    assert oss.copy("source", key, "destination", key)
    resolved = f"{prefix}/{key}" if prefix else key
    oss.conn.copy_object.assert_called_once_with(
        CopySource={"Bucket": bucket or "source", "Key": resolved},
        Bucket=bucket or "destination", Key=resolved,
    )


def test_failed_copy_does_not_delete_source():
    oss = storage()
    oss.conn.copy_object.side_effect = RuntimeError("unavailable")
    assert oss.move("a", "source", "b", "dest") is False
    oss.conn.delete_object.assert_not_called()


def test_move_copies_before_deleting_and_reports_delete_failure():
    oss = storage("shared", "prefix")
    assert oss.move("a", "source", "b", "dest")
    assert [call[0] for call in oss.conn.mock_calls] == ["copy_object", "delete_object"]
    oss.conn.delete_object.assert_called_once_with(Bucket="shared", Key="prefix/source")
    oss.conn.delete_object.side_effect = RuntimeError("denied")
    assert oss.move("a", "source", "b", "dest") is False
