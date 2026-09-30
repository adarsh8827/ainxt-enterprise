// SPDX-License-Identifier: MIT
// "Yours" row renderer for connector items -- status chips + Reconnect
// (only for needs_reauth/expired) + Disconnect + last used
// (docs/ecosystem/CONNECTORS_PHASE_PLAN.md §1 item 6).
import { useEffect, useState } from "react";
import type { ConnectionStatus, ItemDetail, ItemSummary } from "../../types";
import { useEcosystemClient } from "../../context/HostContext";
import { ItemIcon } from "../ItemIcon";
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

function humanize(ref: string): string {
  return ref
    .split(/[-_]/)
    .map((w) => (w.length ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(" ");
}

export function ConnectorsYoursRow({ item, connection }: {
  item: ItemSummary;
  connection: { connector_ref: string; status: ConnectionStatus; last_connected_at: string | null };
}) {
  const client = useEcosystemClient();
  useConnectionOverrideVersion();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const resolved = resolveConnectionStatus(connection.connector_ref, connection as never);
  const style = STATUS_STYLE[resolved.status];

  const reconnect = () => {
    setBusy(true);
    setError(null);
    client.reconnect(connection.connector_ref)
      .then((result) => {
        if (result.authorize_url) { window.location.assign(result.authorize_url); return; }
        setConnectionState(connection.connector_ref, {
          connector_ref: connection.connector_ref, item_id: item.id, status: result.status,
          last_connected_at: new Date().toISOString(), expires_at: null,
        });
      })
      // Same class of real bug fixed in ConnectorDetail.tsx's handleConnect
      // (2026-09-30): connect()/reconnect() used to always resolve
      // {"status": "connected"}, so this never actually rejected in
      // practice -- there was no .catch() here at all.
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Couldn't reconnect."))
      .finally(() => setBusy(false));
  };

  const disconnect = () => {
    setBusy(true);
    setError(null);
    client.disconnect(connection.connector_ref)
      .then(() => setConnectionState(connection.connector_ref, {
        connector_ref: connection.connector_ref, item_id: item.id, status: "not_connected",
        last_connected_at: null, expires_at: null,
      }))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Couldn't disconnect."))
      .finally(() => setBusy(false));
  };

  return (
    <div data-testid="connectors-yours-row" data-connector-ref={connection.connector_ref} style={{ display: "flex", alignItems: "center", gap: "var(--eco-space-md)", padding: "var(--eco-space-sm) 0" }}>
      <ItemIcon iconUrl={item.icon_url ?? null} namespace={item.namespace ?? connection.connector_ref} displayName={item.display_name} size={28} />
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
        <button type="button" data-testid="connectors-yours-reconnect" disabled={busy} title={error ?? undefined} onClick={reconnect}>
          {error ? "Retry" : "Reconnect"}
        </button>
      )}
      {resolved.status === "connected" && (
        <button type="button" data-testid="connectors-yours-disconnect" disabled={busy} title={error ?? undefined} onClick={disconnect}>Disconnect</button>
      )}
      {error && (
        <span data-testid="connectors-yours-row-error" style={{ color: "var(--eco-color-danger)", fontSize: "var(--eco-font-sizeXs)" }}>
          {error}
        </span>
      )}
    </div>
  );
}

/** Real gap found and fixed (2026-09-30): ConnectorsYoursRow above is only
 * a single-row renderer -- CatalogScreen.tsx was always rendering the
 * generic, install-based <Yours> for EVERY item type including "connector",
 * so ConnectorsYoursRow (built, tested) was never actually reachable from
 * the real app. This is the missing list wrapper: fetches the real
 * connection list (client.listConnections(), Stage 2's read-through
 * endpoint) instead of the generic installs list, and renders one
 * ConnectorsYoursRow per connection.
 *
 * Real display names/icons (Connectors+Plugins UI redesign, 2026-09-30):
 * this used to unconditionally synthesize a humanized-from-connector_ref
 * ItemSummary for every row, disclosed at the time as a stub pending "a
 * real native-connectors-as-catalog-items bridge, not built here" -- that
 * bridge now exists (services/ecosystem/legacy_bridge.py's
 * list_native_connector_definitions() + scripts/ecosystem/
 * backfill_legacy_items.py), so a connection whose item_id resolves to a
 * real EcosystemItem now fetches and shows its real display_name/icon_url
 * instead of a guessed-from-slug name. The humanized fallback stays for
 * the genuinely-disclosed remaining case: a connection with no item_id at
 * all (not yet backfilled, or a connector with no catalog row for some
 * other reason). */
export function ConnectorsYours({ onDiscover }: { onDiscover: () => void }) {
  const client = useEcosystemClient();
  const [connections, setConnections] = useState<Array<{ connector_ref: string; item_id: string | null; status: ConnectionStatus; last_connected_at: string | null }> | null>(null);
  const [itemsById, setItemsById] = useState<Record<string, ItemDetail>>({});

  useEffect(() => {
    let cancelled = false;
    client.listConnections().then((rows) => {
      if (cancelled) return;
      setConnections(rows);
      const ids = Array.from(new Set(rows.map((r) => r.item_id).filter((id): id is string => Boolean(id))));
      Promise.all(ids.map((id) => client.getItem(id).catch(() => null))).then((fetched) => {
        if (cancelled) return;
        const byId: Record<string, ItemDetail> = {};
        for (const it of fetched) if (it) byId[it.id] = it;
        setItemsById(byId);
      });
    });
    return () => { cancelled = true; };
  }, [client]);

  if (connections === null) return <div data-testid="connectors-yours-loading">Loading…</div>;
  if (connections.length === 0) {
    return (
      <div data-testid="connectors-yours-empty" style={{ textAlign: "center", padding: "var(--eco-space-xl)" }}>
        <p>No connectors yet.</p>
        <button type="button" data-testid="connectors-yours-browse-discover" onClick={onDiscover}>Browse Discover</button>
      </div>
    );
  }

  return (
    <div data-testid="connectors-yours-list">
      {connections.map((c) => {
        const real = c.item_id ? itemsById[c.item_id] : undefined;
        const item: ItemSummary = real
          ? real
          : ({ id: c.item_id ?? c.connector_ref, namespace: c.connector_ref, display_name: humanize(c.connector_ref), icon_url: null } as ItemSummary);
        return <ConnectorsYoursRow key={c.connector_ref} item={item} connection={c} />;
      })}
    </div>
  );
}
