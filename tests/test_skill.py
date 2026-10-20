import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from jupyter_kernel_client.cli import main
from jupyter_kernel_client.skill import (
    SkillInstallError,
    codex_skill_path,
    install_codex_skill,
)


class CodexSkillInstallerTests(unittest.TestCase):
    def test_user_path_honors_codex_home(self):
        self.assertEqual(
            codex_skill_path(environ={"CODEX_HOME": "/tmp/example-codex"}),
            Path("/tmp/example-codex/skills/jk"),
        )

    def test_install_is_repeatable_and_contains_valid_entrypoint(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "jk"

            path, changed = install_codex_skill(destination=str(destination))
            self.assertEqual(path, destination)
            self.assertTrue(changed)
            self.assertIn("name: jk", (destination / "SKILL.md").read_text())
            self.assertTrue((destination / "agents" / "openai.yaml").is_file())

            _, changed = install_codex_skill(destination=str(destination))
            self.assertFalse(changed)

    def test_changed_install_requires_force(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "jk"
            install_codex_skill(destination=str(destination))
            (destination / "SKILL.md").write_text("locally changed\n")
            (destination / "extra.txt").write_text("keep unless forced\n")

            with self.assertRaises(SkillInstallError):
                install_codex_skill(destination=str(destination))
            self.assertEqual((destination / "SKILL.md").read_text(), "locally changed\n")

            _, changed = install_codex_skill(destination=str(destination), force=True)
            self.assertTrue(changed)
            self.assertIn("name: jk", (destination / "SKILL.md").read_text())
            self.assertFalse((destination / "extra.txt").exists())

    def test_cli_reports_changed_install_without_overwriting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "jk"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["skill", "install", "--dest", str(destination)]), 0)
            (destination / "SKILL.md").write_text("locally changed\n")

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                result = main(["skill", "install", "--dest", str(destination)])

            self.assertEqual(result, 2)
            self.assertIn("Skill install error:", stderr.getvalue())
            self.assertEqual((destination / "SKILL.md").read_text(), "locally changed\n")

    def test_failed_replacement_restores_existing_install(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "jk"
            install_codex_skill(destination=str(destination))
            (destination / "SKILL.md").write_text("locally changed\n")
            rename = Path.rename

            def fail_staged_rename(path, target):
                if path.name == "jk" and path.parent.name.startswith(".jk-skill-"):
                    raise OSError("replacement failed")
                return rename(path, target)

            with patch.object(Path, "rename", fail_staged_rename):
                with self.assertRaisesRegex(OSError, "replacement failed"):
                    install_codex_skill(destination=str(destination), force=True)

            self.assertEqual((destination / "SKILL.md").read_text(), "locally changed\n")
            self.assertEqual(list(Path(directory).iterdir()), [destination])


if __name__ == "__main__":
    unittest.main()
