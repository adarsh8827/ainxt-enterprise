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
  return <aside data-testid="risk-side-panel" className="flex flex-col gap-4">
      <div className="p-4 rounded-md bg-gray-50 border border-gray-200 shadow-sm text-sm">
        <h4 className="mt-0 mb-2 text-sm text-gray-900">Item details</h4>
        {/* User-flow QA round 5 (2026-10-03): the "auto 1fr" second column
            had the grid's own default min-width:auto -- a long, unbroken
            Publisher URL (e.g. "github.com/org/some-long-repo-name") has no
            spaces to wrap on, so its min-content width forced this whole
            grid (and the page under it) wider than the viewport, producing
            an unwanted horizontal scrollbar and making the Detail page look
            like content was cut off. minmax(0, 1fr) removes that forced
            minimum; overflowWrap lets the long word itself break instead of
            overflowing once the column is actually narrow. */}
        <dl data-testid="detail-metadata" className="grid gap-x-3 gap-y-1 m-0 text-gray-500 break-words" style={{
        gridTemplateColumns: "auto minmax(0, 1fr)"
      }}>
          <dt>Namespace</dt><dd>{item.namespace}</dd>
          <dt>Publisher</dt><dd data-testid="detail-publisher">{publisherLine(item)}</dd>
          <dt>License</dt><dd>{item.license}</dd>
          <dt>Category</dt><dd className="capitalize">{item.category.replace(/-/g, " ")}</dd>
          <dt>Version</dt><dd>{item.latest_version ?? "—"}</dd>
        </dl>
      </div>

      {item.item_type === "skill" && <div className="p-4 rounded-md bg-gray-50 border border-gray-200 shadow-sm text-sm text-gray-500">
          <h4 className="mt-0 mb-2 text-sm text-gray-900">What this can do</h4>
          <p className="m-0">Only gives the assistant instructions. It can't access the internet or your files.</p>
        </div>}
    </aside>;
}