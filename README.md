# riZZZhik's dotfiles

Personal macOS and Ubuntu/WSL setup with shell tools, app presets and settings sync.

## Setup

```sh
git clone https://github.com/riZZZhik/dotfiles.git ~/.dotfiles
cd ~/.dotfiles
# Review config/setup.yaml before installing.
./install
```

- **macOS:** if Command Line Tools setup opens, finish it and rerun.
- **Ubuntu/WSL:** keep the checkout in the Linux filesystem. Desktop apps and macOS
  settings are skipped. Run `exec zsh -l` after installation. Codex sync is manual;
  no background agent is registered.
- **Private settings:** clone your private repository into `~/.dotfiles_secret`
  and run its `./install`.

Run `./install` once per checkout to create its `.venv`; other commands do not
bootstrap the installer runtime. Successful install/update cleans package caches.
Removing a package from configuration does not uninstall it.

## Configuration

Edit [config/setup.yaml](config/setup.yaml):

| Field | Controls |
| --- | --- |
| `setup-*` | Software and setup actions. macOS uses `brew`, `cask`, `mas`; Ubuntu uses `apt`, `release`. |
| `copy_settings` | Presets: `home`, `macos`, `codex`, `vscode`, `iterm`. Use `[]` to skip presets without disabling software installation or app sync. |
| `sync.apps` | Apps to sync, independently of preset/software selections. Select only apps you use. |
| `sync.enabled` | Enables exports, including manual sync, and the macOS background agent. |
| `settings` | App paths, backup locations and privacy rules. |

`home` presets include shell plugins; `macos` includes Touch ID and system
preferences. App presets include their settings, links and file associations.
To disable exports and unload this checkout's agent, set `sync.enabled: false`
and run `./install apply`.

Optional user Python libraries go in the `global` group in
[pyproject.toml](pyproject.toml). A nonempty group sets up the version in
`.python-version` as the user-default Python and installs those libraries outside
`.venv`. Keep the `installer` group for installer dependencies.

## Commands

| Command | Effect |
| --- | --- |
| `./install` | Install selected software, apply presets and set up sync. |
| `./install apply` | Relink enabled presets, sync settings and register/unload the macOS agent. |
| `./install update` | Upgrade all Homebrew/apt packages and Sheldon plugins, then clean caches. Release-managed binaries are not upgraded. |
| `./install sync` | Export VS Code/iTerm settings and sync Codex. |
| `./install link SOURCE [DESTINATION]` | Link a directory tree, or a file with an explicit home-relative destination. |
| `./install detach` | Disable the owned agent and replace managed home links with local copies. |
| `./install fork` | Create a GitHub fork and switch `origin`; no push. |

## App settings and recovery

- **Codex:** settings sync both ways. See [Codex configuration](config/codex/README.md)
  for conflict handling and privacy exclusions.
- **VS Code:** presets copy once, including missing extensions. Later syncs export
  settings, keybindings and extensions without changing the app. Private settings
  go to the configured private repository, or `~/.local/state/dotfiles/vscode/`.
  Machine-specific keybindings stay in that local directory.
- **iTerm:** open it once, then quit normally before the first preset copy. Later
  syncs export portable preferences and profiles while it is running. Commands,
  host bindings and machine-specific state are excluded. Existing recovery
  snapshots are preserved; new full-state snapshots are not generated.

Review exported changes before committing. If an app export fails, fix that app
and rerun sync; later apps are skipped until it succeeds. On macOS, install/apply
still registers the agent for retries.

Default backups for replaced files and initial app imports live under the checkout's
ignored `.private/backups/`. Correct links are kept; other symlinks are replaced
without copying their targets. Existing backups are preserved.

Run detach separately from sync or edits. Before deleting a checkout, check for
remaining links that depend on it, including links outside managed home paths.
