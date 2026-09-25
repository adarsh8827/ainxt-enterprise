# Pattern 3 — Package formats

## Problem

Each extension type needs a manifest that's simple enough for a human to write by hand and strict
enough for a machine to validate before running/loading anything.

## How Hermes does it

**SKILL.md** — YAML frontmatter + Markdown body, no separate manifest file. Recognized fields:
`name`, `description`, `version`, `author`, `license`, `platforms` (OS gate: `[macos]`, etc.), and
a `metadata.hermes.*` namespace holding `tags`, `category`, `related_skills`, `config` (a list of
`{key, description, default?, prompt?}` — becomes user-configurable values under
`skills.config.<key>`), and conditional-activation keys: `requires_toolsets`,
`fallback_for_toolsets`, `requires_tools`, `fallback_for_tools`, `session_platforms` (a gateway
*channel* gate, distinct from the OS-level `platforms:`). A real test suite
(`tests/skills/test_authoring_standards.py`) enforces authoring rules beyond schema validity:
description ≤60 chars/one sentence, a fixed section order (`When to Use → Prerequisites → How to
Run → Quick Reference → Procedure → Pitfalls → Verification`), and references to the platform's
own tool names rather than raw shell commands.

**plugin.yaml** — a real manifest (not embedded in code), key fields: `version`, `description`,
`author`, `license`, `homepage`, `tags`, `requires_env`, `provides_tools`, `provides_hooks`,
`requires_plugins` (dependency edges — load order can be a topological sort), `python_dependencies`,
`config_schema` (the plugin's own declared settings shape), `capabilities` (permission-style
declarations, e.g. `tools.override`), `manifest_version` (currently 2 — **a manifest declaring a
higher version than this Hermes understands still loads**, with unknown fields ignored, rather than
hard-failing: forward-compat by design), and `emits`/`listens` (the plugin's own pub/sub event
declarations, separate from the fixed lifecycle-hook list).

**MCP `manifest.yaml`** (catalog only — a hand-added `mcp_servers` config entry needs none of this):
`manifest_version` (hard-pinned — a mismatch is a hard error, no forward-compat leniency, unlike
plugins), `name`, `description`, `source`, `transport` (`{type, command/args/env or url, version}`),
`auth` (`{type: api_key|oauth|none, env, provider, scopes, oauth: {...}}`), `connector_slug`,
`tools` (`default_enabled`/`default_excluded`), `install` (`{type: git, url, ref, bootstrap}` —
pinned ref, same discipline as the plugin catalog), `suggest` (`{keywords, hosts, applications,
examples}`). Validation order is transport → auth → tools → suggest → connector_slug → install, so
the *first* reported error tells you which layer is broken.

**Connector wire schema (Nous Portal)** — a materially richer, strictly-typed schema, because it
has to express per-tool, per-tier access policy, not just "install or don't":
`ConnectorTool{slug, name, description, facet: read|write|destructive|unclassified, hints, categories,
no_auth, deprecated}`; a policy model that layers `org → role → member`, each layer one of
`Unrestricted | DenyAll | Allow(tools, tags) | Deny(tools, tags)`, resolving to one effective
policy. Unknown enum values (e.g. an unrecognized `facet`) coerce to a safe default
(`"unclassified"`) rather than rejecting the whole payload.

**License field**: present in SKILL.md and plugin.yaml; **absent** from both the plugin-catalog
pointer entry and the MCP catalog manifest — a consumer has to go look at the linked repo itself to
learn its license.

## Key design decisions and trade-offs

- **Frontmatter-in-body (skills) vs. separate-manifest (plugins/MCP)** tracks how much metadata
  each format needs: a skill is mostly prose, so cramming a few fields into YAML frontmatter is
  fine; a plugin needs dependency graphs and capability declarations, which justify a dedicated
  file.
- **Forward-compat policy differs deliberately by blast radius**: a plugin manifest with an unknown
  future version still loads (a plugin doing the wrong thing is caught by hooks/timeouts/exceptions
  at runtime); an MCP manifest with an unknown version is refused outright (an MCP server is a
  black box over a wire protocol — Hermes can't safely guess how to talk to a version it's never
  seen).
- **The Portal connector policy model (org/role/member layering) is strictly richer** than anything
  the local trust-tier system offers, because it's solving a genuinely different problem —
  fine-grained per-tool access control for a multi-user hosted service, not "should this file be
  allowed onto one person's disk."

## Failure modes and guards

- A skill whose `platforms:` gate doesn't actually match the shell primitives it uses (e.g. claims
  cross-platform but calls a macOS-only binary) is *not* schema-caught — it's the authoring-standard
  test suite's job, and it only runs on skills contributed to this exact repo, not on arbitrary
  installs.
- A plugin declaring a `config_schema` for its own settings still self-reports that schema — nothing
  independently verifies the plugin's runtime code actually respects it.

## Verdict: ADOPT

Adopt per-type schema strictness proportional to blast radius (loose for prose, strict for
wire-protocol manifests), the `manifest_version` forward-compat split, and the pinned-ref discipline
in the MCP install block. Add a license field to your MCP/connector schemas from day one — Hermes's
own gap here is a real thing to just not repeat.

## Server-side translation

- Store these as validated JSON/JSONB columns rather than files-on-disk-with-frontmatter; keep the
  same field names and validation rules so any tooling/docs describing "what a manifest looks like"
  transfers directly.
- Enforce the Portal-style layered policy model (org → role → member) for *any* multi-tenant
  connector story — the local Hermes trust-tier system (builtin/trusted/community/agent-created)
  is not expressive enough for "user A's org disabled this tool for everyone, but user A personally
  re-enabled it for themselves," which a real multi-tenant product will eventually need.
- Require a license field on every submitted catalog entry (skill, plugin, MCP, connector) at
  ingestion time — don't let it become an afterthought like it is here.
