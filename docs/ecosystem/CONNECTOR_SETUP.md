# Connector setup — per-provider reference

How to make each native connector's "Connect" button actually work, in plain steps. This is the
real, live-verified state of every row in `connectors/registry.py`'s `connector_definitions` table
(as seeded by `connectors/seed.py`), not aspirational.

Two different auth mechanisms exist. Both are real, first-class ways to connect — neither is a
placeholder for the other:

- **OAuth2** — `Connect` redirects the browser to the provider's own login/consent page
  (authorization-code flow, PKCE where the provider supports it, `state` verified server-side). An
  admin must register that provider's OAuth app's client ID/secret first (see "How to configure an
  OAuth connector" below) — until then, `Connect` returns a clear
  `Sign-in for <app> isn't set up yet — ask your admin` message, never a fake "Connected".
- **Personal access token (PAT)** — the user pastes a token they generated themselves into
  **Profile → API Token Vault**; there is no redirect. `Connect` from the Marketplace card for a
  PAT connector doesn't apply — the token vault is the real entry point.
- **DPI consent** — India-specific (DigiLocker / Account Aggregator) government consent flow, a
  different shape entirely from both of the above. See `docs/auth/dpi_consent.md` — not duplicated
  here.

## How to configure an OAuth connector (admin)

1. Go to **Marketplace → Connectors → Admin → OAuth Apps** (`/marketplace/admin/oauth-apps`).
2. Pick the provider, paste the **client ID** and **client secret** from that provider's own
   console (see the table below for exactly which console and which scopes), and save.
   The client secret is encrypted at rest and is never shown again after creation — if you need to
   rotate it, register a new one (there is no "reveal" or "edit" for the secret).
3. The callback URL to register with the provider is shown on that same screen once you pick the
   provider, and is always:
   `<your deployment's base URL>/ainxt/v1/api/connectors/oauth/callback/<provider>`
   — e.g. `http://localhost:5173/ainxt/v1/api/connectors/oauth/callback/github` for a local dev
   stack (`CONNECTOR_OAUTH_REDIRECT_BASE`, default `http://localhost:5173`).
4. Once saved, every user's `Connect` click on that connector redirects to the real provider
   login/consent page immediately — no restart needed.

An OAuth app registered this way takes precedence over the connector's own
`client_id_env`/`client_secret_env` fallback (see "Ops-managed alternative" below) automatically —
nothing else to flip.

### Ops-managed alternative (no admin UI)

Every OAuth connector also has a fallback pair of environment variables (`client_id_env`/
`client_secret_env` in the table below). Set both directly in `.env`/`docker-compose.yml` and skip
the admin screen entirely if you'd rather manage credentials as ops-owned secrets than
DB-stored ones. The admin-registered app always wins if both are present.

## Per-connector reference

| Connector | Auth type | Scopes | Callback URL suffix | Where to create the app | Env var fallback |
|---|---|---|---|---|---|
| **GitHub** | OAuth2 | `repo` | `/connectors/oauth/callback/github` | [github.com/settings/developers](https://github.com/settings/developers) → OAuth Apps → New OAuth App | `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` |
| **Slack** | OAuth2 | `channels:read`, `channels:history`, `search:read`, `users:read`, `im:read`, `im:history`, `groups:read`, `groups:history`, `chat:write` | `/connectors/oauth/callback/slack` | [api.slack.com/apps](https://api.slack.com/apps) → Create New App → OAuth & Permissions (Bot Token Scopes) | `SLACK_CLIENT_ID` / `SLACK_CLIENT_SECRET` |
| **Zoom** | OAuth2 | `meeting:read`, `meeting:write`, `user:read` | `/connectors/oauth/callback/zoom` | [marketplace.zoom.us/develop/create](https://marketplace.zoom.us/develop/create) → OAuth app type | `ZOOM_CLIENT_ID` / `ZOOM_CLIENT_SECRET` |
| **Google Drive** | OAuth2 | `openid`, `email`, `profile`, `drive.readonly` | `/connectors/oauth/callback/google_drive` | [console.cloud.google.com/apis/credentials](https://console.cloud.google.com/apis/credentials) → Create Credentials → OAuth client ID (Web application) | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` |
| **Google Calendar** | OAuth2 | `openid`, `email`, `profile`, `calendar.readonly`, `calendar.events` | `/connectors/oauth/callback/google_calendar` | Same Google Cloud OAuth client as Google Drive/Gmail — one client, three connectors | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` |
| **Gmail** | OAuth2 | `openid`, `email`, `profile`, `gmail.readonly`, `gmail.send`, `gmail.modify` | `/connectors/oauth/callback/gmail` | Same Google Cloud OAuth client as Google Drive/Calendar | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` |
| **Microsoft 365** | OAuth2 | `openid`, `profile`, `email`, `offline_access`, plus Mail/Calendars/Teams/Chat/Files Graph scopes (see `connectors/seed.py` for the full list — 20+ scopes across Outlook/Calendar/Teams) | `/connectors/oauth/callback/microsoft_365` | [portal.azure.com](https://portal.azure.com) → Microsoft Entra ID → App registrations → New registration | `AZURE_AD_CLIENT_ID` / `AZURE_AD_CLIENT_SECRET` |
| **Confluence** | OAuth2 | `read:confluence-content.all`, `read:confluence-content.summary`, `read:confluence-space.summary`, `write:confluence-content`, `search:confluence`, `offline_access` | `/connectors/oauth/callback/confluence` | [developer.atlassian.com/console/myapps](https://developer.atlassian.com/console/myapps/) → Create → OAuth 2.0 (3LO) integration | `ATLASSIAN_CLIENT_ID` / `ATLASSIAN_CLIENT_SECRET` |
| **DocuSign** | OAuth2 | `signature`, `impersonation` | `/connectors/oauth/callback/docusign` | [developers.docusign.com](https://developers.docusign.com) → Apps and Keys → Add App / Integration Key | `DOCUSIGN_CLIENT_ID` / `DOCUSIGN_CLIENT_SECRET` |
| **Jira (OAuth)** | OAuth2 — defined but not the live card (see note below) | `read:jira-work`, `write:jira-work`, `read:jira-user`, `offline_access` | `/connectors/oauth/callback/jira` | Same Atlassian console as Confluence — one app can cover both if scoped for both | `ATLASSIAN_CLIENT_ID` / `ATLASSIAN_CLIENT_SECRET` |
| **Jira (token)** | Personal access token | — | n/a (no redirect) | User generates an API token at [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens), then pastes it into **Profile → API Token Vault**. Also set the Jira site URL there (or `JIRA_URL` env for a single-site deployment). | n/a |
| **GitLab** | Personal access token | — | n/a (no redirect) | User generates a token at their GitLab instance's **Settings → Access Tokens** (`api`, `read_repository` scopes), then pastes it into **Profile → API Token Vault**. | n/a |
| **DigiLocker (DPI)** | DPI consent | `digilocker:docs:read` | n/a — consent artifact flow, not a redirect callback | See `docs/auth/dpi_consent.md` | n/a |
| **Account Aggregator (DPI)** | DPI consent | `aa:accounts:read`, `aa:statement:read` | n/a — consent artifact flow, not a redirect callback | See `docs/auth/dpi_consent.md` | n/a |

**Note on the two Jira rows:** `connector_definitions` has both an OAuth2-shaped `jira` row and a
PAT-shaped `jira_connector` row (a historical duplicate under different names, unlike GitHub's
duplicate which shared one name and got resolved by picking a single winning config). Discover only
ever shows one Jira card — the legacy-bridge's own dedupe-by-display-name logic
(`services/ecosystem/legacy_bridge.py`) currently keeps whichever definition declares more tools,
which today is `jira_connector` (PAT mode). The OAuth2 `jira` row is real and fully configured but
not reachable from the UI as things stand — flagged here rather than silently ignored; switching
which one wins is a real, separate product decision (PAT vs. OAuth login for Jira specifically),
not something this doc changes unilaterally.

## Verifying a real connection end-to-end

Once an OAuth app is registered (or a PAT is saved in the Token Vault):

1. Marketplace → Connectors → Discover → click the connector card → **Connect**.
2. OAuth: you're redirected to the provider's real login/consent page → approve → redirected back
   → the card shows **Connected**.
3. In chat, ask something that needs a read tool from that connector (e.g. "list my GitHub repos",
   "what's on my calendar today"). A working connection means the model actually calls the tool and
   returns real data, not a "not connected" refusal.
4. Marketplace → Connectors → Yours shows the connection with a real status chip (Connected / Needs
   reconnect / Expired) and a Disconnect action.

## CI / local testing without real provider accounts

`tests/e2e_fixtures/test_oauth_provider.py` is a real, minimal, test-only OAuth 2.1 authorization
server (real PKCE verification, no external network) used by the E2E suite so the full
connect → use → disconnect flow can be exercised in CI without registering a real GitHub/Slack/etc.
app. See that file and `ai-ui/e2e/advanced-mcp-server-add-validation.spec.ts` for how it's wired in;
`ECOSYSTEM_E2E_ALLOW_LOCAL_HOSTS=true` is required for the gateway to reach it (never set in a real
deployment — see `services/ecosystem/import_adapters/ssrf_guard.py`'s own docstring).
