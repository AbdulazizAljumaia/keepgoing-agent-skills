"""Command-line interface for the shared keepgoing runtime."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Sequence

from .engine import Runtime
from .errors import INVALID, KeepgoingError
from .util import SCHEMA_VERSION


def _json_file(value: str) -> dict[str, Any]:
    path = Path(value)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise argparse.ArgumentTypeError(f"Could not read JSON object from {value}: {exc}") from exc
    if not isinstance(data, dict):
        raise argparse.ArgumentTypeError(f"Expected JSON object in {value}")
    return data


def _decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"Invalid decimal: {value}") from exc


def _parser(mode: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keepfixing" if mode == "keepfixing" else "keepgoing",
        description="Deterministic organizer for resumable coding-agent workspaces.",
    )
    parser.add_argument("--root", default=".", help="Starting path for workspace discovery")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    commands = parser.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("initialize", help="Create a governed workspace from a full JSON spec")
    initialize.add_argument("--spec", required=True, type=_json_file)
    initialize.add_argument("--target")
    initialize.add_argument("--dry-run", action="store_true")

    adopt = commands.add_parser("adopt", help="Adopt an existing application after a dry-run review")
    adopt.add_argument("--spec", required=True, type=_json_file)
    adopt.add_argument("--target")
    adopt.add_argument("--dry-run", action="store_true")

    commands.add_parser("status", help="Read current project status and continuation")
    resume = commands.add_parser("resume", help="Resume from durable state")
    resume.add_argument("--open-session", action="store_true")
    resume.add_argument("--agent")

    path_check = commands.add_parser("path-check", help="Check a managed path before editing")
    path_check.add_argument("--task", required=True)
    path_check.add_argument("--path", required=True)

    transition = commands.add_parser("task-transition", help="Apply a validated task lifecycle transition")
    transition.add_argument("--task", required=True)
    transition.add_argument("--to", required=True)
    transition.add_argument("--evidence", action="append", default=[])
    transition.add_argument("--evidence-file", action="append", default=[])
    transition.add_argument("--reason")

    checkpoint = commands.add_parser("checkpoint", help="Commit a precise continuation record")
    checkpoint.add_argument("--reason", required=True)
    checkpoint.add_argument("--task")
    checkpoint.add_argument("--step")
    checkpoint.add_argument("--next-action")
    checkpoint.add_argument("--relevant-path", action="append", default=[])
    checkpoint.add_argument("--verification-needed", action="append", default=[])
    checkpoint.add_argument("--do-not-repeat", action="append", default=[])

    complete = commands.add_parser("complete-plan", help="Preserve and close a fully verified plan")
    complete.add_argument("--plan", required=True)

    fix_begin = commands.add_parser("fix-begin", help="Start a strict existing-file correction episode")
    fix_begin.add_argument("--task", required=True)
    fix_begin.add_argument("--event-id", required=True)
    fix_begin.add_argument("--file", action="append", required=True)

    fix_finish = commands.add_parser("fix-finish", help="Finish or block a strict correction episode")
    fix_finish.add_argument("--event-id", required=True)
    fix_finish.add_argument("--evidence", action="append", default=[])
    fix_finish.add_argument("--failed", action="store_true")
    fix_finish.add_argument("--reason")

    rate = commands.add_parser("rate", help="Calculate and record an evidence-backed task rating")
    rate.add_argument("--task", required=True)
    for dimension in ("correctness", "reliability", "maintainability", "compliance", "efficiency"):
        rate.add_argument(f"--{dimension}", default="N/A")
    rate.add_argument("--evidence", action="append", required=True)
    rate.add_argument("--critical-defect", action="store_true")
    rate.add_argument("--material-failure", action="store_true")
    rate.add_argument("--provisional", action="store_true")

    context = commands.add_parser("context-check", help="Evaluate measured, estimated, or unavailable context input")
    context.add_argument("--mode", required=True, choices=("measured", "estimated", "unavailable"))
    context.add_argument("--used", type=_decimal)
    context.add_argument("--capacity", type=_decimal)
    context.add_argument("--next-cost", type=_decimal, default=Decimal("0"))
    context.add_argument("--checkpoint-reserve", type=_decimal, default=Decimal("0"))
    context.add_argument("--source")

    requirement = commands.add_parser("requirement-revise", help="Preserve and supersede a requirement revision")
    requirement.add_argument("--requirement", required=True)
    requirement.add_argument("--title", required=True)
    requirement.add_argument("--acceptance", required=True)
    requirement.add_argument("--reason", required=True)
    requirement.add_argument("--authorized-by", required=True)

    allocate = commands.add_parser("plan-allocate", help="Allocate a plan and stable task identifiers")
    allocate.add_argument("--spec", required=True, type=_json_file)

    revise = commands.add_parser("plan-revise", help="Create a lossless plan revision")
    revise.add_argument("--plan", required=True)
    revise.add_argument("--changes", required=True, type=_json_file)
    revise.add_argument("--reason", required=True)

    commands.add_parser("detect-drift", help="Detect unplanned paths and stale evidence")
    commands.add_parser("validate", help="Validate structure, state, ledger, evidence, and completion")
    commands.add_parser("recover", help="Recover state or roll forward a prepared record transaction")

    replace = commands.add_parser("replace", help="Archive and replace a project generation")
    replace.add_argument("--spec", required=True, type=_json_file)
    replace.add_argument("--reason", required=True)
    replace.add_argument("--dry-run", action="store_true")
    replace.add_argument("--archive-stamp")
    replace.add_argument("--fail-after", help=argparse.SUPPRESS)
    commands.add_parser("recover-replacement", help="Recover an interrupted generation replacement")
    return parser


def _dispatch(runtime: Runtime, args: argparse.Namespace) -> dict[str, Any]:
    command = args.command
    if command == "initialize":
        return runtime.initialize(args.spec, target=args.target, dry_run=args.dry_run)
    if command == "adopt":
        return runtime.initialize(args.spec, target=args.target, dry_run=args.dry_run, adopt=True)
    if command == "status":
        return runtime.status()
    if command == "resume":
        return runtime.resume(open_session=args.open_session, agent=args.agent)
    if command == "path-check":
        return runtime.path_check(args.task, args.path)
    if command == "task-transition":
        return runtime.task_transition(
            args.task,
            args.to,
            evidence=args.evidence,
            evidence_files=args.evidence_file,
            reason=args.reason,
        )
    if command == "checkpoint":
        return runtime.checkpoint(
            reason=args.reason,
            task_id=args.task,
            step=args.step,
            next_action=args.next_action,
            relevant_paths=args.relevant_path,
            verification_needed=args.verification_needed,
            do_not_repeat=args.do_not_repeat,
        )
    if command == "complete-plan":
        return runtime.complete_plan(args.plan)
    if command == "fix-begin":
        return runtime.fix_begin(args.task, args.event_id, args.file)
    if command == "fix-finish":
        return runtime.fix_finish(
            args.event_id, evidence=args.evidence, failed=args.failed, reason=args.reason
        )
    if command == "rate":
        scores = {
            key: getattr(args, key)
            for key in ("correctness", "reliability", "maintainability", "compliance", "efficiency")
        }
        return runtime.rate_task(
            args.task,
            scores,
            evidence=args.evidence,
            critical_defect=args.critical_defect,
            material_failure=args.material_failure,
            provisional=args.provisional,
        )
    if command == "context-check":
        return runtime.context_check(
            args.mode,
            used=args.used,
            capacity=args.capacity,
            next_cost=args.next_cost,
            checkpoint_reserve=args.checkpoint_reserve,
            source=args.source,
        )
    if command == "requirement-revise":
        return runtime.requirement_revise(
            args.requirement,
            title=args.title,
            acceptance=args.acceptance,
            reason=args.reason,
            authorized_by=args.authorized_by,
        )
    if command == "plan-allocate":
        return runtime.plan_allocate(args.spec)
    if command == "plan-revise":
        return runtime.plan_revise(args.plan, args.changes, reason=args.reason)
    if command == "detect-drift":
        return runtime.detect_drift()
    if command == "validate":
        return runtime.validate()
    if command == "recover":
        return runtime.recover()
    if command == "replace":
        return runtime.replace(
            args.spec,
            reason=args.reason,
            dry_run=args.dry_run,
            stamp=args.archive_stamp,
            fail_after=args.fail_after,
        )
    if command == "recover-replacement":
        return runtime.recover_replacement()
    raise KeepgoingError(f"Unsupported command {command}", INVALID)


def _render_text(value: dict[str, Any]) -> str:
    lines = [f"result: {value.get('result', 'unknown')}"]
    if value.get("workspace_root"):
        lines.append(f"workspace: {value['workspace_root']}")
    for key in ("message", "action", "decision", "task_id", "plan_id", "transaction_id"):
        if value.get(key) is not None:
            lines.append(f"{key.replace('_', ' ')}: {value[key]}")
    if value.get("issues"):
        lines.append("issues:")
        lines.extend(f"- {item}" for item in value["issues"])
    if value.get("next"):
        lines.append("next: " + json.dumps(value["next"], ensure_ascii=False, sort_keys=True))
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None, *, mode: str = "keepgoing") -> int:
    parser = _parser(mode)
    args = parser.parse_args(argv)
    runtime = Runtime(args.root, mode=mode)
    try:
        value = _dispatch(runtime, args)
        code = int(value.get("exit_code", 0))
        value.setdefault("schema_version", SCHEMA_VERSION)
        value.setdefault("exit_code", code)
    except KeepgoingError as exc:
        code = exc.code
        value = {
            "schema_version": SCHEMA_VERSION,
            "result": exc.result,
            "exit_code": code,
            "message": exc.message,
            "details": exc.details,
            "workspace_root": str(Path(args.root).resolve()),
        }
    except KeyboardInterrupt:
        code = 130
        value = {
            "schema_version": SCHEMA_VERSION,
            "result": "blocked",
            "exit_code": code,
            "message": "Interrupted before the operation reported completion",
            "workspace_root": str(Path(args.root).resolve()),
        }
    output = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        if args.format == "json"
        else _render_text(value)
    )
    print(output)
    return code


if __name__ == "__main__":
    sys.exit(main())
