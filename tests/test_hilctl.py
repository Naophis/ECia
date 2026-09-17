import json
import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


KIT_ROOT = Path(__file__).resolve().parents[1]


class HilctlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "tools").mkdir()
        (self.root / ".hil").mkdir()
        shutil.copy2(KIT_ROOT / "tools" / "hilctl", self.root / "tools" / "hilctl")
        shutil.copy2(KIT_ROOT / "tools" / "hilctl-user", self.root / "tools" / "hilctl-user")

    def tearDown(self):
        self.tmp.cleanup()

    def write_json(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def run_tool(self, name, *args):
        return subprocess.run(
            [sys.executable, str(self.root / "tools" / name), *map(str, args)],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )

    def valid_config(self):
        py = sys.executable
        arm_elf = (
            "from pathlib import Path; "
            "Path('build').mkdir(exist_ok=True); "
            "d=bytearray(64); d[0:4]=b'\\x7fELF'; d[4]=1; d[5]=1; d[18:20]=(40).to_bytes(2,'little'); "
            "d[24:28]=(0x08000101).to_bytes(4,'little'); "
            "Path('build/firmware.elf').write_bytes(d)"
        )
        return {
            "schema_version": 1,
            "target": {
                "expected_mcu": "STM32G431KBU6",
                "expected_probe_serial": "TEST-PROBE",
                "identity_pattern": "STM32G431",
                "halted_pattern": "halted",
                "flash_start": 134217728,
                "flash_end": 134742016,
                "firmware_artifact": "build/firmware.elf",
                "flash_leaves_target_halted": True,
                "firmware_starts_disarmed": True,
            },
            "commands": {
                "build": [py, "-c", arm_elf],
                "identify": [
                    py,
                    "-c",
                    "import json; print(json.dumps({'mcu':'STM32G431KBU6','probe_serial':'TEST-PROBE','connected':True}))",
                    "{probe_serial}",
                ],
                "flash": [py, "-c", "print('FLASHED {artifact}')", "{artifact}", "{probe_serial}"],
                "verify_halted": [
                    py,
                    "-c",
                    "import json; print(json.dumps({'state':'halted','probe_serial':'TEST-PROBE'}))",
                    "{probe_serial}",
                ],
                "stop": [py, "-c", "print('PWM_OFF')"],
                "test": [
                    py,
                    "-c",
                    "print('{\"status\":\"pass\",\"signature\":\"ok\"}')",
                    "{duty}",
                    "{duration_ms}",
                    "{rpm_limit}",
                ],
                "capture": [py, "-c", "print('CAPTURED')"],
            },
        }

    def policy(self, max_duty=10.0):
        return {
            "schema_version": 1,
            "max_duty_percent": max_duty,
            "max_duration_ms": 500,
            "max_rpm": 20000,
            "max_trials_per_campaign": 10,
            "same_failure_limit": 3,
            "safe_retry_exit_codes": [10],
        }

    def approved(self, milestone=1, armed=True):
        def digest(path):
            return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

        return {
            "schema_version": 1,
            "approved_milestone": milestone,
            "hardware_armed": armed,
            "fault_latched": False,
            "fault_reason": None,
            "approval_id": "test-approval",
            "config_sha256": digest(self.root / ".hil/config.json"),
            "policy_sha256": digest(self.root / ".hil/safety-policy.json"),
        }

    def configure(self, armed=True):
        self.write_json(".hil/config.json", self.valid_config())
        self.write_json(".hil/safety-policy.json", self.policy())
        self.write_json(".hil/approval.json", self.approved(armed=armed))

    def test_doctor_rejects_unconfigured_hardware_commands(self):
        config = self.valid_config()
        config["commands"]["flash"] = ["CONFIGURE_ME"]
        self.write_json(".hil/config.json", config)
        self.write_json(".hil/safety-policy.json", self.policy())
        self.write_json(".hil/approval.json", self.approved())

        result = self.run_tool("hilctl", "doctor", "--json")

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertFalse(report["ok"])
        self.assertTrue(any("flash" in issue for issue in report["issues"]))

    def test_campaign_requires_matching_approval_and_arm(self):
        self.configure(armed=False)

        result = self.run_tool("hilctl", "campaign", "start", "--milestone", "1")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not armed", result.stderr.lower())

    def test_identify_is_read_only_and_does_not_require_arm(self):
        self.configure(armed=False)

        result = self.run_tool("hilctl", "identify", "--json")

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["identity"]["mcu"], "STM32G431KBU6")
        events = [json.loads(line) for line in (self.root / ".hil/logs/events.jsonl").read_text().splitlines()]
        self.assertIn("identify", [event["event"] for event in events])

    def test_doctor_rejects_flash_without_artifact_and_probe_binding(self):
        config = self.valid_config()
        config["commands"]["flash"] = [sys.executable, "-c", "print('flash')"]
        self.write_json(".hil/config.json", config)
        self.write_json(".hil/safety-policy.json", self.policy())
        self.write_json(".hil/approval.json", self.approved())

        result = self.run_tool("hilctl", "doctor", "--json")

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertTrue(any("{artifact}" in issue for issue in report["issues"]))
        self.assertTrue(any("{probe_serial}" in issue for issue in report["issues"]))

    def test_doctor_rejects_shell_wrapped_and_auto_run_flash(self):
        config = self.valid_config()
        config["commands"]["flash"] = [
            "bash",
            "-c",
            "openocd -c 'program {artifact} verify reset run' --probe {probe_serial}",
        ]
        self.write_json(".hil/config.json", config)
        self.write_json(".hil/safety-policy.json", self.policy())
        self.write_json(".hil/approval.json", self.approved())

        result = self.run_tool("hilctl", "doctor", "--json")

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertTrue(any("shell interpreter" in issue for issue in report["issues"]))
        self.assertTrue(any("run after flash" in issue for issue in report["issues"]))

    def test_campaign_preflights_stop_and_target_identity(self):
        self.configure(armed=True)

        result = self.run_tool("hilctl", "campaign", "start", "--milestone", "1")

        self.assertEqual(result.returncode, 0, result.stderr)
        events = [json.loads(line) for line in (self.root / ".hil/logs/events.jsonl").read_text().splitlines()]
        actions = [event["event"] for event in events]
        self.assertLess(actions.index("stop"), actions.index("campaign_started"))
        self.assertLess(actions.index("identify"), actions.index("campaign_started"))

    def test_campaign_refuses_to_start_when_stop_preflight_fails(self):
        config = self.valid_config()
        config["commands"]["stop"] = [sys.executable, "-c", "raise SystemExit(9)"]
        self.write_json(".hil/config.json", config)
        self.write_json(".hil/safety-policy.json", self.policy())
        self.write_json(".hil/approval.json", self.approved())

        result = self.run_tool("hilctl", "campaign", "start", "--milestone", "1")

        self.assertNotEqual(result.returncode, 0)
        approval = json.loads((self.root / ".hil/approval.json").read_text())
        self.assertTrue(approval["fault_latched"])
        self.assertFalse(approval["hardware_armed"])

    def test_campaign_rejects_config_drift_after_approval(self):
        self.configure(armed=True)
        config = self.valid_config()
        config["target"]["expected_probe_serial"] = "CHANGED-AFTER-APPROVAL"
        self.write_json(".hil/config.json", config)

        result = self.run_tool("hilctl", "campaign", "start", "--milestone", "1")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("changed after approval", result.stderr.lower())

    def test_trial_rejects_non_arm_elf_before_flash(self):
        config = self.valid_config()
        config["commands"]["build"] = [
            sys.executable,
            "-c",
            "from pathlib import Path; Path('build').mkdir(exist_ok=True); Path('build/firmware.elf').write_bytes(b'not-elf')",
        ]
        self.write_json(".hil/config.json", config)
        self.write_json(".hil/safety-policy.json", self.policy())
        self.write_json(".hil/approval.json", self.approved())
        self.assertEqual(self.run_tool("hilctl", "campaign", "start", "--milestone", "1").returncode, 0)

        result = self.run_tool(
            "hilctl", "trial", "--duty", "5", "--duration-ms", "100", "--rpm-limit", "10000"
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("arm elf", result.stderr.lower())
        events = [json.loads(line) for line in (self.root / ".hil/logs/events.jsonl").read_text().splitlines()]
        self.assertNotIn("flash", [event["event"] for event in events])

    def test_trial_requires_confirmed_halted_state_before_test(self):
        config = self.valid_config()
        config["commands"]["verify_halted"] = [
            sys.executable,
            "-c",
            "import json; print(json.dumps({'state':'running','probe_serial':'TEST-PROBE'}))",
            "{probe_serial}",
        ]
        self.write_json(".hil/config.json", config)
        self.write_json(".hil/safety-policy.json", self.policy())
        self.write_json(".hil/approval.json", self.approved())
        self.assertEqual(self.run_tool("hilctl", "campaign", "start", "--milestone", "1").returncode, 0)

        result = self.run_tool(
            "hilctl", "trial", "--duty", "5", "--duration-ms", "100", "--rpm-limit", "10000"
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("halted", result.stderr.lower())
        events = [json.loads(line) for line in (self.root / ".hil/logs/events.jsonl").read_text().splitlines()]
        self.assertNotIn("test", [event["event"] for event in events])

    def test_nan_duty_is_rejected(self):
        self.configure(armed=True)
        self.assertEqual(self.run_tool("hilctl", "campaign", "start", "--milestone", "1").returncode, 0)

        result = self.run_tool(
            "hilctl", "trial", "--duty", "nan", "--duration-ms", "100", "--rpm-limit", "10000"
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("finite", result.stderr.lower())

    def test_capture_failure_is_fatal_and_happens_after_stop(self):
        config = self.valid_config()
        config["commands"]["capture"] = [sys.executable, "-c", "raise SystemExit(6)"]
        self.write_json(".hil/config.json", config)
        self.write_json(".hil/safety-policy.json", self.policy())
        self.write_json(".hil/approval.json", self.approved())
        self.assertEqual(self.run_tool("hilctl", "campaign", "start", "--milestone", "1").returncode, 0)

        result = self.run_tool(
            "hilctl", "trial", "--duty", "5", "--duration-ms", "100", "--rpm-limit", "10000"
        )

        self.assertNotEqual(result.returncode, 0)
        events = [json.loads(line) for line in (self.root / ".hil/logs/events.jsonl").read_text().splitlines()]
        actions = [event["event"] for event in events]
        self.assertLess(actions.index("stop", actions.index("test")), actions.index("capture"))
        approval = json.loads((self.root / ".hil/approval.json").read_text())
        self.assertTrue(approval["fault_latched"])

    def test_campaign_stop_executes_hardware_stop(self):
        self.configure(armed=True)
        self.assertEqual(self.run_tool("hilctl", "campaign", "start", "--milestone", "1").returncode, 0)
        before = (self.root / ".hil/logs/events.jsonl").read_text().count('"event": "stop"')

        result = self.run_tool("hilctl", "campaign", "stop", "--reason", "review")

        self.assertEqual(result.returncode, 0, result.stderr)
        after = (self.root / ".hil/logs/events.jsonl").read_text().count('"event": "stop"')
        self.assertEqual(after, before + 1)

    def test_trial_rejects_duty_over_policy_before_running_commands(self):
        self.configure(armed=True)
        started = self.run_tool("hilctl", "campaign", "start", "--milestone", "1")
        self.assertEqual(started.returncode, 0, started.stderr)

        result = self.run_tool(
            "hilctl", "trial", "--duty", "11", "--duration-ms", "100", "--rpm-limit", "10000"
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duty", result.stderr.lower())
        self.assertFalse((self.root / "build" / "firmware.elf").exists())

    def test_successful_trial_builds_flashes_tests_stops_and_logs(self):
        self.configure(armed=True)
        started = self.run_tool("hilctl", "campaign", "start", "--milestone", "1")
        self.assertEqual(started.returncode, 0, started.stderr)

        result = self.run_tool(
            "hilctl",
            "trial",
            "--duty",
            "5",
            "--duration-ms",
            "100",
            "--rpm-limit",
            "10000",
            "--label",
            "open-loop-smoke",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "pass")
        self.assertTrue((self.root / "build" / "firmware.elf").exists())
        events = [json.loads(line) for line in (self.root / ".hil/logs/events.jsonl").read_text().splitlines()]
        actions = [event["event"] for event in events]
        for expected in ("build", "identify", "flash", "verify_halted", "test", "capture", "stop", "trial_complete"):
            self.assertIn(expected, actions)

    def test_fatal_test_failure_latches_fault_and_disarms(self):
        config = self.valid_config()
        config["commands"]["test"] = [
            sys.executable,
            "-c",
            "raise SystemExit(7)",
            "{duty}",
            "{duration_ms}",
            "{rpm_limit}",
        ]
        self.write_json(".hil/config.json", config)
        self.write_json(".hil/safety-policy.json", self.policy())
        self.write_json(".hil/approval.json", self.approved())
        self.assertEqual(self.run_tool("hilctl", "campaign", "start", "--milestone", "1").returncode, 0)

        result = self.run_tool(
            "hilctl", "trial", "--duty", "5", "--duration-ms", "100", "--rpm-limit", "10000"
        )

        self.assertNotEqual(result.returncode, 0)
        approval = json.loads((self.root / ".hil/approval.json").read_text())
        runtime = json.loads((self.root / ".hil/runtime.json").read_text())
        self.assertTrue(approval["fault_latched"])
        self.assertFalse(approval["hardware_armed"])
        self.assertFalse(runtime["campaign_active"])

    def test_user_approval_tool_sets_one_milestone_and_arm(self):
        self.write_json(".hil/config.json", self.valid_config())
        self.write_json(".hil/safety-policy.json", self.policy())
        self.write_json(".hil/approval.json", self.approved(milestone=0, armed=False))

        result = self.run_tool("hilctl-user", "approve-milestone", "2", "--arm", "--yes")

        self.assertEqual(result.returncode, 0, result.stderr)
        approval = json.loads((self.root / ".hil/approval.json").read_text())
        self.assertEqual(approval["approved_milestone"], 2)
        self.assertTrue(approval["hardware_armed"])
        self.assertFalse(approval["fault_latched"])
        self.assertEqual(len(approval["config_sha256"]), 64)
        self.assertEqual(len(approval["policy_sha256"]), 64)

    def test_approval_does_not_clear_latched_fault(self):
        self.write_json(".hil/config.json", self.valid_config())
        self.write_json(".hil/safety-policy.json", self.policy())
        approval = self.approved(milestone=1, armed=False)
        approval.update({"fault_latched": True, "fault_reason": "desync"})
        self.write_json(".hil/approval.json", approval)

        result = self.run_tool("hilctl-user", "approve-milestone", "2", "--arm", "--yes")

        self.assertNotEqual(result.returncode, 0)
        current = json.loads((self.root / ".hil/approval.json").read_text())
        self.assertTrue(current["fault_latched"])

    def test_user_tool_updates_protected_limits(self):
        self.write_json(".hil/safety-policy.json", self.policy())

        result = self.run_tool(
            "hilctl-user",
            "set-limits",
            "--max-duty-percent",
            "15",
            "--max-duration-ms",
            "750",
            "--max-rpm",
            "50000",
            "--max-trials-per-campaign",
            "12",
            "--same-failure-limit",
            "3",
            "--yes",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        policy = json.loads((self.root / ".hil/safety-policy.json").read_text())
        self.assertEqual(policy["max_duty_percent"], 15)
        self.assertEqual(policy["max_duration_ms"], 750)
        self.assertEqual(policy["max_rpm"], 50000)
        self.assertEqual(policy["max_trials_per_campaign"], 12)
        approval = json.loads((self.root / ".hil/approval.json").read_text())
        self.assertFalse(approval["hardware_armed"])

    def test_manual_stop_substitutes_probe_serial(self):
        config = self.valid_config()
        config["commands"]["stop"] = [
            sys.executable,
            "-c",
            "import sys; print(sys.argv[1])",
            "{probe_serial}",
        ]
        self.write_json(".hil/config.json", config)

        result = self.run_tool("hilctl", "stop")

        self.assertEqual(result.returncode, 0, result.stderr)
        logs = list((self.root / ".hil/logs").glob("manual-stop-*/stop.stdout.log"))
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].read_text().strip(), "TEST-PROBE")


if __name__ == "__main__":
    unittest.main()
