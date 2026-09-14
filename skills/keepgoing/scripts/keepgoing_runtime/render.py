"""Human-readable derived views for governed workspaces."""

from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal
from typing import Any

from .profiles import PROFILES, STANDARD_CONTAINERS


def _lines(values: list[str], prefix: str = "- ") -> str:
    return "\n".join(f"{prefix}{value}" for value in values) if values else "- None"


def render_project(state: dict[str, Any]) -> str:
    rows = []
    for requirement_id, requirement in state["requirements"].items():
        plan_ids = ", ".join(requirement["plans"]) or "unmapped"
        rows.append(
            f"| {requirement_id} | {requirement['title']} | {requirement['state']} | "
            f"{plan_ids} | {requirement['acceptance']} |"
        )
    return (
        f"# {state['project_name']}\n\n"
        f"Workspace ID: `{state['workspace_id']}`  \n"
        f"Generation ID: `{state['generation_id']}`  \n"
        f"Predecessor: `{state.get('predecessor_id') or 'none'}`  \n"
        f"Profile: `{state['profile']}`  \n"
        f"Timezone: `{state['timezone']}`\n\n"
        "## Scope\n\n"
        f"{state['scope']}\n\n"
        "## Requirements and coverage\n\n"
        "| ID | Requirement | State | Plans | Acceptance |\n"
        "| --- | --- | --- | --- | --- |\n"
        + "\n".join(rows)
        + "\n\n## Lineage\n\n"
        + (state.get("lineage_note") or "This is the first project generation.")
        + "\n"
    )


def render_structure(state: dict[str, Any]) -> str:
    profile = PROFILES[state["profile"]]
    concrete = sorted(state["structure"]["allowed_paths"])
    containers = "\n".join(
        f"- `Project/{path}/` — standard organizer container" for path in STANDARD_CONTAINERS
    )
    return (
        "# Structure authority\n\n"
        f"Structure version: `{state['structure']['version']}`  \n"
        f"Structure hash: `{state['structure']['hash']}`  \n"
        f"Recorded: `{state['created_at']}`  \n"
        f"Selected profile: `{state['profile']}` — {profile['summary']}\n\n"
        "## Fixed application containers\n\n"
        f"{containers}\n\n"
        "Unused containers remain reserved and must not receive invented implementations.\n\n"
        "## Concrete planned paths\n\n"
        f"{_lines([f'`{path}`' for path in concrete])}\n\n"
        "## Ownership and dependency direction\n\n"
        "- Runnable applications own their native source, manifests, configuration, and local tests.\n"
        "- Shared packages may not depend on application feature internals.\n"
        "- API handlers delegate business behavior to service/data-access boundaries selected by the plan.\n"
        "- API contracts belong in `Project/apis/`; SQL artifacts belong in `Project/sql/`.\n"
        "- Cross-application integration and end-to-end checks belong in `Project/tests/`.\n"
        "- Secrets never belong in client-delivered configuration or committed examples.\n\n"
        "## Extension and generated-output rules\n\n"
        "New persistent paths require an active plan that names the exact path and a revised structure authority. "
        "Generated dependency, build, cache, and runtime-storage output is not application source and must follow "
        "the selected toolchain's ignore/retention rules. Symlinks may not escape this workspace. "
        "keepfixing never revises this structure.\n\n"
        "## Naming and validation\n\n"
        "Use the framework's native casing and file rules inside the selected application root. "
        "All paths must remain under `Project/`, match the current plan, avoid case collisions, and pass "
        "`validate` after implementation. A user-authorized architecture change increments the structure version, "
        "records the decision, and revises affected plans before new paths are created.\n"
    )


def render_rules(state: dict[str, Any]) -> str:
    return (
        "# Project rules\n\n"
        f"{_lines(state.get('rules', []))}\n\n"
        "## Organizer invariants\n\n"
        "- Implementation evidence comes from actual project files and observed checks.\n"
        "- Lifecycle records may summarize evidence but cannot replace it.\n"
        "- Keep secrets and personal data out of records and command excerpts.\n"
        "- Preserve user changes; never use destructive source-control reset as recovery.\n"
    )


def render_decisions(state: dict[str, Any]) -> str:
    decisions = state.get("decisions", [])
    if not decisions:
        body = "- No consequential decisions beyond the initialization specification."
    else:
        body = "\n".join(
            f"- `{item['at']}` — {item['decision']} (basis: {item['basis']})"
            for item in decisions
        )
    return "# Decisions\n\n" + body + "\n"


def render_capabilities(state: dict[str, Any]) -> str:
    return (
        "# Host capabilities\n\n"
        "- Filesystem enforcement: managed runtime operations validate workspace boundaries, exact planned paths, "
        "symlink escapes, case collisions, and single-writer ownership. Direct external edits are detected at "
        "validation/checkpoint; they are not claimed to be intercepted.\n"
        "- Transactions: organizer writes use a checksummed ledger, external staging, atomic replacement where the "
        "filesystem supports it, and recoverable prepared events. Replacement additionally uses the fixed "
        "`deprecated/replacement.json` marker.\n"
        "- Context telemetry: runtime accepts measured or explicitly estimated host input. When unavailable it never "
        "invents a percentage and requests a checkpoint after each meaningful unit.\n"
        "- Hooks: no universal edit/compaction hook API is assumed. Provider adapters may call runtime guards where "
        "their documented hook system supports it.\n"
        "- Continuation: durable records identify the next exact action. Automatic model restart is not claimed; a "
        "user or supervising host must invoke keepgoing again unless that host provides an observed adapter.\n"
        f"- Current context mode: `{state['context']['mode']}`.\n"
    )


def render_plan(state: dict[str, Any], plan_id: str) -> str:
    plan = state["plans"][plan_id]
    requirements = ", ".join(plan["requirements"])
    dependencies = ", ".join(plan["dependencies"]) or "none"
    task_sections: list[str] = []
    for task_id in plan["tasks"]:
        task = state["tasks"][task_id]
        task_sections.append(
            f"### {task_id} — {task['title']}\n\n"
            f"State: `{task['state']}`  \n"
            f"Weight: `{task['weight']}`  \n"
            f"Files:\n{_lines([f'`{item}`' for item in task['files']])}\n\n"
            f"Preconditions:\n{_lines(task['preconditions'])}\n\n"
            f"Implementation steps:\n"
            + "\n".join(f"{index}. {step}" for index, step in enumerate(task["steps"], 1))
            + "\n\nAcceptance criteria:\n"
            + _lines(task["acceptance"])
            + "\n\nPlanned verification:\n"
            + _lines(task["verification"])
            + "\n\nFailure and recovery behavior:\n"
            + _lines(task["failure_behavior"])
        )
    history = "\n".join(
        f"- Revision {entry['revision']} at `{entry['at']}`: {entry['reason']}"
        for entry in plan["revision_history"]
    )
    anchor = plan["continuation"]
    return (
        f"# {plan_id} — {plan['title']}\n\n"
        f"Revision: `{plan['revision']}`  \n"
        f"State: `{plan['state']}`  \n"
        f"Priority: `{plan['priority']}`  \n"
        f"Created: `{plan['created_at']}`  \n"
        f"Updated: `{plan['updated_at']}`  \n"
        f"Requirements: `{requirements}`  \n"
        f"Dependencies: `{dependencies}`  \n"
        f"Owner: `{plan.get('owner') or 'single coordinated writer'}`\n\n"
        "## Outcome and context\n\n"
        f"{plan['outcome']}\n\n"
        "## Scope and boundaries\n\n"
        f"{plan['scope']}\n\n"
        "## Chosen tools and architecture\n\n"
        f"{plan['architecture']}\n\n"
        "## Tasks\n\n"
        + "\n\n".join(task_sections)
        + "\n\n## Completion conditions\n\n"
        + _lines(plan["completion_conditions"])
        + "\n\n## Continuation anchor\n\n"
        + f"Task: `{anchor.get('task_id') or 'none'}`  \n"
        + f"Step: `{anchor.get('step') or 'none'}`  \n"
        + f"Next action: {anchor.get('next_action') or 'Select the first dependency-eligible pending task.'}\n\n"
        + "## Revision history\n\n"
        + history
        + "\n"
    )


def render_plan_index(state: dict[str, Any]) -> str:
    rows = []
    for plan_id in sorted(state["plans"]):
        plan = state["plans"][plan_id]
        completion = plan.get("completion_session") or "active"
        rows.append(
            f"| {plan_id} | {plan['title']} | {plan['state']} | "
            f"{', '.join(plan['dependencies']) or 'none'} | {completion} |"
        )
    return (
        "# Plan index\n\n"
        "| Plan | Title | State | Dependencies | Completion location |\n"
        "| --- | --- | --- | --- | --- |\n"
        + "\n".join(rows)
        + "\n\n## Current continuation\n\n"
        + "```json\n"
        + json.dumps(state.get("resume"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n```\n"
    )


def render_session_header(state: dict[str, Any], session_id: str, instruction: str) -> str:
    session = state["sessions"][session_id]
    return (
        f"# {session_id}\n\n"
        f"Generation: `{state['generation_id']}`  \n"
        f"Started: `{session['started_at']}`  \n"
        f"Ended: `{session.get('ended_at') or 'open'}`  \n"
        f"Status: `{session['status']}`  \n"
        f"Mode: `{session['mode']}`  \n"
        f"Agent/runtime: `{session.get('agent') or 'unknown'}`\n\n"
        "## Starting instruction\n\n"
        f"{instruction}\n\n"
        "## Starting state\n\n"
        f"{session['starting_state']}\n\n"
        "## Chronological work\n\n"
        "- Session initialized; no implementation result is implied.\n\n"
        "## Verification evidence\n\n"
        "- No verification evidence has been recorded in this session.\n\n"
        "## Handoff\n\n"
        "Use the structured continuation in `instructions/state.json` and the active plan named there.\n"
    )


def session_event_block(title: str, body: str, at: str) -> str:
    return f"\n\n## {title} — {at}\n\n{body.rstrip()}\n"


def render_session_summary(state: dict[str, Any]) -> str:
    unresolved = []
    for task_id, task in state["tasks"].items():
        if task["state"] not in {"complete", "cancelled", "superseded"}:
            pointer = state.get("resume") or {}
            detail = pointer.get("next_action") if pointer.get("task_id") == task_id else task["title"]
            unresolved.append(f"- {task_id}: {detail} [{task['state']}]" )
    grouped: dict[str, list[str]] = defaultdict(list)
    for task_id, task in state["tasks"].items():
        if not task.get("completed_at"):
            continue
        session_id = task.get("completion_session") or "session_unknown"
        tokens = f"[complete][{task['completed_at_human']}]"
        for update in task.get("updates", []):
            tokens += f"[updated][{update['at_human']}]"
        grouped[session_id].append(f"{task_id}: {task['title']}. {tokens}")
    sections = []
    for session_id in sorted(state["sessions"], key=lambda item: int(item.split("-")[-1])):
        public_name = "session_" + str(int(session_id.split("-")[-1]))
        entries = grouped.get(session_id, [])
        body = "\n".join(f"{index}- {entry}" for index, entry in enumerate(entries, 1))
        sections.append(f"{public_name}:\n{body or 'No completed tasks recorded.'}")
    return (
        "# Current unresolved work\n\n"
        + ("\n".join(unresolved) if unresolved else "- None")
        + "\n\n# Chronological summaries\n\n"
        + "\n\n".join(sections)
        + "\n"
    )


def render_rates(state: dict[str, Any]) -> str:
    rated = []
    eligible = []
    by_session: dict[str, list[tuple[str, Decimal, Decimal]]] = defaultdict(list)
    for task_id, task in state["tasks"].items():
        if task.get("completed_at"):
            eligible.append(task_id)
        if task.get("rating") and task["rating"].get("score") is not None:
            score = Decimal(str(task["rating"]["score_raw"]))
            weight = Decimal(str(task.get("weight", 1)))
            rated.append((task_id, score, weight))
            by_session[task.get("completion_session") or "SESSION-000"].append(
                (task_id, score, weight)
            )
    if rated:
        numerator = sum(score * weight for _, score, weight in rated)
        denominator = sum(weight for _, _, weight in rated)
        total = f"{(numerator / denominator).quantize(Decimal('0.1'))}/10"
    else:
        total = "N/A"
    required = [task for task in state["tasks"].values() if task.get("required", True)]
    completed = [task for task in required if task["state"] == "complete"]
    active_plans = sum(1 for plan in state["plans"].values() if plan["state"] != "complete")
    sections = []
    for session_id, values in sorted(by_session.items()):
        session_weight = sum(weight for _, _, weight in values)
        average = sum(score * weight for _, score, weight in values) / session_weight
        details = "\n".join(
            f"- {task_id}: {state['tasks'][task_id]['title']}. "
            f"[{Decimal(str(state['tasks'][task_id]['rating']['score'])).quantize(Decimal('0.1'))}/10]"
            for task_id, _, _ in values
        )
        sections.append(f"{session_id.lower().replace('-', '_')}[{average.quantize(Decimal('0.1'))}/10]\n{details}")
    return (
        "# Sessions_rate\n\n"
        f"Total[{total}]\n"
        f"Completion[{len(completed)}/{len(required)} required tasks]\n"
        f"Rating coverage[{len(rated)}/{len(eligible)} tasks with completion history]\n"
        f"Unresolved[{len(required) - len(completed)} required tasks; {active_plans} active plans]\n\n"
        + ("\n\n".join(sections) if sections else "No completed work has sufficient rating evidence.")
        + "\n"
    )
