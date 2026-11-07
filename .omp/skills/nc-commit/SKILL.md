---
name: nc-commit
description: Commit message format and version-bump rules for nextcloud-hermes-tools (conventional commits, plugin.yaml version bump)
---

# Commit + version bump

MUST follow `AGENTS.md` → "Git" for the rules: conventional-commit types, one logical change
per PR, the mandatory `version:` bump in `plugin.yaml` (line 2) with its semver mapping, and
`dashboard/manifest.json` not being synced. `AGENTS.md` is the source of truth and is not
repeated here.

## Commit message format

- Line 1 MUST be the summary: `<type>: <description>` — `<type>` is one of the
  conventional-commit types listed in `AGENTS.md` → "Git"; imperative mood; no trailing
  period; 72 characters hard limit (SHOULD be ≤ 50). A breaking change adds `!` at the end
  of this line.
- Line 2 MUST be blank.
- Big commits MUST then carry the details from line 3: what changed and why, wrapped at
  72 characters per line, bullet points allowed. Small commits MAY be summary-only.
