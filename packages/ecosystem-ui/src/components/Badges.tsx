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
