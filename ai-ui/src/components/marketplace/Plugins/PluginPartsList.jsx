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

import { useHost } from "../lib/context/HostContext";
import { detailPath } from "../lib/routing";
export function PluginPartsList({
  parts,
  routeSlug,
  emptyLabel
}) {
  const {
    router
  } = useHost();
  if (parts.length === 0) {
    return <p data-testid="plugin-parts-empty" className="text-gray-400 text-sm">{emptyLabel}</p>;
  }
  return <ul data-testid="plugin-parts-list" className="list-none p-0 m-0">
      {parts.map(part => <li key={part.namespace} data-testid="plugin-part-row" className="flex justify-between py-2 border-b border-gray-200">
          {routeSlug ? <button type="button" data-testid="plugin-part-link" onClick={() => router.navigate(detailPath(routeSlug, part.namespace))} className="bg-none border-none p-0 cursor-pointer text-left text-indigo-600 hover:opacity-70 font-semibold transition-colors">
              {part.display_name}
            </button> : <span className="font-semibold text-gray-900">{part.display_name}</span>}
          <span className="text-xs text-gray-400 font-mono">{part.namespace}</span>
        </li>)}
    </ul>;
}