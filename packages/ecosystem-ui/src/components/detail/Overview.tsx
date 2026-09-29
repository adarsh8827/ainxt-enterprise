// SPDX-License-Identifier: MIT
// UI-polish round: restructured from a bare description + a metadata
// <dl> (moved to RiskSidePanel -- no duplication with the Detail header)
// into "what it does" (the description, unchanged) + "How to use" (its
// real slash command, derived the same way resolver_service.py does
// server-side -- never hardcoded) + which surfaces it's actually enabled
// for (only meaningful once installed) + a host-supplied "Try in chat"
// action, matching Marketplace's own onCreateWithAi pattern for anything
// this package can't do itself (it has no chat surface of its own).
import { useEffect, useState } from "react";
import type { ItemDetail } from "../../types";
import { useEcosystemClient } from "../../context/HostContext";
import { useConfig } from "../../hooks/useEcosystemConfig";
import { SurfaceToggles } from "../SurfaceToggles";

const SURFACE_LABEL: Record<string, string> = {
  chat: "Chat", agent_studio: "Agent Studio", desktop: "Desktop", workspace_chat: "Chat", cowork: "Cowork",
};

export function Overview({ item, onTryInChat }: { item: ItemDetail; onTryInChat?: () => void }) {
  const client = useEcosystemClient();
  const config = useConfig();
  const slashCommand = `/${item.namespace.split("/")[1] ?? item.namespace}`;
  // Per-surface toggles round (2026-09-29): local, optimistically-updated
  // copy -- same convention Yours.tsx's own (now-removed) toggle used,
  // so the admin-only "Advanced" override below flips immediately on
  // click, before the real PATCH round-trips, and rolls back on error.
  const [surfaces, setSurfaces] = useState(item.install_surfaces ?? []);
  useEffect(() => setSurfaces(item.install_surfaces ?? []), [item.install_surfaces]);

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

      {/* Per-surface toggles round (2026-09-29): the ONLY remaining
          surface-toggle UI anywhere in this package -- admin-only
          (config.caller_permissions.can_admin_surfaces, the real,
          caller-specific RBAC signal, never a product feature flag),
          and only for an already-installed item. The server independently
          enforces this too (routers/ecosystem_router.py's
          set_install_surfaces requires marketplace:admin_surfaces) --
          this client-side gate is a convenience, not the real
          enforcement, same "fails closed twice" pattern this package's
          other admin-only controls already follow (see AdminScreen.tsx's
          own top comment). Also still subject to the file/terminal-tools
          compatibility exception server-side -- a tool-dependent item's
          "chat" toggle here can be clicked, but the server will silently
          drop it from the saved result, same as it would from any other
          caller. */}
      {item.install_id && config.caller_permissions.can_admin_surfaces && (
        <div data-testid="overview-advanced-surfaces" style={{ marginTop: "var(--eco-space-lg)", paddingTop: "var(--eco-space-md)", borderTop: "1px solid var(--eco-color-border)" }}>
          <h4 style={{ margin: "0 0 4px", color: "var(--eco-color-textPrimary)", fontSize: "var(--eco-font-sizeSm)" }}>Advanced</h4>
          <p style={{ margin: "0 0 8px", fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textSecondary)" }}>
            Admin override: which surfaces this specific install is enabled for.
          </p>
          <SurfaceToggles
            enabledSurfaces={surfaces}
            onChange={(next) => {
              const previous = surfaces;
              setSurfaces(next); // optimistic
              client.setSurfaces(item.install_id!, next).catch(() => setSurfaces(previous)); // roll back on error
            }}
          />
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
