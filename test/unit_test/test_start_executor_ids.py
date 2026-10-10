"""Exercise executor lifecycle shell functions without starting real services."""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")


@unittest.skipUnless(BASH, "Bash is required")
class ExecutorIdsTests(unittest.TestCase):
    def run_shell(self, command, offset=None):
        source = (ROOT / "start.sh").read_text(encoding="utf-8")
        config = "\n".join(re.findall(r"^(?:export )?(?:TASK_EXECUTOR_(?:TYPES|COUNT|OFFSET)|RAGFLOW_TASK_QUEUE_NAMESPACE|BACKEND_PORT)=.*$", source, re.MULTILINE))
        names = ["taskexec_pidfiles", "start_taskexec", "stop_all", "status_all"]
        functions = "\n".join(match.group(0) for name in names if (match := re.search(rf"^{name}\(\) \{{.*?^\}}", source, re.MULTILINE | re.DOTALL)))
        with tempfile.TemporaryDirectory(prefix="executor-test-") as folder:
            for index in range(3, 6 if command.startswith("start_taskexec") else 9):
                Path(folder, f"taskexec_common_{index}.pid").write_text("123", encoding="utf-8")
            harness = f"""
{config}
LOG_DIR='{Path(folder).as_posix()}'
PROJECT_DIR="$LOG_DIR"
PID_SERVER=server; PID_WEB=web; PID_ADMIN=admin
VENV_PYTHON=python; PYTHON_BOOTSTRAP=bootstrap
BACKEND_PORT=9380; FRONTEND_PORT=9222; REQUIRED_DEPS=''
kill() {{ return 0; }}
sleep() {{ :; }}
pkill() {{ :; }}
kill_port() {{ :; }}
check_port() {{ return 1; }}
stop_pidfile() {{ echo "STOP:$1"; }}
launch_bg() {{ echo "LAUNCH:$*"; printf 123 > "$1"; }}
{functions}
{command}
"""
            env = {key: value for key, value in os.environ.items() if not key.startswith("TASK_EXECUTOR_") and key != "RAGFLOW_TASK_QUEUE_NAMESPACE"}
            if offset is not None:
                env["TASK_EXECUTOR_OFFSET"] = str(offset)
            result = subprocess.run([BASH, "-c", harness], env=env, capture_output=True, text=True, encoding="utf-8", timeout=20, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout

    def test_defaults_launch_new_ids_and_export_to_checker(self):
        output = self.run_shell(
            'start_taskexec; bash -c \'printf "TASK_EXECUTOR_OFFSET=%s\\nTASK_EXECUTOR_TYPES=%s\\nTASK_EXECUTOR_COUNT=%s\\n" "$TASK_EXECUTOR_OFFSET" "$TASK_EXECUTOR_TYPES" "$TASK_EXECUTOR_COUNT"\''
        )
        for index in (6, 7, 8):
            self.assertIn(f"-t common -i {index}", output)
        self.assertNotIn("-t common -i 3", output)
        self.assertIn("TASK_EXECUTOR_OFFSET=6", output)
        self.assertIn("TASK_EXECUTOR_TYPES=common", output)
        self.assertIn("TASK_EXECUTOR_COUNT=3", output)

    def test_explicit_offset_remains_supported(self):
        output = self.run_shell("start_taskexec", offset=10)
        for index in (10, 11, 12):
            self.assertIn(f"-t common -i {index}", output)

    def test_default_queue_namespace_is_exported_to_all_children(self):
        output = self.run_shell("bash -c 'printf %s \"$RAGFLOW_TASK_QUEUE_NAMESPACE\"'")
        self.assertEqual(output, "ragflow_python_9380")

    def test_stop_leaves_old_executor_pidfiles_alone(self):
        output = self.run_shell("stop_all")
        for index in (3, 4, 5):
            self.assertNotIn(f"taskexec_common_{index}.pid", output)
        for index in (6, 7, 8):
            self.assertIn(f"taskexec_common_{index}.pid", output)

    def test_status_counts_only_configured_executors(self):
        output = self.run_shell("status_all")
        self.assertIn("task executor workers : 3", output)
        self.assertNotIn("taskexec_common_3 :", output)

    def test_executor_only_command_checks_runtime_without_other_services(self):
        source = (ROOT / "start.sh").read_text(encoding="utf-8")
        branch = re.search(r"^    start-taskexec\)\n(.*?)^        ;;", source, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(branch)
        output = self.run_shell(
            "start_taskexec() { echo EXECUTORS; }; runtime_check() { echo RUNTIME; }; VENV_PYTHON=runtime_check; check_executor_conflicts() { echo CONFLICT_CHECK; };\n" + branch.group(1)
        )
        self.assertEqual(output.splitlines(), ["RUNTIME", "CONFLICT_CHECK", "EXECUTORS"])


if __name__ == "__main__":
    unittest.main()
