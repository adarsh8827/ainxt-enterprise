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
import { useCallback, useEffect, useState } from "react";
import { useEcosystemClient } from "../lib/context/HostContext";
import { ToggleSwitch } from "../ToggleSwitch";
import { Button } from "../Button";
// UX-03 fix: 7 sections used to stack with only <h3> headings between
// them on the single densest admin screen -- no card boundaries, no
// in-page nav, easy to lose track of which section you're looking at
// after scrolling. Each section now gets the same bordered/padded panel
// (UX-02's convention, applied here too) plus an id the new jump-nav
// below links to.
const SECTION_CLASS = "mb-6 rounded-md border border-gray-200 bg-gray-50 p-4";
const H3_CLASS = "text-lg text-gray-900 mb-2";
const SECTION_NAV = [{
  id: "sources-catalog",
  label: "External catalog"
}, {
  id: "sources-live-search",
  label: "Live search"
}, {
  id: "sources-well-known",
  label: "Approved websites"
}, {
  id: "sources-org-sources",
  label: "Org sources"
}, {
  id: "sources-service-health",
  label: "Service health"
}, {
  id: "sources-github-credential",
  label: "GitHub credential"
}, {
  id: "sources-gate-policies",
  label: "Verification policies"
}];
const TABLE_CLASS = "w-full border-collapse text-sm";
const TH_CLASS = "text-left text-gray-500";
const TD_MUTED_CLASS = "text-gray-400";
const inputClass = "bg-white border border-gray-300 rounded px-3 py-2 text-sm text-gray-900 focus:outline-none focus-visible:outline-none! focus:border-indigo-300";
function StatusPill({
  ok,
  label
}) {
  return <span data-testid="admin-sources-status-pill" data-ok={ok} className={["text-xs px-2 py-0.5 rounded-full border", ok ? "text-green-700 border-green-700" : "text-red-700 border-red-700"].join(" ")}>
      {label}
    </span>;
}
export function AdminSources() {
  const client = useEcosystemClient();
  const [info, setInfo] = useState(null);
  const [policy, setPolicyState] = useState(null);
  const [error, setError] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState(null);
  const [saving, setSaving] = useState(false);
  // User-flow QA round 8 (2026-10-03, audit finding): savePolicy() below
  // had no .catch() at all, same bug as AdminPolicies.jsx's own save() --
  // a failed save left `policy` holding its pre-save value with zero
  // indication anything went wrong.
  const [saveError, setSaveError] = useState(null);
  const load = useCallback(() => {
    Promise.all([client.getAdminSources(), client.getPolicy()]).then(([sources, pol]) => {
      setInfo(sources);
      setPolicyState(pol);
    }).catch(e => setError(e instanceof Error ? e.message : String(e)));
  }, [client]);
  useEffect(() => {
    load();
  }, [load]);
  const savePolicy = patch => {
    setSaving(true);
    setSaveError(null);
    client.setPolicy(patch).then(setPolicyState).catch(e => setSaveError(e instanceof Error ? e.message : "Couldn't save this change.")).finally(() => setSaving(false));
  };
  const syncNow = () => {
    setSyncing(true);
    setSyncError(null);
    client.syncCatalogNow().then(report => {
      if (!report.ok) {
        const firstError = report.shards.find(s => s.error)?.error;
        setSyncError(firstError ?? "Sync completed with errors.");
      }
      load(); // re-fetch so last_sync reflects this exact run, synced_at included
    }).catch(e => setSyncError(e instanceof Error ? e.message : "Sync failed.")).finally(() => setSyncing(false));
  };
  if (error) return <div role="alert" data-testid="admin-sources-error">{error}</div>;
  if (!info || !policy) return <div data-testid="admin-sources-loading">Loading…</div>;
  return <div data-testid="admin-sources">
      <h2 className="text-xl text-gray-900 mb-3">Sources</h2>

      <nav data-testid="admin-sources-jump-nav" className="flex flex-wrap gap-3 mb-4 pb-3 border-b border-gray-200 text-sm">
        {SECTION_NAV.map(s => <a key={s.id} href={`#${s.id}`} className="text-indigo-600 hover:text-indigo-700 no-underline">
            {s.label}
          </a>)}
      </nav>

      {saveError && <p role="alert" data-testid="admin-sources-save-error" className="text-red-600 text-sm">{saveError}</p>}

      {/* ── Catalog: URL, signer, last sync, errors, Sync now ── */}
      <section id="sources-catalog" className={SECTION_CLASS} data-testid="admin-sources-catalog">
        <h3 className={H3_CLASS}>External catalog</h3>
        <div className="flex gap-4 items-center mb-2">
          <span data-testid="admin-sources-catalog-url" className="font-mono text-sm text-gray-900 break-all">
            {info.catalog_url ?? "Not configured (ECOSYSTEM_CATALOG_URL is unset)"}
          </span>
          <StatusPill ok={info.catalog_signer_configured} label={info.catalog_signer_configured ? "Signer configured" : "No trusted signer"} />
        </div>

        <Button data-testid="admin-sources-sync-now" onClick={syncNow} disabled={syncing || !info.catalog_url} className="mb-2">
          {syncing ? "Syncing…" : "Sync now"}
        </Button>
        {syncError && <div role="alert" data-testid="admin-sources-sync-error" className="text-red-600 text-sm mb-2">
            {syncError}
          </div>}

        {info.last_sync === null ? <p data-testid="admin-sources-no-sync-yet" className="text-gray-400 text-sm">
            No sync has run yet on this instance.
          </p> : <>
            <p className="text-sm text-gray-500">
              Last synced {new Date(info.last_sync.synced_at).toLocaleString()} — <StatusPill ok={info.last_sync.ok} label={info.last_sync.ok ? "OK" : "Errors"} />
            </p>
            <table className={TABLE_CLASS} data-testid="admin-sources-last-sync-table">
              <thead>
                <tr className={TH_CLASS}><th>Shard</th><th>Fetched</th><th>Verified</th><th>Created</th><th>Updated</th><th>Yanked</th><th>Error</th></tr>
              </thead>
              <tbody>
                {info.last_sync.shards.map(s => <tr key={s.shard} data-testid="admin-sources-shard-row" className="border-t border-gray-200">
                    <td>{s.shard}</td>
                    <td>{s.fetched ? "yes" : "no (unchanged)"}</td>
                    <td>{s.verified ? "yes" : "no"}</td>
                    <td>{s.created}</td>
                    <td>{s.updated}</td>
                    <td>{s.yanked}</td>
                    <td className="text-red-600">{s.error ?? "—"}</td>
                  </tr>)}
              </tbody>
            </table>
          </>}
      </section>

      {/* ── Live search on/off (org policy toggle over the instance-wide flag) ── */}
      <section id="sources-live-search" className={SECTION_CLASS} data-testid="admin-sources-live-search">
        <h3 className={H3_CLASS}>Live search ("From the web")</h3>
        <div className="flex items-center gap-2">
          <ToggleSwitch checked={policy.live_sources_enabled} disabled={saving || !info.live_sources_flag_enabled} label="Live search enabled for this org" onChange={next => savePolicy({
          live_sources_enabled: next
        })} />
          <span className="text-sm text-gray-900">
            Enable Discover's "From the web" live-search section for this org
          </span>
        </div>
        {!info.live_sources_flag_enabled && <p className="text-xs text-gray-400 mt-1 mb-0">
            Live search isn't enabled on this deployment (ECOSYSTEM_LIVE_SOURCES is off instance-wide) — this toggle has no effect until an administrator enables it.
          </p>}
      </section>

      {/* ── Approved websites (read-only -- sources.yaml is a reviewed-PR-only file) ── */}
      <section id="sources-well-known" className={SECTION_CLASS} data-testid="admin-sources-well-known">
        <h3 className={H3_CLASS}>Approved websites</h3>
        {info.sources_yaml_error ? <div role="alert" data-testid="admin-sources-yaml-error" className="text-red-600 text-sm">
            Couldn't read the crawl allowlist: {info.sources_yaml_error}
          </div> : info.well_known_sites.length === 0 ? <p className="text-gray-400 text-sm">No approved websites configured.</p> : <table className={TABLE_CLASS}>
            <thead><tr className={TH_CLASS}><th>Domain</th><th>Category</th><th>Tags</th><th>ToS note</th></tr></thead>
            <tbody>
              {info.well_known_sites.map(w => <tr key={w.domain} data-testid="admin-sources-well-known-row" className="border-t border-gray-200">
                  <td className="font-mono">{w.domain}</td>
                  <td>{w.category}</td>
                  <td className={TD_MUTED_CLASS}>{w.tags.join(", ") || "—"}</td>
                  <td className={TD_MUTED_CLASS}>{w.tos_note || "—"}</td>
                </tr>)}
            </tbody>
          </table>}
        <p className="text-xs text-gray-400 mt-1 mb-0">
          Editing this list requires a reviewed pull request against docs/ecosystem/catalog/sources.yaml — not editable from this screen.
        </p>
      </section>

      {/* ── Org sources ── */}
      <section id="sources-org-sources" className={SECTION_CLASS} data-testid="admin-sources-org-sources">
        <h3 className={H3_CLASS}>Org sources</h3>
        {info.org_sources.length === 0 ? <p data-testid="admin-sources-org-sources-empty" className="text-gray-400 text-sm">
            No sources recorded for this org yet.
          </p> : <table className={TABLE_CLASS}>
            <thead><tr className={TH_CLASS}><th>Kind</th><th>URL</th><th>Enabled</th><th>Credential</th><th>Created</th></tr></thead>
            <tbody>
              {info.org_sources.map(s => <tr key={s.id} data-testid="admin-sources-org-source-row" className="border-t border-gray-200">
                  <td>{s.kind}</td>
                  <td className={["font-mono", TD_MUTED_CLASS].join(" ")}>{s.url ?? "—"}</td>
                  <td>{s.enabled ? "yes" : "no"}</td>
                  <td><StatusPill ok={s.credential_configured} label={s.credential_configured ? "Configured" : "Not configured"} /></td>
                  <td className={TD_MUTED_CLASS}>{s.created_at ? new Date(s.created_at).toLocaleDateString() : "—"}</td>
                </tr>)}
            </tbody>
          </table>}
      </section>

      {/* ── Ecosystem service health (real incident, 2026-09-29): a stale
          gateway/gate-worker/gate-sweeper process serving old code kept
          surfacing as false live bugs, only found by manually inspecting
          docker logs/queue depths. Each service self-reports its own
          commit + start time; this renders that directly, plus computed
          warnings (commit mismatch, a gate worker missing a priority
          lane) so a stale process is visible here first. ── */}
      <section id="sources-service-health" className={SECTION_CLASS} data-testid="admin-sources-service-health">
        <h3 className={H3_CLASS}>Ecosystem service health</h3>
        {info.service_health.warnings.length > 0 && <ul data-testid="admin-sources-service-health-warnings" className="text-red-600 text-sm mb-2 pl-5">
            {info.service_health.warnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>}
        <table className={TABLE_CLASS}>
          <thead><tr className={TH_CLASS}><th>Service</th><th>Commit</th><th>Started</th><th>Status</th></tr></thead>
          <tbody>
            {Object.entries(info.service_health.services).map(([name, svc]) => <tr key={name} data-testid="admin-sources-service-health-row" className="border-t border-gray-200">
                <td>{name}</td>
                <td className={["font-mono", TD_MUTED_CLASS].join(" ")}>{svc?.commit ?? "—"}</td>
                <td className={TD_MUTED_CLASS}>{svc?.started_at ? new Date(svc.started_at).toLocaleString() : "—"}</td>
                <td>
                  {svc == null ? <StatusPill ok={false} label="Never reported" /> : <StatusPill ok={!svc.commit_mismatch} label={svc.commit_mismatch ? "Commit mismatch" : "OK"} />}
                </td>
              </tr>)}
          </tbody>
        </table>
      </section>

      {/* ── GitHub credential status (never the actual secret value) ── */}
      <section id="sources-github-credential" className={SECTION_CLASS} data-testid="admin-sources-github-credential">
        <h3 className={H3_CLASS}>GitHub import credential</h3>
        <StatusPill ok={info.github_credential_configured} label={info.github_credential_configured ? "Configured" : "Not configured"} />
        {info.github_credential_hint && <p className="text-sm text-gray-500 mt-1.5">
            {info.github_credential_hint}
          </p>}
      </section>

      {/* ── Ethics review + pre-check policies ── */}
      <section id="sources-gate-policies" className={SECTION_CLASS} data-testid="admin-sources-gate-policies">
        <h3 className={H3_CLASS}>Verification policies</h3>
        <fieldset className="border-none p-0 mb-4">
          <legend className="text-sm text-gray-500">Ethics review</legend>
          {["always", "scripts_or_noncatalog", "never"].map(v => <label key={v} className="flex items-center gap-1.5 text-gray-900">
              <input type="radio" name="ethics_review_policy" value={v} checked={policy.ethics_review_policy === v} disabled={saving} onChange={() => savePolicy({
            ethics_review_policy: v
          })} />
              {v === "always" ? "Always run ethics review" : v === "never" ? "Never run ethics review" : "Only for scripts or non-catalog items (default)"}
            </label>)}
        </fieldset>

        <div className="flex items-center gap-2 mb-2">
          <ToggleSwitch checked={policy.gate_precheck_enabled} disabled={saving} label="Background pre-check enabled" onChange={next => savePolicy({
          gate_precheck_enabled: next
        })} />
          <span className="text-sm text-gray-900">
            Pre-check featured/popular catalog items in the background
          </span>
        </div>
        <label className="flex items-center gap-1.5 text-sm text-gray-500">
          Cap per hour
          <input type="number" min={1} data-testid="admin-sources-precheck-cap" value={policy.gate_precheck_cap_per_hour} disabled={saving || !policy.gate_precheck_enabled} onChange={e => {
          const next = Number(e.target.value);
          if (Number.isFinite(next) && next > 0) savePolicy({
            gate_precheck_cap_per_hour: next
          });
        }} className={[inputClass, "w-[70px] px-1.5 py-1"].join(" ")} />
        </label>
        <p className="text-xs text-gray-400 mt-2 mb-0">
          Auto-update default and who-can-add/share are managed on the Policies tab.
        </p>
      </section>
    </div>;
}
