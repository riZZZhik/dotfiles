"""Remove dotfiles automation and materialize repository-backed home links."""

from __future__ import annotations

import fcntl
import os
import plistlib
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from .apps.base import STATE, SYNC
from .config import load_catalog, path


def owned(target: Path, roots: tuple[Path, ...]) -> bool:
    direct = (
        Path(os.path.abspath(target.parent / os.readlink(target)))
        if target.is_symlink()
        else target
    )
    return any(
        direct.is_relative_to(root) or target.resolve().is_relative_to(root) for root in roots
    )


def links(root: Path, private: Path, home: Path) -> list[Path]:
    roots = (root.resolve(), private.resolve())
    found = set()

    def visit(source, destination, scan=False):
        if destination.is_symlink():
            if owned(destination, roots):
                found.add(destination)
        elif destination.is_dir() and scan:
            for child in destination.iterdir():
                visit(source / child.name, child, True)

    # Scan managed home subtrees, including generated files and orphaned links,
    # without traversing unrelated directories such as Library or Documents.
    for repository in roots:
        source = repository / "home"
        names = {entry.name for entry in source.iterdir()} if source.is_dir() else set()
        names.update(entry.name for entry in home.iterdir() if entry.is_symlink())
        for name in names:
            entry = source / name
            visit(entry, home / name, entry.is_dir() and not entry.is_symlink())
    for stage in load_catalog(root):
        for configuration in stage.configuration:
            if configuration.destination:
                visit(root / configuration.source, home / configuration.destination)
    return sorted(found)


def tree(source: Path, roots: tuple[Path, ...], relative=Path(), ancestors=frozenset()):
    if source.is_symlink():
        if not owned(source, roots):
            yield relative, source, "link"
            return
        source = source.resolve(strict=True)
    mode = source.stat().st_mode
    if stat.S_ISREG(mode):
        yield relative, source, "file"
    elif stat.S_ISDIR(mode):
        identity = (source.stat().st_dev, source.stat().st_ino)
        if identity in ancestors:
            raise ValueError(f"Directory cycle: {source}")
        yield relative, source, "directory"
        for child in source.iterdir():
            yield from tree(child, roots, relative / child.name, ancestors | {identity})
    else:
        raise ValueError(
            f"Cannot copy special file: {source}. Close its owning app/connection and retry."
        )


def stamp(source: Path):
    value = source.lstat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def replace_link(link: Path, roots: tuple[Path, ...]) -> None:
    original = os.readlink(link)
    original_stamp = stamp(link)
    source = link.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix=".dotfiles-detach-", dir=link.parent) as directory:
        payload = Path(directory) / "copy"
        observed = []
        directories = []
        for relative, entry, kind in tree(source, roots):
            destination = payload / relative
            observed.append((entry, stamp(entry)))
            if kind == "directory":
                destination.mkdir(mode=0o700)
                directories.append((entry, destination))
            elif kind == "link":
                # Relative links inside a moved directory must retain their original target.
                destination.symlink_to(entry.resolve(strict=False))
            else:
                shutil.copy2(entry, destination)
        for entry, previous in observed:
            if stamp(entry) != previous:
                raise RuntimeError(
                    f"Source changed while copying: {entry}; retry after edits finish."
                )
        for entry, destination in reversed(directories):
            shutil.copystat(entry, destination)
        if stamp(link) != original_stamp or os.readlink(link) != original:
            raise RuntimeError(f"Link changed while copying: {link}; retry after edits finish.")
        if payload.is_dir():
            # POSIX rename cannot replace a symlink with a directory. Copy first, then
            # restore the original link if the final directory rename fails.
            link.unlink()
            try:
                payload.rename(link)
            except OSError:
                if not link.exists() and not link.is_symlink():
                    link.symlink_to(original, target_is_directory=True)
                raise
        else:
            os.replace(payload, link)


def detach(root: Path, private: Path | None = None) -> None:
    home = Path.home()
    private = home / ".dotfiles_secret" if private is None else private
    roots = (root.resolve(), private.resolve())
    candidates = links(root, private, home)
    errors = []
    for link in candidates:
        try:
            for _ in tree(link.resolve(strict=True), roots):
                pass
        except (OSError, ValueError, RuntimeError) as error:
            errors.append(f"{link}: {error}")
    agent = path(SYNC["agent"])
    original = agent.read_bytes() if agent.exists() else None
    if original is not None:
        document = plistlib.loads(original)
        if (
            document.get("Label") != SYNC["label"]
            or Path(document.get("WorkingDirectory", "")).resolve() != root.resolve()
        ):
            errors.append(f"Refusing to remove an unrelated LaunchAgent: {agent}")
    if errors:
        raise RuntimeError("Detach preflight failed; nothing changed:\n" + "\n".join(errors))

    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / "sync.lock").open("a") as lock:
        # Let an in-flight sync finish before unloading it; reuse the sync owner's lock.
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (agent.read_bytes() if agent.exists() else None) != original:
            raise RuntimeError("LaunchAgent changed during preflight; retry.")
        service = f"gui/{os.getuid()}/{SYNC['label']}"
        loaded = subprocess.run(["launchctl", "print", service], capture_output=True, check=False)
        if loaded.returncode == 0:
            subprocess.run(["launchctl", "bootout", service], check=True)
        agent.unlink(missing_ok=True)
        for link in candidates:
            replace_link(link, roots)
    print(f"Removed dotfiles sync automation; replaced {len(candidates)} links with local copies.")
