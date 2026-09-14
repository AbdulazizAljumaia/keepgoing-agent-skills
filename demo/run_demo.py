#!/usr/bin/env python3
"""Exercise the documented keepgoing/keepfixing lifecycle in an isolated workspace."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = REPO_ROOT / "skills" / "keepgoing" / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))

from keepgoing_runtime.engine import Runtime


def spec(profile: str, name: str) -> dict:
    if profile == "php":
        base = "Project/apps/web/src"
        extension = "php"
    else:
        base = "Project/apps/api/src"
        extension = "py"
    return {
        "project_name": name,
        "scope": "Demonstrate durable planning, resumption, correction, rating, and replacement.",
        "profile": profile,
        "timezone": "UTC",
        "requirements": [
            {"title": f"Demonstration outcome {index}", "acceptance": f"Outcome {index} has observed evidence."}
            for index in range(1, 4)
        ],
        "plans": [
            {
                "title": f"Demonstration plan {index}",
                "outcome": f"Deliver demonstration outcome {index}.",
                "scope": f"Change only the named demonstration file {index}.",
                "architecture": "Each demonstration unit is isolated behind one profile-owned module.",
                "requirements": [index],
                "dependencies": [index - 1] if index > 1 else [],
                "tasks": [
                    {
                        "title": f"Implement demonstration unit {index}",
                        "files": [f"{base}/unit_{index}.{extension}"],
                        "steps": [f"Implement and verify demonstration unit {index}."],
                        "acceptance": [f"Unit {index} produces its expected observable value."],
                        "verification": [f"Run demonstration verification {index} with exit code 0."],
                        "failure_behavior": ["Checkpoint the failing evidence and exact next action."],
                    }
                ],
            }
            for index in range(1, 4)
        ],
        "rules": ["Keep all demonstration side effects inside the selected disposable workspace."],
    }


def complete_first_task(runtime: Runtime, root: Path) -> None:
    relative = "Project/apps/api/src/unit_1.py"
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("quality = 1\n", encoding="utf-8")
    runtime.task_transition("TASK-001", "in_progress")
    runtime.task_transition("TASK-001", "verification")
    runtime.task_transition(
        "TASK-001",
        "complete",
        evidence=["Demonstration unit 1 check returned exit code 0."],
        evidence_files=[relative],
    )
    runtime.rate_task(
        "TASK-001",
        {
            "correctness": 9,
            "reliability": 8,
            "maintainability": 9,
            "compliance": 10,
            "efficiency": 8,
        },
        evidence=["Executed demonstration check and inspected the isolated source."],
    )
    runtime.complete_plan("PLAN-001")


def run(workspace: Path, private: Path) -> dict:
    os.environ["KEEPGOING_PRIVATE_HOME"] = str(private)
    runtime = Runtime(workspace)
    initialized = runtime.initialize(spec("generic", "Keepgoing Demonstration"), target=workspace)
    complete_first_task(runtime, workspace)
    runtime.task_transition("TASK-002", "in_progress")
    context = runtime.context_check(
        "measured", used=70, capacity=100, source="simulated acceptance-fixture input"
    )
    checkpoint = runtime.checkpoint(
        reason="Simulated measured 70% context threshold",
        task_id="TASK-002",
        step="1",
        next_action="Implement unit 2, then run demonstration verification 2.",
        do_not_repeat=["Do not reimplement completed TASK-001."],
    )
    fresh = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_ROOT / "keepgoing.py"),
            "--root",
            str(workspace / "Project" / "apps"),
            "status",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=dict(os.environ),
    )
    if fresh.returncode != 0:
        raise RuntimeError(f"Fresh-context status failed: {fresh.stderr or fresh.stdout}")
    resumed = json.loads(fresh.stdout)
    fixing = Runtime(workspace, mode="keepfixing")
    relative = "Project/apps/api/src/unit_1.py"
    for event_id, quality in (("DEMO-FIX-001", 2), ("DEMO-FIX-002", 3)):
        fixing.fix_begin("TASK-001", event_id, [relative])
        (workspace / relative).write_text(f"quality = {quality}\n", encoding="utf-8")
        fixing.fix_finish(event_id, evidence=[f"{event_id} isolated verification returned exit code 0."])
    replay = fixing.fix_finish(
        "DEMO-FIX-002", evidence=["Idempotent replay must not append another update."]
    )
    fixing.rate_task(
        "TASK-001",
        {
            "correctness": 10,
            "reliability": 9,
            "maintainability": 9,
            "compliance": 10,
            "efficiency": 9,
        },
        evidence=["Two distinct corrected results passed isolated verification."],
    )
    replacement = Runtime(workspace).replace(
        spec("php", "Keepgoing PHP Demonstration"),
        reason="Explicit demonstration conversion to PHP",
    )
    final_state = Runtime(workspace).load_state()
    archive = Path(replacement["archive"])
    return {
        "result": "success",
        "workspace": str(workspace),
        "initialized_generation": initialized["generation_id"],
        "context_decision": context["decision"],
        "context_source": context["measurement"]["source"],
        "checkpoint_next": checkpoint["next"],
        "fresh_process_next_task": resumed["next"]["task_id"],
        "correction_updates": 2,
        "correction_replay_idempotent": replay["idempotent"],
        "archive": str(archive),
        "archive_verified": (archive / "archive_manifest.json").is_file(),
        "replacement_profile": final_state["profile"],
        "replacement_predecessor": final_state["predecessor_id"],
        "replacement_generation": final_state["generation_id"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="Keep the demonstration workspace at this path")
    args = parser.parse_args()
    if args.output:
        workspace = Path(args.output).expanduser().resolve()
        private = workspace.parent / f".{workspace.name}-private"
        result = run(workspace, private)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    with tempfile.TemporaryDirectory(prefix="keepgoing-demo-") as temporary:
        root = Path(temporary)
        result = run(root / "workspace", root / "private")
        result["workspace_disposition"] = "deleted after successful isolated run"
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
