// SPDX-License-Identifier: MIT
// Task 3a: admin Sources screen -- catalog URL/last-sync/signature status/
// errors, "Sync now," live-search on/off, approved websites, org sources,
// GitHub credential status, ethics/pre-check policies. Backed by GET
// /ecosystem/admin/sources (new, this task) + the existing GET/PUT
// /ecosystem/policy (task F-13) -- reuses AdminPolicies.tsx's own
// fetch/save pattern and ToggleSwitch.tsx rather than inventing new
// primitives (auto_update_default itself is already editable there; this
// screen only adds the policy fields that had nowhere to live yet:
// ethics_review_policy, gate_precheck_*, live_sources_enabled).
import { useCallback, useEffect, useState, type CSSProperties } from "react";
import type { AdminSourcesInfo, OrgPolicy } from "../../types";
import { useEcosystemClient } from "../../context/HostContext";
import { ToggleSwitch } from "../ToggleSwitch";

const SECTION_STYLE: CSSProperties = { marginBottom: "var(--eco-space-lg)" };
const H3_STYLE: CSSProperties = { fontSize: "var(--eco-font-sizeLg)", color: "var(--eco-color-textPrimary)", marginBottom: "var(--eco-space-sm)" };
const TABLE_STYLE: CSSProperties = { width: "100%", borderCollapse: "collapse", fontSize: "var(--eco-font-sizeSm)" };
const TH_STYLE: CSSProperties = { textAlign: "left", color: "var(--eco-color-textSecondary)" };
const TD_MUTED: CSSProperties = { color: "var(--eco-color-textMuted)" };

function StatusPill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      data-testid="admin-sources-status-pill"
      data-ok={ok}
      style={{
        fontSize: "var(--eco-font-sizeXs)", padding: "2px 8px", borderRadius: "var(--eco-radius-full)",
        color: ok ? "var(--eco-color-success)" : "var(--eco-color-danger)",
        border: `1px solid ${ok ? "var(--eco-color-success)" : "var(--eco-color-danger)"}`,
      }}
    >
      {label}
    </span>
  );
}

export function AdminSources() {
  const client = useEcosystemClient();
  const [info, setInfo] = useState<AdminSourcesInfo | null>(null);
  const [policy, setPolicyState] = useState<OrgPolicy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    Promise.all([client.getAdminSources(), client.getPolicy()])
      .then(([sources, pol]) => { setInfo(sources); setPolicyState(pol); })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [client]);

  useEffect(() => { load(); }, [load]);

  const savePolicy = (patch: Partial<OrgPolicy>) => {
    setSaving(true);
    client.setPolicy(patch).then(setPolicyState).finally(() => setSaving(false));
  };

  const syncNow = () => {
    setSyncing(true);
    setSyncError(null);
    client.syncCatalogNow()
      .then((report) => {
        if (!report.ok) {
          const firstError = report.shards.find((s) => s.error)?.error;
          setSyncError(firstError ?? "Sync completed with errors.");
        }
        load(); // re-fetch so last_sync reflects this exact run, synced_at included
      })
      .catch((e) => setSyncError(e instanceof Error ? e.message : "Sync failed."))
      .finally(() => setSyncing(false));
  };

  if (error) return <div role="alert" data-testid="admin-sources-error">{error}</div>;
  if (!info || !policy) return <div data-testid="admin-sources-loading">Loading…</div>;

  return (
    <div data-testid="admin-sources">
      <h2 style={{ fontSize: "var(--eco-font-sizeXl)", color: "var(--eco-color-textPrimary)" }}>Sources</h2>

      {/* ── Catalog: URL, signer, last sync, errors, Sync now ── */}
      <section style={SECTION_STYLE} data-testid="admin-sources-catalog">
        <h3 style={H3_STYLE}>External catalog</h3>
        <div style={{ display: "flex", gap: "var(--eco-space-md)", alignItems: "center", marginBottom: "var(--eco-space-sm)" }}>
          <span data-testid="admin-sources-catalog-url" style={{ fontFamily: "monospace", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textPrimary)", wordBreak: "break-all" }}>
            {info.catalog_url ?? "Not configured (ECOSYSTEM_CATALOG_URL is unset)"}
          </span>
          <StatusPill ok={info.catalog_signer_configured} label={info.catalog_signer_configured ? "Signer configured" : "No trusted signer"} />
        </div>

        <button
          type="button"
          data-testid="admin-sources-sync-now"
          onClick={syncNow}
          disabled={syncing || !info.catalog_url}
          style={{
            padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "none", cursor: "pointer",
            background: "var(--eco-color-accentSkill)", color: "var(--eco-color-accentSkillText)",
            opacity: syncing || !info.catalog_url ? 0.6 : 1, marginBottom: "var(--eco-space-sm)",
          }}
        >
          {syncing ? "Syncing…" : "Sync now"}
        </button>
        {syncError && (
          <div role="alert" data-testid="admin-sources-sync-error" style={{ color: "var(--eco-color-danger)", fontSize: "var(--eco-font-sizeSm)", marginBottom: "var(--eco-space-sm)" }}>
            {syncError}
          </div>
        )}

        {info.last_sync === null ? (
          <p data-testid="admin-sources-no-sync-yet" style={{ color: "var(--eco-color-textMuted)", fontSize: "var(--eco-font-sizeSm)" }}>
            No sync has run yet on this instance.
          </p>
        ) : (
          <>
            <p style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}>
              Last synced {new Date(info.last_sync.synced_at).toLocaleString()} — <StatusPill ok={info.last_sync.ok} label={info.last_sync.ok ? "OK" : "Errors"} />
            </p>
            <table style={TABLE_STYLE} data-testid="admin-sources-last-sync-table">
              <thead>
                <tr style={TH_STYLE}><th>Shard</th><th>Fetched</th><th>Verified</th><th>Created</th><th>Updated</th><th>Yanked</th><th>Error</th></tr>
              </thead>
              <tbody>
                {info.last_sync.shards.map((s) => (
                  <tr key={s.shard} data-testid="admin-sources-shard-row" style={{ borderTop: "1px solid var(--eco-color-border)" }}>
                    <td>{s.shard}</td>
                    <td>{s.fetched ? "yes" : "no (unchanged)"}</td>
                    <td>{s.verified ? "yes" : "no"}</td>
                    <td>{s.created}</td>
                    <td>{s.updated}</td>
                    <td>{s.yanked}</td>
                    <td style={{ color: "var(--eco-color-danger)" }}>{s.error ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>

      {/* ── Live search on/off (org policy toggle over the instance-wide flag) ── */}
      <section style={SECTION_STYLE} data-testid="admin-sources-live-search">
        <h3 style={H3_STYLE}>Live search ("From the web")</h3>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--eco-space-sm)" }}>
          <ToggleSwitch
            checked={policy.live_sources_enabled}
            disabled={saving || !info.live_sources_flag_enabled}
            label="Live search enabled for this org"
            onChange={(next) => savePolicy({ live_sources_enabled: next })}
          />
          <span style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textPrimary)" }}>
            Enable Discover's "From the web" live-search section for this org
          </span>
        </div>
        {!info.live_sources_flag_enabled && (
          <p style={{ fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textMuted)", margin: "4px 0 0" }}>
            Live search isn't enabled on this deployment (ECOSYSTEM_LIVE_SOURCES is off instance-wide) — this toggle has no effect until an administrator enables it.
          </p>
        )}
      </section>

      {/* ── Approved websites (read-only -- sources.yaml is a reviewed-PR-only file) ── */}
      <section style={SECTION_STYLE} data-testid="admin-sources-well-known">
        <h3 style={H3_STYLE}>Approved websites</h3>
        {info.sources_yaml_error ? (
          <div role="alert" data-testid="admin-sources-yaml-error" style={{ color: "var(--eco-color-danger)", fontSize: "var(--eco-font-sizeSm)" }}>
            Couldn't read the crawl allowlist: {info.sources_yaml_error}
          </div>
        ) : info.well_known_sites.length === 0 ? (
          <p style={{ color: "var(--eco-color-textMuted)", fontSize: "var(--eco-font-sizeSm)" }}>No approved websites configured.</p>
        ) : (
          <table style={TABLE_STYLE}>
            <thead><tr style={TH_STYLE}><th>Domain</th><th>Category</th><th>Tags</th><th>ToS note</th></tr></thead>
            <tbody>
              {info.well_known_sites.map((w) => (
                <tr key={w.domain} data-testid="admin-sources-well-known-row" style={{ borderTop: "1px solid var(--eco-color-border)" }}>
                  <td style={{ fontFamily: "monospace" }}>{w.domain}</td>
                  <td>{w.category}</td>
                  <td style={TD_MUTED}>{w.tags.join(", ") || "—"}</td>
                  <td style={TD_MUTED}>{w.tos_note || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p style={{ fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textMuted)", margin: "4px 0 0" }}>
          Editing this list requires a reviewed pull request against docs/ecosystem/catalog/sources.yaml — not editable from this screen.
        </p>
      </section>

      {/* ── Org sources ── */}
      <section style={SECTION_STYLE} data-testid="admin-sources-org-sources">
        <h3 style={H3_STYLE}>Org sources</h3>
        {info.org_sources.length === 0 ? (
          <p data-testid="admin-sources-org-sources-empty" style={{ color: "var(--eco-color-textMuted)", fontSize: "var(--eco-font-sizeSm)" }}>
            No sources recorded for this org yet.
          </p>
        ) : (
          <table style={TABLE_STYLE}>
            <thead><tr style={TH_STYLE}><th>Kind</th><th>URL</th><th>Enabled</th><th>Credential</th><th>Created</th></tr></thead>
            <tbody>
              {info.org_sources.map((s) => (
                <tr key={s.id} data-testid="admin-sources-org-source-row" style={{ borderTop: "1px solid var(--eco-color-border)" }}>
                  <td>{s.kind}</td>
                  <td style={{ fontFamily: "monospace", ...TD_MUTED }}>{s.url ?? "—"}</td>
                  <td>{s.enabled ? "yes" : "no"}</td>
                  <td><StatusPill ok={s.credential_configured} label={s.credential_configured ? "Configured" : "Not configured"} /></td>
                  <td style={TD_MUTED}>{s.created_at ? new Date(s.created_at).toLocaleDateString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* ── Ecosystem service health (real incident, 2026-09-29): a stale
          gateway/gate-worker/gate-sweeper process serving old code kept
          surfacing as false live bugs, only found by manually inspecting
          docker logs/queue depths. Each service self-reports its own
          commit + start time; this renders that directly, plus computed
          warnings (commit mismatch, a gate worker missing a priority
          lane) so a stale process is visible here first. ── */}
      <section style={SECTION_STYLE} data-testid="admin-sources-service-health">
        <h3 style={H3_STYLE}>Ecosystem service health</h3>
        {info.service_health.warnings.length > 0 && (
          <ul data-testid="admin-sources-service-health-warnings" style={{ color: "var(--eco-color-danger)", fontSize: "var(--eco-font-sizeSm)", margin: "0 0 var(--eco-space-sm) 0", paddingLeft: "1.2em" }}>
            {info.service_health.warnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        )}
        <table style={TABLE_STYLE}>
          <thead><tr style={TH_STYLE}><th>Service</th><th>Commit</th><th>Started</th><th>Status</th></tr></thead>
          <tbody>
            {Object.entries(info.service_health.services).map(([name, svc]) => (
              <tr key={name} data-testid="admin-sources-service-health-row" style={{ borderTop: "1px solid var(--eco-color-border)" }}>
                <td>{name}</td>
                <td style={{ fontFamily: "monospace", ...TD_MUTED }}>{svc?.commit ?? "—"}</td>
                <td style={TD_MUTED}>{svc?.started_at ? new Date(svc.started_at).toLocaleString() : "—"}</td>
                <td>
                  {svc == null
                    ? <StatusPill ok={false} label="Never reported" />
                    : <StatusPill ok={!svc.commit_mismatch} label={svc.commit_mismatch ? "Commit mismatch" : "OK"} />}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {/* ── GitHub credential status (never the actual secret value) ── */}
      <section style={SECTION_STYLE} data-testid="admin-sources-github-credential">
        <h3 style={H3_STYLE}>GitHub import credential</h3>
        <StatusPill ok={info.github_credential_configured} label={info.github_credential_configured ? "Configured" : "Not configured"} />
        {info.github_credential_hint && (
          <p style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)", marginTop: "6px" }}>
            {info.github_credential_hint}
          </p>
        )}
      </section>

      {/* ── Ethics review + pre-check policies ── */}
      <section style={SECTION_STYLE} data-testid="admin-sources-gate-policies">
        <h3 style={H3_STYLE}>Verification policies</h3>
        <fieldset style={{ border: "none", padding: 0, marginBottom: "var(--eco-space-md)" }}>
          <legend style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}>Ethics review</legend>
          {(["always", "scripts_or_noncatalog", "never"] as const).map((v) => (
            <label key={v} style={{ display: "flex", alignItems: "center", gap: "6px", color: "var(--eco-color-textPrimary)" }}>
              <input
                type="radio" name="ethics_review_policy" value={v} checked={policy.ethics_review_policy === v} disabled={saving}
                onChange={() => savePolicy({ ethics_review_policy: v })}
              />
              {v === "always" ? "Always run ethics review" : v === "never" ? "Never run ethics review" : "Only for scripts or non-catalog items (default)"}
            </label>
          ))}
        </fieldset>

        <div style={{ display: "flex", alignItems: "center", gap: "var(--eco-space-sm)", marginBottom: "var(--eco-space-sm)" }}>
          <ToggleSwitch
            checked={policy.gate_precheck_enabled}
            disabled={saving}
            label="Background pre-check enabled"
            onChange={(next) => savePolicy({ gate_precheck_enabled: next })}
          />
          <span style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textPrimary)" }}>
            Pre-check featured/popular catalog items in the background
          </span>
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}>
          Cap per hour
          <input
            type="number" min={1} data-testid="admin-sources-precheck-cap"
            value={policy.gate_precheck_cap_per_hour} disabled={saving || !policy.gate_precheck_enabled}
            onChange={(e) => {
              const next = Number(e.target.value);
              if (Number.isFinite(next) && next > 0) savePolicy({ gate_precheck_cap_per_hour: next });
            }}
            style={{ width: "70px", padding: "4px 6px", borderRadius: "var(--eco-radius-sm)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)" }}
          />
        </label>
        <p style={{ fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textMuted)", margin: "8px 0 0" }}>
          Auto-update default and who-can-add/share are managed on the Policies tab.
        </p>
      </section>
    </div>
  );
}
