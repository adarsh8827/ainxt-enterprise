// SPDX-License-Identifier: MIT
// Shared badge components for Card.tsx/Detail.tsx -- trust tier, gate
// verdict, and "New".
//
// Full Tailwind pass (2026-10-03): rewritten to literal Tailwind classes
// (no more var(--eco-*)) -- colors mapped 1:1 from the old token hex values
// to their nearest Tailwind palette equivalents (success -> green-700/
// green-50, warning -> amber-700/amber-50, danger -> red-700/red-50,
// info -> blue-700/blue-50, accentSkill -> indigo-600), matching the pill
// badges ProductManager.jsx/KnowledgeBase.jsx already use elsewhere in ai-ui.

import { CheckBadgeIcon } from "@heroicons/react/24/solid";
import { ExclamationTriangleIcon, ClockIcon } from "@heroicons/react/24/outline";
import { useI18n } from "./lib/context/HostContext";

// Item 3 (M5 UI-polish round 2, 2026-09-28): renamed "Agent-created" ->
// "Created with AI" per the user's own explicit wording for what a
// Create-with-AI skill's trust badge should say. Exported so Yours.tsx's
// list-view kebab-menu fold (item 1, same round) can reuse the exact same
// label text when it summarizes a row's badges as a read-only menu line
// below the ~1100px collapse breakpoint, instead of maintaining a second
// copy of this map that could drift.
export const TRUST_LABEL = {
  builtin: "Built-in",
  verified: "Verified",
  org: "Org",
  community: "Community",
  agent_created: "Created with AI"
};
const BADGE_BASE = "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold leading-4 border";
export function TrustBadge({
  tier
}) {
  return <span data-testid="trust-badge" data-tier={tier} className={[BADGE_BASE, "text-gray-600 bg-gray-50 border-gray-200"].join(" ")}>
      {TRUST_LABEL[tier]}
    </span>;
}

// Reference-layout parity (Connectors+Plugins UI redesign, 2026-09-30):
// the reference card/detail design marks a trusted publisher with a small
// checkmark glyph next to the name, separate from -- not a replacement
// for -- TrustBadge's own text pill (which already conveys more, e.g.
// "Community"/"Created with AI", and is wired into existing tests/other
// screens). Additive: only trust_tier "builtin" or "verified" render this
// mark at all; every other tier renders nothing, same as before this mark
// existed.
export function VerifiedMark({
  tier
}) {
  if (tier !== "builtin" && tier !== "verified") return null;
  return <span data-testid="verified-mark" title={TRUST_LABEL[tier]} className="inline-flex flex-shrink-0">
      <CheckBadgeIcon width={16} height={16} aria-hidden="true" className="text-indigo-600" />
    </span>;
}
export function VerdictBadge({
  verdict
}) {
  // Renamed (UI-polish round): "Verified safe" read as a security claim
  // stronger than what the gate actually checks -- "Checks passed" says
  // exactly what happened (the gate's stages passed), same for the warn/
  // fail variants. One place (this map) backs every render site (Detail
  // header, Discover/Yours cards) -- no stale label left behind elsewhere.
  const map = {
    pass: {
      label: "Checks passed",
      className: "text-green-700 bg-green-50 border-green-200"
    },
    warn: {
      label: "Passed with warnings",
      className: "text-amber-700 bg-amber-50 border-amber-200"
    },
    fail: {
      label: "Blocked",
      className: "text-red-700 bg-red-50 border-red-200"
    },
    pending: {
      label: "Verifying…",
      className: "text-blue-700 bg-blue-50 border-blue-200"
    }
  };
  const {
    label,
    className
  } = map[verdict];
  return <span data-testid="verdict-badge" data-verdict={verdict} className={[BADGE_BASE, className].join(" ")}>
      {label}
    </span>;
}

// Card density pass (2026-10-05, explicit product ask: "so many
// informations... capsule design... is this important or we can show in
// other way"): cards show a small icon instead of VerdictBadge's text
// capsule, and ONLY for a state actually worth calling out -- "pass" (the
// common case) renders nothing at all, same silence-means-fine convention
// StatusIndicator below uses for "Active". The full-strength text capsule
// (VerdictBadge above) is unchanged and still used on Detail.tsx, which
// has room for it and is where a caller goes to actually investigate a
// verdict, not just glance at it in a grid.
export function VerdictIcon({
  verdict
}) {
  const map = {
    warn: {
      label: "Passed with warnings",
      className: "text-amber-500"
    },
    fail: {
      label: "Blocked",
      className: "text-red-500"
    },
    pending: {
      label: "Verifying…",
      className: "text-blue-500"
    }
  };
  const entry = map[verdict];
  if (!entry) return null;
  return <span data-testid="verdict-icon" data-verdict={verdict} title={entry.label} className="inline-flex flex-shrink-0">
      {verdict === "pending" ? <ClockIcon width={14} height={14} aria-hidden="true" className={entry.className} /> : <ExclamationTriangleIcon width={14} height={14} aria-hidden="true" className={entry.className} />}
    </span>;
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
  return <span data-testid="catalog-checks-passed-badge" title="License and a fast content scan already ran in CI when this item was crawled. A full gate run happens when you add it." className={[BADGE_BASE, "text-green-700 bg-green-50 border-green-200"].join(" ")}>
      Catalog checks passed
    </span>;
}
export function NewBadge() {
  const strings = useI18n();
  return <span data-testid="new-badge" className={[BADGE_BASE, "text-white bg-indigo-600 border-indigo-600"].join(" ")}>
      {strings.new_badge}
    </span>;
}

/** "chat" (usable purely through a chat conversation) vs "tool_dependent"
 * (assumes shell/git/file-edit access -- Cowork/Desktop/Agent Studio only).
 * null (a version created before this field existed) renders nothing --
 * an unknown compatibility is not the same claim as "works everywhere". */
export function CompatibilityBadge({
  compatibility
}) {
  if (!compatibility) return null;
  const isChat = compatibility === "chat";
  return <span data-testid="compatibility-badge" data-compatibility={compatibility} title={isChat ? "Works in chat" : "Needs file/terminal tools -- Cowork, Desktop, or Agent Studio"} className={[BADGE_BASE, isChat ? "text-blue-700 bg-blue-50 border-blue-200" : "text-gray-600 bg-gray-50 border-gray-200"].join(" ")}>
      {isChat ? "Works in chat" : "Needs file/terminal tools"}
    </span>;
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
export function needsProductLabel(tag) {
  if (!tag.startsWith(NEEDS_PRODUCT_PREFIX)) return null;
  const product = tag.slice(NEEDS_PRODUCT_PREFIX.length);
  if (!product) return null;
  return `Needs ${product.split("-").filter(Boolean).map(word => (word[0] ?? "").toUpperCase() + word.slice(1)).join(" ")}`;
}

/** Renders one badge per `needs-<product>` tag found on the item -- renders
 * nothing when there are none, so callers can pass `item.tags` unconditionally. */
export function NeedsProductBadges({
  tags
}) {
  const labels = tags.map(needsProductLabel).filter(label => Boolean(label));
  if (labels.length === 0) return null;
  return <>
      {labels.map(label => <span key={label} data-testid="needs-product-badge" title="Needs an account with this product to use fully" className={[BADGE_BASE, "text-amber-700 bg-amber-50 border-amber-200"].join(" ")}>
          {label}
        </span>)}
    </>;
}

/** Discover "From the web" section: a real license badge for a
 * live-search result (docs/ecosystem/design/CHANGELOG.md's live-search
 * round) -- purely informational, never a gate the caller has to clear.
 * Every result GET /ecosystem/search/live returns is already MIT/
 * Apache-2.0-filtered server-side (live_search_service.py's own
 * is_allowed_license() pre-filter), so this only ever needs to LABEL the
 * real license, the same way TrustBadge above labels a real trust tier --
 * it never hides "+ Add" or blocks anything itself. */
export function LicenseBadge({
  spdx
}) {
  return <span data-testid="license-badge" data-spdx={spdx} className={[BADGE_BASE, "text-gray-600 bg-gray-50 border-gray-200"].join(" ")}>
      {spdx}
    </span>;
}
export function ComingSoonBadge() {
  const strings = useI18n();
  return <span data-testid="coming-soon-badge" className={[BADGE_BASE, "text-gray-400 bg-gray-50 border-gray-200"].join(" ")}>
      {strings.coming_soon}
    </span>;
}
