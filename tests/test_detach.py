"""Detachment preserves data and refuses unsafe or changing sources."""

import os
import plistlib
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import cli
from src import detach as operation


class DetachTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.home = self.base / "home"
        self.root = self.base / "public"
        self.private = self.base / "private"
        for root in (self.home, self.root / "home", self.private / "home"):
            root.mkdir(parents=True)
        self.agent = self.home / "agent.plist"
        self.agent.write_bytes(
            plistlib.dumps(
                {
                    "Label": "com.dotfiles.sync",
                    "WorkingDirectory": str(self.root),
                }
            )
        )
        for patcher in (
            patch.object(Path, "home", return_value=self.home),
            patch.object(operation, "STATE", self.base / "state"),
            patch.object(
                operation, "SYNC", {"agent": str(self.agent), "label": "com.dotfiles.sync"}
            ),
            patch.object(operation, "load_catalog", return_value=()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.run = patch.object(operation.subprocess, "run", side_effect=self.launchctl).start()
        self.addCleanup(patch.stopall)

    def launchctl(self, command, **kwargs):
        return SimpleNamespace(returncode=0 if self.agent.exists() else 1)

    def file_link(self, name=".zshrc"):
        source = self.root / "home" / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"synthetic settings\n")
        destination = self.home / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(source)
        return source, destination

    def detach(self):
        operation.detach(self.root, self.private)

    def test_both_repos_generated_files_directories_and_reruns(self):
        source, target = self.file_link()
        _, generated = self.file_link(".config/app/generated")
        ssh = self.private / "home/.ssh"
        ssh.mkdir(mode=0o700)
        key = ssh / "key"
        key.write_bytes(b"synthetic private bytes\n")
        key.chmod(0o600)
        (ssh / "alias").symlink_to(key)
        outside = self.base / "outside"
        outside.write_text("external")
        (ssh / "external").symlink_to(os.path.relpath(outside, ssh))
        (self.home / ".ssh").symlink_to(ssh, target_is_directory=True)
        unrelated = self.home / "unrelated"
        unrelated.symlink_to(outside)
        settings = self.root / "config/AGENTS.md"
        settings.parent.mkdir()
        settings.write_text("synthetic instructions")
        destination = self.home / ".codex/AGENTS.md"
        destination.parent.mkdir()
        destination.symlink_to(settings)
        stage = SimpleNamespace(
            configuration=[
                SimpleNamespace(
                    source="config/AGENTS.md",
                    destination=".codex/AGENTS.md",
                )
            ]
        )
        with patch.object(operation, "load_catalog", return_value=(stage,)):
            self.detach()
            self.detach()
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.read_bytes(), source.read_bytes())
        self.assertFalse(generated.is_symlink())
        self.assertFalse(destination.is_symlink())
        self.assertFalse((self.home / ".ssh").is_symlink())
        self.assertEqual((self.home / ".ssh/key").read_bytes(), key.read_bytes())
        self.assertEqual((self.home / ".ssh/key").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.home / ".ssh").stat().st_mode & 0o777, 0o700)
        self.assertFalse((self.home / ".ssh/alias").is_symlink())
        self.assertTrue((self.home / ".ssh/external").samefile(outside))
        self.assertTrue(unrelated.is_symlink())
        self.assertFalse(self.agent.exists())
        self.assertEqual(sum(call.args[0][1] == "bootout" for call in self.run.call_args_list), 1)

    def test_socket_inside_directory_blocks_all_changes(self):
        _, target = self.file_link()
        folder = self.private / "home/.ssh"
        folder.mkdir()
        (self.home / ".ssh").symlink_to(folder)
        with socket.socket(socket.AF_UNIX) as connection:
            connection.bind(str(folder / "control"))
            with self.assertRaisesRegex(RuntimeError, "special file"):
                self.detach()
        self.assertTrue(target.is_symlink())
        self.assertTrue(self.agent.exists())
        self.run.assert_not_called()
        self.assertFalse((self.base / "state").exists())

    def test_broken_target_and_directory_cycle_block_changes(self):
        source, target = self.file_link()
        source.unlink()
        with self.assertRaisesRegex(RuntimeError, "nothing changed"):
            self.detach()
        target.unlink()
        folder = self.root / "home/cycle"
        folder.mkdir()
        (folder / "back").symlink_to(folder)
        (self.home / "cycle").symlink_to(folder)
        with self.assertRaisesRegex(RuntimeError, "Directory cycle"):
            self.detach()
        self.run.assert_not_called()
        self.assertTrue(self.agent.exists())

    def test_copy_failure_keeps_original_link_and_source(self):
        source, target = self.file_link()
        with (
            patch.object(operation.shutil, "copy2", side_effect=OSError("synthetic disk full")),
            self.assertRaisesRegex(OSError, "disk full"),
        ):
            self.detach()
        self.assertTrue(target.is_symlink())
        self.assertEqual(source.read_bytes(), b"synthetic settings\n")
        self.assertEqual(list(self.home.glob(".dotfiles-detach-*")), [])

    def test_directory_install_failure_restores_original_link(self):
        folder = self.root / "home/folder"
        folder.mkdir()
        (folder / "file").write_text("keep")
        target = self.home / "folder"
        target.symlink_to(folder)
        with (
            patch.object(Path, "rename", side_effect=OSError("synthetic rename failure")),
            self.assertRaisesRegex(OSError, "rename failure"),
        ):
            self.detach()
        self.assertTrue(target.is_symlink())
        self.assertTrue(target.samefile(folder))
        self.assertEqual((folder / "file").read_text(), "keep")

    def test_changing_source_or_link_is_not_overwritten(self):
        source, target = self.file_link()
        copy = operation.shutil.copy2

        def changing(entry, destination):
            result = copy(entry, destination)
            entry.write_text("changed during copy")
            return result

        with (
            patch.object(operation.shutil, "copy2", side_effect=changing),
            self.assertRaisesRegex(RuntimeError, "Source changed"),
        ):
            self.detach()
        self.assertTrue(target.is_symlink())
        self.assertEqual(source.read_text(), "changed during copy")

    def test_unload_failure_or_unrelated_agent_keeps_links(self):
        _, target = self.file_link()
        with (
            patch.object(
                operation.subprocess,
                "run",
                side_effect=[
                    SimpleNamespace(returncode=0),
                    subprocess.CalledProcessError(1, "launchctl"),
                ],
            ),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            self.detach()
        self.assertTrue(target.is_symlink())
        self.assertTrue(self.agent.exists())
        self.agent.write_bytes(plistlib.dumps({"Label": "unrelated"}))
        self.run.reset_mock()
        with self.assertRaisesRegex(RuntimeError, "unrelated LaunchAgent"):
            self.detach()
        self.run.assert_not_called()

    def test_cli_dispatch_does_not_apply_or_sync(self):
        with (
            patch.object(cli.sys, "platform", "darwin"),
            patch.object(cli, "detach") as detach,
            patch.object(cli, "load_catalog") as catalog,
            patch.object(cli, "apply") as apply,
            patch.object(cli, "run_shell") as shell,
        ):
            cli.main(["detach"], self.root)
        detach.assert_called_once_with(self.root)
        catalog.assert_not_called()
        apply.assert_not_called()
        shell.assert_not_called()
