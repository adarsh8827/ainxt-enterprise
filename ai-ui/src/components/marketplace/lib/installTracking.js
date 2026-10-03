// SPDX-License-Identifier: MIT
// Item 2 (2026-09-29 live-test round): "install state must be server-driven
// -- Add returns immediately with the install/run id; the UI shows status
// from the server (and live events), never from an in-flight browser
// request... Navigating away must not cancel or fail an install."
//
// The real bug: Card.tsx/Detail.tsx used to track "is this item currently
// being added" as local component state, set directly from the in-flight
// install() promise's own .then()/.catch() (a useState flipped to true
// before the call, false/error inside the callbacks). When the component
// unmounted -- e.g. switching Discover -> Yours and back, which fully
// unmounts/remounts Discover (CatalogScreen.tsx renders one or the other,
// never both) -- that local state was lost. A fresh mount had no way to
// tell "an install is still genuinely running" from "nothing has ever
// happened here," so it fell back to whatever it renders by default,
// inviting a second, conflicting Add click rather than reflecting reality.
//
// This module is the persistent signal that fixes that: a per-item record
// of the currently in-flight (or just-failed) install, keyed by item id,
// living OUTSIDE any one component's lifecycle -- a module-level store
// (read reactively via useSyncExternalStore) backed by sessionStorage, so
// it survives both a React unmount/remount AND a real page reload within
// the same tab. The actual terminal status, though, always comes from a
// fresh server GET (client.getJob(), the SAME polling mechanism
// detail/Verification.tsx already uses for gate-run status) keyed by the
// job_id install_item() itself now returns immediately
// (routers/ecosystem_router.py) -- never from whether the original POST's
// own promise happened to still be "remembered" by some component.
import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";
const IDLE_STATE = {
  phase: "idle",
  jobId: null,
  error: null
};
const POLL_INTERVAL_MS = 2000;
const _state = new Map();
const _listeners = new Map();
function _storageKey(itemId) {
  return `ecosystem-ui:installing:${itemId}`;
}
function _readSeed(itemId) {
  try {
    const raw = window.sessionStorage.getItem(_storageKey(itemId));
    if (!raw) return IDLE_STATE;
    const parsed = JSON.parse(raw);
    // A prior mount/reload's own in-flight install -- surfaces as
    // "installing" again so this fresh mount resumes polling it, rather
    // than silently forgetting an install that's still genuinely running
    // server-side.
    return {
      phase: "installing",
      jobId: parsed.jobId ?? null,
      error: null
    };
  } catch {
    return IDLE_STATE;
  }
}
function _persist(itemId, state) {
  try {
    if (state.phase === "installing") {
      window.sessionStorage.setItem(_storageKey(itemId), JSON.stringify({
        jobId: state.jobId
      }));
    } else {
      window.sessionStorage.removeItem(_storageKey(itemId));
    }
  } catch {
    // Private-browsing/storage-disabled -- tracking still works in-memory
    // for this tab's own lifetime, it just won't survive a reload.
  }
}
function _set(itemId, state) {
  _state.set(itemId, state);
  _persist(itemId, state);
  for (const listener of _listeners.get(itemId) ?? []) listener();
}
function _get(itemId) {
  const existing = _state.get(itemId);
  if (existing) return existing;
  const seeded = _readSeed(itemId);
  _state.set(itemId, seeded);
  return seeded;
}
function _subscribe(itemId, onChange) {
  let set = _listeners.get(itemId);
  if (!set) {
    set = new Set();
    _listeners.set(itemId, set);
  }
  set.add(onChange);
  return () => {
    set.delete(onChange);
    if (set.size === 0) _listeners.delete(itemId);
  };
}

/** Call the instant Add is clicked, before the POST even resolves -- a
 * remount in that brief window must still read "installing," never fall
 * back to a fresh "Add" (item 2's own repro). */
export function beginInstall(itemId, jobId = null) {
  _set(itemId, {
    phase: "installing",
    jobId,
    error: null
  });
}

/** Call once the POST resolves with a real job id (install_item()'s own
 * response, routers/ecosystem_router.py) -- attaches the real, pollable id
 * without disturbing an already-resolved/cleared entry (a slow response
 * landing after the user already retried/cancelled must not resurrect a
 * stale "installing" state). */
export function attachInstallJob(itemId, jobId) {
  const current = _get(itemId);
  if (current.phase !== "installing") return;
  _set(itemId, {
    phase: "installing",
    jobId,
    error: null
  });
}

/** A REAL terminal failure -- the original POST's own rejection (a
 * genuine server error response). Never called merely because a
 * component lost track of an in-flight request. */
export function failInstall(itemId, message) {
  _set(itemId, {
    phase: "failed",
    jobId: null,
    error: message
  });
}

/** Install finished (terminally, any verdict) -- clears tracking
 * entirely; the caller's own item refetch is what actually shows "Added"
 * from here on (item.install_id), not this module. Also used to dismiss
 * a "failed" state before a real Retry click. */
export function clearInstall(itemId) {
  _set(itemId, IDLE_STATE);
}

/** Test-only: clears every tracked install and its sessionStorage backup.
 * Real app code never needs this -- the module-level store above is
 * meant to persist for the whole tab's lifetime -- but a test FILE's
 * module registry is shared across every one of its `it()` blocks, so
 * tests must reset it themselves (afterEach) to stay isolated from each
 * other, especially since several tests intentionally reuse the same
 * fixture item ids. */
export function __resetInstallTrackingForTests() {
  for (const itemId of _state.keys()) _persist(itemId, IDLE_STATE);
  _state.clear();
  _listeners.clear();
}

/** Card.tsx/Detail.tsx's own hook: subscribes to itemId's tracked install
 * state and, whenever it's "installing" with a real job id, polls
 * client.getJob() -- the SAME async-envelope mechanism
 * detail/Verification.tsx already polls for gate-run status -- until the
 * job resolves, at which point it clears tracking and calls onResolved()
 * so the caller re-fetches the item itself (to pick up the real
 * install_id/verdict). Survives the polling component itself unmounting
 * mid-poll: the tracked state lives in the module-level store above, not
 * in this hook's own closure, so a remount simply resumes polling the
 * same job id rather than losing track of it. */
export function useInstallStatus(itemId, client, onResolved) {
  const subscribe = useCallback(onChange => _subscribe(itemId, onChange), [itemId]);
  const getSnapshot = useCallback(() => _get(itemId), [itemId]);
  const state = useSyncExternalStore(subscribe, getSnapshot);
  const onResolvedRef = useRef(onResolved);
  onResolvedRef.current = onResolved;
  useEffect(() => {
    if (state.phase !== "installing" || !state.jobId) return;
    let cancelled = false;
    const jobId = state.jobId;
    const poll = () => {
      client.getJob(jobId).then(job => {
        if (cancelled) return;
        if (job.status !== "verifying") {
          clearInstall(itemId);
          onResolvedRef.current?.();
        }
      }).catch(() => {
        // A poll GET failing (transient network blip) is never treated as
        // a real install failure -- only the original POST's own
        // rejection (failInstall(), from the click handler) is. The next
        // tick simply tries again.
      });
    };
    poll();
    const interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [itemId, client, state.phase, state.jobId]);
  return state;
}