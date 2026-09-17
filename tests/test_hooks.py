import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


KIT_ROOT = Path(__file__).resolve().parents[1]


class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        hooks = self.root / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        (self.root / ".hil").mkdir()
        for name in ("guard_hardware.py", "record_trial.py", "continue_hil_loop.py"):
            shutil.copy2(KIT_ROOT / ".claude" / "hooks" / name, hooks / name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, name, payload):
        return subprocess.run(
            [sys.executable, str(self.root / ".claude/hooks" / name)],
            cwd=self.root,
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )

    def test_guard_blocks_direct_openocd(self):
        result = self.run_hook(
            "guard_hardware.py",
            {"tool_name": "Bash", "tool_input": {"command": "openocd -f target/stm32g4x.cfg"}},
        )
        self.assertEqual(result.returncode, 0)
        decision = json.loads(result.stdout)
        self.assertEqual(decision["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_guard_blocks_absolute_path_to_hardware_tool(self):
        result = self.run_hook(
            "guard_hardware.py",
            {"tool_name": "Bash", "tool_input": {"command": "/usr/local/bin/openocd -f target/stm32g4x.cfg"}},
        )
        decision = json.loads(result.stdout)
        self.assertEqual(decision["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_guard_allows_hilctl(self):
        result = self.run_hook(
            "guard_hardware.py",
            {"tool_name": "Bash", "tool_input": {"command": "./tools/hilctl doctor --json"}},
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_guard_blocks_command_chained_onto_hilctl(self):
        result = self.run_hook(
            "guard_hardware.py",
            {"tool_name": "Bash", "tool_input": {"command": "./tools/hilctl doctor --json | openocd -f x"}},
        )
        decision = json.loads(result.stdout)
        self.assertEqual(decision["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_guard_blocks_claude_from_user_approval_tool(self):
        result = self.run_hook(
            "guard_hardware.py",
            {"tool_name": "Bash", "tool_input": {"command": "./tools/hilctl-user approve-milestone 3 --arm --yes"}},
        )
        decision = json.loads(result.stdout)
        self.assertEqual(decision["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_guard_blocks_writes_to_protected_state(self):
        protected = str(self.root / ".hil" / "safety-policy.json")
        result = self.run_hook(
            "guard_hardware.py",
            {"tool_name": "Write", "tool_input": {"file_path": protected, "content": "{}"}},
        )
        decision = json.loads(result.stdout)
        self.assertEqual(decision["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_record_hook_only_logs_hilctl_calls(self):
        ignored = self.run_hook(
            "record_trial.py",
            {"tool_name": "Bash", "tool_input": {"command": "git status"}, "tool_response": {"stdout": ""}},
        )
        self.assertEqual(ignored.returncode, 0)
        self.assertFalse((self.root / ".hil/logs/claude-tools.jsonl").exists())

        recorded = self.run_hook(
            "record_trial.py",
            {
                "session_id": "session-1",
                "tool_name": "Bash",
                "tool_input": {"command": "./tools/hilctl doctor --json"},
                "tool_response": {"stdout": "ok", "stderr": ""},
            },
        )
        self.assertEqual(recorded.returncode, 0)
        entry = json.loads((self.root / ".hil/logs/claude-tools.jsonl").read_text().strip())
        self.assertEqual(entry["session_id"], "session-1")

    def test_stop_hook_continues_only_active_campaign(self):
        (self.root / ".hil/runtime.json").write_text(
            json.dumps({"campaign_active": True, "stop_reason": None, "milestone": 2}), encoding="utf-8"
        )
        active = self.run_hook("continue_hil_loop.py", {"hook_event_name": "Stop", "stop_hook_active": False})
        self.assertEqual(active.returncode, 2)
        self.assertIn("milestone 2", active.stderr.lower())

        (self.root / ".hil/runtime.json").write_text(
            json.dumps({"campaign_active": False, "stop_reason": "complete", "milestone": 2}), encoding="utf-8"
        )
        inactive = self.run_hook("continue_hil_loop.py", {"hook_event_name": "Stop", "stop_hook_active": False})
        self.assertEqual(inactive.returncode, 0)


if __name__ == "__main__":
    unittest.main()
