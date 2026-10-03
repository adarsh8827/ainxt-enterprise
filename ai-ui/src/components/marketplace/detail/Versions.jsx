// SPDX-License-Identifier: MIT
// Task F-7: rollback calls installs_service.rollback (B-10) -- immutable
// version rows, "Edit" always creates a new version, never mutates one in
// place (CONFIG_AND_PRODUCTS.md §7 item 11).
//
// User-flow QA round 8 (2026-10-03, real user question: "rollback option
// what doing just showing version tab?"): rollback DID work server-side,
// but this component called client.rollbackInstall() directly with no
// confirmation, no loading state, no error handling, and no way to tell
// its parent to refetch -- so a successful click looked identical to a
// silently-failed one, and the "current" badge below never moved until an
// unrelated refresh happened to occur. Fixed by routing the click up
// through Detail.jsx's own onRollback (same confirm-then-run pattern as
// Uninstall/Disable/Retire there), and accepting `refreshKey` so this
// component's own fetch re-runs once that confirm's mutation resolves --
// itemId alone never changes on a rollback, so the original effect
// (keyed only on itemId) would never have refetched on its own.
//
// Same round's audit also found Update (move an install FORWARD onto a
// newer version -- the same update_to_version mechanism, just the other
// direction) had zero UI entry point anywhere despite being fully real
// server-side -- added here as "Update to this version" on the current/
// newest row, same confirm-then-run wiring as Rollback.
import { useEffect, useState } from "react";
import { useEcosystemClient } from "../lib/context/HostContext";
import { VerdictBadge } from "../Badges";
import { Button } from "../Button";

export function Versions({ itemId, installId, canRollback, onRollback, canUpdate, onUpdate, refreshKey }) {
  const client = useEcosystemClient();
  const [versions, setVersions] = useState(null);

  useEffect(() => {
    let cancelled = false;
    client.getVersions(itemId).then(v => {
      if (!cancelled) setVersions(v);
    });
    return () => {
      cancelled = true;
    };
  }, [client, itemId, refreshKey]);

  if (versions === null) return <div data-testid="detail-tab-versions-loading">Loading versions…</div>;

  return (
    <div data-testid="detail-tab-versions">
      {versions.map(v => (
        <div
          key={v.id}
          data-testid="version-row"
          className="flex items-center gap-2 py-2 border-b border-gray-200"
        >
          <span className="font-mono text-gray-900">{v.version}</span>
          {v.is_current && <span className="text-xs text-indigo-600">current</span>}
          <VerdictBadge verdict={v.gate_verdict} />
          <span className="ml-auto text-xs text-gray-400">
            {v.created_at ? new Date(v.created_at).toLocaleDateString() : ""}
          </span>
          {!v.is_current && canRollback && installId && (
            <Button
              variant="secondary"
              data-testid="rollback-button"
              onClick={() => onRollback(v.id)}
              className="text-xs px-2.5 py-1"
            >
              Roll back to this version
            </Button>
          )}
          {/* User-flow QA round 8 (2026-10-03, audit finding): "Update" was
              a real, fully working backend action (installs_service.
              update_to_version -- the exact same mechanism Rollback uses,
              just moving forward instead of back) with NO button anywhere
              in the UI that could ever call it, even when the server's
              own allowed_actions already said a newer version existed.
              The current/newest row (v.is_current) is the only one Update
              ever targets -- rolling an install itself off some OLDER
              version forward onto this one. */}
          {v.is_current && canUpdate && installId && (
            <Button
              data-testid="update-button"
              onClick={() => onUpdate(v.id)}
              className="text-xs px-2.5 py-1"
            >
              Update to this version
            </Button>
          )}
        </div>
      ))}
    </div>
  );
}
