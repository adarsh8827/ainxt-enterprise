// SPDX-License-Identifier: MIT
// Task F-13: default-on/required install scope. Real backend surface
// (CONTRACTS.md §17): POST /ecosystem/items/{id}/require|/unrequire --
// promotes/demotes every existing origin='provisioned' install for that
// item, org-wide, to/from 'required' (CONFIG_AND_PRODUCTS.md §12 point 3).
// There is no separate "make an arbitrary published item org-default"
// endpoint distinct from this -- that provisioning happens at creation
// time via provision_scope (CreateForm.tsx's own picker); this screen's
// real job is the require/unrequire promotion, not group targeting (no
// group concept exists anywhere in this backend surface -- disclosed, not
// faked with a fake selector).
//
// User-flow QA round 8 (2026-10-03, audit finding): "Make required" fired
// immediately -- it's the more restrictive direction (locks the item so
// no user in the org may disable it, org-wide) and now confirms first,
// same reasoning as Force disable. "Make optional" (the reversible,
// loosening direction) deliberately stays immediate.
import { useState } from "react";
import { useEcosystemClient } from "../lib/context/HostContext";
import { ConfirmDialog } from "../ConfirmDialog";
import { Button } from "../Button";

export function AdminProvisioning() {
  const client = useEcosystemClient();
  const [itemId, setItemId] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const run = action => {
    if (!itemId.trim()) return;
    setSubmitting(true);
    setError(null);
    setResult(null);
    const call = action === "require" ? client.requireItem(itemId) : client.unrequireItem(itemId);
    call.then(() => setResult(action === "require" ? "Promoted to Required for this org." : "Demoted back to Org provisioned.")).catch(e => setError(e instanceof Error ? e.message : "Couldn't update this item's provisioning.")).finally(() => setSubmitting(false));
  };

  return (
    <div data-testid="admin-provisioning">
      <h2 className="text-xl text-gray-900">Provisioning</h2>
      <p className="text-gray-500 text-sm">
        Promote an already org-provisioned item to Required (no user in this org may disable it), or demote it back.
      </p>
      <input
        data-testid="admin-provisioning-item-id"
        value={itemId}
        onChange={e => setItemId(e.target.value)}
        placeholder="item id"
        className="w-full bg-white border border-gray-300 rounded px-3 py-2 text-sm text-gray-900 focus:outline-none focus-visible:outline-none! focus:border-indigo-300 mb-2"
      />
      <div className="flex gap-2">
        <Button data-testid="admin-provisioning-require" disabled={submitting || !itemId.trim()} onClick={() => setConfirming(true)}>
          Make required
        </Button>
        <Button variant="secondary" data-testid="admin-provisioning-unrequire" disabled={submitting} onClick={() => run("unrequire")}>
          Make optional
        </Button>
      </div>
      {result && <p data-testid="admin-provisioning-result" className="text-green-700">{result}</p>}
      {error && <p role="alert" className="text-red-600">{error}</p>}
      <ConfirmDialog
        open={confirming}
        title="Make this item required?"
        message={`No user in this org will be able to disable "${itemId.trim()}" afterward, org-wide, until it's demoted back. Confirm the item id is correct before continuing.`}
        confirmLabel="Make required"
        onConfirm={() => {
          setConfirming(false);
          run("require");
        }}
        onCancel={() => setConfirming(false)}
      />
    </div>
  );
}
