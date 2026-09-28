// SPDX-License-Identifier: MIT
// Task F-5: "a component test per badge state (verified/org/community/
// agent_created x pass/warn/fail/pending)" -- this story renders the full
// cross product so every combination is visually reviewable, in both
// themes/layouts via the global toolbar (task-wide "Storybook stories
// full/compact x light/dark" requirement).
import type { Meta, StoryObj } from "@storybook/react-vite";
import type { ItemSummary, GateVerdict, TrustTier } from "../types";
import { Card } from "./Card";

const TIERS: TrustTier[] = ["builtin", "verified", "org", "community", "agent_created"];
const VERDICTS: GateVerdict[] = ["pass", "warn", "fail", "pending"];

function makeItem(tier: TrustTier, verdict: GateVerdict): ItemSummary {
  return {
    id: `${tier}-${verdict}`, namespace: `demo/${tier}-${verdict}`, item_type: "skill",
    display_name: `${tier} / ${verdict}`, description: "A demo item for the badge-state matrix.",
    category: "productivity", tags: [], icon_url: null, trust_tier: tier, license: "MIT",
    status: "active", is_featured: false, is_new: verdict === "pending",
    latest_version: "1.0.0", latest_verdict: verdict, allowed_actions: ["install", "report"],
    install_id: null, enabled: null, install_scope: null, install_surfaces: null, has_other_installs: false, compatibility: "chat",
  };
}

const meta: Meta<typeof Card> = { title: "Discover/Card", component: Card };
export default meta;

export const BadgeMatrix: StoryObj = {
  render: () => (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "12px" }}>
      {TIERS.flatMap((tier) => VERDICTS.map((verdict) => (
        <Card key={`${tier}-${verdict}`} item={makeItem(tier, verdict)} onOpen={() => {}} />
      )))}
    </div>
  ),
};
