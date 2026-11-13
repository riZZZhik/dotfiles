"""Coordinate selected application sync and its launch agent."""

from __future__ import annotations

import fcntl
import os
import plistlib
import subprocess
import sys
from pathlib import Path

from ..config import copy_settings_enabled, path
from .base import STATE, SYNC, App
from .base import write_if_changed as write_if_changed
from .codex import Codex as Codex
from .iterm import ITerm as ITerm
from .vscode import VSCode as VSCode

APPLICATIONS: dict[str, type[App]] = {"vscode": VSCode, "iterm": ITerm, "codex": Codex}


def sync_apps(
    root: Path,
    apps: tuple[str, ...],
    *,
    register_agent: bool = True,
    initialize: tuple[str, ...] = (),
):
    copy = copy_settings_enabled(root)
    enabled = SYNC.get("enabled", True)
    to_copy = initialize if copy else ()
    active = tuple(dict.fromkeys((*to_copy, *(apps if enabled else ()))))
    if not active:
        if register_agent:
            install_agent(root, ())
        return
    STATE.mkdir(parents=True, exist_ok=True)
    failures = []
    with (STATE / "sync.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for name in active:
            try:
                adapter = APPLICATIONS[name]()
                if name in to_copy:
                    adapter.install()
                elif not copy:
                    adapter.install(copy_settings=False)
                if enabled and name in apps:
                    adapter.sync()
            except Exception as error:  # noqa: BLE001 — isolate failures at the application boundary.
                failures.append(f"{name}: {error}")
    if register_agent:
        install_agent(root, apps)
    if failures:
        raise RuntimeError("\n".join(failures))


def install_agent(root: Path, apps: tuple[str, ...]):
    config = SYNC
    agent = path(config["agent"])
    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{config['label']}"
    if not apps or not config.get("enabled", True):
        if agent.exists():
            existing = plistlib.loads(agent.read_bytes())
            if (
                existing.get("Label") != config["label"]
                or Path(existing.get("WorkingDirectory", "")).resolve() != root.resolve()
            ):
                raise RuntimeError("Refusing to disable a sync agent owned by another checkout.")
            subprocess.run(["launchctl", "bootout", service], capture_output=True, check=False)
            agent.unlink()
        return
    watch = [
        root / "install",
        root / "src/system.sh",
        *sorted((root / "src").rglob("*.py")),
        root / "config/setup.yaml",
    ]
    for name in apps:
        watch.extend(APPLICATIONS[name]().WATCH_PATHS)
    content = plistlib.dumps(
        {
            "Label": config["label"],
            "ProgramArguments": [sys.executable, "-m", "src.cli", "sync"],
            "WorkingDirectory": str(root),
            "WatchPaths": [str(path) for path in watch],
            "StartInterval": config["interval_seconds"],
            "RunAtLoad": config["run_at_load"],
            "StandardErrorPath": str(STATE / "sync.log"),
        }
    )
    if agent.exists() and agent.read_bytes() == content:
        loaded = subprocess.run(["launchctl", "print", service], capture_output=True, check=False)
        if loaded.returncode == 0:
            return
    agent.parent.mkdir(parents=True, exist_ok=True)
    (STATE / "sync.log").touch(mode=0o600, exist_ok=True)
    subprocess.run(["launchctl", "bootout", service], capture_output=True, check=False)
    agent.write_bytes(content)
    subprocess.run(["launchctl", "bootstrap", domain, str(agent)], check=True)
