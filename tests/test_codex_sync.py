"""Codex sync preserves local state and fails safely."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tomlkit

from src.apps.codex import Codex


class CodexSyncTests(unittest.TestCase):
    def test_merge_preserves_local_state_and_rerun_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared = root / "shared.toml"
            target = root / "local.toml"
            backups = root / "backups"
            shared.write_text('model="new"\n[desktop]\ntheme="dark"\n')
            target.write_text(
                '# private comment\nmodel="old"\nnotify=["/local/script"]\n'
                '[desktop]\ntheme="light"\nlocal_path="/private"\n'
                '[projects."/private/project"]\ntrust_level="trusted"\n'
            )
            settings = {
                "shared": str(shared),
                "destination": str(target),
                "baseline": str(root / "baseline"),
                "local_only": [["projects"], ["notify"], ["desktop", "local_path"]],
                "backups": str(backups),
            }
            with patch("src.apps.base.load", return_value=settings):
                adapter = Codex()
            adapter.sync()
            data = tomlkit.parse(target.read_text())
            self.assertEqual(data["model"], "old")
            self.assertEqual(data["desktop"]["local_path"], "/private")
            self.assertIn("/private/project", data["projects"])
            self.assertIn("# private comment", target.read_text())
            self.assertTrue(backups.exists())
            before = target.stat().st_mtime_ns
            adapter.sync()
            self.assertEqual(target.stat().st_mtime_ns, before)
            self.assertGreaterEqual(len(list(backups.iterdir())), 1)
            self.assertNotIn("/private", shared.read_text())
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_install_copies_missing_presets_once_without_daemon_sync(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared, target = root / "shared.toml", root / "local.toml"
            shared.write_text('model="preset"\n')
            target.write_text('[projects."/private/project"]\ntrust_level="trusted"\n')
            settings = {
                "shared": str(shared),
                "destination": str(target),
                "backups": str(root / "backups"),
                "baseline": str(root / "baseline"),
                "local_only": [["projects"]],
            }
            with (
                patch("src.apps.base.load", return_value=settings),
                patch("src.apps.base.STATE", root / "state"),
            ):
                adapter = Codex()
                adapter.install()
                result = tomlkit.parse(target.read_text())
                self.assertEqual(result["model"], "preset")
                self.assertIn("/private/project", result["projects"])
                self.assertNotIn("/private/project", shared.read_text())
                before = target.read_bytes()
                shared.write_text('model="changed"\n')
                adapter.install()
                self.assertEqual(target.read_bytes(), before)

    def test_invalid_or_conflicting_input_leaves_local_file_untouched(self):
        for shared_text, local_text in [
            ("broken = [", 'model="local"'),
            ('model="shared"', "broken = ["),
        ]:
            with self.subTest(shared=shared_text), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                shared, target = root / "shared", root / "local"
                shared.write_text(shared_text)
                target.write_text(local_text)
                with patch(
                    "src.apps.base.load",
                    return_value={
                        "shared": str(shared),
                        "destination": str(target),
                        "backups": str(root / "backups"),
                        "baseline": str(root / "baseline"),
                        "local_only": [],
                    },
                ):
                    adapter = Codex()
                with self.assertRaises(ValueError):
                    adapter.sync()
                self.assertEqual(target.read_text(), local_text)
                self.assertFalse((root / "backups").exists())

    def test_new_keys_deletions_and_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared, target = root / "shared", root / "local"
            shared.write_text('model="a"\n')
            target.write_text('model="b"\n')
            with patch(
                "src.apps.base.load",
                return_value={
                    "shared": str(shared),
                    "destination": str(target),
                    "backups": str(root / "backups"),
                    "baseline": str(root / "base"),
                    "local_only": [["projects"], ["mcp_servers", "*", "env"]],
                },
            ):
                adapter = Codex()
            adapter.sync()
            target.write_text(
                target.read_text() + 'new_feature=true\n[mcp_servers.test.env]\nTOKEN="private"\n'
            )
            adapter.sync()
            self.assertTrue(tomlkit.parse(shared.read_text())["new_feature"])
            self.assertNotIn("private", shared.read_text())
            shared.write_text('model="b"\n')
            adapter.sync()
            self.assertNotIn("new_feature", tomlkit.parse(target.read_text()))
            self.assertIn("private", target.read_text())
            target.write_text(target.read_text().replace('model="b"', 'model="local"'))
            shared.write_text('model="repo"\n')
            before = [p.read_bytes() for p in (target, shared, root / "base")]
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                adapter.sync()
            self.assertEqual(before, [p.read_bytes() for p in (target, shared, root / "base")])

    def test_table_replacement_cannot_erase_excluded_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared, target = root / "shared", root / "local"
            shared.write_text("")
            target.write_text('[desktop]\nprivate="keep"\n')
            with patch(
                "src.apps.base.load",
                return_value={
                    "shared": str(shared),
                    "destination": str(target),
                    "backups": str(root / "backups"),
                    "baseline": str(root / "base"),
                    "local_only": [["desktop", "private"]],
                },
            ):
                adapter = Codex()
            adapter.sync()
            shared.write_text('desktop="replacement"\n')
            before = target.read_bytes()
            with self.assertRaisesRegex(ValueError, "local fields"):
                adapter.sync()
            self.assertEqual(target.read_bytes(), before)

    def test_missing_file_after_baseline_stops_without_writes(self):
        for missing in ("local", "shared", "both"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                files = {name: root / name for name in ("local", "shared", "baseline")}
                for file in files.values():
                    file.write_text('model="synthetic"\n')
                for name in ("local", "shared") if missing == "both" else (missing,):
                    files[name].unlink()
                settings = {
                    "shared": str(files["shared"]),
                    "destination": str(files["local"]),
                    "baseline": str(files["baseline"]),
                    "backups": str(root / "backups"),
                    "local_only": [],
                }
                before = {p.name: p.read_bytes() for p in root.iterdir()}
                with patch("src.apps.base.load", return_value=settings):
                    adapter = Codex()
                with self.assertRaisesRegex(FileNotFoundError, "restore missing configuration"):
                    adapter.sync()
                self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})

    def test_first_run_initializes_missing_files(self):
        for missing in ("local", "shared", "both"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name in ("local", "shared"):
                    if missing not in (name, "both"):
                        (root / name).write_text('model="synthetic"\n')
                with patch(
                    "src.apps.base.load",
                    return_value={
                        "shared": str(root / "shared"),
                        "destination": str(root / "local"),
                        "baseline": str(root / "baseline"),
                        "backups": str(root / "backups"),
                        "local_only": [],
                    },
                ):
                    adapter = Codex()
                adapter.sync()
                expected = {} if missing == "both" else {"model": "synthetic"}
                for name in ("local", "shared", "baseline"):
                    self.assertEqual(tomlkit.parse((root / name).read_text()), expected)

    def test_existing_empty_file_still_intentionally_removes_all_portable_keys(self):
        for empty in ("local", "shared"):
            with self.subTest(empty=empty), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name in ("local", "shared", "baseline"):
                    (root / name).write_text('model="synthetic"\n')
                (root / empty).write_text("")
                with patch(
                    "src.apps.base.load",
                    return_value={
                        "shared": str(root / "shared"),
                        "destination": str(root / "local"),
                        "baseline": str(root / "baseline"),
                        "backups": str(root / "backups"),
                        "local_only": [],
                    },
                ):
                    adapter = Codex()
                adapter.sync()
                for name in ("local", "shared", "baseline"):
                    self.assertEqual(tomlkit.parse((root / name).read_text()), {})
