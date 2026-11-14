"""Exercise Linux selection and file lifecycle without changing the real home."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import apps, cli, config, linux
from src import detach as operation

ROOT = Path(__file__).resolve().parents[1]


class LinuxTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.home = self.base / "user"
        self.home.mkdir()
        platform = patch("sys.platform", "linux")
        platform.start()
        self.addCleanup(platform.stop)

    def test_linux_selection_has_cli_packages_and_no_desktop_settings(self):
        stages = config.load_catalog(ROOT)
        self.assertEqual(
            [s.id for s in stages], ["setup-terminal", "setup-development", "setup-codex"]
        )
        self.assertEqual(config.collect_copy_settings(ROOT), ("home", "codex"))
        self.assertEqual(config.collect_apps(ROOT), ("codex",))
        self.assertEqual({p.kind for p in config.collect_packages(stages)}, {"apt", "release"})
        self.assertEqual(
            [c.destination for s in stages for c in s.configuration], [".codex/AGENTS.md"]
        )

    def test_apply_preserves_existing_files_and_skips_mac_home_and_daemon(self):
        original = self.home / ".zshrc"
        original.write_text("original shell\n")
        with (
            patch.object(Path, "home", return_value=self.home),
            patch.object(apps, "sync_apps"),
            patch.object(cli, "run_shell"),
            patch.object(linux, "set_zsh_default") as default_shell,
        ):
            cli.apply(ROOT, config.load_catalog(ROOT))
            backups = list(self.home.glob("dotfiles-backup-*/.zshrc"))
            self.assertEqual([p.read_text() for p in backups], ["original shell\n"])
            self.assertTrue(original.is_symlink())
            self.assertFalse((self.home / ".config/karabiner").exists())
            self.assertFalse((self.home / ".config/linearmouse").exists())
            cli.apply(ROOT, config.load_catalog(ROOT))
            self.assertEqual(backups, list(self.home.glob("dotfiles-backup-*/.zshrc")))
        self.assertTrue(default_shell.called)
        with patch.object(apps.subprocess, "run") as run:
            apps.install_agent(ROOT, ("codex",))
        run.assert_not_called()

    def test_disabling_home_presets_preserves_the_login_shell(self):
        with (
            patch.object(cli, "collect_copy_settings", return_value=()),
            patch.object(apps, "sync_apps"),
            patch.object(linux, "set_zsh_default") as default_shell,
        ):
            cli.apply(ROOT, config.load_catalog(ROOT))
        default_shell.assert_not_called()

    def test_explicit_private_file_destination_and_home_escape(self):
        source = self.base / "private/key"
        source.parent.mkdir()
        source.write_text("synthetic\n")
        with patch.object(Path, "home", return_value=self.home):
            cli.main(["link", str(source), ".ssh/id_example"])
            self.assertEqual((self.home / ".ssh/id_example").resolve(), source.resolve())
            for destination in ["../outside", "/tmp/outside"]:
                with self.assertRaises(SystemExit):
                    cli.main(["link", str(source), destination])
            (self.home / "escape").symlink_to(self.base)
            with self.assertRaises(SystemExit):
                cli.main(["link", str(source), "escape/key"])

    def test_detach_materializes_public_and_private_platform_links_without_launchctl(self):
        public, private = self.base / "public", self.home / ".dotfiles_secret"
        (public / "home").mkdir(parents=True)
        overlay = private / "home-platform/linux"
        overlay.mkdir(parents=True)
        (overlay / ".gitconfig-platform").write_text("# local helper\n")
        target = self.home / ".gitconfig-platform"
        target.symlink_to(overlay / target.name)
        with (
            patch.object(Path, "home", return_value=self.home),
            patch.object(operation, "load_catalog", return_value=()),
            patch.object(operation, "STATE", self.base / "state"),
            patch.object(operation.subprocess, "run") as run,
        ):
            operation.detach(public)
            operation.detach(public)
        run.assert_not_called()
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.read_text(), "# local helper\n")

    def test_release_failure_preserves_installed_executable(self):
        destination = self.home / ".local/bin/fzf"
        destination.parent.mkdir(parents=True)
        destination.write_text("original executable\n")

        def download(url, target):
            if target.name == "release.json":
                target.write_text(
                    '{"tag_name":"v1.0","assets":[{"name":"fzf-1.0-linux_arm64.tar.gz","browser_download_url":"https://example.invalid/archive","digest":"sha256:wrong"}]}'
                )
            else:
                target.write_bytes(b"invalid archive")

        with (
            patch.object(Path, "home", return_value=self.home),
            patch.object(linux.platform, "machine", return_value="aarch64"),
            patch.object(linux, "download", side_effect=download),
            self.assertRaisesRegex(RuntimeError, "Checksum mismatch"),
        ):
            linux.install_release("fzf", update=False)
        self.assertEqual(destination.read_text(), "original executable\n")


if __name__ == "__main__":
    unittest.main()
