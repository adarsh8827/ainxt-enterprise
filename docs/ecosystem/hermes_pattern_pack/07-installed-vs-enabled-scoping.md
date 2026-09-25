# Pattern 7 — Installed vs. enabled, and scoping

## Problem

"Installed" and "active" are not the same question, and neither is "which of my profiles/projects
does this apply to" — conflating them either forces an all-or-nothing model or requires re-fetching
content just to toggle it off temporarily.

## How Hermes does it

**Installed ≠ enabled**, tracked as two independent facts:
- *Installed* = the item's files/registration exist somewhere Hermes can find them (a directory
  scan, or a config entry).
- *Enabled* = a separate, cheap, reversible flag in `config.yaml` (`skills.disabled: [...]`,
  `skills.platform_disabled.<platform>: [...]`, plugin enable/disable state, MCP server `enabled:`).

Toggling enabled/disabled never touches the filesystem or re-triggers install/scan — it's a config
write plus, when it affects the live prompt, an explicit cache-clear (pattern 13).

**Scoping layers, from broadest to narrowest, first-match-wins where they overlap**:

| Scope | Applies to | Example |
|---|---|---|
| Global / user home | Anything in `~/.hermes/skills/`, `~/.hermes/plugins/` | Default for a personal install |
| Profile | A named identity within one install (own home dir + own config + own secrets) | "work bot" vs "personal bot" as two profiles, fully isolated |
| Project-local | `.hermes/skills/` or `.agents/skills/` inside a git repo | A skill that only makes sense for this codebase |
| Platform / session | `platforms:` (skill OS gate), `session_platforms:` (gateway-channel gate), or the session's own recorded surface (desktop vs. terminal vs. messaging) | A skill only shown on macOS; a toolset only exposed to a GUI session |

**Trust gate for project-local items**: an untrusted project directory's skills are *discovered* but
not silently loaded — the user gets a passive banner pointing them at an explicit "trust this
directory" command, mirroring the trust model a code editor uses for workspace-provided
configuration.

**"List installed" always reads local, authoritative state** (a directory scan cross-referenced with
config), never the marketplace catalog — browsing and "what do I have" are structurally different
queries even though they render in similar-looking UI (see pattern 10).

## Key design decisions and trade-offs

- **Disable is a config flag, not an uninstall**, which makes "try disabling this and see if the
  problem goes away" a zero-risk, instantly-reversible action — an important UX property that a
  filesystem-move-based disable mechanism wouldn't have.
- **Profile isolation is deliberately total** (separate home dir, config, and secret scope per
  profile) rather than "one config with per-profile overrides layered on top" — the project's own
  documented reasoning is that partial inheritance between profiles has previously caused real bugs
  by coupling identities that were supposed to be independent.
- **Project trust is opt-in and sticky** (a list of trusted directories in config), not a per-session
  prompt — avoids trust-fatigue for a repo you work in daily, at the cost of a one-time deliberate
  decision the user has to make correctly.

## Failure modes and guards

- Disabling a skill/toolset mid-conversation only removes it from the *next* session's system
  prompt by default (see pattern 13) — a user expecting instant effect needs `--now`/`/reset`.
- A name collision between a project-local skill and a global one is resolved by documented
  precedence order (project > profile-local > global create-dir > external dirs), so behavior is
  deterministic even if surprising to a user who forgot they have both.

## Verdict: ADOPT

The installed/enabled separation and the scope hierarchy (global → profile → project → session)
are both directly reusable concepts for any multi-surface system; the specific "profile" isolation
model maps cleanly onto "tenant" or "workspace" in a multi-user product.

## Server-side translation

- **Profile → tenant/workspace.** Keep the same total-isolation principle: no config inheritance
  between tenants beyond an explicit "clone from template" action, not automatic coupling.
- **Project-local scope → project/workspace-within-a-tenant**, same trust-gate idea: an
  extension declared inside a shared repo/workspace should require an explicit trust action from a
  workspace admin before it loads for other members, not silent auto-trust.
- **Session/platform scoping → surface-awareness in your own session model**: resolve which
  extensions apply based on the actual client surface making the request (web chat vs. Agent
  Studio vs. Cowork), read from the session record itself — never from a shared process-global flag,
  since a server process legitimately serves many concurrent sessions across different surfaces at
  once (this is the direct multi-tenant analog of Hermes's own "surface capability is a property of
  the session, never the process" rule).
- **"List installed" as a pure per-tenant DB read** (pattern 6) keeps the same
  browse-vs-installed distinction Hermes has, just backed by rows instead of a directory scan.
