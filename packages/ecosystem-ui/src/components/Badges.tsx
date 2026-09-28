// SPDX-License-Identifier: MIT
// Shared badge components for Card.tsx/Detail.tsx -- trust tier, gate
// verdict, and "New". No hex values (theme.ts tokens only, task-wide rule).
import type { CSSProperties } from "react";
import type { GateVerdict, TrustTier } from "../types";
import { useI18n } from "../context/HostContext";

const TRUST_LABEL: Record<TrustTier, string> = {
  builtin: "Built-in", verified: "Verified", org: "Org", community: "Community", agent_created: "Agent-created",
};

function baseBadgeStyle(): CSSProperties {
  return {
    display: "inline-flex", alignItems: "center", gap: "4px",
    padding: "2px 8px", borderRadius: "var(--eco-radius-full)",
    fontSize: "var(--eco-font-sizeXs)", fontWeight: 600, lineHeight: "16px",
    border: "1px solid var(--eco-color-border)",
  };
}

export function TrustBadge({ tier }: { tier: TrustTier }) {
  return (
    <span
      data-testid="trust-badge"
      data-tier={tier}
      style={{
        ...baseBadgeStyle(),
        color: "var(--eco-color-textSecondary)",
        background: "var(--eco-color-surface)",
      }}
    >
      {TRUST_LABEL[tier]}
    </span>
  );
}

export function VerdictBadge({ verdict }: { verdict: GateVerdict }) {
  // Renamed (UI-polish round): "Verified safe" read as a security claim
  // stronger than what the gate actually checks -- "Checks passed" says
  // exactly what happened (the gate's stages passed), same for the warn/
  // fail variants. One place (this map) backs every render site (Detail
  // header, Discover/Yours cards) -- no stale label left behind elsewhere.
  const map: Record<GateVerdict, { label: string; color: string; bg: string }> = {
    pass: { label: "Checks passed", color: "var(--eco-color-success)", bg: "var(--eco-color-successBg)" },
    warn: { label: "Passed with warnings", color: "var(--eco-color-warning)", bg: "var(--eco-color-warningBg)" },
    fail: { label: "Blocked", color: "var(--eco-color-danger)", bg: "var(--eco-color-dangerBg)" },
    pending: { label: "Verifying…", color: "var(--eco-color-info)", bg: "var(--eco-color-infoBg)" },
  };
  const { label, color, bg } = map[verdict];
  return (
    <span data-testid="verdict-badge" data-verdict={verdict} style={{ ...baseBadgeStyle(), color, background: bg, borderColor: color }}>
      {label}
    </span>
  );
}

export function NewBadge() {
  const strings = useI18n();
  return (
    <span
      data-testid="new-badge"
      style={{
        ...baseBadgeStyle(),
        color: "var(--eco-color-accentSkillText)",
        background: "var(--eco-color-accentSkill)",
        borderColor: "var(--eco-color-accentSkill)",
      }}
    >
      {strings.new_badge}
    </span>
  );
}

/** "chat" (usable purely through a chat conversation) vs "tool_dependent"
 * (assumes shell/git/file-edit access -- Cowork/Desktop/Agent Studio only).
 * null (a version created before this field existed) renders nothing --
 * an unknown compatibility is not the same claim as "works everywhere". */
export function CompatibilityBadge({ compatibility }: { compatibility: "chat" | "tool_dependent" | null }) {
  if (!compatibility) return null;
  const isChat = compatibility === "chat";
  return (
    <span
      data-testid="compatibility-badge"
      data-compatibility={compatibility}
      title={isChat ? "Works in chat" : "Needs file/terminal tools -- Cowork, Desktop, or Agent Studio"}
      style={{
        ...baseBadgeStyle(),
        color: isChat ? "var(--eco-color-info)" : "var(--eco-color-textSecondary)",
        background: isChat ? "var(--eco-color-infoBg)" : "var(--eco-color-surface)",
      }}
    >
      {isChat ? "Works in chat" : "Needs file/terminal tools"}
    </span>
  );
}

// Tag convention the catalog crawler emits for source repos gated behind a
// specific product account (docs/ecosystem/catalog/sources.yaml's
// `needs_product`/`account_required` fields become a `needs-<product>` tag,
// e.g. `needs-stitch` for the Stitch-sourced skills) -- items_service already
// passes an item's `tags` straight through untouched (see ItemSummary.tags
// in items_service.py / types.ts), this badge was simply never rendered
// anywhere, so the tag reached the frontend but had nowhere to show up.
const NEEDS_PRODUCT_PREFIX = "needs-";

/** Turns a `needs-<product>` tag into a "Needs <Product>" label, title-
 * casing each hyphen-separated word (`needs-figma-make` -> "Needs Figma
 * Make"). Returns null for any tag that isn't this convention. */
export function needsProductLabel(tag: string): string | null {
  if (!tag.startsWith(NEEDS_PRODUCT_PREFIX)) return null;
  const product = tag.slice(NEEDS_PRODUCT_PREFIX.length);
  if (!product) return null;
  return `Needs ${product
    .split("-")
    .filter(Boolean)
    .map((word) => (word[0] ?? "").toUpperCase() + word.slice(1))
    .join(" ")}`;
}

/** Renders one badge per `needs-<product>` tag found on the item -- renders
 * nothing when there are none, so callers can pass `item.tags` unconditionally. */
export function NeedsProductBadges({ tags }: { tags: string[] }) {
  const labels = tags.map(needsProductLabel).filter((label): label is string => Boolean(label));
  if (labels.length === 0) return null;
  return (
    <>
      {labels.map((label) => (
        <span
          key={label}
          data-testid="needs-product-badge"
          title="Needs an account with this product to use fully"
          style={{
            ...baseBadgeStyle(),
            color: "var(--eco-color-warning)",
            background: "var(--eco-color-warningBg)",
          }}
        >
          {label}
        </span>
      ))}
    </>
  );
}

export function ComingSoonBadge() {
  const strings = useI18n();
  return (
    <span
      data-testid="coming-soon-badge"
      style={{ ...baseBadgeStyle(), color: "var(--eco-color-textMuted)", background: "var(--eco-color-surface)" }}
    >
      {strings.coming_soon}
    </span>
  );
}
