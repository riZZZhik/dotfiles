# riZZZhik's dotfiles

Personal macOS setup, with optional presets and app exports.

## Setup

```sh
git clone https://github.com/riZZZhik/dotfiles.git ~/.dotfiles
cd ~/.dotfiles
```

Review `config/setup.yaml` before installing. Its `setup-*` stages select software
and preset actions; `sync.apps` independently selects daemon adapters.
App paths and privacy policies live under `settings.{codex,vscode,iterm}`.
Python libraries are configured in `pyproject.toml` under `global`; keep `installer`.

To use the supplied presets:

```sh
./install
```

Configure the two independent root fields in `config/setup.yaml`:

```yaml
copy_settings: false
sync:
  enabled: true
  apps: [codex, vscode, iterm]
```

Then run `./install`. With `copy_settings: false`, supplied home links, app presets,
macOS defaults and file associations are skipped on install, apply and update.
Configured software, the installer Python runtime and libraries are still reconciled;
remove unwanted `setup-*` stages first. You can delete `home/` and the preset directories
`config/{codex,vscode,iterm2}/`. Keep the installer/runtime files and the operational
app paths/privacy policies under `settings`.

Exports are created from your apps without importing supplied presets. Codex first
captures your current configuration, then retains its normal two-way synchronization.
With `copy_settings: true`, installation performs the one-time preset copy instead.
This works independently of `sync.enabled`; set that to `false` (or clear `sync.apps`)
and run `./install apply` to unload this checkout's daemon. Disabled daemon sync does
not export preferences. No command-line setting switches or machine-local mode file
are used.

If an app has not created its preferences yet, setup reports that export as pending
and still registers the daemon. It retries on later app events or its regular interval;
existing exports remain intact. Select only the apps you use in `sync.apps`.

If Command Line Tools setup opens, finish it and rerun. Removing packages from
configuration does not uninstall them.

## Commands

| Command | Effect |
| --- | --- |
| `./install apply` | Relink presets when enabled; export app preferences and register sync. |
| `./install update` | Pull changes and update configured software. |
| `./install sync` | Export VS Code/iTerm preferences; sync Codex settings. |
| `./install cleanup` | Clear package caches. |
| `./install fork` | Create a GitHub fork and switch `origin`; no push. |
| `./install link SOURCE` | Explicitly link SOURCE's contents into `~/`. |
| `./install detach` | Stop sync and replace both repositories' home links with local copies. |

## App settings

With presets enabled, installation copies VS Code/iTerm settings once, with backups.
Later runs export these apps to dotfiles; they do not change app preferences or
install/remove extensions. Existing VS Code extension baselines and generated iTerm
profiles identify previously configured installations without recopying preferences.

For a fresh iTerm preset copy, open it once, then quit it normally and rerun installation.
The exporter works with iTerm running, including its native custom-preferences mode.
For optional VS Code layout restoration, use **Profiles: Import Profile** into **Default**
and confirm **Replace**. The initial layout is saved at
`.private/backups/vscode/initial-ui-state.code-profile`; no restoration gate is required.

VS Code exports settings, keybindings, installed extensions and selected UI layout.
Existing private overrides, credential-named fields, remote SSH/environment settings
and home paths are excluded from public settings. They go to the configured private
repository when available, otherwise `~/.local/state/dotfiles/vscode/settings.local.jsonc`.
Machine-specific keybindings are saved alongside it as `keybindings.local.json`.

Each iTerm export captures portable native preferences and all profiles, including
dynamic profile definitions. It needs no preset template and captures new settings
and deletions. Public profile references use portable IDs. Commands, host bindings,
paths, arbitrary text macros, credentials and machine metadata stay in the complete
local snapshot at `~/.local/state/dotfiles/iterm/preferences.plist`. These private
recovery files have owner-only permissions; they are separate from public Git exports.
The original preset format remains supported for its initial settings copy.

**Detachment:** contents, permissions and installed apps are preserved. Resolve
reported broken links or live sockets and retry. Earlier copies remain; reruns
are safe. Run detachment separately from installation, apply, update or sync.
