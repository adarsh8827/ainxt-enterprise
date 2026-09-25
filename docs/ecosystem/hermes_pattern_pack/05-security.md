# Pattern 5 — Security scanning, trust tiers, and policy

## Problem

Before letting a marketplace item touch a user's machine (or, server-side, a shared tenant
environment), you need a decision procedure that combines "how much do we trust who published this"
with "what did automated inspection find" — and a way to draw a hard line that even an impatient
user can't cross with a force flag.

## How Hermes does it

**Two independent axes, deliberately not conflated:**

1. **Trust tier** — derived from *source*, not content: `builtin` (ships with the app) →
   `trusted` (a small hardcoded allowlist of known-good repos) → `community` (everything else) →
   `agent-created` (the model itself wrote it).
2. **Scan verdict** — derived from *content*, via pattern-matching against a rule set (~90 rules
   covering categories like: credential/secret exfiltration, reading sensitive files, destructive
   filesystem operations, reverse shells, obfuscated eval/exec, prompt-injection/jailbreak phrasing,
   persistence into the agent's own config files, hardcoded leaked credentials, invisible/zero-width
   Unicode). Verdict is the worst single finding: any critical-severity match → `dangerous`; any
   high-severity match → `caution`; otherwise → `safe`.

**Policy matrix** — the decision table that combines them (illustrative shape, not exact values):

| Trust tier \ Verdict | safe | caution | dangerous |
|---|---|---|---|
| builtin | allow | allow | allow |
| trusted | allow | allow | **block** |
| community | allow | **block** | **block** |
| agent-created | allow | allow | ask user |

**`--force` can override:** the "already installed" guard, a `caution`-tier block, and the
interactive confirmation prompt. **`--force` cannot override:** a `dangerous` verdict combined with
`community`/`trusted` tier — this specific cell is a hard floor with no escape hatch, by explicit
design (the code path even returns a message stating force does not apply here).

**Advisory-only layers** (never gate install, exist for extra visibility): an AST-based dynamic-
import auditor, an external third-party scanner integration treated as "warn, don't block," and an
authoring-style linter unrelated to security.

**Plugin dependency policy** is a separate but related trust boundary: a plugin's own declared
Python dependencies are installed under a *looser* policy than the core app's own dependencies
(the app's deps sit behind a 14-day "don't take anything newer than 2 weeks" supply-chain
quarantine; a plugin's deps explicitly do not, on the reasoning that plugin authors own that
tradeoff for their own package, not the platform). All enabled plugins' dependencies are resolved
into one **shared** environment, not one sandbox per plugin — if that resolution conflicts after a
core upgrade, non-essential plugins are dropped first, essential ones (e.g. anything providing
memory) are protected from being silently disabled.

**Kill list**: a small denylist of name/repo pairs pulled from the catalog for security or policy
reasons, checked at install time (not just at catalog-build time) and matched loosely (by
normalized name or repo URL) specifically so a cosmetic rename can't dodge it. An override flag
exists but is always logged, never silent.

## Key design decisions and trade-offs

- **Separating trust (who) from verdict (what) lets policy be a small, auditable table** instead of
  scattered `if` logic. Anyone can look at the 4×3 grid and know the exact behavior for any
  combination.
- **A hard ceiling with no override for the worst cell** is a deliberate refusal to let user
  impatience become a security bypass — worth keeping even though it will occasionally frustrate a
  user who's sure "it's fine."
- **Advisory scanners exist alongside the gating scanner** on purpose — an external/experimental
  scanner that occasionally has false positives shouldn't be allowed to block installs, but its
  findings are still worth surfacing.

## Failure modes and guards

- The scanner is pattern-based, not semantic — it can miss cleverly obfuscated malicious code and
  can false-positive on legitimate uses of a matched pattern (e.g. a skill that legitimately reads
  environment variables for a documented reason).
- Trust tier is entirely source-derived; a compromised "trusted" repo would still pass the trust
  check even with genuinely malicious new content (the `dangerous`+`trusted` = block cell is the
  actual backstop here, not the tier itself).
- The plugin dependency policy trades a real supply-chain protection (the 14-day quarantine) for
  plugin flexibility — an explicitly accepted risk, not an oversight, but worth naming as one.

## Verdict: ADOPT

The trust-tier × verdict decision table, the hard non-overridable floor, and the
advisory-vs-gating scanner split are all directly reusable regardless of deployment model.

## Server-side translation

- The policy matrix and hard floor translate unchanged — implement as a pure function
  `(trust_tier, verdict, force) -> allow|block|ask`, unit-testable in isolation.
- **A shared-dependency-resolution model does not translate to a multi-tenant server**: one
  tenant's plugin dependency shouldn't be able to conflict with or degrade another tenant's. Give
  each tenant (or each installed plugin instance) an isolated dependency environment
  (container/venv-per-tenant or per-plugin-instance) rather than Hermes's single-shared-venv
  model, which only made sense for a single local user.
- The **14-day-quarantine-for-core, looser-for-plugins** distinction still makes sense, but "looser"
  for a multi-tenant server should mean "still scanned/pinned, just not held to the platform's own
  release cadence" — not "unpinned," since a compromised plugin dependency is now a shared-service
  risk, not a single user's own risk.
- Make the scanner itself a pluggable interface from day one (rule-based scanner as the default
  implementation, with room to add a real static-analysis or sandboxed-execution scanner later) —
  Hermes's regex-rule approach is a reasonable v1 but is the part most worth planning to outgrow.
