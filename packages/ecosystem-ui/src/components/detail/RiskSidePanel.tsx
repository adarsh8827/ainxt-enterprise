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
import type { ItemDetail, SourceKind } from "../../types";

const SOURCE_KIND_LABEL: Record<SourceKind, string> = {
  github_repo: "GitHub", mcp_registry: "MCP registry", well_known: "well-known catalog",
  private_git: "private Git", skills_sh_indirect: "skills.sh", local: "this install",
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
function publisherLine(item: ItemDetail): string {
  if (item.publisher.type === "org") return `${item.publisher.slug} (organization)`;
  if (item.publisher.type === "user") return `${item.publisher.slug} (user)`;
  const sourceLabel = SOURCE_KIND_LABEL[item.source.kind] ?? item.source.kind;
  const cleanUrl = item.source.url?.replace(/^https?:\/\//, "");
  return cleanUrl ? `${item.publisher.slug} (via ${sourceLabel}: ${cleanUrl})` : `${item.publisher.slug} (via ${sourceLabel})`;
}

export function RiskSidePanel({ item }: { item: ItemDetail }) {
  return (
    <aside data-testid="risk-side-panel" style={{ display: "flex", flexDirection: "column", gap: "var(--eco-space-md)" }}>
      <div style={{ padding: "var(--eco-space-md)", borderRadius: "var(--eco-radius-md)", background: "var(--eco-color-surface)", fontSize: "var(--eco-font-sizeSm)" }}>
        <h4 style={{ margin: "0 0 8px", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textPrimary)" }}>Item details</h4>
        <dl data-testid="detail-metadata" style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "4px 12px", margin: 0, color: "var(--eco-color-textSecondary)" }}>
          <dt>Namespace</dt><dd>{item.namespace}</dd>
          <dt>Publisher</dt><dd data-testid="detail-publisher">{publisherLine(item)}</dd>
          <dt>License</dt><dd>{item.license}</dd>
          <dt>Category</dt><dd style={{ textTransform: "capitalize" }}>{item.category.replace(/-/g, " ")}</dd>
          <dt>Version</dt><dd>{item.latest_version ?? "—"}</dd>
        </dl>
      </div>

      {item.item_type === "skill" && (
        <div style={{ padding: "var(--eco-space-md)", borderRadius: "var(--eco-radius-md)", background: "var(--eco-color-surface)", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}>
          <h4 style={{ margin: "0 0 8px", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textPrimary)" }}>What this can do</h4>
          <p style={{ margin: 0 }}>Only gives the assistant instructions. It can't access the internet or your files.</p>
        </div>
      )}
    </aside>
  );
}
