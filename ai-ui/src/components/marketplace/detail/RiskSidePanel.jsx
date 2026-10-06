// SPDX-License-Identifier: MIT
// UI-polish round: absorbed the item-metadata list (namespace/publisher/
// license/version/category) that used to live in both Detail.tsx's own
// header AND Overview.tsx's <dl> -- one place now, the side panel, no
// duplication. The plain-language risk copy below it stays skill-only
// (task F-7's own reasoning: a skill has no execution footprint beyond
// the model's own context window, unlike a future plugin/connector/MCP
// server, which will need a real risk model here) -- non-skill types get
// the metadata list with no risk copy underneath rather than a caveat
// that isn't true for them.

const SOURCE_KIND_LABEL = {
  github_repo: "GitHub",
  mcp_registry: "MCP registry",
  well_known: "well-known catalog",
  private_git: "private Git",
  skills_sh_indirect: "skills.sh",
  local: "this install"
};

/** Item 6.2 (2026-09-29 live-test round, real user report): "Publisher:
 * google-labs-code (user)" -- (user) was a hardcoded backend fallback
 * that never actually checked whether the publisher is a real individual
 * or an organization (services/ecosystem/items_service.py's get_item()).
 * A real ecosystem_publishers row's own owner_type IS a genuine signal
 * (who inside THIS AiNxt install owns the slug) and gets spelled out in
 * full below; item.publisher.type is null when no such row exists at all
 * -- always true for a crawled catalog item (item_scope 'central_index'),
 * since nobody in this install owns that external namespace. Getting the
 * REAL upstream distinction (GitHub's own Organization-vs-User on the
 * owner account -- a real field the GitHub API already returns, just not
 * threaded through the catalog crawler yet, a separate, larger,
 * crawler-side change out of this fix's scope) flowing end to end is a
 * bigger lift than this fix -- the user's own suggested fallback instead:
 * show the item's real, already-known source rather than a fabricated
 * label. */
function publisherLine(item) {
  if (item.publisher.type === "org") return `${item.publisher.slug} (organization)`;
  if (item.publisher.type === "user") return `${item.publisher.slug} (user)`;
  const sourceLabel = SOURCE_KIND_LABEL[item.source.kind] ?? item.source.kind;
  const cleanUrl = item.source.url?.replace(/^https?:\/\//, "");
  return cleanUrl ? `${item.publisher.slug} (via ${sourceLabel}: ${cleanUrl})` : `${item.publisher.slug} (via ${sourceLabel})`;
}
export function RiskSidePanel({
  item
}) {
  // Right-section redesign pass (2026-10-05, explicit product ask: "skill
  // details page right section need better design, alignment"): the old
  // `dt`/`dd` auto/1fr grid put every label and value on the SAME row,
  // which at this column's ~240px width left the value side only ~140px
  // wide after the label column -- "ainxt/weekly-status-report" had no
  // natural break point in that space and wrapped mid-word-ish. Stacked
  // label-over-value rows (same pattern as e.g. the admin panels' own
  // field lists) give the value the full card width to wrap into, reads
  // less cramped, and the small uppercase label matches FilterPopover.jsx's
  // own "Category"/"Publisher" group-label convention instead of a bare
  // text-sm heading one step removed from a plain paragraph.
  const FIELDS = [{
    label: "Namespace",
    value: item.namespace
  }, {
    label: "Publisher",
    value: publisherLine(item),
    testId: "detail-publisher"
  }, {
    label: "License",
    value: item.license
  }, {
    label: "Category",
    value: item.category.replace(/-/g, " "),
    capitalize: true
  }, {
    // Real confusion found live (2026-10-06, user report: "what about old
    // version, even it will confuse"): this always showed item.
    // latest_version -- the item's NEWEST version, regardless of which
    // version the caller's own install was actually pinned to. Someone
    // pinned to an older version (via a deliberate rollback, or because a
    // newer version failed verification) saw a version number here that
    // didn't match what they were actually running, with zero indication
    // the two had diverged. Prefers the install's own pinned version;
    // spells out both explicitly when they differ instead of picking one
    // silently.
    label: "Version",
    value: item.install_id && item.installed_version && item.installed_version !== item.latest_version
      ? `${item.installed_version} (installed) · ${item.latest_version ?? "—"} (latest)`
      : (item.installed_version ?? item.latest_version ?? "—")
  }];
  return <aside data-testid="risk-side-panel" className="flex flex-col gap-4">
      <div className="p-4 rounded-md bg-gray-50 border border-gray-200 shadow-sm">
        <h4 className="mt-0 mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">Item details</h4>
        <dl data-testid="detail-metadata" className="m-0 flex flex-col gap-3">
          {FIELDS.map(f => <div key={f.label} className="flex flex-col gap-0.5">
              <dt className="text-xs text-gray-400">{f.label}</dt>
              <dd data-testid={f.testId} className={["m-0 text-sm text-gray-900 break-words", f.capitalize ? "capitalize" : ""].join(" ")}>{f.value}</dd>
            </div>)}
        </dl>
      </div>

      {item.item_type === "skill" && <div className="p-4 rounded-md bg-gray-50 border border-gray-200 shadow-sm">
          <h4 className="mt-0 mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">What this can do</h4>
          <p className="m-0 text-sm text-gray-600">Only gives the assistant instructions. It can't access the internet or your files.</p>
        </div>}
    </aside>;
}