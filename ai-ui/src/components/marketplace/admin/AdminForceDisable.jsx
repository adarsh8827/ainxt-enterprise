// SPDX-License-Identifier: MIT
// Task F-13: calling B-19's force-disable/unyank. UI hiding is a
// convenience, not the enforcement -- the server independently re-checks
// marketplace:admin_sources on every call regardless of what this screen
// renders (require_permission dependency, routers/ecosystem_router.py).
//
// User-flow QA round 8 (2026-10-03, audit finding): "Force disable" fired
// immediately on click with zero confirmation -- a platform-wide action
// on an arbitrary item-id typed into a plain text input, unlike every
// other destructive marketplace action (Yours/Detail's uninstall/disable,
// delete/retire) which all confirm first. "Unyank" (the safe/reversible
// direction, re-enabling) deliberately stays immediate, same reasoning as
// Enable vs. Disable elsewhere.
import { useState } from "react";
import { useEcosystemClient } from "../lib/context/HostContext";
import { ConfirmDialog } from "../ConfirmDialog";
import { Button } from "../Button";
import { ItemPicker } from "./ItemPicker";

export function AdminForceDisable() {
  const client = useEcosystemClient();
  const [selectedItem, setSelectedItem] = useState(null);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const itemId = selectedItem?.id ?? "";

  const run = action => {
    if (!itemId) return;
    setSubmitting(true);
    setError(null);
    const call = action === "force-disable" ? client.forceDisable(itemId) : client.unyank(itemId);
    call.then(() => setStatus(action === "force-disable" ? "Disabled (yanked)." : "Re-enabled (active).")).catch(e => setError(e instanceof Error ? e.message : "Couldn't update this item.")).finally(() => setSubmitting(false));
  };

  return (
    <div data-testid="admin-force-disable">
      <h2 className="text-xl text-gray-900 mb-3">Force disable / re-enable</h2>
      <div className="rounded-md border border-gray-200 bg-gray-50 p-4">
        <div className="mb-3">
          <ItemPicker value={selectedItem} onChange={item => {
          setSelectedItem(item);
          setStatus(null);
          setError(null);
        }} testId="admin-force-disable-item" />
        </div>
        <div className="flex gap-2">
          <Button variant="danger" data-testid="admin-force-disable-run" disabled={submitting || !itemId} onClick={() => setConfirming(true)}>
            Force disable
          </Button>
          <Button variant="secondary" data-testid="admin-force-disable-unyank" disabled={submitting || !itemId} onClick={() => run("unyank")}>
            Unyank
          </Button>
        </div>
        {status && <p data-testid="admin-force-disable-status" className="text-green-700 mt-2">{status}</p>}
        {error && <p role="alert" className="text-red-600 mt-2">{error}</p>}
      </div>
      <ConfirmDialog
        open={confirming}
        title="Force disable this item?"
        message={`"${selectedItem?.display_name ?? itemId}" will be marked yanked platform-wide -- every org's existing installs stop working immediately until it's unyanked.`}
        confirmLabel="Force disable"
        danger
        onConfirm={() => {
          setConfirming(false);
          run("force-disable");
        }}
        onCancel={() => setConfirming(false)}
      />
    </div>
  );
}
