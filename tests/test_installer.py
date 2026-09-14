from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def test_cross_agent_install_survives_source_removal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="keepgoing-installer-") as temp:
            temp_root = Path(temp)
            source = temp_root / "disposable-source"
            shutil.copytree(REPO_ROOT, source, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            home = temp_root / "fake-home"
            command = [
                sys.executable,
                str(source / "scripts" / "install.py"),
                "--source",
                str(source),
                "--home",
                str(home),
                "--agents",
                "all",
                "--verify",
            ]
            process = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
            result = json.loads(process.stdout)
            self.assertTrue(result["verification"]["verified"])
            self.assertTrue(result["temporary_source_safe_to_delete"])
            for skill in ("keepgoing", "keepfixing"):
                self.assertTrue((home / ".agents" / "skills" / skill / "SKILL.md").is_file())
                self.assertTrue((home / ".claude" / "skills" / skill / "SKILL.md").is_file())
            shutil.rmtree(source)
            wrapper = home / ".agents" / "skills" / "keepfixing" / "scripts" / "keepfixing.py"
            help_run = subprocess.run(
                [sys.executable, str(wrapper), "--help"], capture_output=True, text=True, check=False
            )
            self.assertEqual(help_run.returncode, 0, help_run.stderr)
            self.assertIn("strict", help_run.stdout.lower())

    def test_existing_checkout_links_are_replaced_before_safe_delete_claim(self) -> None:
        with tempfile.TemporaryDirectory(prefix="keepgoing-installer-links-") as temp:
            temp_root = Path(temp)
            source = temp_root / "disposable-source"
            shutil.copytree(REPO_ROOT, source, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            home = temp_root / "fake-home"

            def link_directory(link: Path, target: Path) -> None:
                link.parent.mkdir(parents=True, exist_ok=True)
                try:
                    link.symlink_to(target, target_is_directory=True)
                except OSError:
                    process = subprocess.run(
                        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if process.returncode != 0:
                        self.skipTest("Host permits neither symlinks nor directory junctions")

            for skill in ("keepgoing", "keepfixing"):
                link_directory(home / ".agents" / "skills" / skill, source / "skills" / skill)
                link_directory(home / ".claude" / "skills" / skill, source / "skills" / skill)
            process = subprocess.run(
                [
                    sys.executable,
                    str(source / "scripts" / "install.py"),
                    "--source",
                    str(source),
                    "--home",
                    str(home),
                    "--agents",
                    "all",
                    "--verify",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
            result = json.loads(process.stdout)
            self.assertTrue(result["temporary_source_safe_to_delete"])
            for skill in ("keepgoing", "keepfixing"):
                canonical = home / ".agents" / "skills" / skill
                is_junction = getattr(canonical, "is_junction", lambda: False)()
                self.assertFalse(canonical.is_symlink() or is_junction)
            shutil.rmtree(source)
            wrapper = home / ".agents" / "skills" / "keepfixing" / "scripts" / "keepfixing.py"
            help_run = subprocess.run(
                [sys.executable, str(wrapper), "--help"], capture_output=True, text=True, check=False
            )
            self.assertEqual(help_run.returncode, 0, help_run.stderr)

    def test_dry_run_does_not_create_home(self) -> None:
        with tempfile.TemporaryDirectory(prefix="keepgoing-installer-preview-") as temp:
            home = Path(temp) / "future-home"
            process = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "install.py"),
                    "--source",
                    str(REPO_ROOT),
                    "--home",
                    str(home),
                    "--agents",
                    "all",
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertFalse(home.exists())


if __name__ == "__main__":
    unittest.main()
