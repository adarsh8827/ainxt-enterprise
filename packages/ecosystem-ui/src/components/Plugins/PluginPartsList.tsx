// SPDX-License-Identifier: MIT
// Renders one part-kind section of a plugin's manifest.parts (docs/
// ecosystem/PLUGINS_PHASE_PLAN.md §4). "skills"/"connectors"/"mcp_servers"
// are real EcosystemItem types with their own Detail page, so those rows
// deep-link there (via detailPath -- typeSlug is ROUTE_SLUGS[kind]).
// "commands"/"agents"/"hooks" have no ecosystem-item counterpart of their
// own anywhere in this codebase (confirmed: neither is an ItemType) -- for
// those, rows render as plain, non-clickable labels rather than guessing at
// a link target. Disclosed explicitly rather than silently making them
// look clickable.
import type { PluginPartRef } from "../../types";
import { useHost } from "../../context/HostContext";
import { detailPath } from "../../routing";

export function PluginPartsList({ parts, routeSlug, emptyLabel }: {
  parts: PluginPartRef[];
  /** Route slug (ROUTE_SLUGS[itemType], e.g. "skills"/"connectors"/"mcp")
   * to deep-link into -- omit for a part kind with no detail page of its own
   * (commands/agents/hooks). */
  routeSlug?: string;
  emptyLabel: string;
}) {
  const { router } = useHost();

  if (parts.length === 0) {
    return <p data-testid="plugin-parts-empty" style={{ color: "var(--eco-color-textMuted)", fontSize: "var(--eco-font-sizeSm)" }}>{emptyLabel}</p>;
  }

  return (
    <ul data-testid="plugin-parts-list" style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {parts.map((part) => (
        <li
          key={part.namespace}
          data-testid="plugin-part-row"
          style={{ display: "flex", justifyContent: "space-between", padding: "var(--eco-space-sm) 0", borderBottom: "1px solid var(--eco-color-border)" }}
        >
          {routeSlug ? (
            <button
              type="button"
              data-testid="plugin-part-link"
              onClick={() => router.navigate(detailPath(routeSlug, part.namespace))}
              style={{ background: "none", border: "none", padding: 0, cursor: "pointer", textAlign: "left", color: "var(--eco-color-accentSkill)", fontWeight: 600 }}
            >
              {part.display_name}
            </button>
          ) : (
            <span style={{ fontWeight: 600, color: "var(--eco-color-textPrimary)" }}>{part.display_name}</span>
          )}
          <span style={{ fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textMuted)", fontFamily: "monospace" }}>{part.namespace}</span>
        </li>
      ))}
    </ul>
  );
}
