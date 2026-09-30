// SPDX-License-Identifier: MIT
// Admin -> OAuth Apps (Connectors phase, 2026-09-30): lets an org admin
// register a real OAuth client id/secret per native-connector provider
// (github, slack, ...) without touching env vars or docker-compose. Wired
// server-side by routers/connectors_router.py's oauth_start()/
// oauth_callback() via _admin_oauth_app_credentials() -- an admin-
// registered app takes precedence over the connector's own
// client_id_env/client_secret_env fallback. Secrets are write-only: the
// client_secret is sent once on create and never returned by GET
// (OAuthApp's own type has no client_secret field at all).
import { useEffect, useState } from "react";
import { useEcosystemClient } from "../../context/HostContext";
import type { OAuthApp } from "../../types";

// Kept in sync with docs/ecosystem/CONNECTOR_SETUP.md's provider table --
// must match connectors/registry.py's connector_definitions.name exactly
// (the bare name, never the "default/<name>" Discover namespace) for the
// backend lookup in _admin_oauth_app_credentials() to ever match.
const OAUTH_PROVIDERS = [
  { value: "github", label: "GitHub" },
  { value: "gitlab", label: "GitLab" },
  { value: "slack", label: "Slack" },
  { value: "zoom", label: "Zoom" },
  { value: "google_drive", label: "Google Drive" },
  { value: "google_calendar", label: "Google Calendar" },
  { value: "gmail", label: "Gmail" },
  { value: "microsoft_365", label: "Microsoft 365" },
  { value: "confluence", label: "Confluence" },
  { value: "docusign", label: "DocuSign" },
  { value: "jira", label: "Jira (OAuth)" },
];

function redirectUriFor(provider: string): string {
  // Mirrors routers/connectors_router.py's own _redirect_uri() exactly --
  // shown read-only so an admin can copy/paste it straight into the
  // provider's OAuth app console instead of guessing or mistyping it.
  return `${window.location.origin}/ainxt/v1/api/connectors/oauth/callback/${provider}`;
}

export function AdminOAuthApps() {
  const client = useEcosystemClient();
  const [apps, setApps] = useState<OAuthApp[] | null>(null);
  const [provider, setProvider] = useState(OAUTH_PROVIDERS[0]!.value);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [scopesInput, setScopesInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const reload = () => {
    client.listOAuthApps().then(setApps).catch(() => setApps([]));
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!clientId.trim() || !clientSecret.trim()) return;
    setSubmitting(true);
    setError(null);
    setStatus(null);
    client
      .createOAuthApp({
        provider,
        client_id: clientId.trim(),
        client_secret: clientSecret.trim(),
        redirect_uri: redirectUriFor(provider),
        scopes: scopesInput.split(",").map((s) => s.trim()).filter(Boolean),
      })
      .then(() => {
        setStatus(`${OAUTH_PROVIDERS.find((p) => p.value === provider)?.label ?? provider} is now configured -- Connect will redirect to its real sign-in page.`);
        setClientId("");
        setClientSecret("");
        setScopesInput("");
        reload();
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Couldn't register this OAuth app."))
      .finally(() => setSubmitting(false));
  };

  const handleDelete = (id: string) => {
    setError(null);
    client.deleteOAuthApp(id).then(reload).catch((err: unknown) => setError(err instanceof Error ? err.message : "Couldn't remove this OAuth app."));
  };

  return (
    <div data-testid="admin-oauth-apps">
      <h2 style={{ fontSize: "var(--eco-font-sizeXl)", color: "var(--eco-color-textPrimary)" }}>OAuth Apps</h2>
      <p style={{ color: "var(--eco-color-textSecondary)", fontSize: "var(--eco-font-sizeSm)", maxWidth: "640px" }}>
        Register a real OAuth client id/secret per provider so "Connect" on that connector redirects to the
        provider's own sign-in/consent page. The client secret is stored encrypted and is never shown again after
        creation -- see docs/ecosystem/CONNECTOR_SETUP.md for exactly which scopes and provider console to use.
      </p>

      <form onSubmit={handleCreate} style={{ display: "flex", flexDirection: "column", gap: "var(--eco-space-sm)", maxWidth: "480px", marginBottom: "var(--eco-space-lg)" }}>
        <label style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}>
          Provider
          <select
            data-testid="oauth-app-provider" value={provider} onChange={(e) => setProvider(e.target.value)}
            style={{ display: "block", width: "100%", padding: "8px", borderRadius: "var(--eco-radius-sm)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)", marginTop: "4px" }}
          >
            {OAUTH_PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </label>

        <div style={{ fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textMuted)" }}>
          Redirect/callback URL to register with the provider:{" "}
          <code data-testid="oauth-app-redirect-uri" style={{ userSelect: "all" }}>{redirectUriFor(provider)}</code>
        </div>

        <label style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}>
          Client ID
          <input
            data-testid="oauth-app-client-id" value={clientId} onChange={(e) => setClientId(e.target.value)} required
            style={{ display: "block", width: "100%", boxSizing: "border-box", padding: "8px", borderRadius: "var(--eco-radius-sm)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)", marginTop: "4px" }}
          />
        </label>

        <label style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}>
          Client secret
          <input
            data-testid="oauth-app-client-secret" type="password" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} required
            style={{ display: "block", width: "100%", boxSizing: "border-box", padding: "8px", borderRadius: "var(--eco-radius-sm)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)", marginTop: "4px" }}
          />
        </label>

        <label style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}>
          Scopes (comma-separated, optional -- defaults to the connector's own if left blank)
          <input
            data-testid="oauth-app-scopes" value={scopesInput} onChange={(e) => setScopesInput(e.target.value)} placeholder="repo"
            style={{ display: "block", width: "100%", boxSizing: "border-box", padding: "8px", borderRadius: "var(--eco-radius-sm)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)", marginTop: "4px" }}
          />
        </label>

        <button
          type="submit" data-testid="oauth-app-submit" disabled={submitting}
          style={{ alignSelf: "flex-start", padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "none", background: "var(--eco-color-accentSkill)", color: "var(--eco-color-accentSkillText)", cursor: submitting ? "default" : "pointer" }}
        >
          {submitting ? "Saving…" : "Save OAuth app"}
        </button>
      </form>

      {status && <p data-testid="oauth-app-status" style={{ color: "var(--eco-color-success)" }}>{status}</p>}
      {error && <p role="alert" data-testid="oauth-app-error" style={{ color: "var(--eco-color-danger)" }}>{error}</p>}

      <h3 style={{ fontSize: "var(--eco-font-sizeMd)", color: "var(--eco-color-textPrimary)" }}>Configured</h3>
      {apps === null ? (
        <p data-testid="oauth-apps-loading">Loading…</p>
      ) : apps.length === 0 ? (
        <p data-testid="oauth-apps-empty" style={{ color: "var(--eco-color-textMuted)" }}>No OAuth apps configured yet.</p>
      ) : (
        <table data-testid="oauth-apps-list" style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--eco-font-sizeSm)" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid var(--eco-color-border)" }}>
              <th style={{ padding: "6px 8px" }}>Provider</th>
              <th style={{ padding: "6px 8px" }}>Client ID</th>
              <th style={{ padding: "6px 8px" }}>Scopes</th>
              <th style={{ padding: "6px 8px" }}>Added by</th>
              <th style={{ padding: "6px 8px" }} />
            </tr>
          </thead>
          <tbody>
            {apps.map((app) => (
              <tr key={app.id} data-testid="oauth-app-row" style={{ borderBottom: "1px solid var(--eco-color-border)" }}>
                <td style={{ padding: "6px 8px" }}>{OAUTH_PROVIDERS.find((p) => p.value === app.provider)?.label ?? app.provider}</td>
                <td style={{ padding: "6px 8px", fontFamily: "monospace" }}>{app.client_id}</td>
                <td style={{ padding: "6px 8px" }}>{app.scopes.join(", ") || "—"}</td>
                <td style={{ padding: "6px 8px" }}>{app.created_by}</td>
                <td style={{ padding: "6px 8px" }}>
                  <button
                    type="button" data-testid="oauth-app-delete" onClick={() => handleDelete(app.id)}
                    style={{ background: "none", border: "none", color: "var(--eco-color-danger)", cursor: "pointer" }}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
