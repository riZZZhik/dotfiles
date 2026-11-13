"""iTerm exports portable settings without modifying native preferences or profiles."""

import json
import plistlib
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.apps.iterm import ITerm


class ITermSyncTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.shared = self.root / "shared"
        self.shared.mkdir()
        self.state = self.root / "state"
        mock = patch("src.apps.base.STATE", self.state)
        mock.start()
        self.addCleanup(mock.stop)
        mock = patch("src.apps.iterm.STATE", self.state)
        mock.start()
        self.addCleanup(mock.stop)
        settings = {
            "shared": str(self.shared),
            "backups": str(self.root / "backups"),
            "domain": "fixture.iterm",
            "process": "fixture-iterm",
            "destination": str(self.root / "native/dynamic.json"),
            "theme_library": "https://example.invalid/",
            "theme_timeout_seconds": 1,
            "theme_cache": "unused",
        }
        with patch("src.apps.base.load", return_value=settings):
            self.adapter = ITerm()
        self.template = {
            "Theme": "Fixture",
            "Global": {"TabViewType": 0},
            "Profile": {"Normal Font": "Fixture 12", "Transparency": 0.1},
            "Hotkey": {
                "Has Hotkey": True,
                "Keyboard Map": {"shortcut": {"Action": 27, "Text": "$PROFILE_GUID"}},
            },
            "Remote": {
                "Name": "Remote",
                "Guid": "shared-remote",
                "Has Hotkey": False,
                "Bound Hosts": ["&ssh*"],
            },
        }
        (self.shared / "settings.json").write_text(json.dumps(self.template))
        self.native = {
            "Default Bookmark Guid": "local-guid",
            "TabViewType": 2,
            "Window Frame": "/Users/fixture/private",
            "New Bookmarks": [
                {
                    "Guid": "local-guid",
                    "Name": "Private host",
                    "Normal Font": "Fixture 14",
                    "Transparency": 0.4,
                    "Has Hotkey": True,
                    "Command": "ssh private-host",
                    "Custom Directory": "/Users/fixture/private",
                    "Keyboard Map": {"shortcut": {"Action": 27, "Text": "local-guid"}},
                    "Background Color": {
                        "Red Component": 0.1,
                        "Green Component": 0.2,
                        "Blue Component": 0.3,
                    },
                }
            ],
        }
        mock = patch.object(
            self.adapter,
            "read_preferences",
            side_effect=lambda: (deepcopy(self.native), plistlib.dumps(self.native)),
        )
        mock.start()
        self.addCleanup(mock.stop)

    def test_export_is_read_only_to_app_and_keeps_ids_paths_commands_private(self):
        self.adapter.DESTINATION.parent.mkdir()
        self.adapter.DESTINATION.write_text(
            json.dumps(
                {
                    "Profiles": [
                        {
                            "Guid": "shared-remote",
                            "Name": "Remote",
                            "Dynamic Profile Parent GUID": "local-guid",
                            "Has Hotkey": False,
                            "Command": "ssh private-host",
                            "Bound Hosts": ["&ssh*", "private-host"],
                        }
                    ]
                }
            )
        )
        before = self.adapter.DESTINATION.read_bytes()
        native = deepcopy(self.native)
        with patch("src.apps.iterm.subprocess.run") as run:
            self.adapter.sync()
            run.assert_not_called()
        self.assertEqual(before, self.adapter.DESTINATION.read_bytes())
        self.assertEqual(native, self.native)
        exported = json.loads((self.shared / "settings.json").read_text())["Preferences"]
        self.assertEqual(exported["TabViewType"], 2)
        profile = exported["New Bookmarks"][0]
        self.assertEqual(profile["Normal Font"], "Fixture 14")
        self.assertEqual(profile["Keyboard Map"]["shortcut"]["Text"], "profile-1")
        self.assertEqual(profile["Guid"], "profile-1")
        with patch.object(self.adapter, "load_theme") as load:
            imported, dynamic = self.adapter.build_preferences(self.native)
            load.assert_not_called()
        self.assertIsNone(dynamic)
        self.assertEqual(
            imported["New Bookmarks"][0]["Background Color"], profile["Background Color"]
        )
        self.assertEqual(imported["New Bookmarks"][0]["Guid"], "local-guid")
        self.assertEqual(imported["New Bookmarks"][0]["Command"], "ssh private-host")
        text = (self.shared / "settings.json").read_text()
        for excluded in ("local-guid", "private-host", "/Users/fixture"):
            self.assertNotIn(excluded, text)
        full = plistlib.loads((self.state / "iterm/preferences.plist").read_bytes())
        self.assertEqual(full["New Bookmarks"][0]["Command"], "ssh private-host")
        self.assertEqual((self.state / "iterm/preferences.plist").stat().st_mode & 0o777, 0o600)
        before = (self.shared / "settings.json").stat().st_mtime_ns
        self.adapter.sync()
        self.assertEqual(before, (self.shared / "settings.json").stat().st_mtime_ns)
        self.assertFalse((self.state / "iterm/installed").exists())

    def test_machine_state_stays_in_local_snapshot_and_survives_preset_import(self):
        machine = {
            "NoSyncRecordedVariables": {"hostname": "fixture-machine"},
            "NoSyncSavedWindowPositions": {"window": "{42, 84}"},
            "NoSyncBFPRecents": ["private-arrangement"],
            "NoSyncAllAppVersions": ["fixture-version"],
            "NoSyncFutureState": {"opaque": 123},
            "NSWindow Frame Preferences": "{42, 84}",
            "NSToolbar Configuration com.apple.NSColorPanel": {"TB Is Shown": True},
            "NSRecentDocuments": ["file:///Volumes/private/document"],
            "Window Arrangements": {"private-arrangement": {"Screen": 3}},
            "Default Arrangement Name": "private-arrangement",
            "iTerm Version": "fixture-version",
            "HotkeyMigratedFromSingleToMulti": True,
            "AitermURL": "https://private-provider.invalid/v1",
            "Background Image Location": "/Volumes/private/background.png",
            "Local Helper": "/opt/private/helper",
        }
        self.native.update(machine)
        profile = self.native["New Bookmarks"][0]
        profile.update({"Screen": 3, "Space": 7, "Window Frame": "{42, 84}"})
        native = deepcopy(self.native)
        self.adapter.sync()
        exported = json.loads((self.shared / "settings.json").read_text())["Preferences"]
        self.assertTrue(set(machine).isdisjoint(exported))
        public_profile = exported["New Bookmarks"][0]
        for key in ("Screen", "Space", "Window Frame"):
            self.assertNotIn(key, public_profile)
        self.assertEqual(public_profile["Normal Font"], "Fixture 14")
        self.assertEqual(public_profile["Transparency"], 0.4)
        self.assertEqual(public_profile["Keyboard Map"]["shortcut"]["Text"], "profile-1")
        snapshot = self.state / "iterm/preferences.plist"
        self.assertEqual(plistlib.loads(snapshot.read_bytes()), native)
        self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.native, native)
        receiver = deepcopy(native)
        receiver["NoSyncRecordedVariables"] = {"hostname": "another-fixture"}
        receiver["New Bookmarks"][0].update({"Screen": 1, "Space": 2})
        restored, _ = self.adapter.build_preferences(receiver)
        self.assertEqual(restored["NoSyncRecordedVariables"], receiver["NoSyncRecordedVariables"])
        self.assertEqual(restored["New Bookmarks"][0]["Screen"], 1)
        self.assertEqual(restored["New Bookmarks"][0]["Space"], 2)
        before = (self.shared / "settings.json").stat().st_mtime_ns
        self.adapter.sync()
        self.assertEqual(before, (self.shared / "settings.json").stat().st_mtime_ns)

    def test_export_needs_no_template_and_captures_new_fields_and_all_profiles(self):
        (self.shared / "settings.json").unlink()
        self.native["Personal Global Option"] = True
        self.native["New Bookmarks"][0]["Personal Profile Option"] = 42
        self.native["New Bookmarks"].append(
            {"Guid": "second-guid", "Name": "Second", "Normal Font": "Fixture 16"}
        )
        self.adapter.sync()
        exported = json.loads((self.shared / "settings.json").read_text())["Preferences"]
        self.assertTrue(exported["Personal Global Option"])
        self.assertEqual(exported["New Bookmarks"][0]["Personal Profile Option"], 42)
        self.assertEqual(len(exported["New Bookmarks"]), 2)
        del self.native["Personal Global Option"]
        self.adapter.sync()
        self.assertNotIn(
            "Personal Global Option",
            json.loads((self.shared / "settings.json").read_text())["Preferences"],
        )

    def test_install_copies_once_preserves_native_identity_and_local_values(self):
        imported = []

        def run(args, **kwargs):
            if args[0] == "pgrep":
                return SimpleNamespace(returncode=1)
            self.assertEqual(args[:2], ["defaults", "import"])
            imported.append(plistlib.loads(Path(args[-1]).read_bytes()))
            return SimpleNamespace(returncode=0)

        with (
            patch("src.apps.iterm.subprocess.run", side_effect=run),
            patch.object(self.adapter, "load_theme", return_value={}),
        ):
            self.adapter.install()
        self.assertEqual(len(imported), 1)
        profile = imported[0]["New Bookmarks"][0]
        self.assertEqual(profile["Guid"], "local-guid")
        self.assertEqual(profile["Command"], "ssh private-host")
        self.assertEqual(profile["Normal Font"], "Fixture 12")
        self.assertTrue((self.state / "iterm/installed").exists())
        before = self.adapter.DESTINATION.read_bytes()
        with patch.object(self.adapter, "copy_settings") as copy:
            self.adapter.install()
            copy.assert_not_called()
        self.assertEqual(before, self.adapter.DESTINATION.read_bytes())

    def test_running_app_blocks_initial_copy_without_writing_or_marking_complete(self):
        with (
            patch("src.apps.iterm.subprocess.run", return_value=SimpleNamespace(returncode=0)),
            self.assertRaisesRegex(RuntimeError, "Quit iTerm normally"),
        ):
            self.adapter.install()
        self.assertFalse(self.adapter.DESTINATION.exists())
        self.assertFalse(self.state.exists())

    def test_existing_generated_profile_migrates_without_reimport(self):
        self.adapter.DESTINATION.parent.mkdir()
        self.adapter.DESTINATION.write_text('{"Profiles":[]}')
        with patch.object(self.adapter, "copy_settings") as copy:
            self.adapter.install()
            copy.assert_not_called()
        self.assertTrue((self.state / "iterm/installed").exists())

    def test_missing_native_profile_does_not_erase_saved_settings(self):
        self.native["New Bookmarks"] = []
        before = (self.shared / "settings.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "no native profile"):
            self.adapter.sync()
        self.assertEqual(before, (self.shared / "settings.json").read_bytes())

    def test_no_hotkey_is_exported_without_creating_one(self):
        self.native["New Bookmarks"][0]["Has Hotkey"] = False
        self.adapter.sync()
        settings = json.loads((self.shared / "settings.json").read_text())
        self.assertFalse(settings["Preferences"]["New Bookmarks"][0]["Has Hotkey"])
        with patch.object(self.adapter, "load_theme", return_value={}):
            native, _ = self.adapter.build_preferences(self.native)
        self.assertEqual(len(native["New Bookmarks"]), 1)

    def test_watches_native_inputs_only(self):
        self.assertEqual(
            self.adapter.WATCH_PATHS, (self.adapter.PREFERENCES, self.adapter.DESTINATION.parent)
        )
        self.assertNotIn(self.shared, self.adapter.WATCH_PATHS)

    def test_custom_preferences_folder_remains_usable_for_exports(self):
        self.native["LoadPrefsFromCustomFolder"] = True
        self.native["PrefsCustomFolder"] = "/Users/fixture/private-settings"
        raw = plistlib.dumps(self.native, fmt=plistlib.FMT_BINARY)
        with patch("src.apps.iterm.subprocess.run", return_value=SimpleNamespace(stdout=raw)):
            data, _ = ITerm.read_preferences(self.adapter)
        self.assertTrue(data["LoadPrefsFromCustomFolder"])
        self.adapter.sync()
        public = (self.shared / "settings.json").read_text()
        self.assertNotIn("PrefsCustomFolder", public)
        self.assertNotIn("/Users/fixture", public)
