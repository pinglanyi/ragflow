"""Focused offline regression tests; no model downloads or database needed."""
import ast
import importlib.util
import re
import unittest
import os
import logging
import types
from unittest.mock import patch
from enum import Enum
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


class ModelTypes(str, Enum):
    CHAT = "chat"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    ASR = "asr"
    TTS = "tts"
    VISION = "vision"


def provider_class():
    source = ROOT / "rag/llm/model_meta.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "OpenAIAPICompatible")
    ns = {"Base": object, "LLMType": ModelTypes, "re": re}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), ns)
    return ns["OpenAIAPICompatible"]


class DiscoveryTests(unittest.TestCase):
    def test_embedding_abbreviation_and_boundaries(self):
        provider = provider_class()()
        for name in ["qwen3-emb-0_6b", "QWEN3_EMB_0.6B", "org/emb", "emb", "qwen3-embedding"]:
            with self.subTest(name=name):
                result = provider._format_model_list({"data": [{"id": name}]})
                self.assertEqual(result[0]["model_types"], ["embedding"])
        for name in ["ember-chat", "remember-chat", "ensemble-chat"]:
            self.assertEqual(provider._infer_model_types(name), ["chat"])

    def test_explicit_type_overrides_alias_guess(self):
        provider = provider_class()()
        for field, value in [("model_type", "embedding"), ("model_type", ["embedding"]), ("model_types", ["embedding"])]:
            result = provider._format_model_list({"data": [{"id": "custom-service", field: value}]})
            self.assertEqual(result[0]["model_types"], ["embedding"])
        result = provider._format_model_list({"data": [{"id": "emb-chat", "model_type": ["chat", "vision"]}]})
        self.assertEqual(result[0]["model_types"], ["chat", "vision"])


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        source = ROOT / "deepdoc/vision/onnx_session.py"
        spec = importlib.util.spec_from_file_location("onnx_session_under_test", source)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_gpu_allocation_error_falls_back_once_and_stays_on_cpu(self):
        calls = []
        class GPU:
            def get_inputs(self):
                return ["input"]
            def run(self, *args):
                calls.append("gpu")
                raise RuntimeError("BFCArena::AllocateRawInternal Available memory is smaller than requested bytes of 3839563453410779136")
        class CPU:
            def run(self, *args):
                calls.append("cpu")
                return [np.ones((1, 2))]
        session = self.module.ResilientSession(GPU(), lambda: (CPU(), "cpu-options"), "det.onnx")
        self.assertEqual(session.get_inputs(), ["input"])
        for _ in range(2):
            session.run(None, {"x": np.zeros((1, 3, 32, 32), dtype=np.float32)}, "gpu-options")
        self.assertEqual(calls, ["gpu", "cpu", "cpu"])

    def test_bad_inputs_never_reach_runtime(self):
        class Session:
            def run(self, *args):
                raise AssertionError("runtime must not be called")
        session = self.module.ResilientSession(Session(), None, "det.onnx")
        for array in [np.zeros((1, 3, 0, 32), dtype=np.float32), np.array([np.nan], dtype=np.float32)]:
            with self.assertRaises(ValueError):
                session.run(None, {"x": array})

    def test_non_gpu_error_is_not_hidden(self):
        class Session:
            def run(self, *args):
                raise RuntimeError("Invalid input name")
        def fallback():
            self.fail("unexpected CPU fallback")
        session = self.module.ResilientSession(Session(), fallback, "det.onnx")
        with self.assertRaisesRegex(RuntimeError, "Invalid input name"):
            session.run(None, {"x": np.zeros((1, 3, 32, 32), dtype=np.float32)})

    def test_non_allocation_cuda_errors_are_not_hidden(self):
        for error in ["CUDNN_STATUS_BAD_PARAM", "CUDNN_STATUS_NOT_SUPPORTED", "CUDA_ERROR_ILLEGAL_ADDRESS", "CUDA failure 700: illegal memory access"]:
            with self.subTest(error=error):
                class Session:
                    def run(self, *args):
                        raise RuntimeError(error)
                def fallback():
                    self.fail("Non-allocation CUDA errors must not switch to CPU")
                session = self.module.ResilientSession(Session(), fallback, "det.onnx")
                with self.assertRaisesRegex(RuntimeError, error):
                    session.run(None, {"x": np.zeros((1, 3, 32, 32), dtype=np.float32)})

    def test_real_loader_uses_session_options_and_conservative_cuda_settings(self):
        source = ROOT / "deepdoc/vision/ocr.py"
        func = next(n for n in ast.parse(source.read_text(encoding="utf-8")).body if isinstance(n, ast.FunctionDef) and n.name == "load_model")
        calls = []
        class Session:
            def __init__(self, path, **kwargs):
                calls.append(kwargs)
                self.providers = kwargs["providers"]
            def get_providers(self):
                return self.providers
        ort = types.SimpleNamespace(SessionOptions=types.SimpleNamespace, RunOptions=types.SimpleNamespace,
            InferenceSession=Session, ExecutionMode=types.SimpleNamespace(ORT_SEQUENTIAL=0),
            get_available_providers=lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"], __version__="test")
        ns = {"os": os, "logging": logging, "ort": ort, "loaded_models": {},
              "pip_install_torch": lambda: None, "ResilientSession": self.module.ResilientSession}
        exec(compile(ast.Module(body=[func], type_ignores=[]), str(source), "exec"), ns)
        torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: True, device_count=lambda: 1))
        with patch.dict("sys.modules", {"torch": torch}), patch("os.path.exists", return_value=True), patch.dict(os.environ, {"OCR_DEVICE": "cuda", "OCR_GPUMEM_ARENA_SHRINKAGE": "0", "OCR_CUDNN_CONV_ALGO_SEARCH": "DEFAULT"}):
            ns["load_model"]("models", "det")
        self.assertIn("sess_options", calls[0])
        self.assertNotIn("options", calls[0])
        self.assertEqual(calls[0]["provider_options"][0]["cudnn_conv_algo_search"], "DEFAULT")
        self.assertEqual(calls[0]["provider_options"][0]["cudnn_conv_use_max_workspace"], "0")
        ns["pip_install_torch"] = lambda: self.fail("Forced CPU must not load torch")
        with patch("os.path.exists", return_value=True), patch.dict(os.environ, {"OCR_DEVICE": "cpu"}):
            ns["load_model"]("models", "det")
        self.assertEqual(calls[1]["providers"], ["CPUExecutionProvider"])

    def test_cpu_failure_propagates_and_inputs_are_contiguous(self):
        class GPU:
            def run(self, *args):
                raise RuntimeError("BFCArena failure")
        class CPU:
            def run(inner, names, inputs, options):
                self.assertTrue(inputs["x"].flags.c_contiguous)
                self.assertEqual(options, "cpu")
                raise RuntimeError("CPU inference also failed")
        session = self.module.ResilientSession(GPU(), lambda: (CPU(), "cpu"), "det.onnx")
        with self.assertRaisesRegex(RuntimeError, "CPU inference also failed"):
            session.run(None, {"x": np.zeros((4, 4), dtype=np.float32)[:, ::2]}, "gpu")


if __name__ == "__main__":
    unittest.main()
