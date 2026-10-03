// SPDX-License-Identifier: MIT
// "Yours" row renderer for connector items -- status chips + Reconnect
// (only for needs_reauth/expired) + Disconnect + last used
// (docs/ecosystem/CONNECTORS_PHASE_PLAN.md §1 item 6).
import { useEffect, useState } from "react";
import { useEcosystemClient } from "../lib/context/HostContext";
import { ItemIcon } from "../ItemIcon";
import { Button } from "../Button";
import { resolveConnectionStatus, setConnectionState, useConnectionOverrideVersion } from "../lib/connectionStore";
const STATUS_STYLE = {
  connected: {
    label: "Connected",
    className: "text-green-700"
  },
  needs_reauth: {
    label: "Needs reconnect",
    className: "text-amber-700"
  },
  expired: {
    label: "Expired",
    className: "text-amber-700"
  },
  revoked: {
    label: "Revoked",
    className: "text-red-700"
  },
  insufficient_scope: {
    label: "Needs more access",
    className: "text-amber-700"
  },
  not_connected: {
    label: "Not connected",
    className: "text-gray-400"
  },
  connecting: {
    label: "Connecting…",
    className: "text-blue-700"
  },
  error: {
    label: "Error",
    className: "text-red-700"
  }
};
function humanize(ref) {
  // Real bug found live (2026-09-30): a bridged native connector's own
  // connector_ref is a full "org_slug/connector_name" namespace (e.g.
  // "default/microsoft_365"), but this only ever split on "-"/"_" --
  // never "/" -- so the fallback (meant only for the genuine "no real
  // catalog item at all" case) rendered literal broken names like
  // "Default/microsoft 365" whenever it was reached. Strip a leading
  // "<anything>/" segment first; humanize the connector name alone.
  const bare = ref.includes("/") ? ref.slice(ref.lastIndexOf("/") + 1) : ref;
  return bare.split(/[-_]/).map(w => w.length ? w.charAt(0).toUpperCase() + w.slice(1) : w).join(" ");
}
export function ConnectorsYoursRow({
  item,
  connection
}) {
  const client = useEcosystemClient();
  useConnectionOverrideVersion();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const resolved = resolveConnectionStatus(connection.connector_ref, connection);
  const style = STATUS_STYLE[resolved.status];
  const reconnect = () => {
    setBusy(true);
    setError(null);
    client.reconnect(connection.connector_ref).then(result => {
      if (result.authorize_url) {
        window.location.assign(result.authorize_url);
        return;
      }
      setConnectionState(connection.connector_ref, {
        connector_ref: connection.connector_ref,
        item_id: item.id,
        status: result.status,
        last_connected_at: new Date().toISOString(),
        expires_at: null
      });
    })
    // Same class of real bug fixed in ConnectorDetail.tsx's handleConnect
    // (2026-09-30): connect()/reconnect() used to always resolve
    // {"status": "connected"}, so this never actually rejected in
    // practice -- there was no .catch() here at all.
    .catch(err => setError(err instanceof Error ? err.message : "Couldn't reconnect.")).finally(() => setBusy(false));
  };
  const disconnect = () => {
    setBusy(true);
    setError(null);
    client.disconnect(connection.connector_ref).then(() => setConnectionState(connection.connector_ref, {
      connector_ref: connection.connector_ref,
      item_id: item.id,
      status: "not_connected",
      last_connected_at: null,
      expires_at: null
    })).catch(err => setError(err instanceof Error ? err.message : "Couldn't disconnect.")).finally(() => setBusy(false));
  };
  return <div data-testid="connectors-yours-row" data-connector-ref={connection.connector_ref} className="flex items-center gap-4 py-2">
      <ItemIcon iconUrl={item.icon_url ?? null} namespace={item.namespace ?? connection.connector_ref} displayName={item.display_name} size={28} />
      <span className="flex-1">{item.display_name}</span>
      <span data-testid="connection-status-chip" data-status={resolved.status} className={["text-xs", style.className].join(" ")}>
        {style.label}
      </span>
      {connection.last_connected_at && <span className="text-xs text-gray-400">
          Last used {new Date(connection.last_connected_at).toLocaleDateString()}
        </span>}
      {(resolved.status === "needs_reauth" || resolved.status === "expired") && <Button variant="secondary" data-testid="connectors-yours-reconnect" disabled={busy} loading={busy} title={error ?? undefined} onClick={reconnect}>
          {error ? "Retry" : "Reconnect"}
        </Button>}
      {resolved.status === "connected" && <Button variant="secondary" data-testid="connectors-yours-disconnect" disabled={busy} loading={busy} title={error ?? undefined} onClick={disconnect}>Disconnect</Button>}
      {error && <span data-testid="connectors-yours-row-error" className="text-xs text-red-600">
          {error}
        </span>}
    </div>;
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
export function ConnectorsYours({
  onDiscover
}) {
  const client = useEcosystemClient();
  const [connections, setConnections] = useState(null);
  const [itemsById, setItemsById] = useState({});
  useEffect(() => {
    let cancelled = false;
    client.listConnections().then(rows => {
      if (cancelled) return;
      setConnections(rows);
      const ids = Array.from(new Set(rows.map(r => r.item_id).filter(id => Boolean(id))));
      Promise.all(ids.map(id => client.getItem(id).catch(() => null))).then(fetched => {
        if (cancelled) return;
        const byId = {};
        for (const it of fetched) if (it) byId[it.id] = it;
        setItemsById(byId);
      });
    });
    return () => {
      cancelled = true;
    };
  }, [client]);
  if (connections === null) return <div data-testid="connectors-yours-loading">Loading…</div>;
  if (connections.length === 0) {
    return <div data-testid="connectors-yours-empty" className="text-center py-8">
        <p>No connectors yet.</p>
        <Button variant="secondary" data-testid="connectors-yours-browse-discover" onClick={onDiscover}>Browse Discover</Button>
      </div>;
  }
  return <div data-testid="connectors-yours-list">
      {connections.map(c => {
      const real = c.item_id ? itemsById[c.item_id] : undefined;
      const item = real ? real : {
        id: c.item_id ?? c.connector_ref,
        namespace: c.connector_ref,
        display_name: humanize(c.connector_ref),
        icon_url: null
      };
      return <ConnectorsYoursRow key={c.connector_ref} item={item} connection={c} />;
    })}
    </div>;
}