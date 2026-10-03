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
import { useEcosystemClient } from "../lib/context/HostContext";
import { ConfirmDialog } from "../ConfirmDialog";
import { Button } from "../Button";
const inputClass = "block w-full box-border bg-white border border-gray-300 rounded px-3 py-2 text-sm text-gray-900 focus:outline-none focus-visible:outline-none! focus:border-indigo-300 mt-1";
// Kept in sync with docs/ecosystem/CONNECTOR_SETUP.md's provider table --
// must match connectors/registry.py's connector_definitions.name exactly
// (the bare name, never the "default/<name>" Discover namespace) for the
// backend lookup in _admin_oauth_app_credentials() to ever match.
const OAUTH_PROVIDERS = [{
  value: "github",
  label: "GitHub"
}, {
  value: "gitlab",
  label: "GitLab"
}, {
  value: "slack",
  label: "Slack"
}, {
  value: "zoom",
  label: "Zoom"
}, {
  value: "google_drive",
  label: "Google Drive"
}, {
  value: "google_calendar",
  label: "Google Calendar"
}, {
  value: "gmail",
  label: "Gmail"
}, {
  value: "microsoft_365",
  label: "Microsoft 365"
}, {
  value: "confluence",
  label: "Confluence"
}, {
  value: "docusign",
  label: "DocuSign"
}, {
  value: "jira",
  label: "Jira (OAuth)"
}];
function redirectUriFor(provider) {
  // Mirrors routers/connectors_router.py's own _redirect_uri() exactly --
  // shown read-only so an admin can copy/paste it straight into the
  // provider's OAuth app console instead of guessing or mistyping it.
  return `${window.location.origin}/ainxt/v1/api/connectors/oauth/callback/${provider}`;
}
export function AdminOAuthApps() {
  const client = useEcosystemClient();
  const [apps, setApps] = useState(null);
  const [provider, setProvider] = useState(OAUTH_PROVIDERS[0].value);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [scopesInput, setScopesInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState(null);
  const reload = () => {
    client.listOAuthApps().then(setApps).catch(() => setApps([]));
  };
  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const handleCreate = e => {
    e.preventDefault();
    if (!clientId.trim() || !clientSecret.trim()) return;
    setSubmitting(true);
    setError(null);
    setStatus(null);
    client.createOAuthApp({
      provider,
      client_id: clientId.trim(),
      client_secret: clientSecret.trim(),
      redirect_uri: redirectUriFor(provider),
      scopes: scopesInput.split(",").map(s => s.trim()).filter(Boolean)
    }).then(() => {
      setStatus(`${OAUTH_PROVIDERS.find(p => p.value === provider)?.label ?? provider} is now configured -- Connect will redirect to its real sign-in page.`);
      setClientId("");
      setClientSecret("");
      setScopesInput("");
      reload();
    }).catch(err => setError(err instanceof Error ? err.message : "Couldn't register this OAuth app.")).finally(() => setSubmitting(false));
  };
  // User-flow QA round 8 (2026-10-03, audit finding): "Remove" fired
  // immediately on click -- deleting a live OAuth integration credential
  // every "Connect" on that provider currently depends on, with zero
  // confirmation, unlike every other destructive marketplace action.
  const [removing, setRemoving] = useState(null);
  const handleDelete = id => {
    setError(null);
    client.deleteOAuthApp(id).then(reload).catch(err => setError(err instanceof Error ? err.message : "Couldn't remove this OAuth app."));
  };
  return <div data-testid="admin-oauth-apps">
      <h2 className="text-xl text-gray-900">OAuth Apps</h2>
      <p className="text-gray-500 text-sm max-w-[640px]">
        Register a real OAuth client id/secret per provider so "Connect" on that connector redirects to the
        provider's own sign-in/consent page. The client secret is stored encrypted and is never shown again after
        creation -- see docs/ecosystem/CONNECTOR_SETUP.md for exactly which scopes and provider console to use.
      </p>

      <form onSubmit={handleCreate} className="flex flex-col gap-2 max-w-[480px] mb-6">
        <label className="text-sm text-gray-500">
          Provider
          <select data-testid="oauth-app-provider" value={provider} onChange={e => setProvider(e.target.value)} className={inputClass}>
            {OAUTH_PROVIDERS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
        </label>

        <div className="text-xs text-gray-400">
          Redirect/callback URL to register with the provider:{" "}
          <code data-testid="oauth-app-redirect-uri" className="select-all">{redirectUriFor(provider)}</code>
        </div>

        <label className="text-sm text-gray-500">
          Client ID
          <input data-testid="oauth-app-client-id" value={clientId} onChange={e => setClientId(e.target.value)} required className={inputClass} />
        </label>

        <label className="text-sm text-gray-500">
          Client secret
          <input data-testid="oauth-app-client-secret" type="password" value={clientSecret} onChange={e => setClientSecret(e.target.value)} required className={inputClass} />
        </label>

        <label className="text-sm text-gray-500">
          Scopes (comma-separated, optional -- defaults to the connector's own if left blank)
          <input data-testid="oauth-app-scopes" value={scopesInput} onChange={e => setScopesInput(e.target.value)} placeholder="repo" className={inputClass} />
        </label>

        <Button type="submit" data-testid="oauth-app-submit" disabled={submitting} className="self-start">
          {submitting ? "Saving…" : "Save OAuth app"}
        </Button>
      </form>

      {status && <p data-testid="oauth-app-status" className="text-green-700">{status}</p>}
      {error && <p role="alert" data-testid="oauth-app-error" className="text-red-600">{error}</p>}

      <h3 className="text-sm text-gray-900">Configured</h3>
      {apps === null ? <p data-testid="oauth-apps-loading">Loading…</p> : apps.length === 0 ? <p data-testid="oauth-apps-empty" className="text-gray-400">No OAuth apps configured yet.</p> : <table data-testid="oauth-apps-list" className="w-full border-collapse text-sm">
          <thead>
            <tr className="text-left border-b border-gray-200">
              <th className="px-2 py-1.5">Provider</th>
              <th className="px-2 py-1.5">Client ID</th>
              <th className="px-2 py-1.5">Scopes</th>
              <th className="px-2 py-1.5">Added by</th>
              <th className="px-2 py-1.5" />
            </tr>
          </thead>
          <tbody>
            {apps.map(app => <tr key={app.id} data-testid="oauth-app-row" className="border-b border-gray-200">
                <td className="px-2 py-1.5">{OAUTH_PROVIDERS.find(p => p.value === app.provider)?.label ?? app.provider}</td>
                <td className="px-2 py-1.5 font-mono">{app.client_id}</td>
                <td className="px-2 py-1.5">{app.scopes.join(", ") || "—"}</td>
                <td className="px-2 py-1.5">{app.created_by}</td>
                <td className="px-2 py-1.5">
                  <button type="button" data-testid="oauth-app-delete" onClick={() => setRemoving(app)} className="bg-none border-none text-red-600 hover:opacity-70 cursor-pointer transition-colors">
                    Remove
                  </button>
                </td>
              </tr>)}
          </tbody>
        </table>}
      <ConfirmDialog
        open={removing !== null}
        title="Remove this OAuth app?"
        message={`"Connect" for ${OAUTH_PROVIDERS.find(p => p.value === removing?.provider)?.label ?? removing?.provider} will fall back to this connector's own default credentials (or fail to connect at all if none are configured) until a new one is registered.`}
        confirmLabel="Remove"
        danger
        onConfirm={() => {
          handleDelete(removing.id);
          setRemoving(null);
        }}
        onCancel={() => setRemoving(null)}
      />
    </div>;
}