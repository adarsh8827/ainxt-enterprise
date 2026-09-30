// SPDX-License-Identifier: MIT
// Shared badge components for Card.tsx/Detail.tsx -- trust tier, gate
// verdict, and "New". No hex values (theme.ts tokens only, task-wide rule).
import type { CSSProperties } from "react";
import { CheckBadgeIcon } from "@heroicons/react/24/solid";
import type { GateVerdict, TrustTier } from "../types";
import { useI18n } from "../context/HostContext";

// Item 3 (M5 UI-polish round 2, 2026-09-28): renamed "Agent-created" ->
// "Created with AI" per the user's own explicit wording for what a
// Create-with-AI skill's trust badge should say. Exported so Yours.tsx's
// list-view kebab-menu fold (item 1, same round) can reuse the exact same
// label text when it summarizes a row's badges as a read-only menu line
// below the ~1100px collapse breakpoint, instead of maintaining a second
// copy of this map that could drift.
export const TRUST_LABEL: Record<TrustTier, string> = {
  builtin: "Built-in", verified: "Verified", org: "Org", community: "Community", agent_created: "Created with AI",
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

// Reference-layout parity (Connectors+Plugins UI redesign, 2026-09-30):
// the reference card/detail design marks a trusted publisher with a small
// checkmark glyph next to the name, separate from -- not a replacement
// for -- TrustBadge's own text pill (which already conveys more, e.g.
// "Community"/"Created with AI", and is wired into existing tests/other
// screens). Additive: only trust_tier "builtin" or "verified" render this
// mark at all; every other tier renders nothing, same as before this mark
// existed.
export function VerifiedMark({ tier }: { tier: TrustTier }) {
  if (tier !== "builtin" && tier !== "verified") return null;
  return (
    <span data-testid="verified-mark" title={TRUST_LABEL[tier]} style={{ display: "inline-flex", flexShrink: 0 }}>
      <CheckBadgeIcon width={16} height={16} aria-hidden="true" style={{ color: "var(--eco-color-accentSkill)" }} />
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

/** Catalog-checking round (docs/ecosystem/design/LLD/gate.md, catalogState.ts's
 * isNotYetAddedCatalogItem()): a not-yet-added catalog item's own badge --
 * deliberately NOT VerdictBadge with some new "not_added" GateVerdict
 * value, since no gate run exists for this state at all (VerdictBadge's
 * whole job is rendering an actual EcosystemGateRun's verdict). Real bug
 * found live: before this existed, callers fell back to
 * `<VerdictBadge verdict={item.latest_verdict}>`, and the backend's own
 * `latest_verdict` defaults to `"pending"` when no version/gate run
 * exists yet (items_service._item_to_summary()) -- rendering as
 * "Verifying…" for an item nobody had touched. Styled like VerdictBadge's
 * own "pass" variant (same claim strength: checks already ran and
 * passed, just at crawl time instead of install time). */
export function CatalogChecksPassedBadge() {
  return (
    <span
      data-testid="catalog-checks-passed-badge"
      title="License and a fast content scan already ran in CI when this item was crawled. A full gate run happens when you add it."
      style={{ ...baseBadgeStyle(), color: "var(--eco-color-success)", background: "var(--eco-color-successBg)", borderColor: "var(--eco-color-success)" }}
    >
      Catalog checks passed
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

/** Discover "From the web" section: a real license badge for a
 * live-search result (docs/ecosystem/design/CHANGELOG.md's live-search
 * round) -- purely informational, never a gate the caller has to clear.
 * Every result GET /ecosystem/search/live returns is already MIT/
 * Apache-2.0-filtered server-side (live_search_service.py's own
 * is_allowed_license() pre-filter), so this only ever needs to LABEL the
 * real license, the same way TrustBadge above labels a real trust tier --
 * it never hides "+ Add" or blocks anything itself. */
export function LicenseBadge({ spdx }: { spdx: string }) {
  return (
    <span
      data-testid="license-badge"
      data-spdx={spdx}
      style={{
        ...baseBadgeStyle(),
        color: "var(--eco-color-textSecondary)",
        background: "var(--eco-color-surface)",
      }}
    >
      {spdx}
    </span>
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
