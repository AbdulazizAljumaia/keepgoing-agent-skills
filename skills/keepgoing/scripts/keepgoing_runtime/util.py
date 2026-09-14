"""Filesystem, hashing, locking, and event-log utilities."""

from __future__ import annotations

import hashlib
import errno
import json
import os
import shutil
import socket
import tempfile
import uuid
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .errors import CONFLICT, IO_FAILURE, INVALID, KeepgoingError


SCHEMA_VERSION = 1
RECORD_DIRS = ("instructions", "plans", "sessions", "rates")
ACTIVE_DIRS = ("Project", "instructions", "plans", "sessions", "rates")


def now() -> datetime:
    return datetime.now().astimezone()


def iso_now() -> str:
    return now().isoformat(timespec="seconds")


def human_now() -> str:
    return now().strftime("%Y-%m-%d %H:%M")


def portable_now() -> str:
    return now().strftime("%Y-%m-%d_%H-%M-%S")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(data: str) -> str:
    return sha256_bytes(data.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def private_home() -> Path:
    configured = os.environ.get("KEEPGOING_PRIVATE_HOME")
    root = Path(configured).expanduser() if configured else Path.home() / ".keepgoing"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def workspace_key(root: Path) -> str:
    return sha256_text(str(root.resolve()).casefold())[:24]


def _write_staged(data: bytes, root: Path, suffix: str) -> Path:
    stage_dir = private_home() / "staging" / workspace_key(root)
    stage_dir.mkdir(parents=True, exist_ok=True)
    stage = stage_dir / f"{uuid.uuid4().hex}{suffix}"
    with stage.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return stage


def atomic_write_bytes(path: Path, data: bytes, workspace_root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = _write_staged(data, workspace_root, ".tmp")
    try:
        try:
            os.replace(stage, path)
        except OSError:
            sibling = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
            try:
                shutil.copyfile(stage, sibling)
                with sibling.open("rb+") as handle:
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(sibling, path)
            finally:
                sibling.unlink(missing_ok=True)
    except OSError as exc:
        raise KeepgoingError(
            f"Could not durably write {path}: {exc}", IO_FAILURE, "failure"
        ) from exc
    finally:
        stage.unlink(missing_ok=True)


def atomic_write_text(path: Path, data: str, workspace_root: Path) -> None:
    atomic_write_bytes(path, data.encode("utf-8"), workspace_root)


def atomic_write_json(path: Path, value: Any, workspace_root: Path) -> None:
    atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        workspace_root,
    )


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KeepgoingError(f"Invalid JSON at {path}: {exc}", INVALID) from exc
    if not isinstance(value, dict):
        raise KeepgoingError(f"Expected a JSON object at {path}", INVALID)
    return value


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def safe_path(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    if Path(relative).is_absolute() or ".." in Path(relative.replace("\\", "/")).parts:
        raise KeepgoingError(f"Unsafe path {relative!r}", INVALID)
    root_real = root.resolve()
    candidate = root / relative
    resolved = candidate.resolve(strict=must_exist)
    if not is_relative_to(resolved, root_real):
        raise KeepgoingError(f"Path escapes workspace: {relative}", INVALID)
    cursor = root_real
    for part in Path(relative).parts:
        cursor = cursor / part
        if cursor.exists() and cursor.is_symlink():
            target = cursor.resolve()
            if not is_relative_to(target, root_real):
                raise KeepgoingError(f"Symlink escapes workspace: {relative}", INVALID)
    return candidate


def path_inventory(root: Path) -> list[str]:
    result: list[str] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        relative = path.relative_to(root).as_posix()
        target = path.resolve()
        if not is_relative_to(target, root.resolve()):
            raise KeepgoingError(f"Escaping link or junction in workspace: {relative}", INVALID)
        result.append(path.relative_to(root).as_posix() + ("/" if path.is_dir() else ""))
    return result


def file_inventory(root: Path, *, include_records: bool = True) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not is_relative_to(path.resolve(), root.resolve()):
            relative = path.relative_to(root).as_posix()
            raise KeepgoingError(f"Escaping link or junction in workspace: {relative}", INVALID)
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if not include_records and relative.split("/", 1)[0] in RECORD_DIRS:
            continue
        result[relative] = sha256_file(path)
    return result


def case_collisions(root: Path) -> list[list[str]]:
    seen: dict[str, list[str]] = {}
    for relative in path_inventory(root):
        seen.setdefault(relative.casefold(), []).append(relative)
    return [values for values in seen.values() if len(set(values)) > 1]


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class WorkspaceLock(AbstractContextManager["WorkspaceLock"]):
    """Portable single-writer lock stored outside the governed workspace."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.path = private_home() / "locks" / workspace_key(self.root)
        self.owner_path = self.path / "owner.json"
        self.acquired = False

    def __enter__(self) -> "WorkspaceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.mkdir()
        except FileExistsError:
            owner: dict[str, Any] = {}
            try:
                owner = json.loads(self.owner_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                owner = {"status": "unreadable lock owner; manual inspection required"}
            same_host = owner.get("hostname") == socket.gethostname()
            try:
                owner_pid = int(owner.get("pid", -1))
            except (TypeError, ValueError):
                owner_pid = -1
            if same_host and not process_alive(owner_pid):
                shutil.rmtree(self.path)
                self.path.mkdir()
            else:
                raise KeepgoingError(
                    "Another writer owns this governed workspace",
                    CONFLICT,
                    "conflict",
                    {"owner": owner},
                )
        owner = {
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "workspace": str(self.root),
            "acquired_at": iso_now(),
        }
        self.owner_path.write_text(canonical_json(owner), encoding="utf-8")
        self.acquired = True
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.acquired:
            shutil.rmtree(self.path, ignore_errors=True)
            self.acquired = False


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = canonical_json(value) + "\n"
    try:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise KeepgoingError(f"Could not append {path}: {exc}", IO_FAILURE) from exc


def event_hash(event: dict[str, Any]) -> str:
    value = dict(event)
    value.pop("event_hash", None)
    return sha256_text(canonical_json(value))


def read_ledger(path: Path, *, tolerate_truncated: bool = False) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    issues: list[str] = []
    if not path.exists():
        return events, issues
    previous = ""
    seen_event_ids: set[str] = set()
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    for index, line in enumerate(lines, 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            message = f"Malformed ledger line {index}: {exc.msg}"
            if tolerate_truncated and index == len(lines):
                issues.append(message)
                break
            raise KeepgoingError(message, INVALID) from exc
        if not isinstance(event, dict) or event.get("schema_version") != SCHEMA_VERSION:
            issues.append(f"Unsupported or malformed ledger schema at line {index}")
            break
        required = ("sequence", "event_id", "transaction_id", "type", "payload", "event_hash")
        if any(key not in event for key in required) or not isinstance(event.get("payload"), dict):
            issues.append(f"Malformed ledger event at line {index}")
            break
        if event.get("sequence") != index or not isinstance(event.get("event_id"), str):
            issues.append(f"Ledger sequence anomaly at line {index}")
            break
        if event["event_id"] in seen_event_ids:
            issues.append(f"Duplicate ledger event ID at line {index}")
            break
        if event.get("previous_event_hash", "") != previous:
            issues.append(f"Ledger hash-chain mismatch at line {index}")
            break
        calculated = event_hash(event)
        if event.get("event_hash") != calculated:
            issues.append(f"Ledger event hash mismatch at line {index}")
            break
        events.append(event)
        seen_event_ids.add(event["event_id"])
        previous = calculated
    return events, issues


def new_event(
    *,
    sequence: int,
    transaction_id: str,
    event_type: str,
    payload: dict[str, Any],
    previous_hash: str,
) -> dict[str, Any]:
    event = {
        "schema_version": SCHEMA_VERSION,
        "sequence": sequence,
        "event_id": f"EVENT-{sequence:06d}",
        "transaction_id": transaction_id,
        "occurred_at": iso_now(),
        "actor": "keepgoing-runtime",
        "type": event_type,
        "payload": payload,
        "previous_event_hash": previous_hash,
    }
    event["event_hash"] = event_hash(event)
    return event


def ensure_unique_archive(parent: Path, stamp: str | None = None) -> Path:
    base = str(stamp or portable_now())
    candidate_name = Path(base)
    if (
        not base
        or candidate_name.is_absolute()
        or len(candidate_name.parts) != 1
        or base in {".", ".."}
    ):
        raise KeepgoingError("Archive stamp must be a single relative directory name", INVALID)
    candidate = parent / base
    suffix = 1
    while candidate.exists():
        candidate = parent / f"{base}-{suffix}"
        suffix += 1
    return candidate


def copy_verified(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target, symlinks=True)
        before = file_inventory(source)
        after = file_inventory(target)
        if before != after:
            raise KeepgoingError(f"Copy verification failed for {source}", IO_FAILURE)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)
        if sha256_file(source) != sha256_file(target):
            raise KeepgoingError(f"Copy verification failed for {source}", IO_FAILURE)


def move_verified(source: Path, target: Path) -> str:
    """Rename when possible; use a verified copy-then-remove across filesystems."""

    if target.exists() or target.is_symlink():
        raise KeepgoingError(f"Move target already exists: {target}", CONFLICT)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(source, target)
        return "rename"
    except OSError as exc:
        if exc.errno != errno.EXDEV and getattr(exc, "winerror", None) != 17:
            raise KeepgoingError(f"Could not move {source} to {target}: {exc}", IO_FAILURE) from exc
    copy_verified(source, target)
    try:
        if source.is_dir() and not source.is_symlink():
            shutil.rmtree(source)
        else:
            source.unlink()
    except OSError as exc:
        raise KeepgoingError(
            f"Verified cross-filesystem copy exists at {target}, but source cleanup failed: {exc}",
            IO_FAILURE,
        ) from exc
    return "verified-copy"


def relative_files(paths: Iterable[str]) -> list[str]:
    return sorted({Path(value.replace("\\", "/")).as_posix() for value in paths})
