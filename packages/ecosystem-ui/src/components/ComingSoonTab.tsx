// SPDX-License-Identifier: MIT
// Task F-8, Review fix 18: a read-only placeholder for any item_type whose
// GET /ecosystem/config state is "coming_soon" -- zero network calls fire
// for that type regardless of user interaction (F-8's own test
// requirement). Description text is static per type, not server-driven
// (CONTRACTS.md doesn't carry per-type copy) -- kept out of the
// check_no_hardcoded_config.py banned-literal set deliberately: these are
// display strings, not a rendering/gating decision, matching the same
// exemption reasoning as HostContext.tsx's DEFAULT_STRINGS.
import type { ItemType } from "../types";
import { ComingSoonBadge } from "./Badges";

const DESCRIPTIONS: Record<Exclude<ItemType, "skill">, string> = {
  plugin: "Bundle skills, connectors, and tools into one installable unit.",
  connector: "Connect the marketplace to external systems via OAuth.",
  mcp_server: "Bring any MCP-compatible tool server into the catalog.",
};

export function ComingSoonTab({ itemType }: { itemType: Exclude<ItemType, "skill"> }) {
  return (
    <div data-testid="coming-soon-tab" data-item-type={itemType} style={{ textAlign: "center", padding: "var(--eco-space-xl)" }}>
      <ComingSoonBadge />
      <p style={{ color: "var(--eco-color-textSecondary)", maxWidth: "480px", margin: "var(--eco-space-md) auto 0" }}>
        {DESCRIPTIONS[itemType]}
      </p>
    </div>
  );
}
