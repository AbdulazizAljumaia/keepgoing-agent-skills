#!/usr/bin/env python3
"""Install keepgoing and keepfixing for multiple coding-agent hosts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any


SKILLS = ("keepgoing", "keepfixing")
DISCOVERY = {
    "codex": "Loads the canonical ~/.agents/skills root.",
    "opencode": "Loads the canonical ~/.agents/skills root.",
    "grok": "Loads the canonical ~/.agents/skills root.",
    "claude": "Uses ~/.claude/skills links to the canonical root.",
}


def is_linklike(path: Path) -> bool:
    """Detect symbolic links and Windows directory junction/reparse points."""

    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & 0x400)


def hash_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def source_commit(repo: Path) -> str | None:
    try:
        process = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return process.stdout.strip() or None


def remove_link_or_tree(path: Path) -> None:
    if is_linklike(path):
        if path.is_dir() and not path.is_symlink():
            os.rmdir(path)
        else:
            path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def install_canonical(
    source: Path, destination: Path, *, dry_run: bool, force: bool
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source": str(source),
        "destination": str(destination),
        "mode": "copy",
    }
    if dry_run:
        result["planned"] = True
        return result
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = destination.parent / f".{destination.name}.install-{uuid.uuid4().hex}"
    backup = destination.parent / f".{destination.name}.backup-{uuid.uuid4().hex}"
    shutil.copytree(source, stage, symlinks=False)
    expected = hash_tree(source)
    if hash_tree(stage) != expected:
        shutil.rmtree(stage, ignore_errors=True)
        raise RuntimeError(f"Staged skill hash mismatch for {source.name}")
    had_existing = destination.exists() or destination.is_symlink()
    if had_existing and not force:
        if is_linklike(destination):
            try:
                same_content = hash_tree(destination.resolve(strict=True)) == expected
            except OSError:
                same_content = False
            if not same_content:
                shutil.rmtree(stage, ignore_errors=True)
                raise RuntimeError(
                    f"Canonical destination is an unsafe link with different or missing content: {destination}; rerun with --force after review"
                )
        if destination.is_dir() and hash_tree(destination.resolve()) == expected:
            if not is_linklike(destination):
                shutil.rmtree(stage, ignore_errors=True)
                result.update({"installed": True, "idempotent": True, "sha256": expected})
                return result
        elif not is_linklike(destination):
            shutil.rmtree(stage, ignore_errors=True)
            raise RuntimeError(
                f"Destination exists with different content: {destination}; rerun with --force after review"
            )
    if had_existing:
        os.replace(destination, backup)
    try:
        os.replace(stage, destination)
        if hash_tree(destination) != expected:
            raise RuntimeError(f"Installed skill hash mismatch for {destination}")
    except Exception:
        remove_link_or_tree(destination)
        if backup.exists() or backup.is_symlink():
            os.replace(backup, destination)
        raise
    remove_link_or_tree(backup)
    result.update({"installed": True, "idempotent": False, "sha256": expected})
    return result


def expose(destination: Path, canonical: Path, *, dry_run: bool, force: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "destination": str(destination),
        "canonical": str(canonical),
    }
    if destination.resolve(strict=False) == canonical.resolve(strict=False):
        result.update({"installed": True, "mode": "canonical"})
        return result
    if dry_run:
        result.update({"planned": True, "mode": "link-or-verified-copy"})
        return result
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        if is_linklike(destination):
            try:
                resolved = destination.resolve(strict=True)
                same_content = hash_tree(resolved) == hash_tree(canonical)
            except OSError:
                resolved = None
                same_content = False
            if resolved == canonical.resolve() and same_content:
                result.update({"installed": True, "idempotent": True, "mode": "symlink"})
                return result
            if same_content:
                remove_link_or_tree(destination)
            elif not force:
                raise RuntimeError(
                    f"Provider destination is an unsafe link with different or missing content: {destination}; use --force after review"
                )
            else:
                remove_link_or_tree(destination)
        elif destination.is_dir() and hash_tree(destination.resolve()) == hash_tree(canonical):
            result.update({"installed": True, "idempotent": True, "mode": "verified-copy"})
            return result
        elif not force:
            raise RuntimeError(
                f"Provider destination exists with different content: {destination}; use --force after review"
            )
        else:
            remove_link_or_tree(destination)
    try:
        destination.symlink_to(canonical, target_is_directory=True)
        mode = "symlink"
    except OSError:
        shutil.copytree(canonical, destination)
        if hash_tree(destination) != hash_tree(canonical):
            remove_link_or_tree(destination)
            raise RuntimeError(f"Provider copy verification failed: {destination}")
        mode = "verified-copy"
    result.update({"installed": True, "idempotent": False, "mode": mode})
    return result


def verify_install(home: Path, extra_roots: list[Path]) -> dict[str, Any]:
    canonical_root = home / ".agents" / "skills"
    issues: list[str] = []
    hashes: dict[str, str] = {}
    for skill in SKILLS:
        path = canonical_root / skill
        if not (path / "SKILL.md").is_file():
            issues.append(f"Missing canonical skill: {path}")
            continue
        if is_linklike(path):
            issues.append(f"Canonical skill depends on a link instead of a durable copy: {path}")
            continue
        hashes[skill] = hash_tree(path)
        if skill == "keepgoing" and not (
            path / "scripts" / "keepgoing_runtime" / "cli.py"
        ).is_file():
            issues.append("Canonical keepgoing runtime is missing")
        if skill == "keepfixing":
            sibling = path.parent / "keepgoing" / "scripts" / "keepgoing_runtime" / "cli.py"
            if not sibling.is_file():
                issues.append("keepfixing cannot resolve the sibling keepgoing runtime")
    roots = [home / ".claude" / "skills", *extra_roots]
    for root in roots:
        for skill in SKILLS:
            target = root / skill
            if target.exists() or target.is_symlink():
                if not (target / "SKILL.md").is_file():
                    issues.append(f"Broken provider skill: {target}")
                elif is_linklike(target) and target.resolve() != (canonical_root / skill).resolve():
                    issues.append(f"Provider skill link does not target the durable canonical copy: {target}")
                elif skill in hashes and hash_tree(target.resolve()) != hashes[skill]:
                    issues.append(f"Provider skill differs from canonical source: {target}")
    return {"verified": not issues, "issues": issues, "hashes": hashes}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--home", default=str(Path.home()))
    parser.add_argument(
        "--agents",
        default="all",
        help="Comma-separated detected hosts: all, codex, claude, opencode, grok",
    )
    parser.add_argument("--skill-root", action="append", default=[], help="Additional provider skill root")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--verify", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source_root = Path(args.source).expanduser().resolve()
    home = Path(args.home).expanduser().resolve()
    skill_source = source_root / "skills"
    selected = {item.strip().lower() for item in args.agents.split(",") if item.strip()}
    if "all" in selected:
        selected = set(DISCOVERY)
    unknown = selected - set(DISCOVERY)
    if unknown:
        print(json.dumps({"result": "failure", "issues": [f"Unknown agents: {sorted(unknown)}"]}, indent=2))
        return 2
    for skill in SKILLS:
        if not (skill_source / skill / "SKILL.md").is_file():
            print(json.dumps({"result": "failure", "issues": [f"Source skill missing: {skill}"]}, indent=2))
            return 2
    canonical_root = home / ".agents" / "skills"
    extra_roots = [Path(value).expanduser().resolve() for value in args.skill_root]
    operations: list[dict[str, Any]] = []
    try:
        for skill in SKILLS:
            operations.append(
                install_canonical(
                    skill_source / skill,
                    canonical_root / skill,
                    dry_run=args.dry_run,
                    force=args.force,
                )
            )
        provider_roots: list[Path] = []
        if "claude" in selected:
            provider_roots.append(home / ".claude" / "skills")
        provider_roots.extend(extra_roots)
        for provider_root in provider_roots:
            for skill in SKILLS:
                operations.append(
                    expose(
                        provider_root / skill,
                        canonical_root / skill,
                        dry_run=args.dry_run,
                        force=args.force,
                    )
                )
        manifest = {
            "schema_version": 1,
            "source": str(source_root),
            "source_commit": source_commit(source_root),
            "skills": list(SKILLS),
            "selected_agents": sorted(selected),
            "discovery": {key: DISCOVERY[key] for key in sorted(selected)},
            "operations": operations,
        }
        if not args.dry_run:
            canonical_root.mkdir(parents=True, exist_ok=True)
            (canonical_root / ".keepgoing-install.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        verification = verify_install(home, extra_roots) if args.verify and not args.dry_run else None
        result = {
            "result": "success" if verification is None or verification["verified"] else "failure",
            "canonical_root": str(canonical_root),
            "temporary_source_safe_to_delete": bool(verification and verification["verified"]),
            "manifest": manifest,
            "verification": verification,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["result"] == "success" else 1
    except (OSError, RuntimeError) as exc:
        print(
            json.dumps(
                {"result": "failure", "canonical_root": str(canonical_root), "message": str(exc)},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
