// SPDX-License-Identifier: MIT
// UI-polish round: restructured from a bare description + a metadata
// <dl> (moved to RiskSidePanel -- no duplication with the Detail header)
// into "what it does" (the description, unchanged) + "How to use" (its
// real slash command, derived the same way resolver_service.py does
// server-side -- never hardcoded) + which surfaces it's actually enabled
// for (only meaningful once installed) + a host-supplied "Try in chat"
// action, matching Marketplace's own onCreateWithAi pattern for anything
// this package can't do itself (it has no chat surface of its own).
import type { ItemDetail } from "../../types";

const SURFACE_LABEL: Record<string, string> = {
  chat: "Chat", agent_studio: "Agent Studio", desktop: "Desktop", workspace_chat: "Chat", cowork: "Cowork",
};

export function Overview({ item, onTryInChat }: { item: ItemDetail; onTryInChat?: () => void }) {
  const slashCommand = `/${item.namespace.split("/")[1] ?? item.namespace}`;
  const surfaces = item.install_surfaces ?? [];

  return (
    <div data-testid="detail-tab-overview">
      <p style={{ color: "var(--eco-color-textPrimary)" }}>{item.description}</p>

      {item.item_type === "skill" && (
        <div data-testid="overview-how-to-use" style={{ marginTop: "var(--eco-space-md)" }}>
          <h4 style={{ margin: "0 0 4px", color: "var(--eco-color-textPrimary)", fontSize: "var(--eco-font-sizeSm)" }}>How to use</h4>
          <p style={{ margin: 0, fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}>
            Type <code style={{ fontFamily: "monospace", background: "var(--eco-color-surface)", padding: "1px 6px", borderRadius: "var(--eco-radius-sm)" }}>{slashCommand}</code> in chat.
          </p>
        </div>
      )}

      {item.install_id && (
        <div data-testid="overview-enabled-surfaces" style={{ marginTop: "var(--eco-space-md)" }}>
          <h4 style={{ margin: "0 0 4px", color: "var(--eco-color-textPrimary)", fontSize: "var(--eco-font-sizeSm)" }}>Enabled for</h4>
          <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
            {surfaces.length === 0 ? (
              <span style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textMuted)" }}>No surfaces enabled.</span>
            ) : surfaces.map((s) => (
              <span
                key={s}
                style={{ fontSize: "var(--eco-font-sizeXs)", padding: "2px 8px", borderRadius: "var(--eco-radius-full)", background: "var(--eco-color-surface)", color: "var(--eco-color-textSecondary)", border: "1px solid var(--eco-color-border)" }}
              >
                {SURFACE_LABEL[s] ?? s}
              </span>
            ))}
          </div>
        </div>
      )}

      {item.install_id && onTryInChat && surfaces.includes("chat") && (
        <button
          type="button"
          data-testid="overview-try-in-chat"
          onClick={onTryInChat}
          style={{ marginTop: "var(--eco-space-md)", padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "none", background: "var(--eco-color-accentSkill)", color: "var(--eco-color-accentSkillText)", cursor: "pointer" }}
        >
          Try in chat
        </button>
      )}
    </div>
  );
}
