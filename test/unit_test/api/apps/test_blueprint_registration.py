"""Check route registration without importing database or model services."""

import ast
from pathlib import Path
import unittest

from quart import Blueprint, Quart


class BlueprintRegistrationTest(unittest.TestCase):
    def test_all_page_blueprints_register_without_endpoint_collisions(self):
        root = Path(__file__).resolve().parents[4] / "api" / "apps"
        paths = sorted(set(root.glob("*_app.py")) | set(root.glob("restful_apis/*.py")) | set(root.glob("sdk/*.py")))
        for path in paths:
            with self.subTest(page=path.name):
                blueprint = Blueprint(path.stem, __name__)
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in tree.body:
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    async def view(**kwargs):
                        return "ok"
                    view.__name__ = node.name
                    for decorator in node.decorator_list:
                        if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                                and isinstance(decorator.func.value, ast.Name)
                                and decorator.func.value.id == "manager" and decorator.func.attr == "route"):
                            continue
                        rule = ast.literal_eval(decorator.args[0])
                        options = {kw.arg: ast.literal_eval(kw.value) for kw in decorator.keywords}
                        blueprint.route(rule, **options)(view)
                app = Quart(__name__)
                app.register_blueprint(blueprint)


if __name__ == "__main__":
    unittest.main()
