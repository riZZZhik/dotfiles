# riZZZhik's dotfiles

Personal macOS setup.

## Setup

```sh
git clone https://github.com/riZZZhik/dotfiles.git ~/.dotfiles
cd ~/.dotfiles
```

Before installing, review `config/setup.yaml` (apps and preferences), `home/`
(home links), and `config/` (app settings). Python libraries are configured in
`pyproject.toml` under `global`; keep `installer` intact.

```sh
./install
```

If Command Line Tools setup opens, finish it and rerun. Removing packages from
configuration does not uninstall them.

## Commands

| Command | Effect |
| --- | --- |
| `./install apply` | Relink files and reapply settings. |
| `./install update` | Pull changes and update configured software. |
| `./install sync` | Sync app settings and extensions. |
| `./install cleanup` | Clear package caches. |
| `./install fork` | Create a GitHub fork and switch `origin`; no push. |
| `./install link SOURCE` | Link SOURCE’s contents into `~/`. |
| `./install detach` | Stop sync and replace both repositories' home links with local copies. |

**Fresh VS Code setup:** import `config/vscode/ui-state.code-profile` using
**Profiles: Import Profile**, name it **Default**, and confirm **Replace**.
Reload and check the layout, then run `./install apply --vscode-ui-restored`.

**Detachment:** contents, permissions and installed apps are preserved. Resolve
reported broken links or live sockets and retry. Earlier copies remain; reruns
are safe. Run detachment separately from installation, apply, update or sync.
