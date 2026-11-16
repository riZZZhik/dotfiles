# Codex

- [config.toml](config.toml) syncs both ways with `~/.codex/config.toml`.
- [AGENTS.md](AGENTS.md) links to `~/.codex/AGENTS.md`.
- [keybindings.json](keybindings.json) links to `~/.codex/keybindings.json` on macOS.

Sync exclusions are defined by `settings.codex.local_only` in
[setup.yaml](../setup.yaml). STDIO MCP servers stay local; HTTP servers share
portable settings but exclude authentication fields. Exclude new secrets and
machine-specific settings before syncing, and review diffs before committing.

Local values win on first sync. Later edits and deletions propagate both ways;
conflicts stop sync until both files agree on the conflicting values.

The sync baseline is `~/.local/state/dotfiles/codex/baseline.toml`;
backups are in the checkout's `.private/backups/codex/`.
