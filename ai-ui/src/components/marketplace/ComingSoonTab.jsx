// SPDX-License-Identifier: MIT
// Task F-8, Review fix 18: a read-only placeholder for any item_type whose
// GET /ecosystem/config state is "coming_soon" -- zero network calls fire
// for that type regardless of user interaction (F-8's own test
// requirement). Description/examples text is static per type, not
// server-driven (CONTRACTS.md doesn't carry per-type copy) -- kept out of
// the check_no_hardcoded_config.py banned-literal set deliberately: these
// are display strings, not a rendering/gating decision, matching the same
// exemption reasoning as HostContext.tsx's DEFAULT_STRINGS.
//
// UI-polish round: rebuilt from a bare description line into one clean
// empty state -- an icon, one line of copy, 2-3 concrete examples of what
// the type will eventually do, and a single "Coming soon" tag (not one
// per example).
import { PuzzlePieceIcon, LinkIcon, GlobeAltIcon } from "@heroicons/react/24/outline";
import { ComingSoonBadge } from "./Badges";
const ICON = {
  plugin: PuzzlePieceIcon,
  connector: LinkIcon,
  mcp_server: GlobeAltIcon
};
const DESCRIPTIONS = {
  plugin: "Bundle skills, connectors, and tools into one installable unit.",
  connector: "Connect the marketplace to external systems via OAuth.",
  mcp_server: "Bring any MCP-compatible tool server into the catalog."
};
const EXAMPLES = {
  plugin: ["A code-review plugin bundling 3 related skills", "A release-notes plugin with its own writing style"],
  connector: ["A Jira connector for reading and updating tickets", "A Slack connector for posting summaries", "A Google Drive connector for reading shared docs"],
  mcp_server: ["A Postgres MCP server for querying a database", "A filesystem MCP server for a sandboxed workspace", "A Figma MCP server for reading design files"]
};
export function ComingSoonTab({
  itemType
}) {
  const Icon = ICON[itemType];
  return <div data-testid="coming-soon-tab" data-item-type={itemType} className="text-center py-8">
      <Icon width={40} height={40} aria-hidden="true" className="text-gray-400 mx-auto mb-4" />
      <p className="text-gray-900 max-w-[480px] mx-auto mb-4 text-sm">
        {DESCRIPTIONS[itemType]}
      </p>
      <ul className="list-none p-0 mx-auto mb-4 max-w-[420px] text-gray-500 text-sm">
        {EXAMPLES[itemType].map(example => <li key={example} className="mb-1">{example}</li>)}
      </ul>
      <ComingSoonBadge />
    </div>;
}