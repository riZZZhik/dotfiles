"""A new user can discard presets, retain app preferences, and register exports."""

import json
import os
import plistlib
import shutil
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import tomlkit
import yaml

from src import apps, cli

SOURCE = Path(__file__).resolve().parents[1]


class AdoptSettingsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "repo"
        self.home = Path(temporary.name) / "home"
        self.root.mkdir()
        self.home.mkdir()
        (self.root / "config").mkdir()
        document = yaml.safe_load((SOURCE / "config/setup.yaml").read_text())
        self.sync = document["sync"]
        self.sync["state"] = str(self.home / "state")
        self.sync["agent"] = str(self.home / "Library/LaunchAgents/com.dotfiles.sync.plist")
        self.state = Path(self.sync["state"])
        (self.root / "config/setup.yaml").write_text(
            yaml.safe_dump(
                {"settings": document["settings"], "sync": document["sync"], "copy_settings": []}
            )
        )
        for target, value in (
            ("src.config.ROOT", self.root),
            ("src.apps.STATE", self.state),
            ("src.apps.SYNC", self.sync),
            ("src.apps.base.STATE", self.state),
            ("src.apps.vscode.STATE", self.state),
            ("src.apps.iterm.STATE", self.state),
        ):
            mock = patch(target, value)
            mock.start()
            self.addCleanup(mock.stop)
        mock = patch.object(Path, "home", return_value=self.home)
        mock.start()
        self.addCleanup(mock.stop)
        mock = patch("src.cli.run_shell")
        self.shell = mock.start()
        self.addCleanup(mock.stop)
        self.ready = True
        self.native = {
            "Default Bookmark Guid": "own-guid",
            "Personal Option": True,
            "New Bookmarks": [
                {
                    "Guid": "own-guid",
                    "Name": "Own",
                    "Normal Font": "Own Font 18",
                    "Command": "private-command",
                }
            ],
        }
        mock = patch("src.apps.iterm.ITerm.read_preferences", side_effect=self.read_iterm)
        mock.start()
        self.addCleanup(mock.stop)
        mock = patch("src.apps.subprocess.run", return_value=SimpleNamespace(returncode=0))
        self.launchctl = mock.start()
        self.addCleanup(mock.stop)
        self.code_user = self.home / "Library/Application Support/Code/User"
        self.inventory = self.home / ".vscode/extensions/extensions.json"
        self.codex = self.home / ".codex/config.toml"
        self.write_apps()
        (self.home / ".zshrc").write_text("# My own shell\n")

    def read_iterm(self):
        if not self.ready:
            raise FileNotFoundError("iTerm has not been opened yet")
        return deepcopy(self.native), plistlib.dumps(self.native)

    def write_apps(self):
        self.code_user.mkdir(parents=True, exist_ok=True)
        (self.code_user / "settings.json").write_text(
            '{"editor.fontSize":22,"extension.apiKey":"synthetic-secret"}'
        )
        (self.code_user / "keybindings.json").write_text(
            '[{"key":"ctrl+k","command":"own.command"}]'
        )
        self.inventory.parent.mkdir(parents=True, exist_ok=True)
        self.inventory.write_text('[{"identifier":{"id":"own.extension"}}]')
        self.codex.parent.mkdir(parents=True, exist_ok=True)
        self.codex.write_text(
            'model="own-model"\n[projects."/private/project"]\ntrust_level="trusted"\n'
        )

    def snapshot(self):
        return {
            p: p.read_bytes()
            for p in (
                self.codex,
                self.inventory,
                self.home / ".zshrc",
                self.code_user / "settings.json",
                self.code_user / "keybindings.json",
            )
            if p.exists()
        }

    def test_yaml_disables_copy_with_no_presets_no_private_repo_and_no_stages(self):
        before = self.snapshot()
        self.assertFalse((self.root / "home").exists())
        cli.main(["install"], self.root)
        self.assertEqual(before, self.snapshot())
        self.shell.assert_not_called()
        self.assertFalse((self.home / ".codex/AGENTS.md").exists())
        agent = plistlib.loads(Path(self.sync["agent"]).read_bytes())
        self.assertEqual(agent["WorkingDirectory"], str(self.root))
        self.assertIn(str(self.code_user), agent["WatchPaths"])
        public = self.root / "config/vscode/settings.jsonc"
        self.assertEqual(json.loads(public.read_text())["editor.fontSize"], 22)
        self.assertNotIn("synthetic-secret", public.read_text())
        private = self.state / "vscode/settings.local.jsonc"
        self.assertEqual(json.loads(private.read_text())["extension.apiKey"], "synthetic-secret")
        self.assertEqual(private.stat().st_mode & 0o777, 0o600)
        self.assertIn("own.extension", (self.root / "config/vscode/extensions.txt").read_text())
        saved = json.loads((self.root / "config/iterm2/settings.json").read_text())["Preferences"]
        self.assertTrue(saved["Personal Option"])
        self.assertEqual(saved["New Bookmarks"][0]["Normal Font"], "Own Font 18")
        self.assertNotIn("private-command", json.dumps(saved))
        full = plistlib.loads((self.state / "iterm/preferences.plist").read_bytes())
        self.assertEqual(full["New Bookmarks"][0]["Command"], "private-command")
        self.assertEqual(
            tomlkit.parse((self.root / "config/codex/config.toml").read_text())["model"],
            "own-model",
        )
        (self.code_user / "settings.json").write_text('{"editor.fontSize":26}')
        before = self.snapshot()
        cli.main(["apply"], self.root)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(json.loads(public.read_text())["editor.fontSize"], 26)
        self.assertFalse((self.root / "home").exists())

    def test_app_not_opened_yet_does_not_block_daemon_and_later_retry_exports(self):
        shutil.rmtree(self.code_user)
        self.inventory.unlink()
        self.codex.unlink()
        self.ready = False
        with self.assertRaises(RuntimeError):
            cli.main(["install"], self.root)
        self.assertTrue(Path(self.sync["agent"]).exists())
        self.launchctl.assert_called_with(
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", self.sync["agent"]],
            check=True,
        )
        self.write_apps()
        self.ready = True
        before = self.snapshot()
        cli.main(["sync"], self.root)
        self.assertEqual(before, self.snapshot())
        self.assertTrue((self.root / "config/vscode/settings.jsonc").exists())
        self.assertTrue((self.root / "config/iterm2/settings.json").exists())

    def test_yaml_discards_owner_presets_instead_of_importing_owner_only_keys(self):
        (self.root / "config/codex").mkdir()
        (self.root / "config/codex/config.toml").write_text(
            'model="owner-model"\nowner_only=true\n'
        )
        (self.root / "config/vscode").mkdir()
        (self.root / "config/vscode/settings.jsonc").write_text('{"owner.only":true}')
        (self.root / "config/vscode/extras.jsonc").write_text("{}")
        (self.root / "config/iterm2").mkdir()
        (self.root / "config/iterm2/settings.json").write_text('{"OwnerSetting":true}')
        before = self.snapshot()
        cli.main(["install"], self.root)
        self.assertEqual(before, self.snapshot())
        for path in self.root.glob("config/*/*"):
            if path.is_file():
                self.assertNotIn("owner_only", path.read_text())
                self.assertNotIn("OwnerSetting", path.read_text())
                self.assertNotIn("owner.only", path.read_text())

    def test_yaml_disabling_daemon_removes_owned_agent_and_stops_background_exports(self):
        cli.main(["install"], self.root)
        agent = Path(self.sync["agent"])
        self.assertTrue(agent.exists())
        self.sync["enabled"] = False
        document = yaml.safe_load((self.root / "config/setup.yaml").read_text())
        document["sync"]["enabled"] = False
        (self.root / "config/setup.yaml").write_text(yaml.safe_dump(document))
        before = (self.root / "config/vscode/settings.jsonc").read_bytes()
        (self.code_user / "settings.json").write_text('{"editor.fontSize":30}')
        cli.main(["apply"], self.root)
        self.assertFalse(agent.exists())
        self.assertEqual(before, (self.root / "config/vscode/settings.jsonc").read_bytes())
        cli.main(["sync"], self.root)
        self.assertEqual(before, (self.root / "config/vscode/settings.jsonc").read_bytes())

    def test_yaml_empty_app_list_removes_existing_agent(self):
        cli.main(["install"], self.root)
        document = yaml.safe_load((self.root / "config/setup.yaml").read_text())
        document["sync"]["apps"] = []
        (self.root / "config/setup.yaml").write_text(yaml.safe_dump(document))
        cli.main(["apply"], self.root)
        self.assertFalse(Path(self.sync["agent"]).exists())

    def test_disabling_daemon_refuses_to_remove_another_checkouts_agent(self):
        agent = Path(self.sync["agent"])
        agent.parent.mkdir(parents=True)
        original = plistlib.dumps(
            {"Label": self.sync["label"], "WorkingDirectory": str(self.root / "other")}
        )
        agent.write_bytes(original)
        self.sync["enabled"] = False
        with self.assertRaisesRegex(RuntimeError, "another checkout"):
            apps.install_agent(self.root, ())
        self.assertEqual(agent.read_bytes(), original)

    def test_partial_copy_and_sync_are_independent_without_software_stages(self):
        document = yaml.safe_load((self.root / "config/setup.yaml").read_text())
        document["copy_settings"] = ["vscode"]
        document["sync"]["apps"] = ["iterm"]
        (self.root / "config/setup.yaml").write_text(yaml.safe_dump(document))
        vscode, iterm, codex = (Mock(WATCH_PATHS=()) for _ in range(3))
        with patch.dict(
            apps.APPLICATIONS,
            {
                "vscode": lambda: vscode,
                "iterm": lambda: iterm,
                "codex": lambda: codex,
            },
        ):
            cli.main(["install"], self.root)
        vscode.install.assert_called_once_with()
        vscode.sync.assert_not_called()
        iterm.install.assert_called_once_with(copy_settings=False)
        iterm.sync.assert_called_once_with()
        codex.install.assert_not_called()
        codex.sync.assert_not_called()
        self.shell.assert_not_called()

    def test_home_only_presets_skip_app_links_and_macos_actions(self):
        source = yaml.safe_load((SOURCE / "config/setup.yaml").read_text())
        document = yaml.safe_load((self.root / "config/setup.yaml").read_text())
        document["copy_settings"] = ["home"]
        document.update(
            {key: source[key] for key in ("setup-codex", "setup-macos", "setup-terminal")}
        )
        (self.root / "config/setup.yaml").write_text(yaml.safe_dump(document))
        (self.root / "home").mkdir()
        (self.root / "home/.example").write_text("preset")
        with patch.object(apps, "sync_apps"), patch("src.cli.macos_preferences") as macos:
            cli.main(["apply"], self.root)
        self.assertTrue((self.home / ".example").is_symlink())
        self.assertFalse((self.home / ".codex/AGENTS.md").exists())
        macos.assert_not_called()
        self.shell.assert_called_once_with("packages", "plugins", "install")
