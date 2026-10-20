from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Mapping, Optional, Tuple


class SkillInstallError(RuntimeError):
    """Raised when the bundled Codex skill cannot be installed safely."""


def codex_skill_path(
    *,
    destination: Optional[str] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> Path:
    """Return the destination directory for the user-level jk Codex skill."""
    if destination:
        return Path(destination).expanduser()

    environment = os.environ if environ is None else environ
    codex_home = environment.get("CODEX_HOME")
    base = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
    return base / "skills" / "jk"


def _bundled_skill() -> Path:
    return Path(__file__).resolve().parent / "resources" / "codex_skill"


def _resource_files(root, prefix: str = ""):
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        relative = f"{prefix}/{child.name}" if prefix else child.name
        if child.is_dir():
            yield from _resource_files(child, relative)
        else:
            yield relative, child.read_bytes()


def _installed_files(root: Path):
    if not root.is_dir():
        return None
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _copy_bundled_skill(destination: Path) -> None:
    for relative, content in _resource_files(_bundled_skill()):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def install_codex_skill(
    *,
    destination: Optional[str] = None,
    force: bool = False,
    environ: Optional[Mapping[str, str]] = None,
) -> Tuple[Path, bool]:
    """Install the bundled skill and return ``(path, changed)``."""
    target = codex_skill_path(destination=destination, environ=environ)
    bundled = dict(_resource_files(_bundled_skill()))
    installed = _installed_files(target)

    if installed == bundled:
        return target, False
    if (target.exists() or target.is_symlink()) and not force:
        raise SkillInstallError(
            f"Codex skill already exists and differs: {target}. "
            "Re-run with --force to replace it."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=".jk-skill-", dir=str(target.parent)))
    staged = staging_root / "jk"
    backup = staging_root / "previous"
    try:
        _copy_bundled_skill(staged)
        if target.exists() or target.is_symlink():
            target.rename(backup)
        try:
            staged.rename(target)
        except Exception:
            if backup.exists() or backup.is_symlink():
                backup.rename(target)
            raise
        if backup.exists() or backup.is_symlink():
            if backup.is_dir() and not backup.is_symlink():
                shutil.rmtree(backup)
            else:
                backup.unlink()
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)

    return target, True
