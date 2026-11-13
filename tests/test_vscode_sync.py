"""VS Code initialization is explicit and daemon exports never write to the app."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import json5

from src import apps
from src.apps.vscode import VSCode


class VSCodeSyncTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.shared = self.root / "shared"
        self.shared.mkdir()
        for name in ("settings.jsonc", "extras.jsonc"):
            (self.shared / name).write_text("{}\n")
        (self.shared / "keybindings.json").write_text("[]\n")
        (self.shared / "extensions.txt").write_text("# Empty fixture.\n")
        self.profile = self.shared / "ui-state.code-profile"
        self.profile.write_text('{"name":"Dotfiles UI","globalState":"{}"}')
        self.state = self.root / "state"
        for target in ("src.apps.base.STATE", "src.apps.vscode.STATE"):
            mock = patch(target, self.state)
            mock.start()
            self.addCleanup(mock.stop)
        settings = {
            "shared": str(self.shared),
            "private": str(self.root / "private/settings.local.jsonc"),
            "user": str(self.root / "user"),
            "extensions": str(self.root / "extensions.json"),
            "backups": str(self.root / "backups"),
            "layout_keys": ["workbench.panel.alignment"],
            "cli": "fixture-code",
            "extension_timeout_seconds": 1,
        }
        with patch("src.apps.base.load", return_value=settings):
            self.adapter = VSCode()
        self.adapter.USER.mkdir()
        self.adapter.EXTENSIONS.write_text("[]")
        (self.adapter.USER / "settings.json").write_text("{}\n")

    def snapshot_app(self):
        files = [self.adapter.EXTENSIONS, *self.adapter.USER.rglob("*")]
        return {
            p: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
            for p in files
            if p.is_file()
        }

    def test_commented_splits_preserve_layout_regions_and_private_boundaries(self):
        (self.shared / "extras.jsonc").write_text('{"window.title":"old"}')
        self.adapter.PRIVATE.parent.mkdir()
        self.adapter.PRIVATE.write_text(
            '{"company.option":"old","company.retired":"retired-identifier",'
            '"http.proxySupport":"on"}'
        )
        source = """{
  // #region Editor appearance
  // Machine-only note
  "company.option": "private-identifier", // machine-only inline note

  // Keep this paragraph.
  "editor.fontSize": 18, // Public inline note

  // A private-identifier must not appear in this public comment.
  // retired-identifier
  "editor.fontFamily": "Fixture Mono",
  // #endregion

  // #region Window appearance
  "window.title": "Fixture title",
  // #endregion

  // #region Credentials
  // credential-only note
  "extension.apiKey": "synthetic-secret",
  // #endregion

  // Filtering also keeps retained array-item comments.
  "settingsSync.ignoredSettings": [
    "company.option", // private-identifier
    // Keep this item.
    "public.option"
  ]
}
"""
        (self.adapter.USER / "settings.json").write_text(source)
        (self.adapter.USER / "keybindings.json").write_text("""[
  // #region Shortcuts
  // Machine shortcut note
  {"key":"ctrl+x","command":"fixture.private","args":"/Users/fixture/private"},

  // Editor shortcut note
  {"key":"ctrl+k", "command":"fixture.public"}, // Public shortcut inline note
  // #endregion
]
""")
        before = self.snapshot_app()
        self.adapter.sync()
        self.assertEqual(before, self.snapshot_app())
        main = (self.shared / "settings.jsonc").read_text()
        extras = (self.shared / "extras.jsonc").read_text()
        shortcuts = (self.shared / "keybindings.json").read_text()
        private = self.adapter.PRIVATE.read_text()
        for text in (main, extras, shortcuts):
            self.assertEqual(text.count("// #region"), text.count("// #endregion"))
            for excluded in (
                "private-identifier",
                "retired-identifier",
                "synthetic-secret",
                "Machine-only note",
                "machine-only inline note",
                "credential-only note",
                "Machine shortcut note",
                "Credentials",
                "/Users/fixture",
                "company.option",
            ):
                self.assertNotIn(excluded, text)
        self.assertIn("// #region Editor appearance", main)
        self.assertIn(
            '// Keep this paragraph.\n  "editor.fontSize": 18, // Public inline note', main
        )
        self.assertIn("\n\n", main)
        self.assertIn('// Keep this item.\n    "public.option"', main)
        self.assertIn("// #region Window appearance", extras)
        self.assertIn('"window.title": "Fixture title"', extras)
        self.assertIn("synthetic-secret", private)
        self.assertIn("// Machine-only note", private)
        self.assertIn("// credential-only note", private)
        self.assertEqual(json5.loads(private)["company.option"], "private-identifier")
        self.assertIn("// Editor shortcut note", shortcuts)
        self.assertIn('{"key":"ctrl+k", "command":"fixture.public"}', shortcuts)
        local = self.state / "vscode/keybindings.local.json"
        self.assertIn("// Machine shortcut note", local.read_text())
        self.assertEqual(local.stat().st_mode & 0o777, 0o600)
        redactions = self.state / "vscode/comment-redactions.json"
        self.assertEqual(redactions.stat().st_mode & 0o777, 0o600)
        self.assertIn("retired-identifier", json.loads(redactions.read_text()))
        self.assertEqual(self.adapter.PRIVATE.stat().st_mode & 0o777, 0o600)
        outputs = [*(self.shared.iterdir()), self.adapter.PRIVATE, local]
        saved = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in outputs if p.is_file()}
        self.adapter.sync()
        self.assertEqual(saved, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in saved})
        self.adapter.copy_settings()
        self.assertEqual(len(json5.loads((self.adapter.USER / "keybindings.json").read_text())), 2)

    def test_invalid_redaction_history_does_not_publish_comments(self):
        redactions = self.state / "vscode/comment-redactions.json"
        redactions.parent.mkdir(parents=True)
        redactions.write_text('{"unexpected":"shape"}')
        before = {p: p.read_bytes() for p in self.shared.iterdir()}
        with self.assertRaisesRegex(ValueError, "redaction history"):
            self.adapter.sync()
        self.assertEqual(before, {p: p.read_bytes() for p in self.shared.iterdir()})

    def test_invalid_or_duplicate_source_keeps_existing_exports(self):
        for name, source in (
            ("settings.json", '{"extension.apiKey":"first", "extension.apiKey":"second"}'),
            ("settings.json", '{"editor.fontSize":18, broken'),
            ("keybindings.json", '[{"key":"ctrl+k","command":"first","command":"second"}]'),
            ("settings.local.jsonc", '{"extension.apiKey":"first","extension.apiKey":"second"}'),
            ("extras.jsonc", '{"window.title":"first","window.title":"second"}'),
        ):
            with self.subTest(name=name, source=source):
                (self.adapter.USER / "settings.json").write_text("{}")
                (self.adapter.USER / "keybindings.json").write_text("[]")
                self.adapter.PRIVATE.unlink(missing_ok=True)
                (self.shared / "extras.jsonc").write_text("{}")
                target = (
                    self.adapter.PRIVATE
                    if name == "settings.local.jsonc"
                    else self.shared / name
                    if name == "extras.jsonc"
                    else self.adapter.USER / name
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source)
                before = {p: p.read_bytes() for p in self.shared.iterdir()}
                with self.assertRaisesRegex(ValueError, "Invalid JSONC"):
                    self.adapter.sync()
                self.assertEqual(before, {p: p.read_bytes() for p in self.shared.iterdir()})

    def test_export_updates_repository_and_preserves_app_and_private_values(self):
        (self.shared / "settings.jsonc").write_text('{"obsolete":true,"editor.fontSize":12}')
        (self.shared / "extras.jsonc").write_text('{"window.title":"old"}')
        self.adapter.PRIVATE.parent.mkdir()
        self.adapter.PRIVATE.write_text('{"company.setting":"old"}')
        values = {
            "editor.fontSize": 18,
            "window.title": "new",
            "company.setting": "local",
            "extension.apiKey": "synthetic-secret",
            "python.path": "/Users/fixture/python",
            "remote.SSH.remotePlatform": {"private-host": "linux"},
            "settingsSync.ignoredSettings": ["company.setting"],
        }
        (self.adapter.USER / "settings.json").write_text(json.dumps(values))
        (self.adapter.USER / "keybindings.json").write_text(
            json.dumps(
                [
                    {"key": "ctrl+k", "command": "portable", "args": self.shared.as_uri()},
                    {"key": "ctrl+p", "command": "local", "args": "/Users/fixture/script"},
                ]
            )
        )
        (self.shared / "extensions.txt").write_text("repo.only\n")
        self.adapter.EXTENSIONS.write_text(json.dumps([{"identifier": {"id": "Local.Extension"}}]))
        before = self.snapshot_app()
        with patch("src.apps.vscode.subprocess.run") as run:
            self.adapter.sync()
            run.assert_not_called()
        self.assertEqual(before, self.snapshot_app())
        exported = json5.loads((self.shared / "settings.jsonc").read_text())
        self.assertEqual(exported, {"editor.fontSize": 18, "settingsSync.ignoredSettings": []})
        self.assertEqual(
            json5.loads((self.shared / "extras.jsonc").read_text()), {"window.title": "new"}
        )
        self.assertEqual(
            json5.loads(self.adapter.PRIVATE.read_text())["extension.apiKey"], "synthetic-secret"
        )
        public = "".join(p.read_text() for p in self.shared.iterdir())
        for excluded in ("synthetic-secret", "/Users/fixture", "private-host", "company.setting"):
            self.assertNotIn(excluded, public)
        self.assertEqual(
            json.loads((self.shared / "keybindings.json").read_text()),
            [{"key": "ctrl+k", "command": "portable", "args": "${vscodeDir}"}],
        )
        self.assertIn("local.extension", (self.shared / "extensions.txt").read_text())
        self.assertNotIn("repo.only", (self.shared / "extensions.txt").read_text())
        self.assertFalse((self.state / "vscode/installed").exists())
        self.assertEqual(
            json.loads((self.state / "vscode/keybindings.local.json").read_text())[0]["command"],
            "local",
        )
        exports = {p: p.stat().st_mtime_ns for p in self.shared.iterdir()}
        self.adapter.sync()
        self.assertEqual(exports, {p: p.stat().st_mtime_ns for p in self.shared.iterdir()})

    def test_missing_app_input_keeps_all_exports(self):
        for missing in (self.adapter.EXTENSIONS, self.adapter.USER / "settings.json"):
            with self.subTest(missing=missing):
                original = missing.read_bytes()
                missing.unlink()
                before = {p: p.read_bytes() for p in self.shared.iterdir()}
                with self.assertRaises(FileNotFoundError):
                    self.adapter.sync()
                self.assertEqual(before, {p: p.read_bytes() for p in self.shared.iterdir()})
                missing.write_bytes(original)

    def test_copy_once_retains_unrelated_extensions_and_backs_up_layout(self):
        (self.shared / "settings.jsonc").write_text('{"editor.fontSize":18}')
        self.adapter.PRIVATE.parent.mkdir()
        self.adapter.PRIVATE.write_text('{"company.setting":"private"}')
        (self.shared / "extensions.txt").write_text("new.extension\n")
        self.adapter.EXTENSIONS.write_text('[{"identifier":{"id":"existing.extension"}}]')
        local_bindings = self.state / "vscode/keybindings.local.json"
        local_bindings.parent.mkdir(parents=True)
        local_bindings.write_text(
            '[{"key":"ctrl+k","command":"local.command","args":"${vscodeDir}"}]'
        )
        layout = self.profile.read_bytes()

        def installed(*args, **kwargs):
            self.assertEqual(args[0][-2:], ["--install-extension", "new.extension"])
            self.adapter.EXTENSIONS.write_text(
                json.dumps(
                    [
                        {"identifier": {"id": "existing.extension"}},
                        {"identifier": {"id": "new.extension"}},
                    ]
                )
            )

        with patch("src.apps.vscode.subprocess.run", side_effect=installed) as run:
            self.adapter.install()
            self.assertEqual(run.call_count, 1)
        actual = json.loads((self.adapter.USER / "settings.json").read_text())
        self.assertEqual(actual["company.setting"], "private")
        self.assertEqual(actual["editor.fontSize"], 18)
        self.assertEqual(
            json.loads((self.adapter.USER / "keybindings.json").read_text())[0]["args"],
            self.shared.as_uri(),
        )
        self.assertEqual(
            (self.adapter.BACKUPS / "initial-ui-state.code-profile").read_bytes(), layout
        )
        (self.adapter.USER / "settings.json").write_text('{"editor.fontSize":22}')
        (self.shared / "settings.jsonc").write_text('{"editor.fontSize":10}')
        before = self.snapshot_app()
        with patch("src.apps.vscode.subprocess.run") as run:
            self.adapter.install()
            run.assert_not_called()
        self.assertEqual(before, self.snapshot_app())

    def test_existing_machine_is_marked_initialized_without_app_writes(self):
        legacy = self.state / "vscode/extensions.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("[]")
        before = self.snapshot_app()
        with patch.object(self.adapter, "copy_settings") as copy:
            self.adapter.install()
            copy.assert_not_called()
        self.assertEqual(before, self.snapshot_app())
        self.assertTrue((self.state / "vscode/installed").exists())

    def test_failed_first_copy_is_retryable(self):
        with (
            patch.object(self.adapter, "copy_settings", side_effect=RuntimeError("failed")),
            self.assertRaises(RuntimeError),
        ):
            self.adapter.install()
        self.assertFalse((self.state / "vscode/installed").exists())
        with patch.object(self.adapter, "copy_settings") as copy:
            self.adapter.install()
            copy.assert_called_once()

    def test_layout_export_works_without_restoration_or_settings_sync_gate(self):
        database = self.adapter.USER / "globalStorage/state.vscdb"
        database.parent.mkdir()
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
            connection.executemany(
                "INSERT INTO ItemTable VALUES (?, ?)",
                [
                    ("sync.enable", "true"),
                    ("__$__targetStorageMarker", json.dumps({"workbench.panel.alignment": 0})),
                    ("workbench.panel.alignment", "left"),
                    ("extension.secret", "synthetic-private-value"),
                ],
            )
        before = self.snapshot_app()
        self.adapter.sync()
        self.assertEqual(before, self.snapshot_app())
        profile = json.loads(self.profile.read_text())
        self.assertEqual(
            json.loads(profile["globalState"])["storage"], {"workbench.panel.alignment": "left"}
        )

    def test_watches_app_inputs_only(self):
        self.assertIn(self.adapter.USER, self.adapter.WATCH_PATHS)
        self.assertIn(self.adapter.EXTENSIONS, self.adapter.WATCH_PATHS)
        self.assertNotIn(self.shared, self.adapter.WATCH_PATHS)
        self.assertNotIn(self.adapter.PRIVATE.parent, self.adapter.WATCH_PATHS)

    def test_yaml_copying_is_independent_of_disabled_daemon(self):
        (self.root / "config").mkdir()
        (self.root / "config/setup.yaml").write_text("copy_settings:\n  - vscode\n")
        (self.shared / "settings.jsonc").write_text('{"editor.fontSize":18}')
        with (
            patch.object(apps, "STATE", self.state),
            patch.object(apps, "SYNC", {"enabled": False}),
            patch.dict(apps.APPLICATIONS, {"vscode": lambda: self.adapter}),
        ):
            apps.sync_apps(self.root, (), initialize=("vscode",), register_agent=False)
        self.assertEqual(
            json.loads((self.adapter.USER / "settings.json").read_text())["editor.fontSize"], 18
        )
        self.assertTrue((self.state / "vscode/installed").exists())
