"""State machine and filesystem operations for governed workspaces."""

from __future__ import annotations

import base64
import copy
import json
import os
import shutil
import socket
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from .errors import (
    BLOCKED,
    CHECKPOINT_REQUIRED,
    CONFLICT,
    INVALID,
    IO_FAILURE,
    RECOVERY_REQUIRED,
    KeepgoingError,
)
from .profiles import (
    PROFILES,
    STANDARD_CONTAINERS,
    get_profile,
    normalize_relative_path,
    profile_allows,
)
from .render import (
    render_capabilities,
    render_decisions,
    render_plan,
    render_plan_index,
    render_project,
    render_rates,
    render_rules,
    render_session_header,
    render_session_summary,
    render_structure,
    session_event_block,
)
from .util import (
    ACTIVE_DIRS,
    SCHEMA_VERSION,
    WorkspaceLock,
    append_jsonl,
    atomic_write_json,
    atomic_write_text,
    canonical_json,
    case_collisions,
    copy_verified,
    ensure_unique_archive,
    event_hash,
    file_inventory,
    human_now,
    iso_now,
    move_verified,
    new_event,
    path_inventory,
    private_home,
    read_json,
    read_ledger,
    safe_path,
    sha256_bytes,
    sha256_file,
    sha256_text,
    workspace_key,
)


PLAN_STATES = {
    "planned",
    "ready",
    "in_progress",
    "blocked",
    "complete",
    "superseded",
    "cancelled",
    "closing",
}
TASK_STATES = {
    "pending",
    "ready",
    "in_progress",
    "verification",
    "verification_pending",
    "complete",
    "blocked",
    "needs_fix",
    "superseded",
    "cancelled",
}
TASK_TRANSITIONS = {
    "pending": {"ready", "in_progress", "blocked", "cancelled", "superseded"},
    "ready": {"in_progress", "blocked", "cancelled", "superseded"},
    "in_progress": {"verification", "blocked", "cancelled"},
    "verification": {"complete", "in_progress", "verification_pending", "blocked"},
    "verification_pending": {"verification", "in_progress", "blocked"},
    "complete": {"needs_fix"},
    "needs_fix": {"verification", "verification_pending", "blocked"},
    "blocked": {"ready", "in_progress", "cancelled", "superseded"},
    "superseded": set(),
    "cancelled": set(),
}
RATING_WEIGHTS = {
    "correctness": Decimal("0.40"),
    "reliability": Decimal("0.20"),
    "maintainability": Decimal("0.15"),
    "compliance": Decimal("0.15"),
    "efficiency": Decimal("0.10"),
}


def _numeric(identifier: str) -> int:
    return int(identifier.rsplit("-", 1)[-1])


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KeepgoingError(f"{label} must be a non-empty string", INVALID)
    return value.strip()


def _require_text_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise KeepgoingError(f"{label} must be a non-empty list", INVALID)
    return [_require_text(item, label) for item in value]


def _plan_path(plan_id: str) -> str:
    return f"plans/plan_{_numeric(plan_id)}.md"


def _session_path(session_id: str) -> str:
    return f"sessions/session_{_numeric(session_id)}.md"


def discover_workspace(start: Path, *, required: bool = True) -> Path:
    current = start.resolve()
    candidates = [current, *current.parents]
    for candidate in candidates:
        state_path = candidate / "instructions" / "state.json"
        project_path = candidate / "Project"
        ledger_path = candidate / "instructions" / "ledger.jsonl"
        if (state_path.is_file() or ledger_path.is_file()) and project_path.is_dir():
            try:
                relative = current.relative_to(candidate)
            except ValueError:
                continue
            if relative.parts and relative.parts[0].casefold() == "deprecated":
                raise KeepgoingError(
                    "Archived generations are read-only; invoke from the active workspace",
                    BLOCKED,
                    "blocked",
                )
            try:
                state = read_json(state_path)
            except KeepgoingError:
                return candidate
            if state.get("workspace_id") and state.get("generation_id"):
                return candidate
    if required:
        raise KeepgoingError(
            "No governed workspace found; run initialize or adopt first", BLOCKED, "blocked"
        )
    return current


def _validate_spec(spec: dict[str, Any]) -> None:
    _require_text(spec.get("project_name"), "project_name")
    _require_text(spec.get("scope"), "scope")
    profile_name = _require_text(spec.get("profile"), "profile").lower()
    get_profile(profile_name)
    requirements = spec.get("requirements")
    plans = spec.get("plans")
    if not isinstance(requirements, list) or not requirements:
        raise KeepgoingError("requirements must contain at least one item", INVALID)
    if not isinstance(plans, list) or not plans:
        raise KeepgoingError("plans must contain at least one item", INVALID)
    for index, requirement in enumerate(requirements, 1):
        if not isinstance(requirement, dict):
            raise KeepgoingError(f"Requirement {index} must be an object", INVALID)
        _require_text(requirement.get("title"), f"requirement {index} title")
        _require_text(requirement.get("acceptance"), f"requirement {index} acceptance")
    for index, plan in enumerate(plans, 1):
        if not isinstance(plan, dict):
            raise KeepgoingError(f"Plan {index} must be an object", INVALID)
        for key in ("title", "outcome", "scope", "architecture"):
            _require_text(plan.get(key), f"plan {index} {key}")
        references = plan.get("requirements")
        if not isinstance(references, list) or not references:
            raise KeepgoingError(f"Plan {index} must map requirements", INVALID)
        for reference in references:
            number = int(reference) if isinstance(reference, int) else _numeric(str(reference))
            if number < 1 or number > len(requirements):
                raise KeepgoingError(f"Plan {index} maps unknown requirement {reference}", INVALID)
        dependencies = plan.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise KeepgoingError(f"Plan {index} dependencies must be a list", INVALID)
        for dependency in dependencies:
            number = int(dependency) if isinstance(dependency, int) else _numeric(str(dependency))
            if number < 1 or number >= index:
                raise KeepgoingError(
                    f"Plan {index} dependency {dependency} must reference an earlier plan", INVALID
                )
        tasks = plan.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            raise KeepgoingError(f"Plan {index} must contain at least one task", INVALID)
        for task_index, task in enumerate(tasks, 1):
            if not isinstance(task, dict):
                raise KeepgoingError(f"Plan {index} task {task_index} must be an object", INVALID)
            _require_text(task.get("title"), f"plan {index} task {task_index} title")
            files = _require_text_list(task.get("files"), f"plan {index} task {task_index} files")
            for file_name in files:
                normalized = normalize_relative_path(file_name)
                if not profile_allows(profile_name, normalized):
                    raise KeepgoingError(
                        f"Path {normalized} is outside the {profile_name} profile", INVALID
                    )
            for key in ("steps", "acceptance", "verification", "failure_behavior"):
                _require_text_list(task.get(key), f"plan {index} task {task_index} {key}")
            preconditions = task.get("preconditions", ["Mapped plan dependencies are complete."])
            _require_text_list(preconditions, f"plan {index} task {task_index} preconditions")
    covered: set[int] = set()
    for plan in plans:
        for reference in plan["requirements"]:
            covered.add(int(reference) if isinstance(reference, int) else _numeric(str(reference)))
    missing = sorted(set(range(1, len(requirements) + 1)) - covered)
    if missing:
        raise KeepgoingError(f"Unmapped requirements: {missing}", INVALID)


def _make_state(spec: dict[str, Any], predecessor_id: str | None = None) -> dict[str, Any]:
    _validate_spec(spec)
    timestamp = iso_now()
    timezone = spec.get("timezone") or timestamp[-6:]
    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "workspace_id": str(uuid.uuid4()),
        "generation_id": str(uuid.uuid4()),
        "predecessor_id": predecessor_id,
        "project_name": spec["project_name"].strip(),
        "intent_hash": sha256_text(canonical_json(spec)),
        "scope": spec["scope"].strip(),
        "profile": spec["profile"].lower().strip(),
        "timezone": timezone,
        "created_at": timestamp,
        "updated_at": timestamp,
        "structure": {"version": 1, "hash": "", "allowed_paths": [], "known_files": {}},
        "counters": {"requirement": 0, "plan": 0, "task": 0, "session": 1, "event": 0},
        "last_committed_event": 0,
        "last_transaction": None,
        "requirements": {},
        "plans": {},
        "tasks": {},
        "sessions": {
            "SESSION-001": {
                "started_at": timestamp,
                "ended_at": None,
                "status": "open",
                "mode": "keepgoing",
                "agent": spec.get("agent") or "unknown",
                "starting_state": "Initialized from an explicit complete project specification.",
            }
        },
        "pending_corrections": {},
        "blockers": [],
        "resume": None,
        "context": {"mode": "unavailable", "last_measurement": None},
        "recovery": {"pending_transaction": None, "replacement": None},
        "decisions": list(spec.get("decisions", [])),
        "rules": list(spec.get("rules", [])),
        "lineage_note": spec.get("lineage_note"),
        "status": "active",
    }
    for requirement_spec in spec["requirements"]:
        state["counters"]["requirement"] += 1
        requirement_id = f"REQ-{state['counters']['requirement']:03d}"
        state["requirements"][requirement_id] = {
            "title": requirement_spec["title"].strip(),
            "acceptance": requirement_spec["acceptance"].strip(),
            "state": "planned",
            "plans": [],
            "history": [],
        }
    allowed_paths: set[str] = set()
    for plan_index, plan_spec in enumerate(spec["plans"], 1):
        state["counters"]["plan"] += 1
        plan_id = f"PLAN-{state['counters']['plan']:03d}"
        requirement_ids = [
            f"REQ-{(int(item) if isinstance(item, int) else _numeric(str(item))):03d}"
            for item in plan_spec["requirements"]
        ]
        dependency_ids = [
            f"PLAN-{(int(item) if isinstance(item, int) else _numeric(str(item))):03d}"
            for item in plan_spec.get("dependencies", [])
        ]
        task_ids: list[str] = []
        for task_spec in plan_spec["tasks"]:
            state["counters"]["task"] += 1
            task_id = f"TASK-{state['counters']['task']:03d}"
            task_ids.append(task_id)
            files = [normalize_relative_path(value) for value in task_spec["files"]]
            allowed_paths.update(files)
            state["tasks"][task_id] = {
                "plan_id": plan_id,
                "title": task_spec["title"].strip(),
                "state": "pending",
                "required": bool(task_spec.get("required", True)),
                "weight": str(task_spec.get("weight", 1)),
                "files": files,
                "preconditions": list(task_spec.get("preconditions") or ["Mapped plan dependencies are complete."]),
                "steps": list(task_spec["steps"]),
                "acceptance": list(task_spec["acceptance"]),
                "verification": list(task_spec["verification"]),
                "failure_behavior": list(task_spec["failure_behavior"]),
                "evidence": [],
                "completed_at": None,
                "completed_at_human": None,
                "completion_session": None,
                "updates": [],
                "rating": None,
                "rating_history": [],
            }
        state["plans"][plan_id] = {
            "path": _plan_path(plan_id),
            "title": plan_spec["title"].strip(),
            "outcome": plan_spec["outcome"].strip(),
            "scope": plan_spec["scope"].strip(),
            "architecture": plan_spec["architecture"].strip(),
            "state": "ready" if not dependency_ids else "planned",
            "priority": int(plan_spec.get("priority", plan_index)),
            "requirements": requirement_ids,
            "dependencies": dependency_ids,
            "tasks": task_ids,
            "revision": 1,
            "created_at": timestamp,
            "updated_at": timestamp,
            "owner": plan_spec.get("owner"),
            "completion_conditions": list(
                plan_spec.get("completion_conditions")
                or [
                    "Every required task has committed implementation and verification evidence.",
                    "Integration and documentation obligations named by the plan are complete.",
                    "The plan snapshot is durably preserved before leaving the active queue.",
                ]
            ),
            "continuation": {
                "task_id": task_ids[0],
                "step": "1",
                "next_action": f"Begin {task_ids[0]} at implementation step 1.",
            },
            "revision_history": [
                {"revision": 1, "at": timestamp, "reason": "Initial authorized plan."}
            ],
            "completion_session": None,
            "snapshot_hash": None,
        }
        for requirement_id in requirement_ids:
            state["requirements"][requirement_id]["plans"].append(plan_id)
    profile = get_profile(state["profile"])
    allowed_paths.update(profile["native_paths"])
    allowed_paths.update(profile["entrypoints"])
    state["structure"]["allowed_paths"] = sorted(allowed_paths)
    state["structure"]["hash"] = sha256_text(
        canonical_json(
            {"profile": state["profile"], "allowed_paths": state["structure"]["allowed_paths"]}
        )
    )
    state["resume"] = _select_resume(state)
    return state


def _select_resume(state: dict[str, Any]) -> dict[str, Any] | None:
    plans = sorted(state["plans"].items(), key=lambda item: (item[1]["priority"], _numeric(item[0])))
    for plan_id, plan in plans:
        if plan["state"] in {"complete", "cancelled", "superseded"}:
            continue
        if any(state["plans"][dependency]["state"] != "complete" for dependency in plan["dependencies"]):
            continue
        for task_id in plan["tasks"]:
            task = state["tasks"][task_id]
            if task["state"] not in {"complete", "cancelled", "superseded", "blocked"}:
                return {
                    "plan_path": plan["path"],
                    "plan_id": plan_id,
                    "revision": plan["revision"],
                    "task_id": task_id,
                    "step": plan["continuation"].get("step") or "1",
                    "next_action": plan["continuation"].get("next_action")
                    or f"Continue {task_id}: {task['title']}.",
                    "relevant_paths": task["files"],
                    "verification_needed": task["verification"],
                    "do_not_repeat": [],
                }
    return None


def _core_writes(state: dict[str, Any], *, include_plans: bool = True) -> dict[str, str]:
    writes = {
        "instructions/project.md": render_project(state),
        "instructions/structure.md": render_structure(state),
        "instructions/rules.md": render_rules(state),
        "instructions/decisions.md": render_decisions(state),
        "instructions/capabilities.md": render_capabilities(state),
        "plans/plan_index.md": render_plan_index(state),
        "sessions/session_sum.md": render_session_summary(state),
        "rates/Sessions_rate.md": render_rates(state),
    }
    if include_plans:
        for plan_id, plan in state["plans"].items():
            if plan["state"] not in {"complete", "cancelled", "superseded"}:
                writes[plan["path"]] = render_plan(state, plan_id)
    return writes


def _apply_write_set(root: Path, writes: dict[str, str], deletes: list[str]) -> None:
    for relative, content in writes.items():
        target = safe_path(root, relative)
        atomic_write_text(target, content, root)
    for relative in deletes:
        target = safe_path(root, relative)
        if target.is_dir():
            raise KeepgoingError(f"Refusing to delete directory in record transaction: {relative}", INVALID)
        target.unlink(missing_ok=True)


def _transaction_bundle_path(root: Path, transaction_id: str) -> Path:
    return private_home() / "transactions" / workspace_key(root) / f"{transaction_id}.json"


def _load_transaction_bundle(root: Path, event: dict[str, Any]) -> dict[str, Any]:
    reference = event.get("payload", {}).get("recovery_bundle")
    if not isinstance(reference, str) or not reference:
        raise KeepgoingError(
            "Transaction recovery journal is missing from the ledger event",
            RECOVERY_REQUIRED,
            "blocked",
        )
    bundle = read_json(Path(reference))
    if bundle.get("transaction_id") != event.get("transaction_id"):
        raise KeepgoingError("Transaction recovery journal identity mismatch", RECOVERY_REQUIRED)
    state = bundle.get("target_state")
    writes = bundle.get("writes")
    if not isinstance(state, dict) or not isinstance(writes, dict):
        raise KeepgoingError("Transaction recovery journal is incomplete", RECOVERY_REQUIRED)
    expected_state_hash = event.get("payload", {}).get("state_hash")
    if sha256_text(canonical_json(state)) != expected_state_hash:
        raise KeepgoingError("Transaction recovery state checksum mismatch", RECOVERY_REQUIRED)
    expected_writes = event.get("payload", {}).get("write_hashes", {})
    actual_writes = {relative: sha256_text(content) for relative, content in writes.items()}
    if actual_writes != expected_writes:
        raise KeepgoingError("Transaction recovery write-set checksum mismatch", RECOVERY_REQUIRED)
    expected_deletes = event.get("payload", {}).get("delete_targets", [])
    if sorted(bundle.get("deletes", [])) != sorted(expected_deletes):
        raise KeepgoingError("Transaction recovery delete-set checksum mismatch", RECOVERY_REQUIRED)
    return bundle


def _commit(
    root: Path,
    state: dict[str, Any],
    event_type: str,
    payload: dict[str, Any],
    *,
    writes: dict[str, str] | None = None,
    deletes: list[str] | None = None,
) -> str:
    writes = dict(writes or {})
    deletes = list(deletes or [])
    state = copy.deepcopy(state)
    ledger_path = root / "instructions" / "ledger.jsonl"
    events, issues = read_ledger(ledger_path, tolerate_truncated=True)
    if issues:
        raise KeepgoingError(
            "Ledger requires recovery before mutation", RECOVERY_REQUIRED, "blocked", {"issues": issues}
        )
    if events and events[-1]["type"] == "TX_PREPARED":
        raise KeepgoingError(
            "Prepared transaction requires recovery before mutation", RECOVERY_REQUIRED, "blocked"
        )
    latest_committed = max(
        (event["sequence"] for event in events if event["type"] in {"TX_COMMITTED", "TX_RECOVERED"}),
        default=0,
    )
    if state.get("last_committed_event") != latest_committed:
        raise KeepgoingError(
            "Workspace state changed after this operation began; reload before retrying",
            CONFLICT,
            "conflict",
            {
                "expected_committed_event": state.get("last_committed_event"),
                "actual_committed_event": latest_committed,
            },
        )
    previous_hash = events[-1]["event_hash"] if events else ""
    sequence = events[-1]["sequence"] if events else 0
    transaction_id = f"TX-{uuid.uuid4()}"
    state["updated_at"] = iso_now()
    state["last_committed_event"] = sequence + 2
    state["last_transaction"] = transaction_id
    state["counters"]["event"] = sequence + 2
    state["recovery"]["pending_transaction"] = None
    writes.update(_core_writes(state))
    bundle_path = _transaction_bundle_path(root, transaction_id)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "schema_version": SCHEMA_VERSION,
        "transaction_id": transaction_id,
        "operation": event_type,
        "details": payload,
        "target_state": state,
        "writes": writes,
        "deletes": deletes,
    }
    atomic_write_json(bundle_path, bundle, root)
    transaction_metadata = {
        "operation": event_type,
        "details_hash": sha256_text(canonical_json(payload)),
        "state_hash": sha256_text(canonical_json(state)),
        "write_hashes": {
            relative: sha256_text(content) for relative, content in sorted(writes.items())
        },
        "delete_targets": sorted(deletes),
        "recovery_bundle": str(bundle_path),
    }
    prepared = new_event(
        sequence=sequence + 1,
        transaction_id=transaction_id,
        event_type="TX_PREPARED",
        payload=transaction_metadata,
        previous_hash=previous_hash,
    )
    append_jsonl(ledger_path, prepared)
    try:
        _apply_write_set(root, writes, deletes)
        atomic_write_json(root / "instructions" / "state.json", state, root)
    except KeepgoingError:
        raise
    committed = new_event(
        sequence=sequence + 2,
        transaction_id=transaction_id,
        event_type="TX_COMMITTED",
        payload=transaction_metadata,
        previous_hash=prepared["event_hash"],
    )
    append_jsonl(ledger_path, committed)
    atomic_write_json(root / "instructions" / "state.json", state, root)
    return transaction_id


class Runtime:
    """The sole state-changing implementation shared by both skills."""

    def __init__(self, start: Path | str | None = None, *, mode: str = "keepgoing"):
        self.start = Path(start or Path.cwd()).resolve()
        if mode not in {"keepgoing", "keepfixing"}:
            raise KeepgoingError(f"Unknown runtime mode {mode}", INVALID)
        self.mode = mode

    def initialize(
        self,
        spec: dict[str, Any],
        *,
        target: Path | str | None = None,
        dry_run: bool = False,
        adopt: bool = False,
    ) -> dict[str, Any]:
        if self.mode != "keepgoing":
            raise KeepgoingError("keepfixing cannot initialize or adopt workspaces", BLOCKED, "blocked")
        root = Path(target or self.start).resolve()
        _validate_spec(spec)
        for ancestor in root.parents:
            relative = root.relative_to(ancestor)
            replacement_marker = ancestor / "deprecated" / "replacement.json"
            governed = (
                (ancestor / "instructions" / "state.json").is_file()
                and (ancestor / "Project").is_dir()
            )
            if replacement_marker.is_file() or governed:
                if relative.parts and relative.parts[0].casefold() == "deprecated":
                    message = "Archived or replacing generations cannot contain a new governed workspace"
                else:
                    message = "Nested governed workspaces are not allowed inside an active workspace"
                raise KeepgoingError(
                    message,
                    BLOCKED,
                    "blocked",
                    {"governed_ancestor": str(ancestor), "target": str(root)},
                )
        if (root / "deprecated" / "replacement.json").is_file():
            raise KeepgoingError(
                "Replacement recovery must finish before initialization",
                RECOVERY_REQUIRED,
                "blocked",
            )
        existing_state = root / "instructions" / "state.json"
        if existing_state.exists():
            current = read_json(existing_state)
            if current.get("intent_hash") != sha256_text(canonical_json(spec)):
                raise KeepgoingError(
                    "Existing governed workspace has different initialization intent; resume it or use explicit replacement",
                    CONFLICT,
                    "conflict",
                )
            return {
                "result": "success",
                "workspace_root": str(root),
                "message": "Existing governed workspace preserved; use resume",
                "workspace_id": current["workspace_id"],
                "generation_id": current["generation_id"],
                "next": _select_resume(current),
                "idempotent": True,
            }
        collisions = [name for name in ACTIVE_DIRS[1:] if (root / name).exists()]
        project_exists = (root / "Project").exists()
        if collisions:
            raise KeepgoingError(
                "Organizer paths already exist and will not be overwritten during adoption",
                CONFLICT,
                "conflict",
                {"collisions": sorted(collisions)},
            )
        if project_exists and not adopt:
            raise KeepgoingError(
                "Organizer paths already exist; use adopt with a reviewed dry run",
                CONFLICT,
                "conflict",
                {"collisions": ["Project"]},
            )
        movable = self._adoption_candidates(root) if adopt and not project_exists else []
        preview = {
            "result": "success",
            "workspace_root": str(root),
            "operation": "adopt" if adopt else "initialize",
            "moves": [{"from": item.name, "to": f"Project/{item.name}"} for item in movable],
            "profile": spec.get("profile"),
            "plans": len(spec.get("plans", [])),
            "requirements": len(spec.get("requirements", [])),
        }
        if dry_run:
            preview["dry_run"] = True
            return preview
        root.mkdir(parents=True, exist_ok=True)
        state = _make_state(spec)
        with WorkspaceLock(root):
            for name in (*ACTIVE_DIRS, "deprecated"):
                (root / name).mkdir(parents=True, exist_ok=True)
            for container in STANDARD_CONTAINERS:
                (root / "Project" / Path(container)).mkdir(parents=True, exist_ok=True)
            for native in get_profile(state["profile"])["native_paths"]:
                (root / Path(native)).mkdir(parents=True, exist_ok=True)
            for source in movable:
                target_path = root / "Project" / source.name
                if target_path.exists():
                    raise KeepgoingError(f"Adoption target collision: {target_path}", CONFLICT)
                copy_verified(source, target_path)
            state["structure"]["known_files"] = file_inventory(root / "Project")
            instruction = spec.get("starting_instruction") or state["scope"]
            writes = _core_writes(state)
            writes["sessions/session_1.md"] = render_session_header(
                state, "SESSION-001", instruction
            )
            writes["rates/session_1_rate.md"] = (
                "# SESSION-001 rating history\n\n"
                "No completed task has sufficient rating evidence.\n"
            )
            transaction_id = _commit(
                root,
                state,
                "WORKSPACE_ADOPTED" if adopt else "WORKSPACE_INITIALIZED",
                {"profile": state["profile"], "adopted": [item.name for item in movable]},
                writes=writes,
            )
            state = read_json(root / "instructions" / "state.json")
            for source in movable:
                if source.is_dir() and not source.is_symlink():
                    shutil.rmtree(source)
                else:
                    source.unlink()
        preview.update(
            {
                "transaction_id": transaction_id,
                "workspace_id": state["workspace_id"],
                "generation_id": state["generation_id"],
                "next": state["resume"],
                "dry_run": False,
            }
        )
        return preview

    @staticmethod
    def _adoption_candidates(root: Path) -> list[Path]:
        preserved = {
            ".git",
            ".github",
            ".agents",
            ".claude",
            ".codex",
            ".Codex",
            "AGENTS.md",
            "CLAUDE.md",
            "Project",
            "instructions",
            "plans",
            "sessions",
            "rates",
            "deprecated",
        }
        return sorted(
            [item for item in root.iterdir() if item.name not in preserved],
            key=lambda item: item.name.casefold(),
        )

    def root(self) -> Path:
        return discover_workspace(self.start)

    def load_state(
        self, root: Path | None = None, *, verify_authority: bool = True
    ) -> dict[str, Any]:
        selected = root or self.root()
        state = read_json(selected / "instructions" / "state.json")
        if state.get("schema_version") != SCHEMA_VERSION:
            raise KeepgoingError("Unsupported state schema version", INVALID)
        if verify_authority:
            events, issues = read_ledger(
                selected / "instructions" / "ledger.jsonl", tolerate_truncated=True
            )
            if issues:
                raise KeepgoingError(
                    "Ledger requires recovery before continuing",
                    RECOVERY_REQUIRED,
                    "blocked",
                    {"issues": issues},
                )
            if not events:
                raise KeepgoingError("Ledger has no committed authority", RECOVERY_REQUIRED)
            if events[-1]["type"] == "TX_PREPARED":
                raise KeepgoingError(
                    "Prepared transaction requires recovery before continuing",
                    RECOVERY_REQUIRED,
                    "blocked",
                )
            committed = [
                event for event in events if event["type"] in {"TX_COMMITTED", "TX_RECOVERED"}
            ]
            if not committed:
                raise KeepgoingError("Ledger has no committed authority", RECOVERY_REQUIRED)
            latest = committed[-1]
            if state.get("last_committed_event") != latest["sequence"]:
                raise KeepgoingError(
                    "State snapshot sequence differs from committed ledger authority",
                    RECOVERY_REQUIRED,
                    "blocked",
                )
            expected_hash = latest.get("payload", {}).get("state_hash")
            if not expected_hash or sha256_text(canonical_json(state)) != expected_hash:
                raise KeepgoingError(
                    "State snapshot content differs from committed ledger authority",
                    RECOVERY_REQUIRED,
                    "blocked",
                )
        return state

    def status(self) -> dict[str, Any]:
        root = self.root()
        state = self.load_state(root)
        next_item = _select_resume(state)
        completed_required = sum(
            1
            for task in state["tasks"].values()
            if task.get("required", True) and task["state"] == "complete"
        )
        total_required = sum(1 for task in state["tasks"].values() if task.get("required", True))
        return {
            "result": "success",
            "workspace_root": str(root),
            "workspace_id": state["workspace_id"],
            "generation_id": state["generation_id"],
            "project_name": state["project_name"],
            "mode": self.mode,
            "complete": bool(
                total_required
                and completed_required == total_required
                and all(plan["state"] == "complete" for plan in state["plans"].values())
                and not state["blockers"]
                and not state["pending_corrections"]
                and not next_item
            ),
            "completion": {"completed": completed_required, "required": total_required},
            "next": next_item,
            "blockers": state["blockers"],
            "context_mode": state["context"]["mode"],
        }

    def resume(self, *, open_session: bool = False, agent: str | None = None) -> dict[str, Any]:
        root = self.root()
        state = self.load_state(root)
        result = self.status()
        if not open_session:
            return result
        if self.mode != "keepgoing":
            raise KeepgoingError("keepfixing does not allocate sessions", BLOCKED, "blocked")
        active_id = f"SESSION-{state['counters']['session']:03d}"
        active = state["sessions"][active_id]
        if active["status"] == "open":
            result["session_id"] = active_id
            result["idempotent"] = True
            return result
        state["counters"]["session"] += 1
        session_id = f"SESSION-{state['counters']['session']:03d}"
        state["sessions"][session_id] = {
            "started_at": iso_now(),
            "ended_at": None,
            "status": "open",
            "mode": "keepgoing",
            "agent": agent or "unknown",
            "starting_state": "Resumed from durable records and selected the saved continuation.",
        }
        with WorkspaceLock(root):
            writes = {
                _session_path(session_id): render_session_header(
                    state,
                    session_id,
                    "Resume the first dependency-eligible unfinished task from durable records.",
                ),
                f"rates/session_{_numeric(session_id)}_rate.md": (
                    f"# {session_id} rating history\n\n"
                    "No completed task has sufficient rating evidence.\n"
                ),
            }
            transaction_id = _commit(
                root, state, "SESSION_OPENED", {"session_id": session_id}, writes=writes
            )
        result = self.status()
        result.update({"session_id": session_id, "transaction_id": transaction_id})
        return result

    def path_check(self, task_id: str, relative: str) -> dict[str, Any]:
        root = self.root()
        state = self.load_state(root)
        if task_id not in state["tasks"]:
            raise KeepgoingError(f"Unknown task {task_id}", INVALID)
        normalized = normalize_relative_path(relative)
        task = state["tasks"][task_id]
        authorized = normalized in task["files"] and normalized in state["structure"]["allowed_paths"]
        if not authorized:
            raise KeepgoingError(
                f"Path {normalized} is not authorized by {task_id}",
                BLOCKED,
                "blocked",
                {"allowed": task["files"]},
            )
        target = safe_path(root, normalized)
        if self.mode == "keepfixing" and not target.exists():
            raise KeepgoingError(
                f"keepfixing cannot create {normalized}", BLOCKED, "blocked"
            )
        return {
            "result": "success",
            "workspace_root": str(root),
            "task_id": task_id,
            "path": normalized,
            "exists": target.exists(),
            "authorized": True,
        }

    def task_transition(
        self,
        task_id: str,
        target_state: str,
        *,
        evidence: list[str] | None = None,
        evidence_files: list[str] | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        if self.mode != "keepgoing":
            raise KeepgoingError(
                "keepfixing changes lifecycle only through fix begin/finish", BLOCKED, "blocked"
            )
        root = self.root()
        state = self.load_state(root)
        if task_id not in state["tasks"]:
            raise KeepgoingError(f"Unknown task {task_id}", INVALID)
        target_state = target_state.strip().lower()
        if target_state not in TASK_STATES:
            raise KeepgoingError(f"Unknown task state {target_state}", INVALID)
        task = state["tasks"][task_id]
        current = task["state"]
        if target_state == current:
            return {
                "result": "success",
                "workspace_root": str(root),
                "task_id": task_id,
                "state": current,
                "idempotent": True,
            }
        if target_state not in TASK_TRANSITIONS[current]:
            raise KeepgoingError(
                f"Invalid task transition {current} -> {target_state}", BLOCKED, "blocked"
            )
        plan = state["plans"][task["plan_id"]]
        if target_state in {"ready", "in_progress"}:
            unfinished = [
                dependency
                for dependency in plan["dependencies"]
                if state["plans"][dependency]["state"] != "complete"
            ]
            if unfinished:
                raise KeepgoingError(
                    f"Task {task_id} is blocked by {', '.join(unfinished)}",
                    BLOCKED,
                    "blocked",
                    {"dependencies": unfinished},
                )
        evidence = [item.strip() for item in (evidence or []) if item.strip()]
        file_evidence: dict[str, str] = {}
        for relative in evidence_files or []:
            normalized = normalize_relative_path(relative)
            if normalized not in task["files"]:
                raise KeepgoingError(
                    f"Evidence path {normalized} is not owned by {task_id}", INVALID
                )
            target = safe_path(root, normalized, must_exist=True)
            if not target.is_file():
                raise KeepgoingError(f"Evidence path is not a file: {normalized}", INVALID)
            file_evidence[normalized] = sha256_file(target)
        if target_state == "complete" and (
            not evidence or set(file_evidence) != set(task["files"])
        ):
            raise KeepgoingError(
                "Completion requires observed evidence and current hashes for every task file",
                BLOCKED,
                "blocked",
            )
        timestamp = iso_now()
        session_id = f"SESSION-{state['counters']['session']:03d}"
        task["state"] = target_state
        if current == "blocked" and target_state != "blocked":
            state["blockers"] = [
                blocker for blocker in state["blockers"] if blocker.get("task_id") != task_id
            ]
        if target_state == "complete":
            task["completed_at"] = timestamp
            task["completed_at_human"] = human_now()
            task["completion_session"] = session_id
            task["evidence"].append(
                {
                    "at": timestamp,
                    "claims": evidence,
                    "files": file_evidence,
                    "session_id": session_id,
                }
            )
        elif target_state == "blocked":
            blocker = {
                "task_id": task_id,
                "reason": _require_text(reason, "reason"),
                "at": timestamp,
            }
            state["blockers"].append(blocker)
        if any(state["tasks"][item]["state"] == "in_progress" for item in plan["tasks"]):
            plan["state"] = "in_progress"
        elif all(
            state["tasks"][item]["state"] in {"complete", "cancelled", "superseded"}
            for item in plan["tasks"]
        ):
            plan["state"] = "ready"
        for requirement_id in plan["requirements"]:
            related_tasks = [
                state["tasks"][item]
                for candidate in state["plans"].values()
                if requirement_id in candidate["requirements"]
                for item in candidate["tasks"]
            ]
            state["requirements"][requirement_id]["state"] = (
                "complete"
                if related_tasks
                and all(item["state"] in {"complete", "cancelled", "superseded"} for item in related_tasks)
                else "in_progress"
            )
        state["resume"] = _select_resume(state)
        session_path = root / _session_path(session_id)
        session_text = session_path.read_text(encoding="utf-8")
        block = session_event_block(
            f"{task_id} transition",
            f"State changed from `{current}` to `{target_state}`.\n\n"
            + ("Evidence:\n" + "\n".join(f"- {item}" for item in evidence) if evidence else "No completion evidence was claimed.")
            + (f"\n\nReason: {reason}" if reason else ""),
            timestamp,
        )
        with WorkspaceLock(root):
            transaction_id = _commit(
                root,
                state,
                "TASK_TRANSITIONED",
                {"task_id": task_id, "from": current, "to": target_state},
                writes={_session_path(session_id): session_text.rstrip() + block},
            )
        return {
            "result": "success",
            "workspace_root": str(root),
            "transaction_id": transaction_id,
            "task_id": task_id,
            "state": target_state,
            "next": state["resume"],
        }

    def checkpoint(
        self,
        *,
        reason: str,
        task_id: str | None = None,
        step: str | None = None,
        next_action: str | None = None,
        relevant_paths: list[str] | None = None,
        verification_needed: list[str] | None = None,
        do_not_repeat: list[str] | None = None,
    ) -> dict[str, Any]:
        if self.mode != "keepgoing":
            raise KeepgoingError("keepfixing checkpoints through its correction episode", BLOCKED, "blocked")
        root = self.root()
        state = self.load_state(root)
        drift = self._drift_issues(root, state)
        if drift:
            raise KeepgoingError(
                "Checkpoint blocked by unplanned paths or stale evidence",
                CONFLICT,
                "conflict",
                {"issues": drift},
            )
        reason = _require_text(reason, "reason")
        if task_id:
            if task_id not in state["tasks"]:
                raise KeepgoingError(f"Unknown task {task_id}", INVALID)
            task = state["tasks"][task_id]
            plan = state["plans"][task["plan_id"]]
            if not next_action or not step:
                raise KeepgoingError(
                    "An incomplete checkpoint requires step and next_action", INVALID
                )
            state["resume"] = {
                "plan_path": plan["path"],
                "plan_id": task["plan_id"],
                "revision": plan["revision"],
                "task_id": task_id,
                "step": step,
                "next_action": next_action,
                "relevant_paths": relevant_paths or task["files"],
                "verification_needed": verification_needed or task["verification"],
                "do_not_repeat": do_not_repeat or [],
            }
            plan["continuation"] = {
                "task_id": task_id,
                "step": step,
                "next_action": next_action,
            }
        else:
            state["resume"] = _select_resume(state)
        state["structure"]["known_files"] = file_inventory(root / "Project")
        session_id = f"SESSION-{state['counters']['session']:03d}"
        session = state["sessions"][session_id]
        session["status"] = "checkpointed"
        session["ended_at"] = iso_now()
        session_path = root / _session_path(session_id)
        session_text = session_path.read_text(encoding="utf-8")
        pointer = json.dumps(state["resume"], ensure_ascii=False, indent=2, sort_keys=True)
        block = session_event_block(
            "Checkpoint",
            f"Reason: {reason}\n\nStructured continuation:\n```json\n{pointer}\n```",
            session["ended_at"],
        )
        with WorkspaceLock(root):
            transaction_id = _commit(
                root,
                state,
                "CHECKPOINT_COMMITTED",
                {"reason": reason, "session_id": session_id},
                writes={_session_path(session_id): session_text.rstrip() + block},
            )
        return {
            "result": "success",
            "workspace_root": str(root),
            "transaction_id": transaction_id,
            "session_id": session_id,
            "next": state["resume"],
        }

    def complete_plan(self, plan_id: str) -> dict[str, Any]:
        if self.mode != "keepgoing":
            raise KeepgoingError("keepfixing cannot complete plans", BLOCKED, "blocked")
        root = self.root()
        state = self.load_state(root)
        if plan_id not in state["plans"]:
            raise KeepgoingError(f"Unknown plan {plan_id}", INVALID)
        plan = state["plans"][plan_id]
        if plan["state"] == "complete":
            return {
                "result": "success",
                "workspace_root": str(root),
                "plan_id": plan_id,
                "idempotent": True,
                "snapshot_hash": plan["snapshot_hash"],
            }
        incomplete = [
            task_id
            for task_id in plan["tasks"]
            if state["tasks"][task_id]["state"] not in {"complete", "cancelled", "superseded"}
        ]
        if incomplete:
            raise KeepgoingError(
                f"Plan {plan_id} has incomplete tasks", BLOCKED, "blocked", {"tasks": incomplete}
            )
        plan_path = safe_path(root, plan["path"], must_exist=True)
        plan_bytes = plan_path.read_bytes()
        snapshot_hash = sha256_bytes(plan_bytes)
        session_id = f"SESSION-{state['counters']['session']:03d}"
        task_sessions = {
            task_id: state["tasks"][task_id].get("completion_session")
            for task_id in plan["tasks"]
        }
        snapshot = base64.b64encode(plan_bytes).decode("ascii")
        block = session_event_block(
            f"Completed plan snapshot {plan_id}",
            f"SHA-256: `{snapshot_hash}`\n\n"
            f"Task completion sessions: `{canonical_json(task_sessions)}`\n\n"
            "Exact UTF-8 plan bytes (base64):\n"
            f"```text\n{snapshot}\n```",
            iso_now(),
        )
        session_path = root / _session_path(session_id)
        session_text = session_path.read_text(encoding="utf-8")
        plan["state"] = "complete"
        plan["completion_session"] = session_id
        plan["snapshot_hash"] = snapshot_hash
        plan["updated_at"] = iso_now()
        state["resume"] = _select_resume(state)
        with WorkspaceLock(root):
            transaction_id = _commit(
                root,
                state,
                "PLAN_COMPLETED",
                {
                    "plan_id": plan_id,
                    "snapshot_hash": snapshot_hash,
                    "completion_session": session_id,
                },
                writes={_session_path(session_id): session_text.rstrip() + block},
                deletes=[plan["path"]],
            )
        return {
            "result": "success",
            "workspace_root": str(root),
            "transaction_id": transaction_id,
            "plan_id": plan_id,
            "snapshot_hash": snapshot_hash,
            "next": state["resume"],
        }

    def fix_begin(self, task_id: str, event_id: str, files: list[str]) -> dict[str, Any]:
        root = self.root()
        state = self.load_state(root)
        if task_id not in state["tasks"]:
            raise KeepgoingError(f"Unknown task {task_id}", INVALID)
        task = state["tasks"][task_id]
        if task["state"] not in {"complete", "needs_fix", "verification_pending"}:
            raise KeepgoingError(
                f"{task_id} has no completed result eligible for keepfixing", BLOCKED, "blocked"
            )
        event_id = _require_text(event_id, "event_id")
        for update in task.get("updates", []):
            if update["event_id"] == event_id:
                return {
                    "result": "success",
                    "workspace_root": str(root),
                    "event_id": event_id,
                    "idempotent": True,
                }
        if event_id in state["pending_corrections"]:
            return {
                "result": "success",
                "workspace_root": str(root),
                "event_id": event_id,
                "idempotent": True,
                "allowlist": state["pending_corrections"][event_id]["allowlist"],
            }
        allowlist: list[str] = []
        for relative in files:
            normalized = normalize_relative_path(relative)
            if normalized not in task["files"]:
                raise KeepgoingError(f"{normalized} is not owned by {task_id}", BLOCKED, "blocked")
            target = safe_path(root, normalized, must_exist=True)
            if not target.is_file():
                raise KeepgoingError(f"keepfixing target is not an existing file: {normalized}", BLOCKED)
            allowlist.append(normalized)
        if not allowlist:
            raise KeepgoingError("keepfixing requires a non-empty existing-file allowlist", INVALID)
        session_id = f"SESSION-{state['counters']['session']:03d}"
        episode = {
            "event_id": event_id,
            "task_id": task_id,
            "started_at": iso_now(),
            "allowlist": sorted(set(allowlist)),
            "path_inventory": path_inventory(root),
            "project_hashes": file_inventory(root / "Project"),
            "workspace_hashes": file_inventory(root),
            "structure_hash": state["structure"]["hash"],
            "session_id": session_id,
        }
        state["pending_corrections"][event_id] = episode
        task["state"] = "needs_fix"
        state["resume"] = {
            "correction_event": event_id,
            "task_id": task_id,
            "next_action": f"Modify only {', '.join(episode['allowlist'])}, then verify and run fix-finish.",
            "relevant_paths": episode["allowlist"],
            "verification_needed": task["verification"],
            "do_not_repeat": [],
        }
        session_path = root / _session_path(session_id)
        session_text = session_path.read_text(encoding="utf-8")
        block = session_event_block(
            f"Correction episode {event_id} started",
            f"Target: `{task_id}`\n\nPermitted existing files:\n"
            + "\n".join(f"- `{item}`" for item in episode["allowlist"])
            + "\n\nNo persistent path creation, deletion, rename, move, or structure change is authorized.",
            episode["started_at"],
        )
        episode["session_hash_after_begin"] = sha256_text(session_text.rstrip() + block)
        with WorkspaceLock(root):
            transaction_id = _commit(
                root,
                state,
                "CORRECTION_STARTED",
                {"event_id": event_id, "task_id": task_id, "allowlist": episode["allowlist"]},
                writes={_session_path(session_id): session_text.rstrip() + block},
            )
        return {
            "result": "success",
            "workspace_root": str(root),
            "transaction_id": transaction_id,
            "event_id": event_id,
            "task_id": task_id,
            "allowlist": episode["allowlist"],
        }

    def fix_finish(
        self,
        event_id: str,
        *,
        evidence: list[str] | None = None,
        failed: bool = False,
        reason: str | None = None,
    ) -> dict[str, Any]:
        root = self.root()
        state = self.load_state(root)
        event_id = _require_text(event_id, "event_id")
        for task_id, task in state["tasks"].items():
            for update in task.get("updates", []):
                if update["event_id"] == event_id:
                    return {
                        "result": "success",
                        "workspace_root": str(root),
                        "event_id": event_id,
                        "task_id": task_id,
                        "idempotent": True,
                    }
        if event_id not in state["pending_corrections"]:
            raise KeepgoingError(f"Unknown correction event {event_id}", INVALID)
        episode = state["pending_corrections"][event_id]
        task = state["tasks"][episode["task_id"]]
        derived_issues = self._derived_view_issues(root, state)
        if derived_issues:
            raise KeepgoingError(
                "keepfixing found organizer drift before recording the correction",
                CONFLICT,
                "conflict",
                {"issues": derived_issues},
            )
        current_paths = path_inventory(root)
        if current_paths != episode["path_inventory"]:
            added = sorted(set(current_paths) - set(episode["path_inventory"]))
            removed = sorted(set(episode["path_inventory"]) - set(current_paths))
            raise KeepgoingError(
                "keepfixing changed the persistent path inventory",
                BLOCKED,
                "blocked",
                {"added": added, "removed": removed},
            )
        if state["structure"]["hash"] != episode["structure_hash"]:
            raise KeepgoingError("keepfixing cannot change structure authority", BLOCKED, "blocked")
        current_hashes = file_inventory(root / "Project")
        changed = sorted(
            path
            for path in set(current_hashes) | set(episode["project_hashes"])
            if current_hashes.get(path) != episode["project_hashes"].get(path)
        )
        changed_workspace = [f"Project/{path}" for path in changed]
        unauthorized = [path for path in changed_workspace if path not in episode["allowlist"]]
        if unauthorized:
            raise KeepgoingError(
                "keepfixing modified files outside its allowlist",
                BLOCKED,
                "blocked",
                {"unauthorized": unauthorized},
            )
        workspace_hashes = file_inventory(root)
        internal_mutable = {
            "instructions/state.json",
            "instructions/ledger.jsonl",
            _session_path(episode["session_id"]),
            *_core_writes(state).keys(),
        }
        protected_changes = sorted(
            relative
            for relative in set(workspace_hashes) | set(episode["workspace_hashes"])
            if relative not in internal_mutable
            and relative not in episode["allowlist"]
            and workspace_hashes.get(relative) != episode["workspace_hashes"].get(relative)
        )
        if protected_changes:
            raise KeepgoingError(
                "keepfixing modified protected organizer or workspace-boundary content",
                BLOCKED,
                "blocked",
                {"unauthorized": protected_changes},
            )
        current_session = safe_path(root, _session_path(episode["session_id"]), must_exist=True)
        if sha256_file(current_session) != episode["session_hash_after_begin"]:
            raise KeepgoingError(
                "keepfixing modified its organizer session outside the runtime",
                BLOCKED,
                "blocked",
            )
        claims = [item.strip() for item in (evidence or []) if item.strip()]
        timestamp = iso_now()
        session_id = episode["session_id"]
        if failed:
            task["state"] = "verification_pending"
            state["blockers"].append(
                {
                    "task_id": episode["task_id"],
                    "reason": _require_text(reason, "reason"),
                    "at": timestamp,
                    "correction_event": event_id,
                }
            )
            title = f"Correction episode {event_id} remains unresolved"
            body = f"Verification did not succeed. Reason: {reason}\n\nNo `[updated]` event was recorded."
            outcome = "blocked"
            episode["status"] = "verification_pending"
            episode["last_failure"] = reason
            episode["updated_at"] = timestamp
        else:
            if not changed_workspace:
                raise KeepgoingError(
                    "A successful correction requires an observed content change in an allowlisted file",
                    BLOCKED,
                    "blocked",
                )
            if not claims:
                raise KeepgoingError(
                    "A successful correction requires observed verification evidence",
                    BLOCKED,
                    "blocked",
                )
            update = {
                "event_id": event_id,
                "at": timestamp,
                "at_human": human_now(),
                "evidence": claims,
                "changed_files": changed_workspace,
            }
            for record in task.get("evidence", []):
                record["superseded_by"] = event_id
            refreshed_hashes = {
                relative: sha256_file(safe_path(root, relative, must_exist=True))
                for relative in task["files"]
                if safe_path(root, relative).is_file()
            }
            task["evidence"].append(
                {
                    "at": timestamp,
                    "claims": claims,
                    "files": refreshed_hashes,
                    "session_id": session_id,
                    "correction_event": event_id,
                }
            )
            task["updates"].append(update)
            task["state"] = "complete"
            state["blockers"] = [
                blocker
                for blocker in state["blockers"]
                if blocker.get("task_id") != episode["task_id"]
            ]
            title = f"Correction episode {event_id} completed"
            body = (
                f"Updated `{episode['task_id']}` without changing persistent paths or its original completion timestamp.\n\n"
                "Changed files:\n"
                + ("\n".join(f"- `{item}`" for item in changed_workspace) or "- No file-content difference remained")
                + "\n\nEvidence:\n"
                + "\n".join(f"- {item}" for item in claims)
            )
            outcome = "success"
        if not failed:
            del state["pending_corrections"][event_id]
        state["resume"] = _select_resume(state) if not failed else {
            "correction_event": event_id,
            "task_id": episode["task_id"],
            "next_action": reason,
            "relevant_paths": episode["allowlist"],
            "verification_needed": task["verification"],
            "do_not_repeat": [],
        }
        session_path = root / _session_path(session_id)
        session_text = session_path.read_text(encoding="utf-8")
        block = session_event_block(title, body, timestamp)
        if failed:
            episode["session_hash_after_begin"] = sha256_text(session_text.rstrip() + block)
        with WorkspaceLock(root):
            transaction_id = _commit(
                root,
                state,
                "CORRECTION_FAILED" if failed else "CORRECTION_COMPLETED",
                {"event_id": event_id, "task_id": episode["task_id"], "changed": changed_workspace},
                writes={_session_path(session_id): session_text.rstrip() + block},
            )
        return {
            "result": outcome,
            "workspace_root": str(root),
            "transaction_id": transaction_id,
            "event_id": event_id,
            "task_id": episode["task_id"],
            "changed_files": changed_workspace,
            "updated": not failed,
        }

    def rate_task(
        self,
        task_id: str,
        scores: dict[str, str | int | float | None],
        *,
        evidence: list[str],
        critical_defect: bool = False,
        material_failure: bool = False,
        provisional: bool = False,
    ) -> dict[str, Any]:
        root = self.root()
        state = self.load_state(root)
        if task_id not in state["tasks"]:
            raise KeepgoingError(f"Unknown task {task_id}", INVALID)
        task = state["tasks"][task_id]
        if not task.get("completed_at"):
            raise KeepgoingError("Only tasks with completion history can be rated", BLOCKED, "blocked")
        evidence = [item.strip() for item in evidence if item.strip()]
        if not evidence:
            raise KeepgoingError("A numeric rating requires evidence", INVALID)
        applicable: dict[str, Decimal] = {}
        for dimension, weight in RATING_WEIGHTS.items():
            value = scores.get(dimension)
            if value is None or (isinstance(value, str) and value.strip().upper() == "N/A"):
                continue
            try:
                number = Decimal(str(value))
            except InvalidOperation as exc:
                raise KeepgoingError(f"Invalid score for {dimension}: {value}", INVALID) from exc
            if number < 1 or number > 10:
                raise KeepgoingError(f"{dimension} must be between 1 and 10 or N/A", INVALID)
            applicable[dimension] = number
        if not applicable:
            rating = {
                "score": None,
                "score_raw": None,
                "dimensions": {key: scores.get(key) for key in RATING_WEIGHTS},
                "evidence": evidence,
                "reason": "N/A — insufficient evidence",
                "at": iso_now(),
            }
        else:
            denominator = sum(RATING_WEIGHTS[key] for key in applicable)
            raw = sum(applicable[key] * RATING_WEIGHTS[key] for key in applicable) / denominator
            caps: list[Decimal] = []
            if critical_defect:
                caps.append(Decimal("3"))
            if material_failure:
                caps.append(Decimal("5"))
            if provisional:
                caps.append(Decimal("6"))
            if caps:
                raw = min(raw, min(caps))
            rating = {
                "score": str(raw.quantize(Decimal("0.1"))),
                "score_raw": str(raw),
                "dimensions": {
                    key: (str(applicable[key]) if key in applicable else "N/A")
                    for key in RATING_WEIGHTS
                },
                "evidence": evidence,
                "caps": [str(value) for value in caps],
                "provisional": provisional,
                "at": iso_now(),
            }
        task["rating"] = rating
        task["rating_history"].append(copy.deepcopy(rating))
        session_id = task.get("completion_session") or f"SESSION-{state['counters']['session']:03d}"
        rate_path = f"rates/session_{_numeric(session_id)}_rate.md"
        target = safe_path(root, rate_path, must_exist=True)
        rate_text = target.read_text(encoding="utf-8")
        display = rating["score"] + "/10" if rating["score"] is not None else "N/A"
        block = session_event_block(
            f"{task_id} rating",
            f"Current score: `{display}`\n\nEvidence:\n"
            + "\n".join(f"- {item}" for item in evidence),
            rating["at"],
        )
        with WorkspaceLock(root):
            transaction_id = _commit(
                root,
                state,
                "TASK_RATED",
                {"task_id": task_id, "score": rating["score"]},
                writes={rate_path: rate_text.rstrip() + block},
            )
        return {
            "result": "success",
            "workspace_root": str(root),
            "transaction_id": transaction_id,
            "task_id": task_id,
            "rating": rating,
        }

    def context_check(
        self,
        mode: str,
        *,
        used: Decimal | None = None,
        capacity: Decimal | None = None,
        next_cost: Decimal = Decimal("0"),
        checkpoint_reserve: Decimal = Decimal("0"),
        source: str | None = None,
    ) -> dict[str, Any]:
        root = self.root()
        state = self.load_state(root)
        mode = mode.lower().strip()
        if mode not in {"measured", "estimated", "unavailable"}:
            raise KeepgoingError("Context mode must be measured, estimated, or unavailable", INVALID)
        measurement: dict[str, Any] = {
            "mode": mode,
            "at": iso_now(),
            "source": source or ("host input" if mode != "unavailable" else "no host telemetry"),
        }
        if mode == "unavailable":
            checkpoint = True
            reason = "Exact context usage is unavailable; checkpoint after this meaningful work unit."
        else:
            try:
                used = Decimal(str(used)) if used is not None else None
                capacity = Decimal(str(capacity)) if capacity is not None else None
                next_cost = Decimal(str(next_cost))
                checkpoint_reserve = Decimal(str(checkpoint_reserve))
            except InvalidOperation as exc:
                raise KeepgoingError("Context inputs must be decimal numbers", INVALID) from exc
            if used is None or capacity is None or capacity <= 0 or used < 0:
                raise KeepgoingError(f"{mode} mode requires non-negative used and positive capacity", INVALID)
            ratio = used / capacity
            forecast = (used + next_cost + checkpoint_reserve) / capacity
            threshold = Decimal("0.70") if mode == "measured" else Decimal("0.65")
            checkpoint = ratio >= threshold or forecast >= threshold
            measurement.update(
                {
                    "used": str(used),
                    "capacity": str(capacity),
                    "usage_percent": str((ratio * 100).quantize(Decimal("0.1"))),
                    "forecast_percent": str((forecast * 100).quantize(Decimal("0.1"))),
                    "threshold_percent": str(threshold * 100),
                }
            )
            reason = (
                f"{mode.capitalize()} usage or forecast reached the safe checkpoint threshold."
                if checkpoint
                else f"{mode.capitalize()} usage and forecast remain below the safe checkpoint threshold."
            )
        measurement["decision"] = "checkpoint" if checkpoint else "continue"
        measurement["reason"] = reason
        state["context"] = {"mode": mode, "last_measurement": measurement}
        with WorkspaceLock(root):
            transaction_id = _commit(
                root,
                state,
                "CONTEXT_CHECKED",
                {key: value for key, value in measurement.items() if key != "source"},
            )
        return {
            "result": "checkpoint" if checkpoint else "success",
            "workspace_root": str(root),
            "transaction_id": transaction_id,
            "decision": measurement["decision"],
            "measurement": measurement,
            "exit_code": CHECKPOINT_REQUIRED if checkpoint else 0,
        }

    def requirement_revise(
        self,
        requirement_id: str,
        *,
        title: str,
        acceptance: str,
        reason: str,
        authorized_by: str,
    ) -> dict[str, Any]:
        if self.mode != "keepgoing":
            raise KeepgoingError("keepfixing cannot revise project scope", BLOCKED, "blocked")
        root = self.root()
        state = self.load_state(root)
        if requirement_id not in state["requirements"]:
            raise KeepgoingError(f"Unknown requirement {requirement_id}", INVALID)
        item = state["requirements"][requirement_id]
        item["history"].append(
            {
                "title": item["title"],
                "acceptance": item["acceptance"],
                "state": item["state"],
                "superseded_at": iso_now(),
                "reason": _require_text(reason, "reason"),
                "authorized_by": _require_text(authorized_by, "authorized_by"),
            }
        )
        item["title"] = _require_text(title, "title")
        item["acceptance"] = _require_text(acceptance, "acceptance")
        item["state"] = "planned"
        state["decisions"].append(
            {
                "at": iso_now(),
                "decision": f"Revised {requirement_id}: {item['title']}",
                "basis": f"{reason}; authorized by {authorized_by}",
            }
        )
        with WorkspaceLock(root):
            transaction_id = _commit(
                root,
                state,
                "REQUIREMENT_REVISED",
                {"requirement_id": requirement_id, "reason": reason, "authorized_by": authorized_by},
            )
        return {
            "result": "success",
            "workspace_root": str(root),
            "transaction_id": transaction_id,
            "requirement_id": requirement_id,
            "history_entries": len(item["history"]),
        }

    def plan_allocate(self, plan_spec: dict[str, Any]) -> dict[str, Any]:
        if self.mode != "keepgoing":
            raise KeepgoingError("keepfixing cannot allocate plans", BLOCKED, "blocked")
        root = self.root()
        state = self.load_state(root)
        for key in ("title", "outcome", "scope", "architecture"):
            _require_text(plan_spec.get(key), key)
        requirement_ids = _require_text_list(plan_spec.get("requirements"), "requirements")
        for requirement_id in requirement_ids:
            if requirement_id not in state["requirements"]:
                raise KeepgoingError(f"Unknown requirement {requirement_id}", INVALID)
        dependencies = list(plan_spec.get("dependencies", []))
        for dependency in dependencies:
            if dependency not in state["plans"]:
                raise KeepgoingError(f"Unknown dependency {dependency}", INVALID)
        tasks_spec = plan_spec.get("tasks")
        if not isinstance(tasks_spec, list) or not tasks_spec:
            raise KeepgoingError("A plan requires tasks", INVALID)
        state["counters"]["plan"] += 1
        plan_id = f"PLAN-{state['counters']['plan']:03d}"
        task_ids: list[str] = []
        for task_spec in tasks_spec:
            state["counters"]["task"] += 1
            task_id = f"TASK-{state['counters']['task']:03d}"
            files = [normalize_relative_path(item) for item in _require_text_list(task_spec.get("files"), "files")]
            for relative in files:
                if not profile_allows(state["profile"], relative):
                    raise KeepgoingError(f"Path {relative} is outside the selected profile", INVALID)
            task_ids.append(task_id)
            state["tasks"][task_id] = {
                "plan_id": plan_id,
                "title": _require_text(task_spec.get("title"), "task title"),
                "state": "pending",
                "required": bool(task_spec.get("required", True)),
                "weight": str(task_spec.get("weight", 1)),
                "files": files,
                "preconditions": list(task_spec.get("preconditions") or ["Mapped plan dependencies are complete."]),
                "steps": _require_text_list(task_spec.get("steps"), "steps"),
                "acceptance": _require_text_list(task_spec.get("acceptance"), "acceptance"),
                "verification": _require_text_list(task_spec.get("verification"), "verification"),
                "failure_behavior": _require_text_list(task_spec.get("failure_behavior"), "failure_behavior"),
                "evidence": [],
                "completed_at": None,
                "completed_at_human": None,
                "completion_session": None,
                "updates": [],
                "rating": None,
                "rating_history": [],
            }
        timestamp = iso_now()
        state["plans"][plan_id] = {
            "path": _plan_path(plan_id),
            "title": plan_spec["title"].strip(),
            "outcome": plan_spec["outcome"].strip(),
            "scope": plan_spec["scope"].strip(),
            "architecture": plan_spec["architecture"].strip(),
            "state": "ready" if all(state["plans"][item]["state"] == "complete" for item in dependencies) else "planned",
            "priority": int(plan_spec.get("priority", state["counters"]["plan"])),
            "requirements": requirement_ids,
            "dependencies": dependencies,
            "tasks": task_ids,
            "revision": 1,
            "created_at": timestamp,
            "updated_at": timestamp,
            "owner": plan_spec.get("owner"),
            "completion_conditions": list(plan_spec.get("completion_conditions") or ["All required tasks and evidence are complete."]),
            "continuation": {"task_id": task_ids[0], "step": "1", "next_action": f"Begin {task_ids[0]} at step 1."},
            "revision_history": [{"revision": 1, "at": timestamp, "reason": "Authorized plan allocation."}],
            "completion_session": None,
            "snapshot_hash": None,
        }
        for requirement_id in requirement_ids:
            state["requirements"][requirement_id]["plans"].append(plan_id)
        state["structure"]["allowed_paths"] = sorted(
            set(state["structure"]["allowed_paths"])
            | {path for task_id in task_ids for path in state["tasks"][task_id]["files"]}
        )
        state["structure"]["version"] += 1
        state["structure"]["hash"] = sha256_text(
            canonical_json({"profile": state["profile"], "allowed_paths": state["structure"]["allowed_paths"]})
        )
        state["resume"] = _select_resume(state)
        with WorkspaceLock(root):
            transaction_id = _commit(
                root, state, "PLAN_ALLOCATED", {"plan_id": plan_id, "tasks": task_ids}
            )
        return {
            "result": "success",
            "workspace_root": str(root),
            "transaction_id": transaction_id,
            "plan_id": plan_id,
            "task_ids": task_ids,
        }

    def plan_revise(self, plan_id: str, changes: dict[str, Any], *, reason: str) -> dict[str, Any]:
        if self.mode != "keepgoing":
            raise KeepgoingError("keepfixing cannot revise plans", BLOCKED, "blocked")
        root = self.root()
        state = self.load_state(root)
        if plan_id not in state["plans"]:
            raise KeepgoingError(f"Unknown plan {plan_id}", INVALID)
        plan = state["plans"][plan_id]
        if plan["state"] == "complete":
            raise KeepgoingError("Completed plans require a new corrective plan", BLOCKED, "blocked")
        path = safe_path(root, plan["path"], must_exist=True)
        prior = path.read_bytes()
        next_revision = plan["revision"] + 1
        plan["revision_history"].append(
            {
                "revision": plan["revision"],
                "at": iso_now(),
                "reason": f"Superseded by revision {next_revision}: {reason}",
                "snapshot_hash": sha256_bytes(prior),
                "snapshot_base64": base64.b64encode(prior).decode("ascii"),
            }
        )
        for key in ("title", "outcome", "scope", "architecture"):
            if key in changes:
                plan[key] = _require_text(changes[key], key)
        plan["revision"] = next_revision
        plan["updated_at"] = iso_now()
        plan["revision_history"].append(
            {"revision": next_revision, "at": plan["updated_at"], "reason": _require_text(reason, "reason")}
        )
        state["resume"] = _select_resume(state)
        with WorkspaceLock(root):
            transaction_id = _commit(
                root,
                state,
                "PLAN_REVISED",
                {"plan_id": plan_id, "revision": next_revision, "reason": reason},
            )
        return {
            "result": "success",
            "workspace_root": str(root),
            "transaction_id": transaction_id,
            "plan_id": plan_id,
            "revision": next_revision,
        }

    @staticmethod
    def _drift_issues(root: Path, state: dict[str, Any]) -> list[str]:
        issues: list[str] = []
        known = {f"Project/{path}" for path in state["structure"].get("known_files", {})}
        task_paths = {path for task in state["tasks"].values() for path in task["files"]}
        for relative in file_inventory(root / "Project"):
            workspace_relative = f"Project/{relative}"
            if workspace_relative not in known and workspace_relative not in task_paths:
                issues.append(f"Unplanned application path: {workspace_relative}")
        for task_id, task in state["tasks"].items():
            for record in task.get("evidence", []):
                if record.get("superseded_by"):
                    continue
                for relative, expected in record.get("files", {}).items():
                    target = safe_path(root, relative)
                    if not target.is_file():
                        issues.append(f"Evidence file missing for {task_id}: {relative}")
                    elif sha256_file(target) != expected:
                        issues.append(f"Evidence stale for {task_id}: {relative}")
        return issues

    @staticmethod
    def _derived_view_issues(root: Path, state: dict[str, Any]) -> list[str]:
        issues: list[str] = []
        for relative, expected in _core_writes(state).items():
            target = root / relative
            if not target.is_file():
                issues.append(f"Missing derived record: {relative}")
                continue
            try:
                actual = target.read_text(encoding="utf-8")
            except OSError as exc:
                issues.append(f"Could not read derived record {relative}: {exc}")
                continue
            if actual != expected:
                issues.append(f"Derived record differs from committed state: {relative}")
        return issues

    def detect_drift(self) -> dict[str, Any]:
        root = self.root()
        state = self.load_state(root)
        issues = self._drift_issues(root, state)
        return {
            "result": "conflict" if issues else "success",
            "workspace_root": str(root),
            "issues": issues,
            "exit_code": CONFLICT if issues else 0,
        }

    def validate(self) -> dict[str, Any]:
        root = self.root()
        issues: list[str] = []
        required_paths = [
            "Project",
            "instructions/project.md",
            "instructions/structure.md",
            "instructions/rules.md",
            "instructions/decisions.md",
            "instructions/capabilities.md",
            "instructions/state.json",
            "instructions/ledger.jsonl",
            "sessions/session_sum.md",
            "plans/plan_index.md",
            "rates/Sessions_rate.md",
        ]
        for relative in required_paths:
            if not (root / relative).exists():
                issues.append(f"Missing required path: {relative}")
        try:
            state = self.load_state(root, verify_authority=False)
        except KeepgoingError as exc:
            return {
                "result": "failure",
                "workspace_root": str(root),
                "issues": [str(exc)],
                "complete": False,
                "exit_code": INVALID,
            }
        events, ledger_issues = read_ledger(
            root / "instructions" / "ledger.jsonl", tolerate_truncated=True
        )
        issues.extend(ledger_issues)
        if not events:
            issues.append("Ledger contains no committed history")
        elif events[-1]["type"] == "TX_PREPARED":
            issues.append("Ledger ends with an uncommitted prepared transaction")
        committed = [event for event in events if event["type"] in {"TX_COMMITTED", "TX_RECOVERED"}]
        if committed and state["last_committed_event"] != committed[-1]["sequence"]:
            issues.append("State snapshot does not match the latest committed ledger event")
        if committed:
            expected_state_hash = committed[-1].get("payload", {}).get("state_hash")
            if not expected_state_hash:
                issues.append("Latest committed ledger event has no state checksum")
            elif sha256_text(canonical_json(state)) != expected_state_hash:
                issues.append("State snapshot content differs from committed ledger authority")
        expected_structure_hash = sha256_text(
            canonical_json(
                {"profile": state["profile"], "allowed_paths": state["structure"]["allowed_paths"]}
            )
        )
        if state["structure"]["hash"] != expected_structure_hash:
            issues.append("Structure policy hash does not match its allowed paths")
        try:
            for collision in case_collisions(root):
                issues.append("Case-colliding paths: " + ", ".join(collision))
        except KeepgoingError as exc:
            issues.append(str(exc))
        for requirement_id, requirement in state["requirements"].items():
            if not requirement["plans"]:
                issues.append(f"Requirement has no plan mapping: {requirement_id}")
            for plan_id in requirement["plans"]:
                if plan_id not in state["plans"]:
                    issues.append(f"Requirement {requirement_id} references unknown {plan_id}")
        for plan_id, plan in state["plans"].items():
            for dependency in plan["dependencies"]:
                if dependency not in state["plans"]:
                    issues.append(f"Plan {plan_id} references unknown dependency {dependency}")
                elif _numeric(dependency) >= _numeric(plan_id):
                    issues.append(f"Plan {plan_id} has non-prior dependency {dependency}")
            active_path = root / plan["path"]
            if plan["state"] == "complete":
                if active_path.exists():
                    issues.append(f"Completed plan remains in active queue: {plan_id}")
                session_id = plan.get("completion_session")
                if not session_id:
                    issues.append(f"Completed plan has no completion session: {plan_id}")
                else:
                    session_path = root / _session_path(session_id)
                    if not session_path.exists() or plan.get("snapshot_hash") not in session_path.read_text(
                        encoding="utf-8"
                    ):
                        issues.append(f"Completed plan snapshot is not recoverable: {plan_id}")
            elif plan["state"] not in {"cancelled", "superseded"} and not active_path.exists():
                issues.append(f"Active plan file missing: {plan_id}")
            for task_id in plan["tasks"]:
                if task_id not in state["tasks"]:
                    issues.append(f"Plan {plan_id} references unknown task {task_id}")
        issues.extend(self._derived_view_issues(root, state))
        issues.extend(self._drift_issues(root, state))
        resume = state.get("resume")
        if resume and resume.get("task_id") not in state["tasks"]:
            issues.append("Continuation pointer references an unknown task")
        max_ids = {
            "requirement": max((_numeric(item) for item in state["requirements"]), default=0),
            "plan": max((_numeric(item) for item in state["plans"]), default=0),
            "task": max((_numeric(item) for item in state["tasks"]), default=0),
            "session": max((_numeric(item) for item in state["sessions"]), default=0),
        }
        for key, maximum in max_ids.items():
            if state["counters"].get(key, -1) < maximum:
                issues.append(f"Counter {key} is behind allocated identifiers")
        required_tasks = [task for task in state["tasks"].values() if task.get("required", True)]
        complete = bool(required_tasks) and all(task["state"] == "complete" for task in required_tasks)
        complete = complete and all(plan["state"] == "complete" for plan in state["plans"].values())
        complete = complete and not state["blockers"] and not state["pending_corrections"] and not issues
        return {
            "result": "success" if not issues else "failure",
            "workspace_root": str(root),
            "issues": issues,
            "complete": complete,
            "exit_code": 0 if not issues else INVALID,
            "last_committed_event": state["last_committed_event"],
        }

    def recover(self) -> dict[str, Any]:
        root = discover_workspace(self.start)
        ledger_path = root / "instructions" / "ledger.jsonl"
        raw = ledger_path.read_text(encoding="utf-8")
        events, issues = read_ledger(ledger_path, tolerate_truncated=True)
        preserved_tail: str | None = None
        if issues:
            if len(issues) != 1 or not issues[0].startswith("Malformed ledger line"):
                raise KeepgoingError(
                    "Ledger corruption is not a safely truncatable tail",
                    RECOVERY_REQUIRED,
                    "blocked",
                    {"issues": issues},
                )
            recovery_dir = private_home() / "recovery" / workspace_key(root)
            recovery_dir.mkdir(parents=True, exist_ok=True)
            preserved = recovery_dir / f"ledger-tail-{uuid.uuid4().hex}.txt"
            preserved.write_text(raw, encoding="utf-8")
            preserved_tail = str(preserved)
            valid_text = "".join(canonical_json(event) + "\n" for event in events)
            atomic_write_text(ledger_path, valid_text, root)
        if not events:
            raise KeepgoingError("No valid ledger event is available for recovery", RECOVERY_REQUIRED)
        last = events[-1]
        with WorkspaceLock(root):
            if last["type"] == "TX_PREPARED":
                payload = last["payload"]
                bundle = _load_transaction_bundle(root, last)
                state = bundle["target_state"]
                _apply_write_set(root, bundle.get("writes", {}), bundle.get("deletes", []))
                state["last_committed_event"] = last["sequence"] + 1
                state["counters"]["event"] = last["sequence"] + 1
                state["last_transaction"] = last["transaction_id"]
                state["recovery"]["pending_transaction"] = None
                recovered = new_event(
                    sequence=last["sequence"] + 1,
                    transaction_id=last["transaction_id"],
                    event_type="TX_RECOVERED",
                    payload=payload,
                    previous_hash=last["event_hash"],
                )
                append_jsonl(ledger_path, recovered)
                atomic_write_json(root / "instructions" / "state.json", state, root)
                action = "rolled forward prepared transaction"
                transaction_id = last["transaction_id"]
            else:
                try:
                    state = _load_transaction_bundle(root, last)["target_state"]
                except KeepgoingError:
                    current = self.load_state(root, verify_authority=False)
                    expected_hash = last.get("payload", {}).get("state_hash")
                    if not expected_hash or sha256_text(canonical_json(current)) != expected_hash:
                        raise
                    state = current
                atomic_write_json(root / "instructions" / "state.json", state, root)
                _apply_write_set(root, _core_writes(state), [])
                action = "rebuilt state and derived views from latest commit"
                transaction_id = last["transaction_id"]
        return {
            "result": "success",
            "workspace_root": str(root),
            "transaction_id": transaction_id,
            "action": action,
            "preserved_invalid_ledger": preserved_tail,
        }

    @staticmethod
    def _replacement_root(start: Path) -> Path:
        current = start.resolve()
        for candidate in [current, *current.parents]:
            if (candidate / "deprecated" / "replacement.json").is_file():
                return candidate
        raise KeepgoingError("No replacement recovery marker found", BLOCKED, "blocked")

    @staticmethod
    def _write_replacement_marker(root: Path, marker: dict[str, Any]) -> None:
        atomic_write_json(root / "deprecated" / "replacement.json", marker, root)

    @staticmethod
    def _tree_manifest(root: Path, names: list[str]) -> dict[str, Any]:
        entries: dict[str, Any] = {}
        for name in names:
            target = root / name
            if not target.exists():
                continue
            if target.is_dir():
                entries[name] = {
                    "kind": "directory",
                    "files": file_inventory(target),
                    "paths": path_inventory(target),
                }
            else:
                entries[name] = {"kind": "file", "sha256": sha256_file(target)}
        return entries

    def replace(
        self,
        spec: dict[str, Any],
        *,
        reason: str,
        dry_run: bool = False,
        stamp: str | None = None,
        fail_after: str | None = None,
    ) -> dict[str, Any]:
        if self.mode != "keepgoing":
            raise KeepgoingError("keepfixing cannot replace a project", BLOCKED, "blocked")
        root = self.root()
        old_state = self.load_state(root)
        marker_path = root / "deprecated" / "replacement.json"
        if marker_path.is_file():
            existing_marker = read_json(marker_path)
            if existing_marker.get("status") not in {"committed", "rolled_back"}:
                raise KeepgoingError(
                    "An interrupted replacement requires recovery before another replacement",
                    RECOVERY_REQUIRED,
                    "blocked",
                    {"marker": str(marker_path), "status": existing_marker.get("status")},
                )
        _validate_spec(spec)
        reason = _require_text(reason, "reason")
        archive = ensure_unique_archive(root / "deprecated", stamp)
        plan = {
            "result": "success",
            "workspace_root": str(root),
            "operation": "replace",
            "archive": str(archive),
            "preserve": [name for name in ACTIVE_DIRS if (root / name).exists()],
            "new_profile": spec["profile"],
            "predecessor_id": old_state["generation_id"],
        }
        if dry_run:
            plan["dry_run"] = True
            return plan
        transaction_id = f"REPLACE-{uuid.uuid4()}"
        stage = private_home() / "replacements" / workspace_key(root) / transaction_id
        if stage.exists():
            raise KeepgoingError(f"Replacement stage already exists: {stage}", CONFLICT)
        stage.mkdir(parents=True)
        new_state = _make_state(spec, predecessor_id=old_state["generation_id"])
        new_state["workspace_id"] = old_state["workspace_id"]
        new_state["lineage_note"] = (
            f"This generation replaces `{old_state['generation_id']}` because: {reason}"
        )
        for name in (*ACTIVE_DIRS, "deprecated"):
            (stage / name).mkdir(parents=True, exist_ok=True)
        for container in STANDARD_CONTAINERS:
            (stage / "Project" / Path(container)).mkdir(parents=True, exist_ok=True)
        for native in get_profile(new_state["profile"])["native_paths"]:
            (stage / Path(native)).mkdir(parents=True, exist_ok=True)
        new_state["structure"]["known_files"] = file_inventory(stage / "Project")
        staged_writes = _core_writes(new_state)
        staged_writes["sessions/session_1.md"] = render_session_header(
            new_state,
            "SESSION-001",
            spec.get("starting_instruction") or new_state["scope"],
        )
        staged_writes["rates/session_1_rate.md"] = (
            "# SESSION-001 rating history\n\nNo completed task has sufficient rating evidence.\n"
        )
        with WorkspaceLock(stage):
            _commit(
                stage,
                new_state,
                "WORKSPACE_REPLACEMENT_STAGED",
                {"predecessor_id": old_state["generation_id"], "reason": reason},
                writes=staged_writes,
            )
        marker = {
            "schema_version": SCHEMA_VERSION,
            "transaction_id": transaction_id,
            "status": "prepared",
            "reason": reason,
            "created_at": iso_now(),
            "workspace_id": old_state["workspace_id"],
            "old_generation_id": old_state["generation_id"],
            "new_generation_id": new_state["generation_id"],
            "archive": str(archive),
            "stage": str(stage),
            "preserve": plan["preserve"],
            "staged_manifest": self._tree_manifest(stage, list(ACTIVE_DIRS)),
            "moved": [],
            "promoted": [],
            "last_step": "prepared",
        }
        (root / "deprecated").mkdir(parents=True, exist_ok=True)
        with WorkspaceLock(root):
            events, ledger_issues = read_ledger(
                root / "instructions" / "ledger.jsonl", tolerate_truncated=True
            )
            if ledger_issues or not events or events[-1]["type"] == "TX_PREPARED":
                raise KeepgoingError(
                    "Active generation requires recovery before replacement",
                    RECOVERY_REQUIRED,
                    "blocked",
                    {"issues": ledger_issues},
                )
            if old_state["last_committed_event"] != events[-1]["sequence"]:
                raise KeepgoingError(
                    "Active generation changed while replacement was staged",
                    CONFLICT,
                    "conflict",
                )
            marker["baseline_manifest"] = self._tree_manifest(root, plan["preserve"])
            marker["baseline_manifest_hash"] = sha256_text(
                canonical_json(marker["baseline_manifest"])
            )
            self._write_replacement_marker(root, marker)
            if fail_after == "prepared":
                raise KeepgoingError("Injected replacement interruption after prepared", IO_FAILURE)
            archive.mkdir()
            for name in plan["preserve"]:
                source = root / name
                target = archive / name
                if source.exists():
                    move_verified(source, target)
                marker["moved"].append(name)
                marker["status"] = "archiving"
                marker["last_step"] = f"archived:{name}"
                self._write_replacement_marker(root, marker)
                if fail_after == f"archived:{name}":
                    raise KeepgoingError(
                        f"Injected replacement interruption after archiving {name}", IO_FAILURE
                    )
            after_manifest = self._tree_manifest(archive, plan["preserve"])
            if marker["baseline_manifest"] != after_manifest:
                raise KeepgoingError("Archived generation verification failed", IO_FAILURE)
            archive_manifest = {
                "schema_version": SCHEMA_VERSION,
                "workspace_id": old_state["workspace_id"],
                "generation_id": old_state["generation_id"],
                "archived_at": iso_now(),
                "reason": reason,
                "entries": after_manifest,
            }
            atomic_write_json(archive / "archive_manifest.json", archive_manifest, root)
            marker["status"] = "promoting"
            marker["last_step"] = "archive-verified"
            self._write_replacement_marker(root, marker)
            for name in ACTIVE_DIRS:
                source = stage / name
                target = root / name
                if target.exists():
                    raise KeepgoingError(f"Replacement promotion collision: {target}", CONFLICT)
                move_verified(source, target)
                marker["promoted"].append(name)
                marker["last_step"] = f"promoted:{name}"
                self._write_replacement_marker(root, marker)
                if fail_after == f"promoted:{name}":
                    raise KeepgoingError(
                        f"Injected replacement interruption after promoting {name}", IO_FAILURE
                    )
            promoted_state = read_json(root / "instructions" / "state.json")
            if promoted_state["generation_id"] != new_state["generation_id"]:
                raise KeepgoingError("Promoted generation identity mismatch", IO_FAILURE)
            marker["status"] = "committed"
            marker["last_step"] = "committed"
            marker["committed_at"] = iso_now()
            self._write_replacement_marker(root, marker)
        shutil.rmtree(stage, ignore_errors=True)
        plan.update(
            {
                "dry_run": False,
                "transaction_id": transaction_id,
                "generation_id": new_state["generation_id"],
                "marker": str(root / "deprecated" / "replacement.json"),
            }
        )
        return plan

    def recover_replacement(self) -> dict[str, Any]:
        root = self._replacement_root(self.start)
        marker_path = root / "deprecated" / "replacement.json"
        marker = read_json(marker_path)
        if marker.get("status") == "committed":
            return {
                "result": "success",
                "workspace_root": str(root),
                "transaction_id": marker["transaction_id"],
                "idempotent": True,
                "action": "replacement already committed",
            }
        stage = Path(marker["stage"])
        archive = Path(marker["archive"])
        preserve = list(marker["preserve"])
        baseline = marker.get("baseline_manifest")
        staged_manifest = marker.get("staged_manifest")
        if not isinstance(baseline, dict) or sha256_text(canonical_json(baseline)) != marker.get(
            "baseline_manifest_hash"
        ):
            raise KeepgoingError(
                "Replacement marker has no trustworthy predecessor baseline",
                RECOVERY_REQUIRED,
                "blocked",
            )
        if not isinstance(staged_manifest, dict):
            raise KeepgoingError(
                "Replacement marker has no staged-generation manifest",
                RECOVERY_REQUIRED,
                "blocked",
            )
        with WorkspaceLock(root):
            if stage.exists():
                archive.mkdir(parents=True, exist_ok=True)
                for name in preserve:
                    source = root / name
                    archived = archive / name
                    expected = baseline.get(name)
                    if name in marker["moved"]:
                        if self._tree_manifest(archive, [name]).get(name) != expected:
                            raise KeepgoingError(
                                f"Archived predecessor content no longer matches its baseline: {name}",
                                RECOVERY_REQUIRED,
                                "blocked",
                            )
                        if source.exists() and name not in marker.get("promoted", []):
                            raise KeepgoingError(
                                f"Unexpected active content appeared during replacement: {name}",
                                RECOVERY_REQUIRED,
                                "blocked",
                            )
                        continue
                    if archived.exists():
                        if self._tree_manifest(archive, [name]).get(name) != expected:
                            raise KeepgoingError(
                                f"Ambiguous interrupted archive move: {name}",
                                RECOVERY_REQUIRED,
                                "blocked",
                            )
                        if source.exists():
                            if self._tree_manifest(root, [name]).get(name) != expected:
                                raise KeepgoingError(
                                    f"Predecessor changed during interrupted copy: {name}",
                                    RECOVERY_REQUIRED,
                                    "blocked",
                                )
                            if source.is_dir() and not source.is_symlink():
                                shutil.rmtree(source)
                            else:
                                source.unlink()
                    else:
                        if not source.exists() or self._tree_manifest(root, [name]).get(name) != expected:
                            raise KeepgoingError(
                                f"Predecessor content changed before recovery: {name}",
                                RECOVERY_REQUIRED,
                                "blocked",
                            )
                        move_verified(source, archived)
                    marker["moved"].append(name)
                    marker["last_step"] = f"archived:{name}"
                    self._write_replacement_marker(root, marker)
                if self._tree_manifest(archive, preserve) != baseline:
                    raise KeepgoingError(
                        "Archived predecessor does not match the durable baseline",
                        RECOVERY_REQUIRED,
                        "blocked",
                    )
                archive_manifest_path = archive / "archive_manifest.json"
                if archive_manifest_path.exists():
                    existing_manifest = read_json(archive_manifest_path)
                    if existing_manifest.get("entries") != baseline:
                        raise KeepgoingError(
                            "Existing archive manifest conflicts with the durable baseline",
                            RECOVERY_REQUIRED,
                            "blocked",
                        )
                else:
                    archive_manifest = {
                        "schema_version": SCHEMA_VERSION,
                        "workspace_id": marker["workspace_id"],
                        "generation_id": marker["old_generation_id"],
                        "archived_at": iso_now(),
                        "reason": marker["reason"],
                        "entries": baseline,
                    }
                    atomic_write_json(archive_manifest_path, archive_manifest, root)
                for name in ACTIVE_DIRS:
                    target = root / name
                    staged = stage / name
                    expected = staged_manifest.get(name)
                    if name in marker["promoted"]:
                        if self._tree_manifest(root, [name]).get(name) != expected:
                            raise KeepgoingError(
                                f"Promoted generation content changed before recovery: {name}",
                                RECOVERY_REQUIRED,
                                "blocked",
                            )
                        continue
                    if target.exists():
                        if self._tree_manifest(root, [name]).get(name) != expected:
                            raise KeepgoingError(f"Recovery promotion collision: {target}", CONFLICT)
                        if staged.exists():
                            if self._tree_manifest(stage, [name]).get(name) != expected:
                                raise KeepgoingError(
                                    f"Replacement stage changed during recovery: {name}",
                                    RECOVERY_REQUIRED,
                                )
                            remove_target = staged
                            if remove_target.is_dir() and not remove_target.is_symlink():
                                shutil.rmtree(remove_target)
                            else:
                                remove_target.unlink()
                    elif not staged.exists():
                        raise KeepgoingError(
                            f"Replacement stage is missing {name}", RECOVERY_REQUIRED
                        )
                    else:
                        if self._tree_manifest(stage, [name]).get(name) != expected:
                            raise KeepgoingError(
                                f"Replacement stage changed during recovery: {name}",
                                RECOVERY_REQUIRED,
                            )
                        move_verified(staged, target)
                    marker["promoted"].append(name)
                    marker["last_step"] = f"promoted:{name}"
                    self._write_replacement_marker(root, marker)
                marker["status"] = "committed"
                marker["last_step"] = "committed"
                marker["committed_at"] = iso_now()
                self._write_replacement_marker(root, marker)
                shutil.rmtree(stage, ignore_errors=True)
                action = "completed interrupted replacement"
            else:
                recovery_home = private_home() / "failed-replacements" / marker["transaction_id"]
                recovery_home.mkdir(parents=True, exist_ok=True)
                for name in reversed(marker.get("promoted", [])):
                    active = root / name
                    if active.exists():
                        move_verified(active, recovery_home / name)
                for name in reversed(marker.get("moved", [])):
                    archived = archive / name
                    active = root / name
                    if active.exists():
                        raise KeepgoingError(f"Rollback would overwrite {active}", CONFLICT)
                    if archived.exists():
                        if self._tree_manifest(archive, [name]).get(name) != baseline.get(name):
                            raise KeepgoingError(
                                f"Rollback source differs from predecessor baseline: {name}",
                                RECOVERY_REQUIRED,
                            )
                        move_verified(archived, active)
                marker["status"] = "rolled_back"
                marker["last_step"] = "rolled-back"
                marker["rolled_back_at"] = iso_now()
                marker["preserved_failed_generation"] = str(recovery_home)
                self._write_replacement_marker(root, marker)
                action = "restored predecessor and preserved partial replacement privately"
        return {
            "result": "success",
            "workspace_root": str(root),
            "transaction_id": marker["transaction_id"],
            "action": action,
            "status": marker["status"],
        }
