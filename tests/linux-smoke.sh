#!/usr/bin/env bash
set -euo pipefail
cd "$HOME/.dotfiles"
export TERM=xterm-256color
for tool in zsh sheldon starship atuin fzf zoxide git git-lfs gh delta lazygit uv nvim tmux direnv rg fd bat eza duf dust htop curl wget unzip lsof trash ssh ip; do
  command -v "$tool" >/dev/null || { echo "Missing CLI: $tool" >&2; exit 1; }
done
[[ ! -e "$HOME/.config/karabiner" && ! -e "$HOME/.config/linearmouse" ]]
[[ ! -e "$HOME/Library" && ! -e "$HOME/.codex/keybindings.json" ]]
[[ -L "$HOME/.zshrc" && -f "$HOME/.codex/config.toml" ]]
.venv/bin/python -c 'import yaml, json5, tomlkit'
login_shell=$(getent passwd "$(id -un)" | cut -d: -f7)
[[ "$(readlink -f "$login_shell")" == "$(readlink -f /usr/bin/zsh)" ]]
if [[ "${DOTFILES_TEST_VERIFY_CODEX:-true}" == true ]]; then
  command -v codex >/dev/null
  codex features list >/dev/null
fi
# Run in a PTY: widgets and prompt integrations require an interactive terminal.
script -q -e -c 'zsh -i -c '\''(( ${plugins[(Ie)macos]} == 0 && ${plugins[(Ie)brew]} == 0 )) || exit 1; alias myip 2>/dev/null || functions myip; fzf --zsh >/dev/null || exit 1; starship prompt >/dev/null || exit 1; print SHELL_OK'\''' /tmp/dotfiles-shell.log
if grep -Ei 'command not found|bad option|unknown (option|flag)|no such file|failed to load' /tmp/dotfiles-shell.log; then
  exit 1
fi
grep -q SHELL_OK /tmp/dotfiles-shell.log
./install apply
./install sync
./install
./install update
./install detach
[[ ! -L "$HOME/.zshrc" && -f "$HOME/.zshrc" ]]
./install detach
./install apply
[[ -L "$HOME/.zshrc" ]]
printf 'UBUNTU_SMOKE_OK\n'
