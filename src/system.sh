#!/usr/bin/env bash
set -euo pipefail
export PATH="$PATH:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin"

homebrew() (
  if ! command -v brew >/dev/null; then
    script=$(mktemp)
    trap 'rm -f "$script"' EXIT
    curl --fail --location https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o "$script"
    bash "$script"
  fi
)

python_setup() (
  if ! command -v uv >/dev/null; then
    homebrew
    brew install uv
  fi
  bash src/python.sh
)

fork() (
  if ! command -v gh >/dev/null; then
    echo 'Install GitHub CLI (gh) before creating a fork.' >&2
    exit 1
  fi
  gh auth status >/dev/null 2>&1 || gh auth login

  repo=$(gh repo view --json name --jq .name)
  login=$(gh api user --jq .login)
  gh repo fork --clone=false --remote=false
  git remote set-url origin "https://github.com/$login/$repo.git"
  printf 'Fork ready: https://github.com/%s/%s\n' "$login" "$repo"
)

packages() (
  action=$1
  shift
  case "$action" in
    plugins)
      sheldon lock
      exit 0
      ;;
  esac
  homebrew
  manifest=$1
  brew bundle install "--file=$manifest"
)

touch_id() (
  config=$1
  source=$config
  [[ -f "$source" ]] || source=$2
  entry='^auth[[:space:]]+sufficient[[:space:]]+pam_tid\.so([[:space:]]|$)'
  if [[ -f "$config" ]] && grep -Eq "$entry" "$config"; then
    exit 0
  fi
  file=$(mktemp)
  trap 'rm -f "$file"' EXIT
  sed -E 's/^#(auth[[:space:]]+sufficient[[:space:]]+pam_tid\.so)/\1/' "$source" > "$file"
  if ! grep -Eq "$entry" "$file"; then
    echo 'No Touch ID entry found in the system sudo template.' >&2
    exit 1
  fi
  sudo install -o root -g wheel -m 0444 "$file" "$config"
)

cleanup() (
  if [[ $(uname -s) == Linux ]]; then
    bash "$(dirname "${BASH_SOURCE[0]}")/linux.sh" --cleanup
  else
    brew cleanup
  fi
)

update() (
  if [[ $(uname -s) == Linux ]]; then
    bash "$(dirname "${BASH_SOURCE[0]}")/linux.sh" --update
  else
    brew upgrade
  fi
  sheldon lock --update
  cleanup
)

case "${1:-}" in
  --python)
    python_setup
    exit
    ;;
  --fork)
    shift
    fork "$@"
    exit
    ;;
  --packages)
    shift
    packages "$@"
    exit
    ;;
  --touch-id)
    shift
    touch_id "$@"
    exit
    ;;
  --cleanup)
    cleanup
    exit
    ;;
  --update)
    update
    exit
    ;;
esac
