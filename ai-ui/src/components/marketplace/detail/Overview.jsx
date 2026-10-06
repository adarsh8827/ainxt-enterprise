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
import { useEcosystemClient } from "../lib/context/HostContext";
import { useConfig } from "../lib/hooks/useEcosystemConfig";
import { SurfaceToggles } from "../SurfaceToggles";
import { Button } from "../Button";
const SURFACE_LABEL = {
  chat: "Chat",
  agent_studio: "Agent Studio",
  desktop: "Desktop",
  workspace_chat: "Chat",
  cowork: "Cowork"
};
export function Overview({
  item,
  onTryInChat
}) {
  const client = useEcosystemClient();
  const config = useConfig();
  const slashCommand = `/${item.namespace.split("/")[1] ?? item.namespace}`;
  // Per-surface toggles round (2026-09-29): local, optimistically-updated
  // copy -- same convention Yours.tsx's own (now-removed) toggle used,
  // so the admin-only "Advanced" override below flips immediately on
  // click, before the real PATCH round-trips, and rolls back on error.
  const [surfaces, setSurfaces] = useState(item.install_surfaces ?? []);
  useEffect(() => setSurfaces(item.install_surfaces ?? []), [item.install_surfaces]);
  // Real confusion found live (2026-10-06, user report): "Enabled for"
  // and "Try in chat" below are driven by the raw install.surfaces
  // column alone, with zero connection to whether this install's own
  // pinned version actually passed verification -- matches
  // resolver_service.py's own bar (pass/warn, never fail) for real
  // usability, not just configuration.
  const installedVerdictFailed = item.installed_verdict === "fail";
  return <div data-testid="detail-tab-overview">
      <p className="text-gray-900">{item.description}</p>

      {item.item_type === "skill" && <div data-testid="overview-how-to-use" className="mt-4">
          <h4 className="mt-0 mb-1 text-gray-900 text-sm">How to use</h4>
          <p className="m-0 text-sm text-gray-500">
            Type <code className="font-mono bg-gray-50 px-1.5 py-0.5 rounded">{slashCommand}</code> in chat.
          </p>
        </div>}

      {item.install_id && <div data-testid="overview-enabled-surfaces" className="mt-4">
          <h4 className="mt-0 mb-1 text-gray-900 text-sm">Enabled for</h4>
          <div className="flex gap-1.5 flex-wrap">
            {surfaces.length === 0 ? <span className="text-sm text-gray-400">No surfaces enabled.</span> : surfaces.map(s => <span key={s} className="text-xs px-2 py-0.5 rounded-full bg-gray-50 text-gray-500 border border-gray-200">
                {SURFACE_LABEL[s] ?? s}
              </span>)}
          </div>
          {/* Real confusion found live (2026-10-06, user report): this
              list is just the raw install.surfaces column -- it said
              "Chat" here and still offered "Try in chat" below even once
              the installed version's own verdict had failed and chat had
              genuinely stopped honoring it (resolver_service.py's own,
              separately-fixed check). This surfaces list is still an
              accurate record of what's CONFIGURED; this note is the
              difference between "configured" and "currently usable". */}
          {installedVerdictFailed && surfaces.length > 0 && <p className="m-0 mt-1.5 text-xs text-amber-600">
              Configured, but not currently usable — this version failed verification.
            </p>}
        </div>}

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
      {item.install_id && config.caller_permissions.can_admin_surfaces && <div data-testid="overview-advanced-surfaces" className="mt-6 pt-4 border-t border-gray-200">
          <h4 className="mt-0 mb-1 text-gray-900 text-sm">Advanced</h4>
          <p className="mt-0 mb-2 text-xs text-gray-500">
            Admin override: which surfaces this specific install is enabled for.
          </p>
          <SurfaceToggles enabledSurfaces={surfaces} onChange={next => {
        const previous = surfaces;
        setSurfaces(next); // optimistic
        client.setSurfaces(item.install_id, next).catch(() => setSurfaces(previous)); // roll back on error
      }} />
        </div>}

      {item.install_id && onTryInChat && surfaces.includes("chat") && !installedVerdictFailed && <Button data-testid="overview-try-in-chat" className="mt-4" onClick={onTryInChat}>
          Try in chat
        </Button>}
    </div>;
}
