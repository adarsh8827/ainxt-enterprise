# Pattern 14 — Secret scoping and redaction

## Problem

Extensions (skills, plugins, MCP servers, connectors) often need credentials — but a platform that
lets those credentials leak across identities, into logs, or into the model's own context has a
serious security problem, not just a bug. And before any of that: where do the credentials
themselves actually get *stored*, given that "we can't just store an API key" is the instinctive
(and only partially correct) worry?

## How Hermes does it

**There is no single answer — Hermes uses three genuinely different storage models depending on who
ends up holding the real credential.** This is the most important thing to internalize before
copying anything here: the right model depends on whether the credential is a static secret you
control, or a third party's OAuth token, or something a hosted broker could hold instead of you.

| Credential type | Where it's actually stored | Encrypted at rest? | Real protection |
|---|---|---|---|
| Messaging-platform bot tokens (Telegram, Discord, Slack, etc.) | Plaintext `.env` file, per profile | No | OS file permissions only, plus never-logged/never-in-prompt redaction |
| Hosted-connector OAuth tokens (Nous Portal model — Gmail/Notion-style "Connect" button) | **Not stored locally at all** — held entirely by the hosting broker's own backend | N/A (never leaves the broker) | You only hold a short-lived access token to *your own account on the broker*, not the underlying third-party token |
| Direct MCP-server OAuth tokens (a vendor's own hosted MCP server, e.g. a real catalog entry for Atlassian's Jira/Confluence MCP) | Local JSON files, one per server, under a dedicated token directory | No | `0600` file permissions (owner-only), parent directory tightened too, written atomically |
| Browser-autofill passwords (a related but separate feature, not a connector) | Local encrypted file | **Yes** — real symmetric encryption | Real encryption, but the key is a sibling file protected by the same `0600` permission — protects against copying the file elsewhere, not against local account compromise |

**Model 1 — plaintext + permissions** (bot tokens): the simplest and most common case. No attempt
at encryption; the file's OS permission bit is the entire security boundary. This is the same model
essentially every local CLI tool uses for its own credentials (git, cloud CLIs, package manager
tokens) and is a reasonable choice specifically *because* there's only one local user who could ever
read that file.

**Model 2 — delegate storage to whoever owns the OAuth relationship** (hosted connectors): the
cleverest of the three. Rather than solving "how do I safely store a live Gmail refresh token on a
random user's laptop," Hermes never receives that token at all — the OAuth exchange for the
*underlying* third-party service happens entirely on the hosting broker's servers. What sits on the
user's disk is only a short-lived access token scoped to *their own account on the broker*, refreshed
automatically:

```
call_connector_tool(slug, args):
    token = read_my_broker_access_token()     # local, short-lived, auto-refreshed
    response = https_post(broker_api_url, headers={"Authorization": f"Bearer {token}"},
                           body={connector: slug, action: args})
    # the broker holds the REAL Gmail/Notion/etc. token and makes that call itself
    return response
```

This structurally eliminates an entire class of local-credential-leak risk for anything routed
through it, at the cost of an unconditional network dependency (you cannot use that connector
offline, and you're trusting the broker's own security).

**Model 3 — locally-held OAuth tokens with automatic lifecycle management** (a direct MCP-server
OAuth connection, e.g. a vendor's hosted MCP endpoint reached with Dynamic Client Registration +
PKCE): this is the case where a real, usable, third-party access/refresh token pair genuinely does
end up on the user's own disk. Concretely, per connected server, three small JSON files:

```
<token-dir>/<server_name>.json          # access_token, refresh_token, expiry (0600)
<token-dir>/<server_name>.client.json   # dynamically-registered client_id/secret (0600)
<token-dir>/<server_name>.meta.json     # the auth server's discovered endpoints, cached (0600)
```

Every write goes through one shared "write this JSON file at 0600, parent directory tightened to
0700" helper — a single audited choke point rather than each OAuth integration inventing its own
persistence. A noteworthy safety detail: each stored refresh token is **bound to the specific
authorization server that issued it** (a small extra field recording that issuer); if Hermes ever
detects a stored refresh token about to be sent to a *different* issuer than the one that granted
it, it strips just the refresh token rather than risk a token-substitution attack — the still-valid
access token remains usable in the meantime.

**Token attachment to outgoing calls is automatic, not hand-rolled per integration.** A generic
OAuth auth-provider object is attached once at HTTP-client construction time; from then on, every
outgoing request to that server gets a fresh `Authorization: Bearer <token>` header, with the
provider transparently refreshing an expired access token (using the stored refresh token) before
the request goes out, and persisting the new token pair immediately.

**Model 4 (unrelated feature, useful contrast) — real client-side encryption**: a separate
browser-autofill vault feature (not a connector) genuinely encrypts stored secrets with a locally
generated symmetric key. Reading this code is instructive precisely because of its honest
limitation: the encryption key is generated once and written to its own file, `0600`, sitting right
next to the encrypted vault it protects. This *is* real encryption (protects a copied-elsewhere
backup of that file, or a different local account without permission to read `0600` files), but it
is **not** protection against anyone who already has full access to the account both files live
under — the key is right there. Worth internalizing as the honest ceiling of "encrypt with a
locally-stored key" as a technique.

**Scoping — orthogonal to storage, applies to all four models.** Regardless of *where* a secret is
stored, *reading* it always goes through a context-scoped accessor tied to the active profile,
never a global environment mutation:

```
with secret_scope(profile_X_secrets):
    run_one_turn_or_request()
    # get_secret("API_KEY") resolves from profile_X's own store
# outside the with-block, the previous scope is restored automatically
# the real process environment was never touched
```

This is what makes it safe for **one process to serve multiple profiles/identities concurrently** —
a structural property, not a discipline every call site has to remember.

**Child-process spawning** goes through one dedicated env-builder that actively **strips** every
provider/tool credential from the base environment before selectively re-adding only the *target*
identity's own secrets — a subprocess acting for profile A can never accidentally inherit profile
B's key.

**Redaction** happens at the log/prompt boundary, pattern-based (generic secret-shaped patterns plus
platform-specific ones for credentials with a recognizable shape) — applied on the way out, not by
trying to prevent secrets from ever being read into memory in the first place.

## Key design decisions and trade-offs

- **Matching the storage model to who ultimately controls the credential is the real insight here**,
  more than any single technique: a static secret you fully own (bot token) can reasonably be a
  permissioned file; a third party's live OAuth token is safest never touching your infrastructure
  at all if you can arrange that (Model 2); only when neither applies do you actually need Model 3's
  local-token-plus-lifecycle-management, and even then, encryption-with-a-local-key (Model 4) only
  raises the bar so far.
- **Context-scoping over environment-mutation** is the single most important idea independent of
  storage model — it's what lets multi-identity concurrency be safe by construction instead of by
  convention.
- **A single, audited env-builder for every child spawn**, rather than each call site building its
  own environment dict, means a credential-leak fix only has to happen in one place.
- **Redaction at the output boundary, not the read boundary**, accepts that secrets must pass through
  normal code paths to be used, and focuses effort on making sure they never escape into a log line,
  a prompt, or a UI.

## Failure modes and guards

- Model 1 and Model 3 both have the same honest ceiling: **anyone with full access to the local user
  account can read the secret**, full stop. Neither pretends otherwise.
- A completely novel secret shape will not be caught by pattern-based redaction — a known, accepted
  limitation, not a claimed guarantee.
- A boot-time probe running with no identity/scope bound at all is treated as expected (logged
  quietly); a call that *should* have had a scope bound but doesn't is treated as a real bug (logged
  loudly) — distinguishing these two cases is itself a deliberate design decision.
- Refresh-token issuer binding specifically guards against a token being replayed against the wrong
  authorization server — a real, non-hypothetical class of OAuth implementation bug.

## Verdict: ADOPT (the scoping/redaction/spawn-env pieces) — ADAPT the storage models

Context-scoped secret resolution, one shared env-builder with active stripping, and boundary-based
redaction are close to mandatory for any system serving more than one identity from a process. The
storage models themselves are each locally reasonable but each need adaptation for a real
multi-tenant, server-side platform (below).

## Server-side translation

- **This whole area gets more important, not less, in a multi-tenant server.** Replace "profile"
  with "tenant" throughout; no request-handling code path may resolve a secret except through a
  scope bound to the current request/tenant, enforced structurally.
- **Model 1 (plaintext + permissions) does not translate.** A shared server has many tenants' secrets
  in the same storage substrate; file permissions can't distinguish between them. Replace with a real
  secrets manager or a KMS-encrypted column, keyed per tenant, with access-controlled reads.
- **Model 2 (delegate to a hosting broker) is the strongest pattern here and should be your default
  for any "connect my Gmail/Notion/etc." feature** in a multi-tenant product — build (or buy) a
  connector-broker service that holds the real third-party OAuth tokens itself, and give your main
  application only a scoped capability token to call through it. This is *more* natural in a
  multi-tenant system than in Hermes's single-user design, since you likely already need a
  centralized service boundary for connector calls anyway.
- **Model 3 (local OAuth tokens) still applies whenever you can't avoid holding a real third-party
  token yourself** (e.g. a self-hosted or directly-configured MCP server with no broker in front of
  it) — keep the exact mechanics (one audited write path, atomic writes, issuer-binding on refresh
  tokens, automatic attach+refresh via a generic provider), but back the store with your actual
  secrets infrastructure (KMS/Vault/cloud secrets manager) instead of a `0600` file, and key every
  record by `(tenant_id, server_name)`, never just `server_name`.
- **Model 4's honest limitation is the strongest argument for using real infrastructure instead of
  reinventing encryption-with-a-local-key** — a hosted platform has real options (hardware security
  modules, cloud KMS, envelope encryption with keys that never live beside their ciphertext) that a
  single-user desktop app doesn't, and should use them rather than replicating Hermes's
  Fernet-key-as-a-sibling-file approach at server scale.
