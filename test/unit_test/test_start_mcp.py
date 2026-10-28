"""MCP lifecycle checks without backend, Docker or network dependencies."""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class McpStartupTests(unittest.TestCase):
    def run_shell(self, command):
        source = (ROOT / 'start.sh').read_text()
        names = ['mcp_pid_is_ours', 'start_mcp', 'stop_mcp']
        functions = '\n'.join(m.group() for name in names if
            (m := re.search(rf'^{name}\(\) \{{.*?^\}}', source, re.M | re.S)))
        with tempfile.TemporaryDirectory() as folder:
            script = f'''
PROJECT_DIR={folder}
PID_MCP="$PROJECT_DIR/mcp.pid"; LOG_MCP="$PROJECT_DIR/mcp.log"
VENV_PYTHON=/bin/true
RAGFLOW_MCP_PORT=19382
check_port() {{ return 1; }}
launch_bg() {{ echo LAUNCHED; }}
stop_pidfile() {{ echo STOPPED; }}
{functions}
{command}
'''
            return subprocess.run(['bash', '-c', script], capture_output=True,
                                  text=True, timeout=10)

    def test_busy_port_is_never_taken_over(self):
        result = self.run_shell('check_port() { return 0; }; start_mcp')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn('LAUNCHED', result.stdout)
        self.assertIn('19382', result.stdout + result.stderr)

    def test_foreign_live_pid_is_not_stopped(self):
        result = self.run_shell('echo $$ > "$PID_MCP"; stop_mcp')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn('STOPPED', result.stdout)

    def test_owned_process_start_is_idempotent(self):
        result = self.run_shell('echo $$ > "$PID_MCP"; mcp_pid_is_ours() { return 0; }; check_port() { return 0; }; start_mcp')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('LAUNCHED', result.stdout)

    def test_stale_pid_can_be_removed(self):
        result = self.run_shell('echo 99999999 > "$PID_MCP"; stop_mcp; test ! -f "$PID_MCP"')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_launch_uses_project_native_server(self):
        result = self.run_shell('''
mkdir -p "$PROJECT_DIR/mcp/server"
touch "$PROJECT_DIR/mcp/server/server.py"
launch_bg() { echo "LAUNCH:$*"; echo $$ > "$1"; }
mcp_pid_is_ours() { return 0; }
check_port() { [ -f "$PID_MCP" ]; }
start_mcp
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('/bin/true', result.stdout)
        self.assertIn('/mcp/server/server.py', result.stdout)
        self.assertNotIn('start_python.py', result.stdout)

    def test_standalone_start_does_not_start_other_services(self):
        source = (ROOT / 'start.sh').read_text()
        branch = re.search(r'^    start-mcp\)\n(.*?)^        ;;', source, re.M | re.S)
        self.assertIsNotNone(branch)
        result = self.run_shell('start_mcp() { echo MCP_ONLY; };\n' + branch.group(1))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'MCP_ONLY')


if __name__ == '__main__':
    unittest.main()
