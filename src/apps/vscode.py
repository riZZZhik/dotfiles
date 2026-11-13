"""Copy VS Code defaults once, then export app preferences without changing the app."""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import json5

from ..config import path
from .base import STATE, App, write_if_changed
from .jsonc import Document


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
                    json5.loads(keybindings) + json5.loads(local_bindings.read_text()), indent=2
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
        settings_document = Document(settings_file.read_text())
        settings = settings_document.value
        if not isinstance(settings, dict):
            raise TypeError("VS Code settings must be an object.")
        installed = self.read_installed_extensions()
        bindings = self.USER / "keybindings.json"
        text = bindings.read_text() if bindings.exists() else "[]"
        text = text.replace(self.SHARED.as_uri(), "${vscodeDir}")
        bindings_document = Document(text)
        all_bindings = bindings_document.value
        if not isinstance(all_bindings, list):
            raise TypeError("VS Code keybindings must be an array.")
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
        local_settings = {key: settings[key] for key in settings if key in local_keys}
        private_literals = set(local_keys)
        redactions_file = STATE / "vscode/comment-redactions.json"
        if redactions_file.exists():
            try:
                history = json.loads(redactions_file.read_text())
                if not isinstance(history, list) or any(
                    not isinstance(value, str) or not value for value in history
                ):
                    raise ValueError
                private_literals.update(history)
            except ValueError:
                raise ValueError(
                    "Invalid local comment redaction history; export stopped."
                ) from None

        def collect_private(value, *, sensitive=False):
            if isinstance(value, str) and value:
                # Enum values are not private identifiers ("on" also occurs in #region).
                if sensitive or value not in {
                    "on",
                    "off",
                    "auto",
                    "always",
                    "never",
                    "default",
                    "none",
                    "true",
                    "false",
                    "yes",
                    "no",
                    "linux",
                    "windows",
                    "osx",
                    "macos",
                }:
                    private_literals.add(value)
            elif isinstance(value, dict):
                for key, item in value.items():
                    if key not in {"key", "command", "when", "args"}:
                        private_literals.add(key)
                    collect_private(item, sensitive=sensitive or self.sensitive_key(key))
            elif isinstance(value, list):
                for item in value:
                    collect_private(item, sensitive=sensitive)

        collect_private(local_settings)
        collect_private(local_bindings)
        collect_private(private)

        def safe_comment(comment):
            return not (
                self.sensitive_key(comment)
                or "credential" in comment.casefold()
                or self.local_data(comment)
                or re.search(r"(?:~|file:)?/(?:Users|Volumes|private|opt|home|tmp)/", comment)
                or any(value in comment for value in private_literals)
            )

        # Render every split before writing: invalid source must preserve existing exports.
        exports = {
            # Persist privacy history before publishing any public output.
            redactions_file: json.dumps(sorted(private_literals), ensure_ascii=False) + "\n",
            self.SHARED / "settings.jsonc": settings_document.project(
                {k: v for k, v in public.items() if k not in extras_keys}, safe_comment
            ),
            extras_file: settings_document.project(
                {k: v for k, v in public.items() if k in extras_keys}, safe_comment
            ),
            self.SHARED / "keybindings.json": bindings_document.project(keybindings, safe_comment),
        }
        if local_keys or private_file.exists():
            exports[private_file] = settings_document.project(local_settings)
        local_bindings_file = STATE / "vscode/keybindings.local.json"
        if local_bindings or local_bindings_file.exists():
            exports[local_bindings_file] = bindings_document.project(local_bindings)
        for destination, content in exports.items():
            write_if_changed(destination, content)
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
        try:
            return json5.loads(file.read_text(), allow_duplicate_keys=False)
        except ValueError:
            raise ValueError(
                "Invalid JSONC configuration; existing exports were not replaced."
            ) from None

    def read_installed_extensions(self) -> set[str]:
        return (
            {entry["identifier"]["id"].lower() for entry in json.loads(self.EXTENSIONS.read_text())}
            if self.EXTENSIONS.exists()
            else set()
        )
