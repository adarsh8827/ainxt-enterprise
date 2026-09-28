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
import type { ItemType } from "../types";
import { ComingSoonBadge } from "./Badges";

type ComingSoonType = Exclude<ItemType, "skill">;

const ICON: Record<ComingSoonType, typeof PuzzlePieceIcon> = {
  plugin: PuzzlePieceIcon, connector: LinkIcon, mcp_server: GlobeAltIcon,
};

const DESCRIPTIONS: Record<ComingSoonType, string> = {
  plugin: "Bundle skills, connectors, and tools into one installable unit.",
  connector: "Connect the marketplace to external systems via OAuth.",
  mcp_server: "Bring any MCP-compatible tool server into the catalog.",
};

const EXAMPLES: Record<ComingSoonType, string[]> = {
  plugin: ["A code-review plugin bundling 3 related skills", "A release-notes plugin with its own writing style"],
  connector: ["A Jira connector for reading and updating tickets", "A Slack connector for posting summaries", "A Google Drive connector for reading shared docs"],
  mcp_server: ["A Postgres MCP server for querying a database", "A filesystem MCP server for a sandboxed workspace", "A Figma MCP server for reading design files"],
};

export function ComingSoonTab({ itemType }: { itemType: ComingSoonType }) {
  const Icon = ICON[itemType];
  return (
    <div data-testid="coming-soon-tab" data-item-type={itemType} style={{ textAlign: "center", padding: "var(--eco-space-xl)" }}>
      <Icon width={40} height={40} aria-hidden="true" style={{ color: "var(--eco-color-textMuted)", margin: "0 auto var(--eco-space-md)" }} />
      <p style={{ color: "var(--eco-color-textPrimary)", maxWidth: "480px", margin: "0 auto var(--eco-space-md)", fontSize: "var(--eco-font-sizeMd)" }}>
        {DESCRIPTIONS[itemType]}
      </p>
      <ul style={{ listStyle: "none", padding: 0, margin: "0 auto var(--eco-space-md)", maxWidth: "420px", color: "var(--eco-color-textSecondary)", fontSize: "var(--eco-font-sizeSm)" }}>
        {EXAMPLES[itemType].map((example) => (
          <li key={example} style={{ marginBottom: "4px" }}>{example}</li>
        ))}
      </ul>
      <ComingSoonBadge />
    </div>
  );
}
