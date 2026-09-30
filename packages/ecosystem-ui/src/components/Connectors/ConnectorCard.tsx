// SPDX-License-Identifier: MIT
// Discover card for a connector item -- mirrors Card.tsx's QuickAddButton
// pattern (docs/ecosystem/CONNECTORS_PHASE_PLAN.md §1 item 6) but reflects
// live ConnectionStatus instead of install state, via connectionStore.ts
// (the connector-status analogue of installStore.ts, same
// cross-tab-consistency treatment this session's own install-state fix
// established as the required pattern for anything with a status that can
// change from another screen/tab).
import { useEffect, useState } from "react";
import { LinkIcon } from "@heroicons/react/24/outline";
import type { ConnectionStatus, ItemSummary } from "../../types";
import { ItemIcon } from "../ItemIcon";
import { CompatibilityBadge, NewBadge, TrustBadge, VerifiedMark } from "../Badges";
import { useEcosystemClient } from "../../context/HostContext";
import { EcosystemApiError } from "../../client/EcosystemClient";
import { publisherLabel } from "../../publisherLabel";
import {
  resolveConnectionStatus, setConnectionState, useConnectionOverrideVersion,
} from "../../connectionStore";

const STATUS_LABEL: Record<ConnectionStatus, string> = {
  connected: "Connected", needs_reauth: "Needs reconnect", expired: "Expired", revoked: "Revoked",
  insufficient_scope: "Needs more access", not_connected: "Connect", connecting: "Connecting…", error: "Error",
};

function ConnectButton({ connectorRef }: { connectorRef: string }) {
  const client = useEcosystemClient();
  useConnectionOverrideVersion();
  const [fetched, setFetched] = useState<ReturnType<typeof resolveConnectionStatus> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  // Real UX gap found live (2026-09-30): OAUTH_APP_NOT_CONFIGURED isn't a
  // transient failure -- clicking "Retry" repeats the exact same request
  // and gets the exact same answer every time, since nothing changes
  // until an admin registers the app. See the connector's own Detail page
  // for the real "Set up sign-in" admin link -- this compact card just
  // needs an honest label, not another copy of that link.
  const notConfigured = errorCode === "OAUTH_APP_NOT_CONFIGURED";

  useEffect(() => {
    let alive = true;
    client.listConnections().then((conns) => {
      if (!alive) return;
      const found = conns.find((c) => c.connector_ref === connectorRef);
      setFetched(resolveConnectionStatus(connectorRef, found));
    });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectorRef]);

  const status = resolveConnectionStatus(connectorRef, fetched ?? undefined).status;

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setBusy(true);
    setError(null);
    setErrorCode(null);
    const call = status === "needs_reauth" || status === "expired" ? client.reconnect(connectorRef) : client.connect(connectorRef);
    call
      .then((result) => {
        if (result.authorize_url) {
          setConnectionState(connectorRef, {
            connector_ref: connectorRef, item_id: null, status: "connecting",
            last_connected_at: null, expires_at: null,
          });
          window.location.assign(result.authorize_url);
          return;
        }
        setConnectionState(connectorRef, {
          connector_ref: connectorRef, item_id: null, status: result.status,
          last_connected_at: new Date().toISOString(), expires_at: null,
        });
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Couldn't connect.");
        setErrorCode(err instanceof EcosystemApiError ? err.code : null);
      })
      .finally(() => setBusy(false));
  };

  if (status === "connected") {
    return (
      <span data-testid="connector-connected-badge" style={{ display: "inline-flex", alignItems: "center", gap: "4px", fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-success)" }}>
        Connected
      </span>
    );
  }

  return (
    <button
      type="button"
      data-testid="connector-connect-button"
      data-status={status}
      disabled={busy}
      onClick={handleClick}
      title={error ?? undefined}
      style={{
        boxSizing: "border-box", display: "inline-flex", alignItems: "center", gap: "4px",
        padding: "8px 12px", borderRadius: "var(--eco-radius-md)", border: "1px solid transparent",
        cursor: busy ? "default" : "pointer",
        background: error ? "var(--eco-color-dangerBg)" : "var(--eco-color-accentSkill)",
        color: error ? "var(--eco-color-danger)" : "var(--eco-color-accentSkillText)",
      }}
    >
      <LinkIcon width={14} height={14} aria-hidden="true" />
      {busy ? "Connecting…" : notConfigured ? "Not set up" : error ? "Retry" : STATUS_LABEL[status]}
    </button>
  );
}

export function ConnectorCard({ item, onOpen }: { item: ItemSummary; onOpen: (item: ItemSummary) => void }) {
  return (
    <div
      role="button"
      tabIndex={0}
      data-testid="connector-card"
      data-item-id={item.id}
      onClick={() => onOpen(item)}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(item); } }}
      style={{
        display: "flex", flexDirection: "column", gap: "var(--eco-space-sm)",
        padding: "var(--eco-space-md)", borderRadius: "var(--eco-radius-lg)",
        border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)",
        textAlign: "left", cursor: "pointer", width: "100%",
      }}
    >
      {/* Same reference-layout shape as Card.tsx (2026-09-30): icon left,
          name+verified/description/"by maker" as a text column, action
          control pinned top-right of the row -- kept visually consistent
          across skill/plugin (Card.tsx) and connector/mcp_server (this
          component) cards, just swapping install-state for connection-state. */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: "var(--eco-space-sm)" }}>
        <ItemIcon iconUrl={item.icon_url} namespace={item.namespace} displayName={item.display_name} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span title={item.display_name} style={{ display: "block", fontWeight: 600, fontSize: "var(--eco-font-sizeMd)", color: "var(--eco-color-textPrimary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {item.display_name}
            </span>
            <VerifiedMark tier={item.trust_tier} />
          </div>
          <p style={{ margin: "2px 0 0", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)", overflow: "hidden", textOverflow: "ellipsis", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>
            {item.description}
          </p>
          <span style={{ display: "block", marginTop: "4px", fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textMuted)" }}>
            by {publisherLabel(item.namespace)}
          </span>
        </div>
        <div style={{ flexShrink: 0 }}>
          <ConnectButton connectorRef={item.namespace} />
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "nowrap", overflow: "hidden" }}>
        <TrustBadge tier={item.trust_tier} />
        {item.is_new && <NewBadge />}
        <CompatibilityBadge compatibility={item.compatibility} />
      </div>
    </div>
  );
}
