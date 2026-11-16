import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import yaml

from src import apps
from src import cli as installer
from src import config as model
from src.apps.base import write_if_changed

SOURCE = Path(__file__).resolve().parents[1]
main = installer.main
configuration = installer


class InstallerTests(unittest.TestCase):
    def setUp(self):
        platform_patch = patch("sys.platform", "darwin")
        platform_patch.start()
        self.addCleanup(platform_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo with spaces"
        self.root.mkdir(parents=True)
        (self.root / "config").mkdir()
        shutil.copy2(SOURCE / "config/setup.yaml", self.root / "config/setup.yaml")
        (self.root / "home/.config").mkdir(parents=True)
        (self.root / "home/.zshrc").write_text("# fixture shell\n")
        (self.root / "home/.config/starship.toml").write_text("# fixture prompt\n")
        self.catalog = model.load_catalog(self.root)
        for bundle in self.catalog:
            for config in bundle.configuration:
                source = self.root / config.source
                source.parent.mkdir(parents=True, exist_ok=True)
                if (SOURCE / config.source).is_dir():
                    source.mkdir(exist_ok=True)
                else:
                    source.write_text("original\n")
        self.local_home = Path(self.temp.name) / "local-home"
        self.local_home.mkdir()
        home_patch = patch.object(configuration.Path, "home", return_value=self.local_home)
        home_patch.start()
        self.addCleanup(home_patch.stop)
        for module in ("src.apps", "src.apps.base", "src.apps.vscode", "src.apps.iterm"):
            state_patch = patch(module + ".STATE", self.local_home / "state")
            state_patch.start()
            self.addCleanup(state_patch.stop)
        self.selected = set()
        fork = patch("src.cli.run_shell")
        fork.start()
        self.addCleanup(fork.stop)
        self.shell_command("uname", "echo Darwin\n")

    def init_git(self, *, commit=False):
        self.git("init", "-q")
        if commit:
            self.git("config", "user.name", "Fixture")
            self.git("config", "user.email", "fixture@example.test")
            self.git("add", ".")
            self.git("-c", "commit.gpgsign=false", "commit", "-qm", "fixture")

    def copy_runtime(self):
        shutil.copytree(
            SOURCE / "src", self.root / "src", ignore=shutil.ignore_patterns("__pycache__")
        )

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], text=True)

    def stages(self):
        return tuple(stage for stage in self.catalog if stage.id in self.selected)

    def configure(self):
        path = self.root / "config/setup.yaml"
        document = yaml.safe_load(path.read_text())
        document["copy_settings"] = [
            name
            for name in document["copy_settings"]
            if name == "home" or "setup-" + name in self.selected
        ]
        document["sync"]["apps"] = [
            name for name in ("codex", "vscode", "iterm") if "setup-" + name in self.selected
        ]
        path.write_text(
            yaml.safe_dump(
                {
                    key: value
                    for key, value in document.items()
                    if key in {"settings", "sync", "copy_settings"} or key in self.selected
                },
                sort_keys=False,
            )
        )

    def test_setup_groups_match_the_requested_order(self):
        self.assertEqual(
            [stage.id for stage in self.catalog],
            [
                "setup-terminal",
                "setup-macos",
                "setup-development",
                "setup-codex",
                "setup-desktop",
                "setup-vscode",
                "setup-iterm",
            ],
        )
        document = yaml.safe_load((self.root / "config/setup.yaml").read_text())
        for name in ("macos", "vscode", "iterm"):
            self.assertNotIn("settings", document["setup-" + name])
            self.assertIn(name, document["settings"])

    def test_selection_and_shared_dependency_are_resolved_once(self):
        self.selected.add("setup-desktop")
        plan = self.stages()
        names = [p.name for p in model.collect_packages(plan)]
        self.assertEqual(names.count("mas"), 1)
        self.assertNotIn("visual-studio-code", names)
        self.assertNotIn("tldr", names)

    def test_catalog_rejects_overlapping_ownership(self):
        path = self.root / "config/setup.yaml"
        settings = yaml.safe_load(path.read_text())
        settings["setup-vscode"]["link"] = [{"source": "config/iterm2"}]
        path.write_text(yaml.safe_dump(settings))
        with self.assertRaisesRegex(ValueError, "overlapping owners"):
            model.load_catalog(self.root)

    def test_cli_installs_github_cli_alongside_git(self):
        self.selected.add("setup-terminal")
        self.assertTrue(
            {"gh", "git", "git-lfs"} <= {p.name for p in model.collect_packages(self.stages())}
        )

    def test_macos_commands_and_vscode_associations_have_separate_settings(self):
        settings = model.load("macos")
        self.assertNotIn("editor", settings)
        self.assertEqual(len(model.load("vscode")["file_associations"]), 6)
        self.assertIn("destination", model.load("iterm"))
        with patch.object(configuration.subprocess, "run") as run:
            configuration.macos_preferences()
        commands = [call.args[0] for call in run.call_args_list if call.args[0][0] == "defaults"]
        self.assertEqual(len(commands), 19)
        self.assertIn(
            ["defaults", "-currentHost", "write", "com.apple.controlcenter", "Sound", "-int", "18"],
            commands,
        )
        self.assertNotIn("duti", {call.args[0][0] for call in run.call_args_list})
        settings["defaults"] = ['defaults write test greeting "hello world"']
        with (
            patch.object(configuration, "load", return_value=settings),
            patch.object(configuration.subprocess, "run") as run,
        ):
            configuration.macos_preferences()
        self.assertIn(
            ["defaults", "write", "test", "greeting", "hello world"],
            [call.args[0] for call in run.call_args_list],
        )

    def test_vscode_associations_do_not_require_the_macos_stage(self):
        self.selected.add("setup-vscode")
        self.shell_command("duti", 'echo "$*" >> "$COMMAND_LOG"\n')
        log = Path(self.temp.name) / "associations.log"
        with (
            patch.object(apps, "sync_apps"),
            patch.dict(
                os.environ,
                {
                    "PATH": str(Path(self.temp.name) / "commands")
                    + os.pathsep
                    + os.environ["PATH"],
                    "COMMAND_LOG": str(log),
                },
            ),
        ):
            configuration.apply(self.root, self.stages(), command="install")
        self.assertEqual(len(log.read_text().splitlines()), 6)

    def test_unknown_stage_actions_are_rejected(self):
        path = self.root / "config/setup.yaml"
        data = yaml.safe_load(path.read_text())
        data["setup-test"] = {"title": "Test", "description": "Test", "mystery": True}
        path.write_text(yaml.safe_dump(data))
        with self.assertRaisesRegex(ValueError, "Unknown actions"):
            model.load_catalog(self.root)

    def test_daemon_selection_is_independent_of_preset_stages(self):
        path = self.root / "config/setup.yaml"
        document = yaml.safe_load(path.read_text())
        for name in ("codex", "vscode", "iterm"):
            del document["setup-" + name]
        path.write_text(yaml.safe_dump(document))
        model.load_catalog(self.root)
        self.assertEqual(model.collect_apps(self.root), ("codex", "vscode", "iterm"))
        for invalid in (["unsupported"], ["vscode", "vscode"], "vscode"):
            document["sync"]["apps"] = invalid
            path.write_text(yaml.safe_dump(document))
            with self.assertRaises(ValueError):
                model.load_catalog(self.root)

    def test_yaml_copy_selection_and_daemon_switch_are_validated(self):
        path = self.root / "config/setup.yaml"
        original = path.read_text()
        for invalid in (True, False, "vscode", ["unknown"], ["vscode", "vscode"], [False]):
            with self.subTest(invalid=invalid):
                document = yaml.safe_load(original)
                document["copy_settings"] = invalid
                path.write_text(yaml.safe_dump(document))
                with self.assertRaisesRegex(ValueError, "copy_settings"):
                    model.load_catalog(self.root)
        document = yaml.safe_load(original)
        document["sync"]["enabled"] = "false"
        path.write_text(yaml.safe_dump(document))
        with self.assertRaisesRegex(ValueError, "must be true or false"):
            model.load_catalog(self.root)

    def test_scalar_package_action_is_rejected_before_installation(self):
        path = self.root / "config/setup.yaml"
        data = yaml.safe_load(path.read_text())
        data["setup-terminal"]["brew"] = "git"
        path.write_text(yaml.safe_dump(data))
        with self.assertRaisesRegex(ValueError, "setup-terminal.brew"):
            model.load_catalog(self.root)

    def test_home_links_even_with_no_app_stages(self):
        with patch.object(apps, "sync_apps") as sync:
            configuration.apply(self.root, self.stages())
        target = self.local_home / ".config/starship.toml"
        self.assertTrue(target.is_symlink())
        self.assertFalse(target.parent.is_symlink())
        self.assertEqual(target.resolve(), (self.root / "home/.config/starship.toml").resolve())
        extra = self.local_home / ".config/new-app.conf"
        extra.write_text("local only")
        self.assertFalse((self.root / "home/.config/new-app.conf").exists())
        sync.assert_called_once_with(self.root, ("codex", "vscode", "iterm"), initialize=())

    def test_missing_home_source_stops_before_linking(self):
        shutil.rmtree(self.root / "home")
        with self.assertRaisesRegex(RuntimeError, "Restore the repository home/"):
            configuration.apply(self.root, self.stages())
        self.assertEqual(list(self.local_home.iterdir()), [])

    def test_correct_directory_symlink_is_preserved_on_rerun(self):
        (self.local_home / ".config").symlink_to(self.root / "home/.config")
        source = self.root / "home/.config/personal.conf"
        source.write_text("personal")
        before = (self.local_home / ".config").lstat().st_mtime_ns
        configuration.link_home(self.root / "home", self.local_home, root=self.root)
        self.assertTrue((self.local_home / ".config").is_symlink())
        self.assertEqual((self.local_home / ".config/personal.conf").read_text(), "personal")
        self.assertEqual(source.read_text(), "personal")
        configuration.link_home(self.root / "home", self.local_home, root=self.root)
        self.assertFalse((self.root / ".private/backups/links").exists())
        self.assertEqual((self.local_home / ".config").lstat().st_mtime_ns, before)

    def test_link_replaces_symlinks_without_touching_targets_or_creating_backups(self):
        source = self.root / "home/.zshrc"
        other = self.local_home / "other"
        other.write_text("local target")
        destination = self.local_home / ".zshrc"
        for target in (other, self.local_home / "missing"):
            with self.subTest(target=target):
                destination.symlink_to(target)
                configuration.link(source, destination, root=self.root)
                self.assertEqual(destination.resolve(), source.resolve())
                before = destination.lstat().st_mtime_ns
                configuration.link(source, destination, root=self.root)
                self.assertEqual(destination.lstat().st_mtime_ns, before)
                destination.unlink()
        self.assertEqual(other.read_text(), "local target")
        self.assertFalse((self.root / ".private/backups").exists())

    def test_linking_a_file_to_itself_preserves_the_file_without_backup(self):
        source = self.local_home / ".zshrc"
        source.write_text("personal shell")
        main(["link", str(source), ".zshrc"], self.root)
        self.assertFalse(source.is_symlink())
        self.assertEqual(source.read_text(), "personal shell")
        self.assertFalse((self.root / ".private/backups").exists())

    def test_link_backs_up_a_directory_collision_inside_the_checkout(self):
        destination = self.local_home / ".zshrc"
        destination.mkdir()
        (destination / "personal").write_text("preserved")
        configuration.link(self.root / "home/.zshrc", destination, root=self.root)
        (backup,) = (self.root / ".private/backups/links").glob("*/.zshrc")
        self.assertEqual((backup / "personal").read_text(), "preserved")
        self.assertTrue(destination.is_symlink())

    def test_link_does_not_copy_a_directory_symlink_target_or_clean_unrelated_links(self):
        original = self.local_home / "external"
        original.mkdir()
        (original / "local-only").write_text("preserved")
        (self.local_home / ".config").symlink_to(original)
        unrelated = self.local_home / "unrelated"
        unrelated.symlink_to(self.root / "absent")
        main(["link", str(self.root / "home")], self.root)
        self.assertFalse((self.local_home / ".config/local-only").exists())
        self.assertEqual((original / "local-only").read_text(), "preserved")
        self.assertTrue(unrelated.is_symlink())

    def test_seed_mode_is_rejected(self):
        with self.assertRaises(TypeError):
            model.Configuration("home/example", mode="seed")

    def test_install_leaves_existing_index_untouched(self):
        self.init_git(commit=True)
        (self.root / "home/.zshrc").write_text("existing edit")
        self.git("add", "home/.zshrc")
        before = self.git("diff", "--cached")
        self.configure()
        with patch("builtins.input", side_effect=AssertionError("Unexpected prompt")):
            main(["install"], self.root)
        self.assertEqual(self.git("diff", "--cached"), before)

    def test_real_entrypoint_uses_edited_config_without_input(self):
        self.copy_runtime()
        self.configure()
        for name in ("install", ".python-version", "pyproject.toml"):
            shutil.copy2(SOURCE / name, self.root / name)
        self.shell_command("xcode-select", "exit 0\n")
        self.shell_command(
            "uv",
            'case "$1" in\n'
            '  venv) mkdir -p .venv/bin; '
            'printf \'#!/bin/bash\\nexec "$INSTALLER_TEST_PYTHON" "$@"\\n\' '
            '> .venv/bin/python; chmod +x .venv/bin/python ;;\n'
            '  pip) [[ "$*" == *"--python .venv/bin/python --group installer"* ]] ;;\n'
            '  *) exit 91 ;;\n'
            "esac\n",
        )
        result = subprocess.run(
            ["bash", str(self.root / "install")],
            input="",
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "HOME": str(self.local_home),
                "INSTALLER_TEST_PYTHON": sys.executable,
                # The CLI prepends Homebrew to PATH; a function keeps cleanup isolated.
                "BASH_FUNC_brew%%": '() { [[ "$*" == cleanup ]]; }',
                "PATH": str(Path(self.temp.name) / "commands") + os.pathsep + os.environ["PATH"],
            },
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / ".install/choices.local.json").exists())
        self.assertTrue((self.local_home / ".zshrc").is_symlink())

    def test_python_bootstrap_is_isolated_retryable_and_global_libraries_are_opt_in(self):
        self.copy_runtime()
        shutil.copy2(SOURCE / ".python-version", self.root / ".python-version")
        user_python = self.local_home / ".local/bin/python3"
        user_python.parent.mkdir(parents=True)
        user_python.write_text("existing user Python\n")
        self.shell_command("sudo", 'exec "$@"\n')
        self.shell_command("apt-get", "exit 0\n")
        self.shell_command(
            "uv",
            'printf "%s\\n" "$*" >> "$RUNTIME_LOG"\n'
            'case "$1" in\n'
            '  venv) mkdir -p .venv/bin; ln -sf "$INSTALLER_TEST_PYTHON" .venv/bin/python ;;\n'
            '  pip) if [[ "$*" == *"--group installer"* && "$RUNTIME_FAIL" == 1 ]]; '
            'then exit 89; fi ;;\n'
            '  python) [[ "$2" == install && "$*" == *--default* ]] ;;\n'
            '  *) exit 91 ;;\n'
            'esac\n',
        )
        log = Path(self.temp.name) / "runtime.log"
        env = {
            **os.environ,
            "HOME": str(self.local_home),
            "PATH": str(Path(self.temp.name) / "commands") + os.pathsep + os.environ["PATH"],
            "INSTALLER_TEST_PYTHON": sys.executable,
            "RUNTIME_LOG": str(log),
            "BASH_FUNC_source%%": "() { ID=ubuntu; }",
        }
        for platform, script in (("Darwin", "system.sh"), ("Linux", "linux.sh")):
            self.shell_command("uname", f"echo {platform}\n")
            for libraries in ([], ["fixture-library"]):
                with self.subTest(platform=platform, global_libraries=libraries):
                    (self.root / "pyproject.toml").write_text(
                        f"[dependency-groups]\ninstaller = []\nglobal = {libraries!r}\n"
                    )
                    log.unlink(missing_ok=True)
                    failed = subprocess.run(
                        ["bash", str(self.root / "src" / script), "--python"],
                        cwd=self.root,
                        env={**env, "RUNTIME_FAIL": "1"},
                        capture_output=True,
                        text=True,
                    )
                    self.assertNotEqual(failed.returncode, 0)
                    self.assertNotIn("--group global", log.read_text())
                    log.unlink()
                    result = subprocess.run(
                        ["bash", str(self.root / "src" / script), "--python"],
                        cwd=self.root,
                        env={**env, "RUNTIME_FAIL": "0"},
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    commands = log.read_text().splitlines()
                    self.assertIn(
                        "pip install --python .venv/bin/python --group installer", commands
                    )
                    self.assertEqual(
                        any("--default" in command for command in commands), bool(libraries)
                    )
                    global_commands = [
                        command for command in commands if "--group global" in command
                    ]
                    self.assertEqual(
                        global_commands,
                        [f"pip install --python {user_python} --break-system-packages --group global"]
                        if libraries
                        else [],
                    )
                    self.assertEqual(user_python.read_text(), "existing user Python\n")
                    self.assertTrue((self.root / ".venv/bin/python").is_file())

    def test_launcher_help_and_maintenance_do_not_bootstrap(self):
        self.copy_runtime()
        shutil.copy2(SOURCE / "install", self.root / "install")
        for name in ("uv", "brew", "xcode-select"):
            self.shell_command(name, "echo unexpected-setup >&2; exit 91\n")
        env = {
            **os.environ,
            "HOME": str(self.local_home),
            "PATH": str(Path(self.temp.name) / "commands") + os.pathsep + os.environ["PATH"],
        }
        for args in (["--help"], ["install", "--help"], ["link", "--help"]):
            with self.subTest(args=args):
                result = subprocess.run(
                    ["bash", str(self.root / "install"), *args],
                    check=False,
                    env=env,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Usage:", result.stdout)
        for command in ("apply", "sync", "link", "fork", "detach"):
            with self.subTest(command=command):
                result = subprocess.run(
                    ["bash", str(self.root / "install"), command],
                    check=False,
                    env=env,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("Run ./install first", result.stderr)
                self.assertNotIn("unexpected-setup", result.stderr)

        for name in ("brew", "sheldon"):
            self.shell_command(name, 'echo "$0 $*"\n')
        result = subprocess.run(
            ["bash", str(self.root / "install"), "update"],
            check=False,
            env=env,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [line.split("/")[-1] for line in result.stdout.splitlines()],
            ["brew upgrade", "sheldon lock --update", "brew cleanup"],
        )

        self.configure()
        python = self.root / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text('#!/bin/bash\nexec "$INSTALLER_TEST_PYTHON" "$@"\n')
        python.chmod(0o755)
        env["INSTALLER_TEST_PYTHON"] = sys.executable
        for args in (["apply"], ["link", str(self.root / "home")]):
            with self.subTest(args=args):
                result = subprocess.run(
                    ["bash", str(self.root / "install"), *args],
                    check=False,
                    env=env,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue((self.local_home / ".zshrc").is_symlink())

    def test_cleanup_is_not_a_public_command(self):
        with self.assertRaises(SystemExit) as error:
            main(["cleanup"], self.root)
        self.assertEqual(error.exception.code, 2)

    def test_failed_install_can_rerun_the_config_without_staging(self):
        self.init_git(commit=True)
        self.selected.add("setup-desktop")
        self.configure()
        with (
            patch("src.cli.run_shell", side_effect=RuntimeError("package failed")),
            self.assertRaisesRegex(RuntimeError, "package failed"),
        ):
            main(["install"], self.root)
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")
        with (
            patch("builtins.input") as ask,
            patch("src.cli.run_shell"),
        ):
            main(["install"], self.root)
            ask.assert_not_called()

    def run_fork(self, fail=False):
        commands = Path(self.temp.name) / "commands"
        commands.mkdir(exist_ok=True)
        gh = commands / "gh"
        gh.write_text(
            "#!/bin/bash\n"
            'printf "%s\\n" "$*" >> "$FORK_LOG"\n'
            'case "$1 $2" in\n'
            '  "api user") echo friend ;;\n'
            '  "repo fork") [[ "$FORK_FAIL" != 1 ]] ;;\n'
            '  "repo view") echo dotfiles ;;\n'
            "esac\n"
        )
        gh.chmod(0o755)
        return subprocess.run(
            ["bash", str(SOURCE / "src/system.sh"), "--fork"],
            cwd=self.root,
            input="",
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "PATH": str(commands) + os.pathsep + os.environ["PATH"],
                "FORK_LOG": str(Path(self.temp.name) / "fork.log"),
                "FORK_FAIL": "1" if fail else "0",
            },
            check=False,
        )

    def test_explicit_fork_updates_origin_after_creation(self):
        self.init_git()
        origin = "https://github.com/source/dotfiles.git"
        self.git("remote", "add", "origin", origin)
        result = self.run_fork()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("remote").strip(), "origin")
        self.assertEqual(
            self.git("remote", "get-url", "origin").strip(),
            "https://github.com/friend/dotfiles.git",
        )

    def test_sync_stops_on_first_failure_and_still_registers_agent(self):
        first = SimpleNamespace(sync=Mock(side_effect=RuntimeError("invalid settings")))
        second = SimpleNamespace(sync=Mock())
        with (
            patch.object(apps, "STATE", Path(self.temp.name) / "state"),
            patch.dict(apps.APPLICATIONS, {"vscode": lambda: first, "iterm": lambda: second}),
            patch.object(apps, "install_agent") as register,
            self.assertRaisesRegex(RuntimeError, "invalid settings"),
        ):
            apps.sync_apps(self.root, ("vscode", "iterm"))
        first.sync.assert_called_once()
        second.sync.assert_not_called()
        register.assert_called_once_with(self.root, ("vscode", "iterm"))

    def shell_command(self, name, content):
        directory = Path(self.temp.name) / "commands"
        directory.mkdir(exist_ok=True)
        script = directory / name
        script.write_text("#!/bin/bash\nset -euo pipefail\n" + content)
        script.chmod(0o755)
        return script

    def run_shell(self, name, *args, fail=False):
        return subprocess.run(
            [
                "bash",
                str(SOURCE / "src/system.sh"),
                "--" + name,
                *map(str, args),
            ],
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "PATH": str(Path(self.temp.name) / "commands") + os.pathsep + os.environ["PATH"],
                "COMMAND_LOG": str(Path(self.temp.name) / "commands.log"),
                "COMMAND_FAIL": "1" if fail else "0",
            },
            check=False,
        )

    def test_package_install_uses_manifest_and_update_upgrades_everything(self):
        self.shell_command(
            "brew",
            'echo "brew $*" >> "$COMMAND_LOG"\n'
            '[[ "$COMMAND_FAIL" != 1 ]]\n',
        )
        self.shell_command("sheldon", 'echo "sheldon $*" >> "$COMMAND_LOG"\n')
        for action, expected in (
            ("install", ["brew bundle install --file=selected.Brewfile"]),
            ("update", ["brew upgrade", "sheldon lock --update", "brew cleanup"]),
        ):
            with self.subTest(action=action):
                arguments = ("selected.Brewfile",) if action == "install" else ()
                result = (
                    self.run_shell("update")
                    if action == "update"
                    else self.run_shell("packages", action, *arguments)
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                log = Path(self.temp.name) / "commands.log"
                self.assertEqual(log.read_text().splitlines(), expected)
                log.unlink()
        result = self.run_shell("update", fail=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(log.read_text().splitlines(), ["brew upgrade"])

    def test_linux_update_cleans_only_after_packages_and_plugins_succeed(self):
        self.shell_command("uname", "echo Linux\n")
        self.shell_command("sudo", 'exec "$@"\n')
        self.shell_command(
            "apt-get", 'echo "apt-get $*" >> "$COMMAND_LOG"\n'
            '[[ "$COMMAND_FAIL" != 1 ]]\n',
        )
        self.shell_command("sheldon", 'echo "sheldon $*" >> "$COMMAND_LOG"\n')
        with patch.dict(os.environ, {"BASH_FUNC_source%%": "() { ID=ubuntu; }"}):
            result = self.run_shell("update")
            self.assertEqual(result.returncode, 0, result.stderr)
            log = Path(self.temp.name) / "commands.log"
            self.assertEqual(
                log.read_text().splitlines(),
                [
                    "apt-get update",
                    "apt-get upgrade -y",
                    "sheldon lock --update",
                    "apt-get clean",
                ],
            )
            log.unlink()
            result = self.run_shell("update", fail=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(log.read_text().splitlines(), ["apt-get update"])

    def test_install_cleans_only_after_successful_apply(self):
        self.configure()
        events = []
        with (
            patch("src.cli.apply", side_effect=lambda *args, **kw: events.append("apply")) as apply,
            patch("src.cli.run_shell", side_effect=lambda *args: events.append(args)) as shell,
        ):
            main(["install"], self.root)
            self.assertEqual(events, ["apply", ("cleanup",)])
            shell.reset_mock()
            apply.side_effect = RuntimeError("apply failed")
            with self.assertRaisesRegex(RuntimeError, "apply failed"):
                main(["install"], self.root)
            shell.assert_not_called()

    def test_touch_id_preserves_enabled_entry_and_rejects_invalid_template(self):
        self.shell_command(
            "sudo", 'echo "$*" >> "$COMMAND_LOG"\n/usr/bin/install -m 0444 "${@: -2}"\n'
        )
        config = Path(self.temp.name) / "sudo_local"
        template = Path(self.temp.name) / "template"
        template.write_text("# PAM\n#auth sufficient pam_tid.so\naccount required pam_permit.so\n")
        result = self.run_shell("touch-id", config, template)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            config.read_text(),
            "# PAM\nauth sufficient pam_tid.so\naccount required pam_permit.so\n",
        )
        self.assertEqual(config.stat().st_mode & 0o777, 0o444)
        log = Path(self.temp.name) / "commands.log"
        before = log.read_text()
        result = self.run_shell("touch-id", config, template)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(log.read_text(), before)
        config.unlink()
        template.write_text("# no supported entry\n")
        result = self.run_shell("touch-id", config, template)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(config.exists())
        self.assertEqual(log.read_text(), before)

    def test_fork_failure_never_changes_local_remotes(self):
        self.init_git()
        origin = "git@github.com:source/dotfiles.git"
        self.git("remote", "add", "origin", origin)
        result = self.run_fork(fail=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git("remote").strip(), "origin")
        self.assertEqual(self.git("remote", "get-url", "origin").strip(), origin)

    def test_fork_leaves_existing_upstream_untouched(self):
        self.init_git()
        origin = "https://github.com/source/dotfiles.git"
        self.git("remote", "add", "origin", origin)
        self.git("remote", "add", "upstream", "https://github.com/other/dotfiles.git")
        result = self.run_fork()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.git("remote", "get-url", "upstream").strip(),
            "https://github.com/other/dotfiles.git",
        )

    def test_existing_configuration_is_backed_up(self):
        home = Path(self.temp.name) / "home"
        home.mkdir()
        destination = home / ".zshrc"
        destination.write_text("personal settings")
        with patch.object(configuration.Path, "home", return_value=home):
            configuration.link(self.root / "home/.zshrc", destination, root=self.root)
        self.assertTrue(destination.is_symlink())
        (backup,) = (self.root / ".private/backups/links").glob("*/.zshrc")
        self.assertEqual(backup.read_text(), "personal settings")

    def test_sync_agent_invokes_installer_directly_and_does_not_reload_unchanged(self):
        source = self.root / "src/apps/vscode.py"
        source.parent.mkdir(parents=True)
        source.write_text("# watched adapter\n")
        home = Path(self.temp.name) / "home"
        state = home / "state"
        state.mkdir(parents=True)
        adapter = SimpleNamespace(WATCH_PATHS=[self.root / "config/vscode"])
        codex_config = {
            "shared": str(self.root / "config/codex/config.toml"),
            "destination": str(home / ".codex/config.toml"),
            "baseline": str(state / "codex-baseline.toml"),
            "backups": str(state / "backups"),
        }
        with patch("src.apps.base.load", return_value=codex_config):
            codex_adapter = apps.Codex()
        with (
            patch.object(configuration.Path, "home", return_value=home),
            patch.object(apps, "STATE", state),
            patch.dict(
                apps.APPLICATIONS,
                {"vscode": lambda: adapter, "codex": lambda: codex_adapter},
            ),
            patch.object(apps.subprocess, "run") as run,
        ):
            run.return_value.returncode = 0
            apps.install_agent(self.root, ("vscode", "codex"))
            agent = home / "Library/LaunchAgents/com.dotfiles.sync.plist"
            data = plistlib.loads(agent.read_bytes())
            self.assertEqual(data["ProgramArguments"], [sys.executable, "-m", "src.cli", "sync"])
            self.assertEqual(data["WorkingDirectory"], str(self.root))
            self.assertIn(str(self.root / "config/setup.yaml"), data["WatchPaths"])
            self.assertIn(str(self.root / "src/apps/vscode.py"), data["WatchPaths"])
            self.assertIn(str(codex_adapter.SHARED), data["WatchPaths"])
            self.assertIn(codex_config["destination"], data["WatchPaths"])
            self.assertNotIn(str(home / ".codex"), data["WatchPaths"])
            self.assertFalse(any("sync.py" in p for p in data["ProgramArguments"]))
            apps.install_agent(self.root, ("vscode", "codex"))
            self.assertEqual(run.call_count, 3)
            run.assert_called_with(
                ["launchctl", "print", f"gui/{os.getuid()}/com.dotfiles.sync"],
                capture_output=True,
                check=False,
            )
            run.side_effect = [
                SimpleNamespace(returncode=1),
                SimpleNamespace(returncode=0),
                subprocess.CalledProcessError(5, "launchctl"),
            ]
            with self.assertRaises(subprocess.CalledProcessError):
                apps.install_agent(self.root, ("vscode", "codex"))
            run.side_effect = [SimpleNamespace(returncode=1), run.return_value, run.return_value]
            apps.install_agent(self.root, ("vscode", "codex"))
            run.assert_called_with(
                ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(agent)], check=True
            )

    def test_moved_iterm_adapter_preserves_profile_identity_and_local_keys(self):
        iterm = apps.ITerm()
        original = {
            "New Bookmarks": [
                {
                    "Guid": "local-guid",
                    "Name": "Personal",
                    "Keyboard Map": {"personal": {"Action": 1}},
                }
            ],
            "Default Bookmark Guid": "local-guid",
        }
        shared = self.root / "iterm-fixture"
        shared.mkdir()
        (shared / "settings.json").write_text(
            '{"Theme":"Fixture","Profile":{},"Hotkey":{"Has Hotkey":false},'
            '"Global":{},"Remote":{"Guid":"fixture-remote","Name":"Remote"}}'
        )
        with (
            patch.object(iterm, "load_theme", return_value={}),
            patch.object(iterm, "SHARED", shared),
        ):
            result, profiles = iterm.build_preferences(original)
        self.assertEqual(result["New Bookmarks"][0]["Guid"], "local-guid")
        self.assertEqual(result["New Bookmarks"][0]["Keyboard Map"]["personal"], {"Action": 1})
        self.assertEqual(profiles["Profiles"][0]["Dynamic Profile Parent GUID"], "local-guid")
        self.assertEqual(original["New Bookmarks"][0]["Keyboard Map"], {"personal": {"Action": 1}})

    def test_shared_preference_writer_keeps_private_permissions_and_content(self):
        path = Path(self.temp.name) / "preferences/settings.json"
        write_if_changed(path, "settings\n")
        self.assertEqual(path.read_text(), "settings\n")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        write_if_changed(path, "updated\n")
        self.assertEqual(path.read_text(), "updated\n")

    def test_unsupported_platform_stops_before_any_operation(self):
        with (
            patch("src.cli.sys.platform", "win32"),
            patch("src.cli.run_shell") as operation,
            self.assertRaises(SystemExit),
        ):
            with patch("sys.stderr") as stderr:
                main(["apply"], self.root)
        diagnostic = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("supports macOS and Ubuntu Linux only", diagnostic)
        operation.assert_not_called()

    def test_apply_and_sync_use_config_without_installing(self):
        self.configure()
        with (
            patch("builtins.input") as ask,
            patch("src.cli.run_shell") as install,
            patch.object(configuration, "apply") as apply,
        ):
            main(["apply"], self.root)
            apply.assert_called_once()
            install.assert_not_called()
            ask.assert_not_called()
        with patch.object(apps, "sync_apps") as sync:
            main(["sync"], self.root)
            sync.assert_called_once_with(self.root, (), register_agent=False)

    def test_only_install_initializes_apps(self):
        self.selected.add("setup-vscode")
        self.configure()
        for command in ("install", "apply"):
            with (
                self.subTest(command=command),
                patch.object(apps, "sync_apps") as sync,
                patch.object(configuration.subprocess, "run"),
            ):
                main([command], self.root)
                sync.assert_called_once_with(
                    self.root, ("vscode",), initialize=("vscode",) if command == "install" else ()
                )

    def test_update_only_upgrades_packages_and_plugins_without_loading_settings(self):
        for platform in ("darwin", "linux"):
            with (
                self.subTest(platform=platform),
                patch("src.cli.sys.platform", platform),
                patch("src.cli.load_catalog") as catalog,
                patch("src.cli.run_shell") as update,
                patch.object(apps, "sync_apps") as sync,
            ):
                main(["update"], self.root)
            update.assert_called_once_with("update")
            catalog.assert_not_called()
            sync.assert_not_called()


if __name__ == "__main__":
    unittest.main()
