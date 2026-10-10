import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace


def test_empty_query_clears_previous_json_results():
    path = Path(__file__).resolve().parents[4] / "agent/tools/retrieval.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Retrieval")
    fn = next(node for node in cls.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_invoke_async")
    fn.decorator_list = []
    scope = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), "exec"), scope)  # noqa: S102 - trusted repository function
    outputs = {"json": [{"id": "previous"}]}
    tool = SimpleNamespace(
        _param=SimpleNamespace(empty_response="no evidence"),
        check_if_canceled=lambda _: False,
        set_output=lambda key, value: outputs.update({key: value}),
    )
    asyncio.run(scope["_invoke_async"](tool, query=""))
    assert outputs == {"json": [], "formalized_content": "no evidence"}
