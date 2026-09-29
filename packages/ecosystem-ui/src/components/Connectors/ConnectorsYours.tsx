// SPDX-License-Identifier: MIT
// "Yours" row renderer for connector items -- status chips + Reconnect
// (only for needs_reauth/expired) + Disconnect + last used
// (docs/ecosystem/CONNECTORS_PHASE_PLAN.md §1 item 6).
import { useState } from "react";
import type { ConnectionStatus, ItemSummary } from "../../types";
import { useEcosystemClient } from "../../context/HostContext";
import { resolveConnectionStatus, setConnectionState, useConnectionOverrideVersion } from "../../connectionStore";

const STATUS_STYLE: Record<ConnectionStatus, { label: string; color: string }> = {
  connected: { label: "Connected", color: "var(--eco-color-success)" },
  needs_reauth: { label: "Needs reconnect", color: "var(--eco-color-warning)" },
  expired: { label: "Expired", color: "var(--eco-color-warning)" },
  revoked: { label: "Revoked", color: "var(--eco-color-danger)" },
  insufficient_scope: { label: "Needs more access", color: "var(--eco-color-warning)" },
  not_connected: { label: "Not connected", color: "var(--eco-color-textMuted)" },
  connecting: { label: "Connecting…", color: "var(--eco-color-info)" },
  error: { label: "Error", color: "var(--eco-color-danger)" },
};

export function ConnectorsYoursRow({ item, connection }: {
  item: ItemSummary;
  connection: { connector_ref: string; status: ConnectionStatus; last_connected_at: string | null };
}) {
  const client = useEcosystemClient();
  useConnectionOverrideVersion();
  const [busy, setBusy] = useState(false);
  const resolved = resolveConnectionStatus(connection.connector_ref, connection as never);
  const style = STATUS_STYLE[resolved.status];

  const reconnect = () => {
    setBusy(true);
    client.reconnect(connection.connector_ref)
      .then((result) => {
        if (result.authorize_url) { window.location.assign(result.authorize_url); return; }
        setConnectionState(connection.connector_ref, {
          connector_ref: connection.connector_ref, item_id: item.id, status: result.status,
          last_connected_at: new Date().toISOString(), expires_at: null,
        });
      })
      .finally(() => setBusy(false));
  };

  const disconnect = () => {
    setBusy(true);
    client.disconnect(connection.connector_ref)
      .then(() => setConnectionState(connection.connector_ref, {
        connector_ref: connection.connector_ref, item_id: item.id, status: "not_connected",
        last_connected_at: null, expires_at: null,
      }))
      .finally(() => setBusy(false));
  };

  return (
    <div data-testid="connectors-yours-row" data-connector-ref={connection.connector_ref} style={{ display: "flex", alignItems: "center", gap: "var(--eco-space-md)", padding: "var(--eco-space-sm) 0" }}>
      <span style={{ flex: 1 }}>{item.display_name}</span>
      <span data-testid="connection-status-chip" data-status={resolved.status} style={{ color: style.color, fontSize: "var(--eco-font-sizeXs)" }}>
        {style.label}
      </span>
      {connection.last_connected_at && (
        <span style={{ fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textMuted)" }}>
          Last used {new Date(connection.last_connected_at).toLocaleDateString()}
        </span>
      )}
      {(resolved.status === "needs_reauth" || resolved.status === "expired") && (
        <button type="button" data-testid="connectors-yours-reconnect" disabled={busy} onClick={reconnect}>Reconnect</button>
      )}
      {resolved.status === "connected" && (
        <button type="button" data-testid="connectors-yours-disconnect" disabled={busy} onClick={disconnect}>Disconnect</button>
      )}
    </div>
  );
}
