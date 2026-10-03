// SPDX-License-Identifier: MIT
// ============================================================
// Connectors phase: the connector-status analogue of installStore.ts.
// Same architectural pattern (deliberately, per this session's own
// install-state-consistency precedent) -- a module-level Map keyed by
// connector_ref, living outside any one component's lifecycle. Every
// connect/disconnect/reconnect call site writes here immediately so
// every other mounted ConnectorCard/ConnectorDetail/ConnectorsYours row
// for the SAME connector re-renders with the corrected status on the
// same tick, without waiting for a refetch.
//
// Cross-tab consistency reuses the exact same mechanism installStore.ts
// relies on: client.streamChanges() (the real, already-existing
// ecosystem.changed SSE relay) -- a second tab's own copy of this module
// is corrected by ITS OWN streamChanges() subscription triggering a
// listConnections() refetch, not by anything written here.
// ============================================================
import { useCallback, useSyncExternalStore } from "react";
const _overrides = new Map();
const _listeners = new Set();
let _version = 0;
function _notify() {
  _version += 1;
  for (const listener of _listeners) listener();
}

/** Call immediately after any successful connect/disconnect/reconnect
 * resolves. */
export function setConnectionState(connectorRef, conn) {
  _overrides.set(connectorRef, conn);
  _notify();
}
export function getConnectionOverride(connectorRef) {
  return _overrides.get(connectorRef);
}

/** Merges the freshest known override onto a freshly-fetched connection
 * status list -- a no-op for any ref with no override yet. */
export function applyConnectionOverrides(connections) {
  return connections.map(c => _overrides.get(c.connector_ref) ?? c);
}

/** For a connector_ref not present at all in a freshly-fetched list
 * (never connected server-side) but overridden locally (e.g. optimistic
 * "connecting" state right after a click) -- returns the override, or a
 * default "not_connected" row when neither exists. */
export function resolveConnectionStatus(connectorRef, fetched) {
  const override = _overrides.get(connectorRef);
  if (override) return override;
  if (fetched) return fetched;
  return {
    connector_ref: connectorRef,
    item_id: null,
    status: "not_connected",
    last_connected_at: null,
    expires_at: null
  };
}
export function useConnectionOverrideVersion() {
  const subscribe = useCallback(onChange => {
    _listeners.add(onChange);
    return () => {
      _listeners.delete(onChange);
    };
  }, []);
  const getSnapshot = useCallback(() => _version, []);
  return useSyncExternalStore(subscribe, getSnapshot);
}

/** Test-only reset -- same convention as installStore.ts's own. */
export function __resetConnectionStoreForTests() {
  _overrides.clear();
  _version = 0;
}