"""HTTP contract tests: real Quart routes, isolated authenticated service seam."""
# ruff: noqa: S102 -- execute only trusted repository AST to isolate external services

import ast
import functools
import io
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from quart import Blueprint, Quart, jsonify, request
from werkzeug.datastructures import FileStorage

ROOT = Path(__file__).resolve().parents[2]


class ApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []

        def submit(*args):
            self.calls.append(("submit", args))
            return {"task_id": "job", "status": "queued"}

        def upload(*args):
            self.calls.append(("upload", args))
            return {"task_id": "job", "document_id": "doc", "status": "queued"}

        class ApiError(Exception):
            def __init__(self, message, status=400, data=None):
                self.status, self.data = status, data
                super().__init__(message)

        def status(*args):
            if args[-1] == "missing":
                raise ApiError("Task not found", 404)
            return {"task_id": args[-1], "status": "complete", "progress": 1}

        def login_required(fn):
            @functools.wraps(fn)
            async def wrapped(*args, **kwargs):
                if request.headers.get("Authorization") != "Bearer test":
                    return jsonify(code=401), 401
                return await fn(*args, **kwargs)

            return wrapped

        def add_tenant(fn):
            @functools.wraps(fn)
            async def wrapped(*args, **kwargs):
                return await fn(*args, tenant_id="tenant", **kwargs)

            return wrapped

        async def thread_pool_exec(fn, *args):
            return fn(*args)

        path = ROOT / "api/apps/restful_apis/multimodal_api.py"
        self.assertTrue(path.is_file(), "Custom multimodal routes are missing")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
        bp = Blueprint("mm", __name__)
        ns = {
            "manager": bp,
            "request": request,
            "jsonify": jsonify,
            "json": json,
            "login_required": login_required,
            "add_tenant_id_to_kwargs": add_tenant,
            "thread_pool_exec": thread_pool_exec,
            "service": SimpleNamespace(submit=submit, upload=upload, status=status, ApiError=ApiError),
        }
        exec(compile(tree, str(path), "exec"), ns)
        self.service = ns["service"]
        self.app = Quart(__name__)
        self.app.register_blueprint(bp, url_prefix="/api/v1")
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer test"}

    async def test_parse_returns_202(self):
        res = await self.client.post("/api/v1/multimodal/parse", headers=self.headers, json={"dataset_id": "kb", "document_id": "doc", "multimodal": {"model": "m"}})
        self.assertEqual(res.status_code, 202)
        self.assertEqual((await res.get_json())["data"]["task_id"], "job")
        self.assertEqual(self.calls[0][1][:3], ("tenant", "kb", "doc"))

    async def test_reject_missing_and_unknown_fields(self):
        for value in ({}, [], {"dataset_id": "kb", "document_id": "doc", "api_key": "secret"}, {"dataset_id": 1, "document_id": "doc"}):
            res = await self.client.post("/api/v1/multimodal/parse", headers=self.headers, json=value)
            self.assertEqual(res.status_code, 400)
        self.assertEqual(self.calls, [])

    async def test_requires_auth(self):
        res = await self.client.post("/api/v1/multimodal/parse", json={})
        self.assertEqual(res.status_code, 401)

    async def test_conflict_preserves_existing_task_id(self):
        def conflict(*args):
            raise self.service.ApiError("Already active", 409, {"task_id": "existing"})

        self.service.submit = conflict
        res = await self.client.post("/api/v1/multimodal/parse", headers=self.headers, json={"dataset_id": "kb", "document_id": "doc"})
        self.assertEqual(res.status_code, 409)
        self.assertEqual((await res.get_json())["data"]["task_id"], "existing")

    async def test_get_status_and_missing(self):
        res = await self.client.get("/api/v1/multimodal/tasks/job", headers=self.headers)
        self.assertEqual((await res.get_json())["data"]["status"], "complete")
        res = await self.client.get("/api/v1/multimodal/tasks/missing", headers=self.headers)
        self.assertEqual(res.status_code, 404)

    async def test_upload_and_parse(self):
        res = await self.client.post(
            "/api/v1/multimodal/upload-and-parse",
            headers=self.headers,
            form={"dataset_id": "kb", "multimodal": '{"model":"m"}'},
            files={"file": FileStorage(io.BytesIO(b"fake png"), filename="x.png")},
        )
        self.assertEqual(res.status_code, 202)
        self.assertEqual(self.calls[0][0], "upload")
        self.assertEqual(self.calls[0][1][2].filename, "x.png")

    async def test_upload_bad_json(self):
        res = await self.client.post(
            "/api/v1/multimodal/upload-and-parse", headers=self.headers, form={"dataset_id": "kb", "multimodal": "broken"}, files={"file": FileStorage(io.BytesIO(b"x"), filename="x.pdf")}
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
