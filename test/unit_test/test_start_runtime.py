import importlib.util
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


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
        modules = {"torch": types.SimpleNamespace(__version__="2.14", version=types.SimpleNamespace(cuda="13.0")),
                   "onnxruntime": types.SimpleNamespace(__version__="1.27.0", get_available_providers=lambda: ["CUDAExecutionProvider"])}
        def load(name):
            calls.append(name)
            return modules[name]
        with patch.object(self.m.importlib, "import_module", side_effect=load):
            self.m.load_runtime()
        self.assertEqual(calls, ["torch", "onnxruntime"])

    def test_cuda13_with_old_ort_is_rejected(self):
        modules = {"torch": types.SimpleNamespace(__version__="2.14", version=types.SimpleNamespace(cuda="13.0")),
                   "onnxruntime": types.SimpleNamespace(__version__="1.23.2")}
        with patch.object(self.m.importlib, "import_module", side_effect=modules.__getitem__):
            with self.assertRaisesRegex(RuntimeError, "CUDA 13"):
                self.m.load_runtime()

    def test_all_python_services_use_bootstrap_and_run_alias_exists(self):
        source = (ROOT / "start.sh").read_text(encoding="utf-8")
        for target in ["api/ragflow_server.py", "rag/svr/task_executor.py", "admin/server/admin_server.py"]:
            self.assertIn('"$VENV_PYTHON" "$PYTHON_BOOTSTRAP" ' + target, source)
        self.assertIn("start|run)", source)
        self.assertIn("check-runtime)", source)

    def test_reexec_preserves_service_arguments(self):
        args = [str(ROOT / "scripts/start_python.py"), "rag/svr/task_executor.py", "-t", "common", "-i", "3"]
        with patch.object(self.m.sys, "argv", args), patch.object(self.m.sys, "platform", "linux"), \
             patch.object(self.m, "library_path", return_value="/venv/nvidia/cudnn/lib"), \
             patch.dict(os.environ, {"LD_LIBRARY_PATH": "/system/cuda"}), \
             patch.object(self.m.os, "execve", side_effect=SystemExit) as execute:
            with self.assertRaises(SystemExit):
                self.m.main()
        executable, forwarded, environment = execute.call_args.args
        self.assertEqual(executable, self.m.sys.executable)
        self.assertEqual(forwarded[2:], args[1:])
        self.assertEqual(environment["LD_LIBRARY_PATH"], "/venv/nvidia/cudnn/lib")

    def test_target_runs_after_preload_with_original_arguments(self):
        target = str(ROOT / "rag/svr/task_executor.py")
        events = []
        with patch.object(self.m.sys, "argv", ["bootstrap", target, "-i", "3"]), \
             patch.object(self.m.sys, "platform", "win32"), \
             patch.object(self.m.sys, "path", list(self.m.sys.path)), \
             patch.object(self.m, "load_runtime", side_effect=lambda: events.append("preload")), \
             patch.object(self.m.runpy, "run_path", side_effect=lambda *a, **kw: events.append("service")) as run:
            self.m.main()
            self.assertEqual(self.m.sys.argv, [str(Path(target).resolve()), "-i", "3"])
        self.assertEqual(events, ["preload", "service"])
        self.assertEqual(run.call_args.kwargs["run_name"], "__main__")


if __name__ == "__main__":
    unittest.main()
