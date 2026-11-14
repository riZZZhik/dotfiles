# Codex

`config.toml` synchronizes both ways with `~/.codex/config.toml` through the existing
installer sync agent. New keys are shared unless excluded by `local_only` key paths
in `config/setup.yaml`. Exclusions also apply to nested fields; arrays sync as units.
The exclusion list is not a privacy guarantee: newly introduced machine-specific or
secret fields must be excluded before sync. Review repository diffs before committing.

STDIO MCP servers stay entirely local. HTTP servers share their URL and portable
options; authentication headers, tokens and local header helpers stay local.
Excluding an HTTP URL keeps that entire server local. Deleting a shared HTTP server
also removes its local authentication fields, with the original file backed up.
Sync removes transport-less fragments from older exports, backing up the original
file first. A shared HTTP server cannot replace a local STDIO server of the same name.

On first sync, local values win overlaps and shared-only settings are imported.
A local baseline then distinguishes changes and deletions on either side. Conflicting
edits to the same setting stop the sync without changing either file; make the values
agree to resolve them. Removing a key on one side removes it on the other. Excluded
fields remain local and are removed from the shared file. No automatic Git operations.

Baseline and backups live under `~/.local/state/dotfiles/codex/`, outside Git.
Avoid editing settings during sync: input changes are checked before writing, but
Codex does not participate in the installer lock. Writes are atomic per file, not
across files; the baseline is written last so an interrupted sync can be rerun.
Restart Codex after changing startup settings.

In the Codex terminal, `/presets` provides two saved prompts: **1 — Explore and
plan** investigates the current request without edits; **2 — Approve and finish**
authorizes the agreed plan through verification, commit, main integration and task
cleanup, without push or deployment. Select the second only after reviewing the plan.

Portable guidance is linked as `~/.codex/AGENTS.md`. Start a fresh chat after
installation to check instruction discovery. Runtime state stays local.
The former `dev-flow` skill is retired; remove its old symlink at
`~/.agents/skills/dev-flow` if present. No replacement skill is required.

## Maintaining instructions

Keep `AGENTS.md` a compact set of decisions that improve everyday judgment.
This note is maintenance guidance, not another instruction file to load each task.

- Revise or replace an existing rule before adding one. Fix the underlying decision
  failure rather than appending a rule for each incident.
- Keep global preferences in `AGENTS.md`; put repository facts, commands and
  operating procedures in their owning project. Do not copy system/tool instructions or
  maintain a parallel development workflow in a skill.
- Before expanding guidance, name the recurring failure, explain why existing rules
  did not cover it and remove overlap. A single awkward task rarely needs a global
  rule. Reconsider the structure if the file grows beyond roughly 800 words.
- Evaluate changes against realistic cases: a trivial fix proceeds directly; a
  nontrivial refactor waits for design agreement; a simplification reduces concepts;
  a language change covers visible buttons; failed Mac emulation triggers a cheaper
  alternative discussion; approved integration preserves another chat's work.
- Text review, links and formatting establish instruction consistency only. Claims
  of fewer corrections or faster completion require observed behavior in comparable
  tasks. Keep evaluation evidence in chat unless a durable artifact is requested.
