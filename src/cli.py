"""Install configured stages, link dotfiles and apply settings."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import apps
from .config import (
    COPY_NAMES,
    ROOT,
    Stage,
    collect_apps,
    collect_copy_settings,
    collect_packages,
    load,
    load_catalog,
    path,
)
from .detach import detach


def run_shell(name, *args, **kwargs):
    return subprocess.run(
        ["bash", str(ROOT / "src/system.sh"), "--" + name, *map(str, args)],
        check=True,
        **kwargs,
    )


def link(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and source.exists() and destination.samefile(source):
        return
    preserve(destination)
    destination.symlink_to(source, target_is_directory=source.is_dir())


def preserve(destination):
    if destination.exists() or destination.is_symlink():
        backup = (
            Path(tempfile.mkdtemp(prefix="dotfiles-backup-", dir=Path.home())) / destination.name
        )
        shutil.move(str(destination), backup)
        print(f"Preserved {destination} at {backup}")


def link_home(source, destination):
    if not source.is_dir() or source.is_symlink():
        link(source, destination)
        return
    if destination.is_symlink():
        existing = destination.resolve()
        preserve(destination)
        destination.mkdir(parents=True)
        if existing.is_dir():
            link_home(existing, destination)
    elif destination.exists() and not destination.is_dir():
        preserve(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        link_home(entry, destination / entry.name)


def check_sources(root: Path, stages: tuple[Stage, ...]):
    if "home" in collect_copy_settings(root) and not (root / "home").is_dir():
        raise RuntimeError("Restore the repository home/ directory before applying dotfiles.")
    for stage in stages:
        for config in stage.configuration:
            if not (root / config.source).exists():
                raise RuntimeError(f"Restore missing selected configuration first: {config.source}")


def apply(
    root: Path,
    stages: tuple[Stage, ...],
    command="apply",
):
    copies = collect_copy_settings(root)
    preset_stages = []
    for stage in stages:
        name = stage.id.removeprefix("setup-")
        if (name if name in COPY_NAMES else "home") in copies:
            preset_stages.append(stage)
    check_sources(root, tuple(preset_stages))
    if "home" in copies:
        link_home(root / "home", Path.home())
    for stage in stages:
        print(f"Stage: {stage.title}")
        if command in {"install", "update"} and stage.packages:
            selected = collect_packages((stage,))
            with tempfile.NamedTemporaryFile(mode="w", suffix=".Brewfile") as temporary:
                temporary.write("\n".join(p.brew_line() for p in selected) + "\n")
                temporary.flush()
                run_shell("packages", command, temporary.name)
        for config in stage.configuration if stage in preset_stages else ():
            if not config.destination:
                continue
            source, destination = root / config.source, Path.home() / config.destination
            if config.mode == "seed":
                if not destination.exists() and not destination.is_symlink():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
            else:
                link(source, destination)
        for extra in stage.actions:
            scope = {
                "shell-plugins": "home",
                "sudo-touch-id": "macos",
                "macos-defaults": "macos",
                "vscode-associations": "vscode",
            }[extra]
            if scope not in copies:
                continue
            if extra == "shell-plugins":
                run_shell("packages", "plugins", "update" if command == "update" else "install")
            elif extra == "sudo-touch-id" and command == "install":
                touch_id = load("macos")["touch_id"]
                if touch_id["enabled"]:
                    run_shell("touch-id", path(touch_id["path"]), path(touch_id["template"]))
            elif extra == "macos-defaults" and command == "install":
                macos_preferences()
            elif extra == "vscode-associations" and command == "install":
                for association in load("vscode")["file_associations"]:
                    subprocess.run(shlex.split(association), check=True)
    initialize = (
        tuple(name for name in copies if name in apps.APPLICATIONS) if command == "install" else ()
    )
    apps.sync_apps(root, collect_apps(root), initialize=initialize)


def macos_preferences():
    settings = load("macos")
    subprocess.run(["osascript", "-e", 'tell application "System Preferences" to quit'], check=True)
    for command in settings["defaults"]:
        subprocess.run(shlex.split(command), check=True)
    for name in settings["restart"]:
        subprocess.run(["killall", name], capture_output=True, check=False)


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(prog="./install", description=__doc__)
    parser.add_argument(
        "command",
        choices=["install", "apply", "update", "sync", "cleanup", "link", "fork", "detach"],
        nargs="?",
        default="install",
    )
    parser.add_argument("source", nargs="?", type=Path, help="Repository home directory to link")
    args = parser.parse_args(argv)
    if sys.platform != "darwin":
        parser.error("This installer supports macOS only.")
    os.environ["PATH"] = (
        f"{Path.home() / '.local/bin'}:/opt/homebrew/bin:/usr/local/bin:"
        + os.environ.get("PATH", "")
    )
    command = args.command
    if command == "link":
        if args.source is None or not args.source.is_dir():
            parser.error("link requires an existing repository home directory")
        source = args.source.resolve()
        home = Path.home()
        if home.resolve().is_relative_to(source):
            parser.error("the source must not contain your home directory")
        link_home(source, home)
        for entry in home.iterdir():
            if (
                entry.is_symlink()
                and not entry.exists()
                and entry.resolve().is_relative_to(source.parent)
            ):
                entry.unlink()
        print("Dotfiles linked.")
        return
    if args.source is not None:
        parser.error("a source directory is only valid with link")
    if command == "detach":
        detach(root)
        return
    if command == "cleanup":
        run_shell("packages", "cleanup")
        print("Package caches cleaned.")
        return
    if command == "update" and not os.environ.get("DOTFILES_AFTER_PULL"):
        os.execv("/bin/bash", ["bash", str(ROOT / "src/system.sh"), "--update", str(root)])
        return

    if command == "fork":
        run_shell("fork", cwd=root)
        return
    stages = load_catalog(root)
    if command == "sync":
        apps.sync_apps(
            root,
            collect_apps(root),
            register_agent=False,
        )
        return
    apply(root, stages, command=command)
    print("Dotfiles applied. Review changes, then stage, commit and push them yourself.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit("Interrupted.") from None
