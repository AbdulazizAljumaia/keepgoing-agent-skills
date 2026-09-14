from __future__ import annotations

import base64
import errno
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "skills" / "keepgoing" / "scripts"
sys.path.insert(0, str(RUNTIME_SCRIPTS))

from keepgoing_runtime import engine, util
from keepgoing_runtime.engine import Runtime
from keepgoing_runtime.errors import BLOCKED, CONFLICT, INVALID, IO_FAILURE, RECOVERY_REQUIRED, KeepgoingError
from keepgoing_runtime.util import WorkspaceLock, path_inventory, read_json


def make_spec(profile: str = "generic", project_name: str = "Behavior Fixture") -> dict:
    extensions = {"generic": "py", "angular": "ts", "flutter": "dart", "php": "php"}
    roots = {
        "generic": "Project/apps/api/src",
        "angular": "Project/apps/web/src/app/features",
        "flutter": "Project/apps/flutter_app/lib/features",
        "php": "Project/apps/web/src",
    }
    ext = extensions[profile]
    base = roots[profile]
    requirements = [
        {"title": f"Requirement {index}", "acceptance": f"Observable acceptance {index}."}
        for index in range(1, 4)
    ]
    plans = []
    for index in range(1, 4):
        plans.append(
            {
                "title": f"Plan {index}",
                "outcome": f"Deliver the complete behavior for requirement {index}.",
                "scope": f"Change only the named plan {index} file.",
                "architecture": f"The profile-owned module {index} contains the behavior.",
                "requirements": [index],
                "dependencies": [1] if index == 2 else [],
                "priority": index,
                "tasks": [
                    {
                        "title": f"Task {index}",
                        "files": [f"{base}/feature_{index}.{ext}"],
                        "steps": [f"Implement behavior {index} in the named file."],
                        "acceptance": [f"Behavior {index} is observed."],
                        "verification": [f"Run fixture verification {index} and record exit code 0."],
                        "failure_behavior": [f"Keep task {index} incomplete with the failing evidence."],
                    }
                ],
            }
        )
    return {
        "project_name": project_name,
        "scope": "Exercise durable organizer behavior in an isolated fixture.",
        "profile": profile,
        "timezone": "UTC",
        "requirements": requirements,
        "plans": plans,
        "rules": ["Keep fixture work inside its temporary workspace."],
    }


class RuntimeBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="keepgoing-tests-")
        self.base = Path(self.temp.name)
        self.root = self.base / "workspace with spaces ü"
        self.private = self.base / "private"
        self.previous_private = os.environ.get("KEEPGOING_PRIVATE_HOME")
        os.environ["KEEPGOING_PRIVATE_HOME"] = str(self.private)
        self.runtime = Runtime(self.root)

    def tearDown(self) -> None:
        if self.previous_private is None:
            os.environ.pop("KEEPGOING_PRIVATE_HOME", None)
        else:
            os.environ["KEEPGOING_PRIVATE_HOME"] = self.previous_private
        self.temp.cleanup()

    def initialize(self, profile: str = "generic", root: Path | None = None) -> Runtime:
        selected = root or self.root
        runtime = Runtime(selected)
        result = runtime.initialize(make_spec(profile), target=selected)
        self.assertEqual(result["result"], "success")
        return runtime

    def write_task_files(self, runtime: Runtime, task_id: str, content: str = "implemented = True\n") -> list[str]:
        state = runtime.load_state()
        paths = state["tasks"][task_id]["files"]
        for relative in paths:
            target = runtime.root() / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return paths

    def complete_task(self, runtime: Runtime, task_id: str, content: str = "implemented = True\n") -> None:
        files = self.write_task_files(runtime, task_id, content)
        runtime.task_transition(task_id, "in_progress")
        runtime.task_transition(task_id, "verification")
        runtime.task_transition(
            task_id,
            "complete",
            evidence=["Fixture verification observed exit code 0."],
            evidence_files=files,
        )

    def test_01_fresh_initialization(self) -> None:
        runtime = self.initialize()
        required = ["Project", "instructions", "plans", "sessions", "rates", "deprecated"]
        self.assertTrue(all((self.root / name).is_dir() for name in required))
        self.assertTrue(all((self.root / "plans" / f"plan_{index}.md").is_file() for index in range(1, 4)))
        state = runtime.load_state()
        self.assertEqual(len(state["requirements"]), 3)
        self.assertEqual(len(state["plans"]), 3)

    def test_02_repeated_initialization_is_idempotent(self) -> None:
        runtime = self.initialize()
        before = runtime.load_state()
        result = runtime.initialize(make_spec(), target=self.root)
        after = runtime.load_state()
        self.assertTrue(result["idempotent"])
        self.assertEqual(before["workspace_id"], after["workspace_id"])
        self.assertEqual(before["counters"], after["counters"])
        self.assertFalse((self.root / "Project" / "Project").exists())
        changed = make_spec(project_name="Different Project")
        with self.assertRaises(KeepgoingError) as caught:
            runtime.initialize(changed, target=self.root)
        self.assertEqual(caught.exception.code, CONFLICT)

    def test_03_resume_from_nested_application_path(self) -> None:
        runtime = self.initialize()
        nested = self.root / "Project" / "apps" / "api" / "src"
        nested.mkdir(parents=True, exist_ok=True)
        status = Runtime(nested).status()
        self.assertEqual(status["workspace_id"], runtime.load_state()["workspace_id"])
        self.assertEqual(status["next"]["task_id"], "TASK-001")

    def test_04_archive_invocation_is_protected(self) -> None:
        runtime = self.initialize()
        archive = self.root / "deprecated" / "2026-01-01_00-00-00" / "Project"
        archive.mkdir(parents=True)
        with self.assertRaises(KeepgoingError) as caught:
            Runtime(archive).status()
        self.assertEqual(caught.exception.code, BLOCKED)
        self.assertEqual(runtime.status()["next"]["task_id"], "TASK-001")

    def test_05_framework_profiles_share_envelope_and_differ_inside(self) -> None:
        expected = {
            "angular": "Project/apps/web/src/app/core/auth",
            "flutter": "Project/apps/flutter_app/lib/core",
            "php": "Project/apps/web/public",
        }
        generations = set()
        for profile, path in expected.items():
            root = self.base / profile
            runtime = self.initialize(profile, root)
            generations.add(runtime.load_state()["generation_id"])
            self.assertTrue((root / path).is_dir())
            self.assertTrue((root / "instructions" / "state.json").is_file())
        self.assertEqual(len(generations), 3)

    def test_06_unplanned_path_is_rejected_and_drift_detected(self) -> None:
        runtime = self.initialize()
        with self.assertRaises(KeepgoingError) as caught:
            runtime.path_check("TASK-001", "Project/apps/api/src/unplanned.py")
        self.assertEqual(caught.exception.code, BLOCKED)
        drift = self.root / "Project" / "apps" / "api" / "src" / "unplanned.py"
        drift.parent.mkdir(parents=True, exist_ok=True)
        drift.write_text("external = True\n", encoding="utf-8")
        result = runtime.detect_drift()
        self.assertEqual(result["result"], "conflict")
        with self.assertRaises(KeepgoingError):
            runtime.checkpoint(reason="drift check")
        self.assertTrue(drift.exists())

    def test_07_complete_plan_preserves_exact_snapshot(self) -> None:
        runtime = self.initialize()
        self.complete_task(runtime, "TASK-001")
        plan_path = self.root / "plans" / "plan_1.md"
        original = plan_path.read_bytes()
        result = runtime.complete_plan("PLAN-001")
        self.assertFalse(plan_path.exists())
        session = (self.root / "sessions" / "session_1.md").read_text(encoding="utf-8")
        match = re.search(r"Exact UTF-8 plan bytes \(base64\):\n```text\n([^\n]+)", session)
        self.assertIsNotNone(match)
        self.assertEqual(base64.b64decode(match.group(1)), original)
        self.assertIn(result["snapshot_hash"], session)

    def test_08_plan_spanning_sessions_keeps_original_completion_sessions(self) -> None:
        spec = make_spec()
        spec["plans"][0]["tasks"].append(
            {
                "title": "Second plan-one task",
                "files": ["Project/apps/api/src/feature_1b.py"],
                "steps": ["Implement the second coherent unit."],
                "acceptance": ["The second unit is observed."],
                "verification": ["Run its fixture verification."],
                "failure_behavior": ["Preserve a precise continuation on failure."],
            }
        )
        self.runtime.initialize(spec, target=self.root)
        self.complete_task(self.runtime, "TASK-001")
        self.runtime.checkpoint(
            reason="session boundary",
            task_id="TASK-002",
            step="1",
            next_action="Implement the second plan-one task.",
        )
        self.runtime.resume(open_session=True, agent="fresh-test-process")
        self.complete_task(self.runtime, "TASK-002")
        self.runtime.complete_plan("PLAN-001")
        state = self.runtime.load_state()
        self.assertEqual(state["tasks"]["TASK-001"]["completion_session"], "SESSION-001")
        self.assertEqual(state["tasks"]["TASK-002"]["completion_session"], "SESSION-002")
        closing = (self.root / "sessions" / "session_2.md").read_text(encoding="utf-8")
        self.assertIn('"TASK-001":"SESSION-001"', closing)
        self.assertIn('"TASK-002":"SESSION-002"', closing)

    def test_09_partial_task_checkpoint_is_executable(self) -> None:
        runtime = self.initialize()
        runtime.task_transition("TASK-001", "in_progress")
        runtime.checkpoint(
            reason="simulated interruption",
            task_id="TASK-001",
            step="1.2",
            next_action="Finish the parser branch, then run fixture verification 1.",
            relevant_paths=["Project/apps/api/src/feature_1.py"],
            do_not_repeat=["Do not recreate the initialized workspace."],
        )
        pointer = runtime.load_state()["resume"]
        self.assertEqual(pointer["task_id"], "TASK-001")
        self.assertIn("run fixture verification", pointer["next_action"])
        self.assertEqual(runtime.load_state()["tasks"]["TASK-001"]["state"], "in_progress")

    def test_10_fresh_process_resume_uses_saved_records(self) -> None:
        runtime = self.initialize()
        self.complete_task(runtime, "TASK-001")
        runtime.complete_plan("PLAN-001")
        command = [
            sys.executable,
            str(RUNTIME_SCRIPTS / "keepgoing.py"),
            "--root",
            str(self.root / "Project" / "apps"),
            "status",
        ]
        environment = dict(os.environ)
        process = subprocess.run(command, capture_output=True, text=True, env=environment, check=False)
        self.assertEqual(process.returncode, 0, process.stderr)
        output = json.loads(process.stdout)
        self.assertEqual(output["next"]["task_id"], "TASK-002")
        self.assertNotEqual(output["next"]["task_id"], "TASK-001")

    def test_11_exact_context_boundary_and_forecast(self) -> None:
        runtime = self.initialize()
        at_boundary = runtime.context_check("measured", used=Decimal("70"), capacity=Decimal("100"))
        self.assertEqual(at_boundary["decision"], "checkpoint")
        below = runtime.context_check(
            "measured",
            used=Decimal("69.9"),
            capacity=Decimal("100"),
            next_cost=Decimal("0.01"),
            checkpoint_reserve=Decimal("0.01"),
        )
        self.assertEqual(below["decision"], "continue")
        forecast = runtime.context_check(
            "measured",
            used=Decimal("69.9"),
            capacity=Decimal("100"),
            next_cost=Decimal("0.2"),
        )
        self.assertEqual(forecast["decision"], "checkpoint")
        integer_input = runtime.context_check("measured", used=7, capacity=10)
        self.assertEqual(integer_input["decision"], "checkpoint")
        integer_input = runtime.context_check("measured", used=7, capacity=10)
        self.assertEqual(integer_input["decision"], "checkpoint")
        integer_input = runtime.context_check("measured", used=7, capacity=10)
        self.assertEqual(integer_input["decision"], "checkpoint")

    def test_12_unknown_context_never_fabricates_percentage(self) -> None:
        runtime = self.initialize()
        result = runtime.context_check("unavailable")
        self.assertEqual(result["decision"], "checkpoint")
        self.assertNotIn("usage_percent", result["measurement"])
        self.assertIn("unavailable", result["measurement"]["mode"])

    def test_13_interrupted_record_transaction_rolls_forward(self) -> None:
        runtime = self.initialize()
        original = runtime.load_state()["last_committed_event"]
        with mock.patch.object(engine, "_apply_write_set", side_effect=KeepgoingError("injected", IO_FAILURE)):
            with self.assertRaises(KeepgoingError):
                runtime.task_transition("TASK-001", "in_progress")
        with self.assertRaises(KeepgoingError) as pending:
            runtime.status()
        self.assertEqual(pending.exception.code, RECOVERY_REQUIRED)
        self.assertEqual(
            read_json(self.root / "instructions" / "state.json")["last_committed_event"], original
        )
        recovery = runtime.recover()
        self.assertEqual(recovery["action"], "rolled forward prepared transaction")
        self.assertEqual(runtime.load_state()["tasks"]["TASK-001"]["state"], "in_progress")

    def test_14_disk_write_failure_preserves_prior_snapshot(self) -> None:
        runtime = self.initialize()
        before = (self.root / "instructions" / "state.json").read_bytes()
        with mock.patch.object(engine, "_apply_write_set", side_effect=KeepgoingError("disk full", IO_FAILURE)):
            with self.assertRaises(KeepgoingError) as caught:
                runtime.task_transition("TASK-001", "in_progress")
        self.assertEqual(caught.exception.code, IO_FAILURE)
        self.assertEqual((self.root / "instructions" / "state.json").read_bytes(), before)

    def test_15_damaged_state_and_truncated_tail_are_recovered(self) -> None:
        runtime = self.initialize()
        (self.root / "instructions" / "state.json").write_text("{broken", encoding="utf-8")
        with (self.root / "instructions" / "ledger.jsonl").open("a", encoding="utf-8") as handle:
            handle.write('{"truncated":')
        recovered = runtime.recover()
        self.assertTrue(recovered["preserved_invalid_ledger"])
        state = runtime.load_state()
        self.assertEqual(state["counters"]["plan"], 3)
        self.assertEqual(runtime.validate()["issues"], [])

    def test_16_one_keepfixing_correction_preserves_completion(self) -> None:
        runtime = self.initialize()
        self.complete_task(runtime, "TASK-001")
        original = runtime.load_state()["tasks"]["TASK-001"]["completed_at"]
        path = "Project/apps/api/src/feature_1.py"
        fixing = Runtime(self.root, mode="keepfixing")
        fixing.fix_begin("TASK-001", "FIX-ONE", [path])
        (self.root / path).write_text("implemented = 'improved'\n", encoding="utf-8")
        fixing.fix_finish("FIX-ONE", evidence=["Correction fixture passed with exit code 0."])
        task = fixing.load_state()["tasks"]["TASK-001"]
        self.assertEqual(task["completed_at"], original)
        self.assertEqual(len(task["updates"]), 1)
        summary = (self.root / "sessions" / "session_sum.md").read_text(encoding="utf-8")
        self.assertIn("[updated]", summary)
        self.assertEqual(fixing.validate()["issues"], [])

    def test_17_repeated_corrections_are_distinct_and_idempotent(self) -> None:
        runtime = self.initialize()
        self.complete_task(runtime, "TASK-001")
        fixing = Runtime(self.root, mode="keepfixing")
        path = "Project/apps/api/src/feature_1.py"
        for event, value in (("FIX-A", "a"), ("FIX-B", "b")):
            fixing.fix_begin("TASK-001", event, [path])
            (self.root / path).write_text(f"value = '{value}'\n", encoding="utf-8")
            fixing.fix_finish(event, evidence=[f"{event} verified."])
        replay = fixing.fix_finish("FIX-B", evidence=["Replay evidence is ignored."])
        self.assertTrue(replay["idempotent"])
        updates = fixing.load_state()["tasks"]["TASK-001"]["updates"]
        self.assertEqual([item["event_id"] for item in updates], ["FIX-A", "FIX-B"])

    def test_18_keepfixing_blocks_new_persistent_path(self) -> None:
        runtime = self.initialize()
        self.complete_task(runtime, "TASK-001")
        fixing = Runtime(self.root, mode="keepfixing")
        path = "Project/apps/api/src/feature_1.py"
        fixing.fix_begin("TASK-001", "FIX-NEW-PATH", [path])
        unexpected = self.root / "Project" / "apps" / "api" / "src" / "new.py"
        unexpected.write_text("not_allowed = True\n", encoding="utf-8")
        with self.assertRaises(KeepgoingError) as caught:
            fixing.fix_finish("FIX-NEW-PATH", evidence=["Not valid."])
        self.assertEqual(caught.exception.code, BLOCKED)
        self.assertTrue(unexpected.exists())

    def test_19_keepfixing_metadata_creates_no_workspace_path(self) -> None:
        runtime = self.initialize()
        self.complete_task(runtime, "TASK-001")
        before = path_inventory(self.root)
        fixing = Runtime(self.root, mode="keepfixing")
        fixing.fix_begin(
            "TASK-001", "FIX-INVENTORY", ["Project/apps/api/src/feature_1.py"]
        )
        self.assertEqual(before, path_inventory(self.root))

    def test_20_failed_correction_stays_unresolved_without_update(self) -> None:
        runtime = self.initialize()
        self.complete_task(runtime, "TASK-001")
        fixing = Runtime(self.root, mode="keepfixing")
        path = "Project/apps/api/src/feature_1.py"
        fixing.fix_begin("TASK-001", "FIX-FAIL", [path])
        (self.root / path).write_text("broken = True\n", encoding="utf-8")
        result = fixing.fix_finish(
            "FIX-FAIL", failed=True, reason="Restore the valid branch and rerun fixture verification."
        )
        task = fixing.load_state()["tasks"]["TASK-001"]
        self.assertEqual(result["result"], "blocked")
        self.assertEqual(task["state"], "verification_pending")
        self.assertEqual(task["updates"], [])
        self.assertIn("FIX-FAIL", fixing.load_state()["pending_corrections"])
        retry = fixing.fix_begin("TASK-001", "FIX-FAIL", [path])
        self.assertTrue(retry["idempotent"])
        (self.root / path).write_text("repaired = True\n", encoding="utf-8")
        fixing.fix_finish("FIX-FAIL", evidence=["Retried correction verification passed."])
        recovered = fixing.load_state()
        self.assertEqual(len(recovered["tasks"]["TASK-001"]["updates"]), 1)
        self.assertNotIn("FIX-FAIL", recovered["pending_corrections"])
        self.assertFalse(any(item.get("task_id") == "TASK-001" for item in recovered["blockers"]))

    def test_21_rating_aggregation_uses_unique_weighted_tasks(self) -> None:
        runtime = self.initialize()
        self.complete_task(runtime, "TASK-001")
        runtime.rate_task(
            "TASK-001",
            {key: "10" for key in engine.RATING_WEIGHTS},
            evidence=["All task-one fixture checks passed."],
        )
        runtime.complete_plan("PLAN-001")
        runtime.checkpoint(reason="new scoring session")
        runtime.resume(open_session=True)
        self.complete_task(runtime, "TASK-002")
        runtime.rate_task(
            "TASK-002",
            {key: "6" for key in engine.RATING_WEIGHTS},
            evidence=["Task-two checks passed with documented limitations."],
        )
        rates = (self.root / "rates" / "Sessions_rate.md").read_text(encoding="utf-8")
        self.assertIn("Total[8.0/10]", rates)
        self.assertIn("Rating coverage[2/2", rates)

    def test_22_unfinished_project_never_claims_ten(self) -> None:
        runtime = self.initialize()
        validation = runtime.validate()
        rates = (self.root / "rates" / "Sessions_rate.md").read_text(encoding="utf-8")
        self.assertFalse(validation["complete"])
        self.assertIn("Total[N/A]", rates)
        self.assertNotIn("Total[10", rates)

    def test_23_scope_revision_preserves_superseded_requirement(self) -> None:
        runtime = self.initialize()
        runtime.requirement_revise(
            "REQ-001",
            title="Revised requirement one",
            acceptance="The revised observable result is present.",
            reason="The user changed the accepted behavior.",
            authorized_by="explicit test instruction",
        )
        item = runtime.load_state()["requirements"]["REQ-001"]
        self.assertEqual(item["title"], "Revised requirement one")
        self.assertEqual(item["history"][0]["title"], "Requirement 1")
        self.assertIn("explicit test instruction", item["history"][0]["authorized_by"])

    def test_24_blocked_dependency_does_not_hide_independent_work(self) -> None:
        runtime = self.initialize()
        with self.assertRaises(KeepgoingError) as caught:
            runtime.task_transition("TASK-002", "in_progress")
        self.assertEqual(caught.exception.code, BLOCKED)
        runtime.task_transition("TASK-001", "blocked", reason="External fixture dependency is unavailable.")
        status = runtime.status()
        self.assertEqual(status["next"]["task_id"], "TASK-003")

    def test_25_external_source_change_invalidates_evidence(self) -> None:
        runtime = self.initialize()
        self.complete_task(runtime, "TASK-001")
        target = self.root / "Project" / "apps" / "api" / "src" / "feature_1.py"
        target.write_text("external_change = True\n", encoding="utf-8")
        issues = runtime.detect_drift()["issues"]
        self.assertTrue(any("Evidence stale" in item for item in issues))
        self.assertIn("external_change", target.read_text(encoding="utf-8"))

    def test_26_explicit_replacement_preserves_history_and_lineage(self) -> None:
        runtime = self.initialize()
        old = runtime.load_state()
        result = runtime.replace(make_spec("php", "PHP Generation"), reason="Explicit PHP conversion")
        archive = Path(result["archive"])
        self.assertTrue(all((archive / name).exists() for name in ("Project", "instructions", "plans", "sessions", "rates")))
        self.assertTrue((archive / "archive_manifest.json").is_file())
        new = runtime.load_state()
        self.assertEqual(new["profile"], "php")
        self.assertEqual(new["predecessor_id"], old["generation_id"])
        self.assertNotEqual(new["generation_id"], old["generation_id"])

    def test_27_interrupted_replacement_recovers_each_boundary_class(self) -> None:
        for index, boundary in enumerate(("prepared", "archived:Project", "promoted:Project"), 1):
            with self.subTest(boundary=boundary):
                root = self.base / f"replace-{index}"
                runtime = self.initialize("generic", root)
                with self.assertRaises(KeepgoingError):
                    runtime.replace(
                        make_spec("php", f"Replacement {index}"),
                        reason="Injected recovery exercise",
                        fail_after=boundary,
                    )
                recovered = Runtime(root).recover_replacement()
                self.assertEqual(recovered["status"], "committed")
                self.assertEqual(Runtime(root).load_state()["profile"], "php")
                self.assertFalse((root / "Project" / "Project").exists())

    def test_28_archive_name_collision_uses_portable_suffix(self) -> None:
        runtime = self.initialize()
        existing = self.root / "deprecated" / "2026-09-14_12-00-00"
        existing.mkdir()
        result = runtime.replace(
            make_spec("php", "Collision Replacement"),
            reason="Exercise portable archive collision",
            stamp="2026-09-14_12-00-00",
        )
        self.assertTrue(result["archive"].endswith("2026-09-14_12-00-00-1"))
        self.assertTrue(existing.exists())

    def test_29_path_platform_and_symlink_boundaries(self) -> None:
        runtime = self.initialize()
        self.assertIn("spaces ü", runtime.status()["workspace_root"])
        with self.assertRaises(KeepgoingError):
            runtime.path_check("TASK-001", "Project/../escape.py")
        outside = self.base / "outside"
        outside.mkdir()
        link = self.root / "Project" / "apps" / "api" / "escape-link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                self.skipTest("This host does not permit test symlink creation")
            junction = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                capture_output=True,
                text=True,
                check=False,
            )
            if junction.returncode != 0:
                self.skipTest("This Windows host permits neither symlinks nor test junctions")
        with self.assertRaises(KeepgoingError):
            path_inventory(self.root)

    def test_30_concurrent_writer_cannot_consume_shared_state(self) -> None:
        runtime = self.initialize()
        before = runtime.load_state()["counters"]
        with WorkspaceLock(self.root):
            with self.assertRaises(KeepgoingError) as caught:
                with WorkspaceLock(self.root):
                    self.fail("A second writer unexpectedly acquired the lock")
        self.assertEqual(caught.exception.code, CONFLICT)
        self.assertEqual(runtime.load_state()["counters"], before)

    def test_adoption_preview_and_execution_preserve_boundary_files(self) -> None:
        root = self.base / "legacy"
        root.mkdir()
        (root / "legacy.php").write_text("<?php echo 'legacy';\n", encoding="utf-8")
        (root / "AGENTS.md").write_text("# Boundary instructions\n", encoding="utf-8")
        runtime = Runtime(root)
        preview = runtime.initialize(make_spec("php"), target=root, adopt=True, dry_run=True)
        self.assertEqual(preview["moves"], [{"from": "legacy.php", "to": "Project/legacy.php"}])
        runtime.initialize(make_spec("php"), target=root, adopt=True)
        self.assertTrue((root / "Project" / "legacy.php").is_file())
        self.assertTrue((root / "AGENTS.md").is_file())

    def test_plan_revision_preserves_prior_bytes(self) -> None:
        runtime = self.initialize()
        before = (self.root / "plans" / "plan_1.md").read_bytes()
        runtime.plan_revise(
            "PLAN-001",
            {"outcome": "Deliver revised behavior one without changing its authorized path."},
            reason="User clarified the result.",
        )
        history = runtime.load_state()["plans"]["PLAN-001"]["revision_history"]
        snapshot = next(item for item in history if item.get("snapshot_base64"))
        self.assertEqual(base64.b64decode(snapshot["snapshot_base64"]), before)

    def test_completion_requires_hashes_for_every_task_file(self) -> None:
        spec = make_spec()
        spec["plans"][0]["tasks"][0]["files"].append(
            "Project/apps/api/tests/feature_1_test.py"
        )
        self.runtime.initialize(spec, target=self.root)
        files = self.write_task_files(self.runtime, "TASK-001")
        self.runtime.task_transition("TASK-001", "in_progress")
        self.runtime.task_transition("TASK-001", "verification")
        with self.assertRaises(KeepgoingError) as caught:
            self.runtime.task_transition(
                "TASK-001",
                "complete",
                evidence=["Only one file was observed."],
                evidence_files=[files[0]],
            )
        self.assertEqual(caught.exception.code, BLOCKED)
        self.assertEqual(self.runtime.load_state()["tasks"]["TASK-001"]["state"], "verification")

    def test_31_initialization_rejects_nested_active_and_archive_targets(self) -> None:
        runtime = self.initialize()
        nested = self.root / "Project" / "apps" / "api" / "nested"
        with self.assertRaises(KeepgoingError) as active:
            Runtime(nested).initialize(make_spec(), target=nested)
        self.assertEqual(active.exception.code, BLOCKED)
        archived = self.root / "deprecated" / "historical"
        with self.assertRaises(KeepgoingError) as protected:
            Runtime(archived).initialize(make_spec(), target=archived)
        self.assertEqual(protected.exception.code, BLOCKED)
        self.assertEqual(runtime.status()["project_name"], "Behavior Fixture")

    def test_32_adoption_refuses_user_owned_organizer_collision(self) -> None:
        root = self.base / "adopt-collision"
        protected = root / "instructions" / "project.md"
        protected.parent.mkdir(parents=True)
        protected.write_text("user-owned\n", encoding="utf-8")
        with self.assertRaises(KeepgoingError) as caught:
            Runtime(root).initialize(make_spec(), target=root, adopt=True)
        self.assertEqual(caught.exception.code, CONFLICT)
        self.assertEqual(protected.read_text(encoding="utf-8"), "user-owned\n")

    def test_33_status_requires_plan_closure_before_completion(self) -> None:
        runtime = self.initialize()
        self.complete_task(runtime, "TASK-001")
        runtime.complete_plan("PLAN-001")
        for task_id in ("TASK-002", "TASK-003"):
            self.complete_task(runtime, task_id)
        status = runtime.status()
        self.assertEqual(status["completion"], {"completed": 3, "required": 3})
        self.assertFalse(status["complete"])
        self.assertTrue((self.root / "plans" / "plan_2.md").is_file())

    def test_34_state_and_derived_views_are_checked_against_authority(self) -> None:
        runtime = self.initialize()
        state_path = self.root / "instructions" / "state.json"
        state = read_json(state_path)
        state["project_name"] = "tampered"
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        validation = runtime.validate()
        self.assertTrue(any("ledger authority" in issue for issue in validation["issues"]))
        with self.assertRaises(KeepgoingError) as caught:
            runtime.status()
        self.assertEqual(caught.exception.code, RECOVERY_REQUIRED)
        runtime.recover()
        project_record = self.root / "instructions" / "project.md"
        project_record.write_text("tampered derived view\n", encoding="utf-8")
        self.assertTrue(any("Derived record" in issue for issue in runtime.validate()["issues"]))

    def test_35_successful_fix_requires_change_and_protects_boundary_content(self) -> None:
        runtime = self.initialize()
        self.complete_task(runtime, "TASK-001")
        fixing = Runtime(self.root, mode="keepfixing")
        path = "Project/apps/api/src/feature_1.py"
        fixing.fix_begin("TASK-001", "FIX-NOOP", [path])
        with self.assertRaises(KeepgoingError) as noop:
            fixing.fix_finish("FIX-NOOP", evidence=["Claimed verification only."])
        self.assertEqual(noop.exception.code, BLOCKED)

        boundary = self.root / "AGENTS.md"
        boundary.write_text("before\n", encoding="utf-8")
        fixing.fix_begin("TASK-001", "FIX-BOUNDARY", [path])
        boundary.write_text("after\n", encoding="utf-8")
        (self.root / path).write_text("corrected = True\n", encoding="utf-8")
        with self.assertRaises(KeepgoingError) as protected:
            fixing.fix_finish("FIX-BOUNDARY", evidence=["Observed fixture pass."])
        self.assertEqual(protected.exception.code, BLOCKED)

    def test_36_stale_serialized_writer_cannot_erase_allocated_plan(self) -> None:
        runtime = self.initialize()
        barrier = threading.Barrier(2)
        serial = threading.Lock()

        class SerializingTestLock:
            def __init__(self, root: Path):
                self.root = root

            def __enter__(self):
                barrier.wait(timeout=10)
                serial.acquire()
                return self

            def __exit__(self, exc_type, exc, traceback):
                serial.release()

        plan_spec = {
            "title": "Concurrent allocation",
            "outcome": "Allocate exactly once.",
            "scope": "One existing profile path.",
            "architecture": "Use the governed runtime.",
            "requirements": ["REQ-001"],
            "tasks": [{
                "title": "Concurrent task",
                "files": ["Project/apps/api/src/concurrent.py"],
                "steps": ["Allocate."],
                "acceptance": ["One plan exists."],
                "verification": ["Inspect counters."],
                "failure_behavior": ["Report conflict."],
            }],
        }
        outcomes: list[object] = []

        def allocate() -> None:
            try:
                outcomes.append(runtime.plan_allocate(plan_spec))
            except Exception as exc:  # captured for assertion in the parent thread
                outcomes.append(exc)

        with mock.patch.object(engine, "WorkspaceLock", SerializingTestLock):
            threads = [threading.Thread(target=allocate) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(sum(isinstance(item, dict) for item in outcomes), 1)
        failures = [item for item in outcomes if isinstance(item, KeepgoingError)]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].code, CONFLICT)
        state = runtime.load_state()
        self.assertEqual(state["counters"]["plan"], 4)
        self.assertEqual(state["counters"]["task"], 4)
        self.assertEqual(len(state["plans"]), 4)

    def test_37_prepared_ledger_is_checksum_metadata_not_raw_records(self) -> None:
        self.initialize()
        first = json.loads(
            (self.root / "instructions" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()[0]
        )
        payload = first["payload"]
        self.assertEqual(first["type"], "TX_PREPARED")
        self.assertNotIn("target_state", payload)
        self.assertNotIn("writes", payload)
        self.assertNotIn("details", payload)
        self.assertTrue(Path(payload["recovery_bundle"]).is_file())

    def test_38_replacement_recovery_rejects_tampered_archive(self) -> None:
        runtime = self.initialize()
        with self.assertRaises(KeepgoingError):
            runtime.replace(
                make_spec("php", "Replacement tamper"),
                reason="Exercise baseline verification",
                fail_after="archived:Project",
            )
        marker = read_json(self.root / "deprecated" / "replacement.json")
        self.assertIn("baseline_manifest", marker)
        archive = Path(marker["archive"])
        tampered = archive / "Project" / "tampered.txt"
        tampered.write_text("unexpected\n", encoding="utf-8")
        with self.assertRaises(KeepgoingError) as caught:
            Runtime(self.root).recover_replacement()
        self.assertEqual(caught.exception.code, RECOVERY_REQUIRED)
        self.assertTrue(tampered.is_file())

    def test_39_verified_move_falls_back_across_filesystems(self) -> None:
        source = self.base / "cross-source"
        target = self.base / "cross-target"
        source.mkdir()
        (source / "payload.txt").write_text("durable\n", encoding="utf-8")
        cross_device = OSError(errno.EXDEV, "cross-device link")
        with mock.patch.object(util.os, "replace", side_effect=cross_device):
            mode = util.move_verified(source, target)
        self.assertEqual(mode, "verified-copy")
        self.assertFalse(source.exists())
        self.assertEqual((target / "payload.txt").read_text(encoding="utf-8"), "durable\n")

    def test_40_archive_stamp_and_recovery_delete_set_are_bounded(self) -> None:
        runtime = self.initialize()
        outside = self.base / "outside-archive"
        with self.assertRaises(KeepgoingError) as stamp:
            runtime.replace(make_spec("php"), reason="Reject absolute archive", stamp=str(outside))
        self.assertEqual(stamp.exception.code, INVALID)
        with mock.patch.object(engine, "_apply_write_set", side_effect=KeepgoingError("injected", IO_FAILURE)):
            with self.assertRaises(KeepgoingError):
                runtime.task_transition("TASK-001", "in_progress")
        prepared = json.loads(
            (self.root / "instructions" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()[-1]
        )
        bundle_path = Path(prepared["payload"]["recovery_bundle"])
        bundle = read_json(bundle_path)
        bundle["deletes"] = ["AGENTS.md"]
        bundle_path.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(KeepgoingError) as recovery:
            runtime.recover()
        self.assertEqual(recovery.exception.code, RECOVERY_REQUIRED)

    def test_41_replacement_marker_and_missing_state_require_recovery(self) -> None:
        runtime = self.initialize()
        with self.assertRaises(KeepgoingError):
            runtime.replace(make_spec("php"), reason="Interrupted replacement", fail_after="prepared")
        with self.assertRaises(KeepgoingError) as second:
            runtime.replace(make_spec("php"), reason="Do not orphan first marker")
        self.assertEqual(second.exception.code, RECOVERY_REQUIRED)
        Runtime(self.root).recover_replacement()
        state_path = self.root / "instructions" / "state.json"
        state_path.unlink()
        recovered = Runtime(self.root).recover()
        self.assertIn("rebuilt", recovered["action"])
        self.assertTrue(state_path.is_file())

    def test_42_ledger_schema_errors_are_reported(self) -> None:
        runtime = self.initialize()
        ledger = self.root / "instructions" / "ledger.jsonl"
        lines = ledger.read_text(encoding="utf-8").splitlines()
        first = json.loads(lines[0])
        first["schema_version"] = 999
        lines[0] = json.dumps(first, separators=(",", ":"))
        ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = runtime.validate()
        self.assertTrue(any("schema" in issue.lower() for issue in result["issues"]))

    def test_43_shipped_example_spec_generates_documented_envelope(self) -> None:
        spec_path = REPO_ROOT / "skills" / "keepgoing" / "assets" / "workspace-spec.example.json"
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        root = self.base / "documented-notes-example"
        runtime = Runtime(root)
        result = runtime.initialize(spec, target=root)
        self.assertEqual(result["result"], "success")
        required = (
            "Project/apps/api/src",
            "Project/apps/api/tests",
            "instructions/project.md",
            "instructions/structure.md",
            "instructions/state.json",
            "instructions/ledger.jsonl",
            "plans/plan_1.md",
            "plans/plan_index.md",
            "sessions/session_1.md",
            "sessions/session_sum.md",
            "rates/session_1_rate.md",
            "rates/Sessions_rate.md",
            "deprecated",
        )
        self.assertTrue(all((root / relative).exists() for relative in required))
        for relative in spec["plans"][0]["tasks"][0]["files"]:
            self.assertFalse((root / relative).exists())
        structure = (root / "instructions" / "structure.md").read_text(encoding="utf-8")
        self.assertIn("Project/apps/api/src/notes.py", structure)
        self.assertIn("Project/apps/api/tests/test_notes.py", structure)
        self.assertEqual(runtime.validate()["issues"], [])


if __name__ == "__main__":
    unittest.main()
