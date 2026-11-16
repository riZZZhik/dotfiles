#!/usr/bin/env bash
set -euo pipefail

# Both platform bootstraps run this from the checkout root after provisioning uv.
version=$(cat .python-version)
uv venv --allow-existing --python "$version" .venv
uv pip install --python .venv/bin/python --group installer

global_packages=$(.venv/bin/python - <<'PYTHON'
import tomllib

with open("pyproject.toml", "rb") as source:
    print(bool(tomllib.load(source)["dependency-groups"].get("global", [])))
PYTHON
)
if [[ "$global_packages" == True ]]; then
  uv python install "$version" --default
  uv pip install --python "$HOME/.local/bin/python3" --break-system-packages --group global
fi
