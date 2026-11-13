"""Copy VS Code defaults once, then export app preferences without changing the app."""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import json5

from ..config import path
from .base import STATE, App, write_if_changed


class VSCode(App):
    NAME = "vscode"

    def __init__(self):
        super().__init__()
        self.PRIVATE = path(self.CONFIG["private"])
        self.USER = path(self.CONFIG["user"])
        self.EXTENSIONS = path(self.CONFIG["extensions"])
        self.WATCH_PATHS = (self.USER, self.USER / "globalStorage/state.vscdb", self.EXTENSIONS)
        self.LAYOUT_KEYS = frozenset(self.CONFIG["layout_keys"])

    def install(self, *, copy_settings: bool = True) -> None:
        self.install_once(
            self.copy_settings,
            configured=not copy_settings or (STATE / "vscode/extensions.json").exists(),
        )

    def private_file(self) -> Path:
        if self.PRIVATE.parent.is_dir():
            return self.PRIVATE
        return STATE / "vscode/settings.local.jsonc"

    def copy_settings(self) -> None:
        settings = self.read_jsonc(self.SHARED / "settings.jsonc")
        settings.update(self.read_jsonc(self.SHARED / "extras.jsonc"))
        private_file = self.private_file()
        private = self.read_jsonc(private_file) if private_file.exists() else {}
        settings.update(private)
        settings["settingsSync.ignoredSettings"] = sorted(
            set(settings.get("settingsSync.ignoredSettings", [])) | set(private)
        )
        keybindings = (
            (self.SHARED / "keybindings.json")
            .read_text()
            .replace("${vscodeDir}", self.SHARED.as_uri())
        )
        # Keep the optional native layout import available after automatic exports begin.
        profile = self.SHARED / "ui-state.code-profile"
        if profile.exists():
            self.write(self.BACKUPS / "initial-ui-state.code-profile", profile.read_text())
        self.write(
            self.USER / "settings.json", json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
        )
        local_bindings = STATE / "vscode/keybindings.local.json"
        if local_bindings.exists():
            keybindings = (
                json.dumps(
                    json5.loads(keybindings) + json.loads(local_bindings.read_text()), indent=2
                )
                + "\n"
            )
        self.write(
            self.USER / "keybindings.json",
            keybindings.replace("${vscodeDir}", self.SHARED.as_uri()),
        )
        requested = {
            line.strip().lower()
            for line in (self.SHARED / "extensions.txt").read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        code = shutil.which("code") or str(path(self.CONFIG["cli"]))
        for extension in sorted(requested - self.read_installed_extensions()):
            subprocess.run(
                [code, "--install-extension", extension],
                check=True,
                timeout=self.CONFIG["extension_timeout_seconds"],
            )
        if requested - self.read_installed_extensions():
            raise RuntimeError("VS Code extension inventory did not reflect installation.")

    def sync(self) -> None:
        settings_file = self.USER / "settings.json"
        if not settings_file.exists() or not self.EXTENSIONS.exists():
            raise FileNotFoundError(
                "VS Code settings or extension inventory is missing; keeping exports."
            )
        settings = self.read_jsonc(settings_file)
        installed = self.read_installed_extensions()
        bindings = self.USER / "keybindings.json"
        text = bindings.read_text() if bindings.exists() else "[]"
        text = text.replace(self.SHARED.as_uri(), "${vscodeDir}")
        all_bindings = json5.loads(text)
        keybindings = [item for item in all_bindings if not self.local_data(item)]
        local_bindings = [item for item in all_bindings if self.local_data(item)]
        values = {}
        database = self.USER / "globalStorage/state.vscdb"
        if database.exists():
            with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
                values = dict(connection.execute("SELECT key, value FROM ItemTable"))
        private_file = self.private_file()
        private = self.read_jsonc(private_file) if private_file.exists() else {}
        local_keys = {
            key
            for key, value in settings.items()
            if key in private
            or self.sensitive_key(key)
            or self.local_data(value)
            or key.startswith(("remote.SSH.", "terminal.integrated.env."))
        }
        public = {key: value for key, value in settings.items() if key not in local_keys}
        if "settingsSync.ignoredSettings" in public:
            public["settingsSync.ignoredSettings"] = [
                key for key in public["settingsSync.ignoredSettings"] if key not in local_keys
            ]
        extras_file = self.SHARED / "extras.jsonc"
        extras_keys = set(self.read_jsonc(extras_file)) if extras_file.exists() else set()
        for filename, data in (
            ("settings.jsonc", {k: v for k, v in public.items() if k not in extras_keys}),
            ("extras.jsonc", {k: v for k, v in public.items() if k in extras_keys}),
            ("keybindings.json", keybindings),
        ):
            write_if_changed(
                self.SHARED / filename, json.dumps(data, indent=2, ensure_ascii=False) + "\n"
            )
        if local_keys or private_file.exists():
            write_if_changed(
                private_file,
                json.dumps(
                    {key: settings[key] for key in settings if key in local_keys},
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
            )
        local_bindings_file = STATE / "vscode/keybindings.local.json"
        if local_bindings or local_bindings_file.exists():
            write_if_changed(local_bindings_file, json.dumps(local_bindings, indent=2) + "\n")
        write_if_changed(
            self.SHARED / "extensions.txt",
            "# Exported from local VS Code.\n" + "\n".join(sorted(installed)) + "\n",
        )
        if values:
            self.export_ui_state(values, self.SHARED / "ui-state.code-profile")

    def export_ui_state(self, values: dict, destination: Path) -> None:
        targets = json.loads(values.get("__$__targetStorageMarker", "{}"))
        storage = {
            key: value
            for key, value in sorted(values.items())
            if targets.get(key) == 0
            and (
                key in self.LAYOUT_KEYS
                or key.startswith(("workbench.", "~remote."))
                and key.endswith(".hidden")
            )
        }
        profile = {"name": "Dotfiles UI", "globalState": json.dumps({"storage": storage})}
        write_if_changed(destination, json.dumps(profile, indent=2, ensure_ascii=False) + "\n")

    def read_jsonc(self, file: Path) -> dict[str, Any]:
        return json5.loads(file.read_text())

    def read_installed_extensions(self) -> set[str]:
        return (
            {entry["identifier"]["id"].lower() for entry in json.loads(self.EXTENSIONS.read_text())}
            if self.EXTENSIONS.exists()
            else set()
        )
