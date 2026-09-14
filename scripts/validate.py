#!/usr/bin/env python3
"""Run repository compile, skill-shape, JSON, installer, and behavioral validation."""

from __future__ import annotations

import compileall
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = (ROOT / "skills" / "keepgoing", ROOT / "skills" / "keepfixing")


def validate_skill(path: Path) -> list[str]:
    issues: list[str] = []
    entrypoint = path / "SKILL.md"
    if not entrypoint.is_file():
        return [f"Missing skill entrypoint: {entrypoint}"]
    text = entrypoint.read_text(encoding="utf-8")
    lines = text.splitlines()
    if len(lines) < 5 or lines[0] != "---":
        issues.append(f"Invalid frontmatter opening: {entrypoint}")
        return issues
    try:
        end = lines.index("---", 1)
    except ValueError:
        issues.append(f"Invalid frontmatter closing: {entrypoint}")
        return issues
    frontmatter = lines[1:end]
    fields = {
        line.split(":", 1)[0].strip(): line.split(":", 1)[1].strip()
        for line in frontmatter
        if ":" in line and not line.startswith(" ")
    }
    if fields.get("name") != path.name:
        issues.append(f"Skill name does not match folder: {entrypoint}")
    if not fields.get("description"):
        issues.append(f"Skill description is missing: {entrypoint}")
    for reference in path.rglob("*.md"):
        body = reference.read_text(encoding="utf-8")
        forbidden_phrases = (
            "rest of " + "code unchanged",
            "your " + "logic here",
            "implement " + "later",
        )
        for forbidden in forbidden_phrases:
            if forbidden in body.lower():
                issues.append(f"Unfinished scaffold phrase in {reference}: {forbidden}")
    return issues


def run() -> int:
    issues: list[str] = []
    checks: list[dict[str, object]] = []
    compiled = compileall.compile_dir(str(ROOT / "skills"), quiet=1)
    compiled = compileall.compile_dir(str(ROOT / "scripts"), quiet=1) and compiled
    compiled = compileall.compile_dir(str(ROOT / "demo"), quiet=1) and compiled
    checks.append({"name": "compileall", "passed": compiled})
    if not compiled:
        issues.append("Python compilation failed")
    for skill in SKILLS:
        skill_issues = validate_skill(skill)
        checks.append({"name": f"skill-shape:{skill.name}", "passed": not skill_issues})
        issues.extend(skill_issues)
    for path in ROOT.rglob("*.json"):
        if ".Codex/ghl-state.json" in path.as_posix():
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            issues.append(f"Invalid JSON {path.relative_to(ROOT)}: {exc}")
    checks.append({"name": "json", "passed": not any(item.startswith("Invalid JSON") for item in issues)})
    with tempfile.TemporaryDirectory(prefix="keepgoing-validation-") as temporary:
        installer = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "install.py"),
                "--source",
                str(ROOT),
                "--home",
                str(Path(temporary) / "home"),
                "--agents",
                "all",
                "--verify",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        checks.append({"name": "isolated-install", "passed": installer.returncode == 0})
        if installer.returncode:
            issues.append("Isolated installer failed: " + (installer.stderr or installer.stdout).strip())
    demo = subprocess.run(
        [sys.executable, str(ROOT / "demo" / "run_demo.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    checks.append({"name": "isolated-demo", "passed": demo.returncode == 0})
    if demo.returncode:
        issues.append("Isolated demo failed: " + (demo.stderr or demo.stdout).strip())
    tests = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        check=False,
    )
    checks.append({"name": "behavioral-tests", "passed": tests.returncode == 0})
    if tests.returncode:
        issues.append("Behavioral tests failed; inspect the streamed unittest output above.")
    result = {"result": "success" if not issues else "failure", "checks": checks, "issues": issues}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(run())
