#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root, just like system.sh.
source /etc/os-release
if [[ "$ID" != ubuntu ]]; then
  echo 'Linux installation currently supports Ubuntu only.' >&2
  exit 1
fi
privileged() {
  if [[ $(id -u) == 0 ]]; then "$@"; else sudo "$@"; fi
}
case "${1:-}" in
  --python)
    privileged apt-get update
    privileged apt-get install -y --no-install-recommends ca-certificates curl git
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv >/dev/null; then
      script=$(mktemp)
      trap 'rm -f "$script"' EXIT
      curl --fail --location --retry 3 https://astral.sh/uv/install.sh -o "$script"
      UV_NO_MODIFY_PATH=1 sh "$script"
    fi
    version=$(cat .python-version)
    uv python install "$version" --default
    uv pip install --python "$HOME/.local/bin/python3" --break-system-packages --group installer --group global
    ;;
  --cleanup)
    privileged apt-get clean
    ;;
  *) echo 'Unknown Linux bootstrap operation.' >&2; exit 1 ;;
esac
