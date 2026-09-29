// SPDX-License-Identifier: MIT
// ============================================================
// Install-state-consistency round (2026-09-29): real bug reported live --
// "installed a catalog skill, uninstalled it from Yours (worked), went
// back to Discover -> it still shows Installed and can't be removed
// there." Root cause: Discover/Yours/Detail each only ever refreshed
// THEIR OWN fetched data on a mutation -- nothing told the other screens
// (or catalogCache.ts's own tab-switch cache, see patchCachedInstallState)
// that anything had changed. Discover's own Card also never offered an
// uninstall action at all for an installed item (a read-only "Added"
// badge only) -- part of this same round adds one.
//
// This module is the single client-side source of truth for "is item X
// currently installed, and how" -- a module-level Map, keyed by item id,
// living OUTSIDE any one component's lifecycle (same architectural
// pattern as installTracking.ts's own in-flight-install tracker, but for
// the STEADY-STATE result rather than the transient in-flight phase).
// Every mutation call site (Card.tsx's Add, Yours.tsx's uninstall/enable/
// disable/delete/retire/unshare, Detail.tsx's install/uninstall/
// setEnabled) writes here immediately, synchronously, before the
// server round-trip even needs to be waited on by anyone else currently
// mounted -- and patches catalogCache.ts's own cached entries so even a
// screen that ISN'T currently mounted shows the correction the instant
// it next reads its cache, not after a further network round trip.
//
// Cross-TAB consistency (the user's own explicit "same across two open
// tabs" test) is handled separately, in client/EcosystemClient.ts's
// streamChanges() -- the real, already-existing, per-org Redis
// `ecosystem.changed` pub/sub (CONTRACTS.md §13), the exact mechanism
// ai-ui's chat "/" menu (useEcosystemChatSkills.js) already subscribes to
// for the same reason. Each browser tab holds its own separate instance
// of this module (JS module state is per-tab, not shared), so a second
// tab's own copy of this store is corrected by ITS OWN streamChanges()
// subscription triggering a refetch, not by anything written here.
// ============================================================
import { useCallback, useSyncExternalStore } from "react";
import type { ItemSummary } from "./types";
import { patchCachedInstallState, removeItemFromCaches } from "./catalogCache";

export interface InstallStatePatch {
  install_id: string | null;
  enabled?: boolean | null;
  install_scope?: ItemSummary["install_scope"];
  install_surfaces?: ItemSummary["install_surfaces"];
}

const _overrides = new Map<string, InstallStatePatch>();
const _listeners = new Set<() => void>();
let _version = 0;

function _notify(): void {
  _version += 1;
  for (const listener of _listeners) listener();
}

/** Call immediately after ANY successful install/uninstall/enable/
 * disable mutation resolves, from wherever it happens (Card.tsx, Yours.tsx,
 * Detail.tsx). Never waits for a poll or a background refetch -- every
 * OTHER currently-mounted consumer of applyInstallOverride()/
 * useInstallOverrideVersion() re-renders with the correct state on this
 * same tick, and catalogCache.ts's tab-switch cache is patched so a
 * not-currently-mounted screen is already correct the moment it reads it. */
export function setInstallState(itemId: string, patch: InstallStatePatch): void {
  _overrides.set(itemId, patch);
  patchCachedInstallState(itemId, patch);
  _notify();
}

/** Call after delete_draft (the item itself no longer exists at all, not
 * merely uninstalled) -- clears any override (nothing left to override)
 * and removes the item from catalogCache.ts's cached Discover entries
 * outright. */
export function removeInstallTracking(itemId: string): void {
  _overrides.delete(itemId);
  removeItemFromCaches(itemId);
  _notify();
}

/** Merges the freshest known override onto a freshly-fetched item --
 * used everywhere an ItemSummary/ItemDetail is about to be rendered.
 * A no-op (returns the same object) when nothing has overridden this
 * item id, so this is always safe to call unconditionally. */
export function applyInstallOverride<T extends ItemSummary>(item: T): T {
  const override = _overrides.get(item.id);
  if (!override) return item;
  return {
    ...item,
    install_id: override.install_id,
    enabled: override.enabled ?? (override.install_id === null ? null : item.enabled),
    install_scope: override.install_scope ?? (override.install_id === null ? null : item.install_scope),
    install_surfaces: override.install_surfaces ?? (override.install_id === null ? null : item.install_surfaces),
  };
}

/** Subscribe hook: returns a version number that changes on every
 * setInstallState()/removeInstallTracking() call, from ANY item id --
 * cheap and simple rather than a per-item subscription registry, since
 * every consumer of this already re-maps its own full item list through
 * applyInstallOverride() on every render regardless of which specific
 * item changed. */
export function useInstallOverrideVersion(): number {
  const subscribe = useCallback((onChange: () => void) => {
    _listeners.add(onChange);
    return () => { _listeners.delete(onChange); };
  }, []);
  const getSnapshot = useCallback(() => _version, []);
  return useSyncExternalStore(subscribe, getSnapshot);
}

/** Test-only reset -- same convention as installTracking.ts's own
 * __resetInstallTrackingForTests(). */
export function __resetInstallStoreForTests(): void {
  _overrides.clear();
  _version = 0;
}
