import importlib.util
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def torch_stub(available=False, count=0):
    return types.SimpleNamespace(
        __version__="2.14.0+cu130",
        version=types.SimpleNamespace(cuda="13.0"),
        cuda=types.SimpleNamespace(is_available=lambda: available, device_count=lambda: count),
    )


def ort_stub(providers=("CUDAExecutionProvider",), folder="/tmp/ort"):
    return types.SimpleNamespace(
        __version__="1.27.0",
        __file__=str(Path(folder) / "__init__.py"),
        get_available_providers=lambda: list(providers),
    )


class StartRuntimeTests(unittest.TestCase):
    def setUp(self):
        source = ROOT / "scripts/start_python.py"
        self.assertTrue(source.exists(), "Python service bootstrap is missing")
        spec = importlib.util.spec_from_file_location("start_python", source)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def test_venv_libraries_precede_system_without_duplicates(self):
        with tempfile.TemporaryDirectory(prefix="runtime space ") as folder:
            base = Path(folder)
            for path in ["nvidia/cudnn/lib", "nvidia/cu13/lib", "torch/lib"]:
                (base / path).mkdir(parents=True)
            cudnn = str(base / "nvidia/cudnn/lib")
            old = os.pathsep.join(["/usr/local/cuda-12.6/lib64", cudnn, "/opt/openfoam/lib", ""])
            result = self.m.library_path([base], old)
            self.assertEqual(result.split(os.pathsep)[0], cudnn)
            self.assertEqual(result.split(os.pathsep).count(cudnn), 1)
            self.assertIn("/opt/openfoam/lib", result)
            self.assertFalse(result.endswith(os.pathsep))
            self.assertEqual(self.m.library_path([base], result), result)

    def test_torch_is_loaded_before_ort(self):
        calls = []
        modules = {
            "torch": types.SimpleNamespace(__version__="2.14", version=types.SimpleNamespace(cuda="13.0")),
            "onnxruntime": types.SimpleNamespace(__version__="1.27.0", get_available_providers=lambda: ["CUDAExecutionProvider"]),
        }

        def load(name):
            calls.append(name)
            return modules[name]

        with patch.object(self.m.importlib, "import_module", side_effect=load):
            self.m.load_runtime()
        self.assertEqual(calls, ["torch", "onnxruntime"])

    def test_cuda13_with_old_ort_is_rejected(self):
        modules = {"torch": types.SimpleNamespace(__version__="2.14", version=types.SimpleNamespace(cuda="13.0")), "onnxruntime": types.SimpleNamespace(__version__="1.23.2")}
        with patch.object(self.m.importlib, "import_module", side_effect=modules.__getitem__):
            with self.assertRaisesRegex(RuntimeError, "CUDA 13"):
                self.m.load_runtime()

    def test_all_python_services_use_bootstrap_and_run_alias_exists(self):
        source = (ROOT / "start.sh").read_text(encoding="utf-8")
        for target in ["api/ragflow_server.py", "rag/svr/task_executor.py", "admin/server/admin_server.py"]:
            self.assertIn('"$VENV_PYTHON" "$PYTHON_BOOTSTRAP" ' + target, source)
        self.assertIn("start|run)", source)
        self.assertIn("check-runtime)", source)

    def test_start_checks_executor_conflicts(self):
        source = (ROOT / "start.sh").read_text(encoding="utf-8")
        self.assertIn("scripts/check_executors.py", source)
        self.assertIn("check-executors)", source)
        self.assertIn("check_executor_conflicts", source)

    def test_reexec_preserves_service_arguments(self):
        args = [str(ROOT / "scripts/start_python.py"), "rag/svr/task_executor.py", "-t", "common", "-i", "3"]
        with (
            patch.object(self.m.sys, "argv", args),
            patch.object(self.m.sys, "platform", "linux"),
            patch.object(self.m, "library_path", return_value="/venv/nvidia/cudnn/lib"),
            patch.dict(os.environ, {"LD_LIBRARY_PATH": "/system/cuda"}),
            patch.object(self.m.os, "execve", side_effect=SystemExit) as execute,
        ):
            with self.assertRaises(SystemExit):
                self.m.main()
        executable, forwarded, environment = execute.call_args.args
        self.assertEqual(executable, self.m.sys.executable)
        self.assertEqual(forwarded[2:], args[1:])
        self.assertEqual(environment["LD_LIBRARY_PATH"], "/venv/nvidia/cudnn/lib")

    def test_target_runs_after_preload_with_original_arguments(self):
        target = str(ROOT / "rag/svr/task_executor.py")
        events = []
        with (
            patch.object(self.m.sys, "argv", ["bootstrap", target, "-i", "3"]),
            patch.object(self.m.sys, "platform", "win32"),
            patch.object(self.m.sys, "path", list(self.m.sys.path)),
            patch.object(self.m, "load_runtime", side_effect=lambda: (torch_stub(True, 1), ort_stub())),
            patch.object(self.m, "verify_gpu", side_effect=lambda *a, **kw: events.append("gpu")),
            patch.object(self.m.runpy, "run_path", side_effect=lambda *a, **kw: events.append("service")) as run,
        ):
            self.m.main()
            self.assertEqual(self.m.sys.argv, [str(Path(target).resolve()), "-i", "3"])
        self.assertEqual(events, ["gpu", "service"])
        self.assertEqual(run.call_args.kwargs["run_name"], "__main__")

    def test_gpu_check_is_strict_for_check_and_executor(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(self.m.gpu_strict("--check"))
            self.assertTrue(self.m.gpu_strict("rag/svr/task_executor.py"))
            self.assertFalse(self.m.gpu_strict("api/ragflow_server.py"))
        with patch.dict(os.environ, {"RAGFLOW_ALLOW_CPU": "1"}):
            self.assertFalse(self.m.gpu_strict("--check"))
        with patch.dict(os.environ, {"RAGFLOW_REQUIRE_GPU": "1"}):
            self.assertTrue(self.m.gpu_strict("api/ragflow_server.py"))

    def test_hidden_gpu_fails_strict_check_with_actionable_message(self):
        with (
            patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": ""}, clear=True),
            patch.object(self.m, "cuda_provider_library", return_value=Path("/tmp/ort/capi/onnxruntime_providers_cuda.so")),
            patch.object(self.m, "provider_library_error", return_value="libcudnn.so.9: cannot open shared object file"),
        ):
            with self.assertRaisesRegex(RuntimeError, "GPU runtime unusable") as caught:
                self.m.verify_gpu(torch_stub(False, 0), ort_stub(), strict=True)
            message = str(caught.exception)
            self.assertIn("CUDA_VISIBLE_DEVICES", message)
            self.assertIn("cannot load onnxruntime_providers_cuda.so", message)
            self.assertIn("RAGFLOW_ALLOW_CPU", message)

    def test_gpu_check_only_warns_when_cpu_is_allowed(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(self.m, "cuda_provider_library", return_value=None):
            status = self.m.verify_gpu(torch_stub(False, 0), ort_stub(providers=["CPUExecutionProvider"]), strict=False)
        self.assertFalse(status["available"])
        self.assertEqual(["CPUExecutionProvider"], status["providers"])

    def test_running_the_bootstrap_executes_main(self):
        """Guard against dropping the __main__ entry: the script must really run."""
        import subprocess

        env = {**os.environ, "RAGFLOW_ALLOW_CPU": "1"}
        result = subprocess.run(
            [os.sys.executable, str(ROOT / "scripts/start_python.py"), "--check"],
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[runtime] GPU ", result.stdout, result.stdout + result.stderr)

    def test_cuda_provider_library_uses_lib_prefixed_name(self):
        with tempfile.TemporaryDirectory() as folder:
            capi = Path(folder) / "capi"
            capi.mkdir()
            library = capi / "libonnxruntime_providers_cuda.so"
            library.write_bytes(b"")
            ort = types.SimpleNamespace(__file__=str(Path(folder) / "__init__.py"))
            self.assertEqual(self.m.cuda_provider_library(ort), library)
            library.unlink()
            self.assertIsNone(self.m.cuda_provider_library(ort))

    def test_unloadable_provider_library_is_reported(self):
        self.assertIn("libmissing", self.m.provider_library_error("/tmp/libmissing_providers_cuda.so"))

    def test_working_gpu_reports_devices(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(self.m, "cuda_provider_library", return_value=Path("/tmp/ort/capi/onnxruntime_providers_cuda.so")),
            patch.object(self.m, "provider_library_error", return_value=""),
        ):
            status = self.m.verify_gpu(torch_stub(True, 1), ort_stub(), strict=True)
        self.assertTrue(status["available"])
        self.assertEqual(1, status["device_count"])


if __name__ == "__main__":
    unittest.main()
