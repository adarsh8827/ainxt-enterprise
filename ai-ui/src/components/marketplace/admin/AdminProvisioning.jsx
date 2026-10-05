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
import { ItemPicker } from "./ItemPicker";
import { useOptionalToast } from "../lib/useOptionalToast";

export function AdminProvisioning() {
  const client = useEcosystemClient();
  const toast = useOptionalToast();
  const [selectedItem, setSelectedItem] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const itemId = selectedItem?.id ?? "";

  const run = action => {
    if (!itemId) return;
    setSubmitting(true);
    setError(null);
    setResult(null);
    const call = action === "require" ? client.requireItem(itemId) : client.unrequireItem(itemId);
    call.then(res => {
      // BUG-06 fix: the backend now 404s a genuinely nonexistent item (caught
      // below, in .catch), but a REAL item can legitimately have nothing left
      // to promote/demote (e.g. already fully required) -- count=0 in that
      // case isn't an error, just not the success this copy used to claim
      // regardless of count.
      const count = action === "require" ? res?.promoted_installs : res?.demoted_installs;
      const message = count === 0 ? action === "require"
          ? "No org-provisioned installs needed promotion for this item."
          : "No required installs needed demotion for this item."
        : action === "require" ? "Promoted to Required for this org." : "Demoted back to Org provisioned.";
      setResult(message);
      toast.success(message);
    }).catch(e => {
      const message = e instanceof Error ? e.message : "Couldn't update this item's provisioning.";
      setError(message);
      toast.error(message);
    }).finally(() => setSubmitting(false));
  };

  return (
    <div data-testid="admin-provisioning">
      {/* Admin-polish pass (2026-10-05): same missing-font-weight gap as
          every other `text-xl`/`text-lg` heading fixed elsewhere this
          round -- see CategorySection.jsx's own comment for the full
          rationale. mb-1 added -- this heading had no margin below it at
          all, the description paragraph's own mb-3 was carrying 100% of
          the gap. */}
      <h2 className="text-xl font-semibold text-gray-900 mb-1">Provisioning</h2>
      <p className="text-gray-500 text-sm mb-3">
        Promote an already org-provisioned item to Required (no user in this org may disable it), or demote it back.
      </p>
      <div className="rounded-md border border-gray-200 bg-gray-50 p-4">
        <div className="mb-3">
          <ItemPicker value={selectedItem} onChange={item => {
          setSelectedItem(item);
          setResult(null);
          setError(null);
        }} testId="admin-provisioning-item" />
        </div>
        <div className="flex gap-2">
          <Button data-testid="admin-provisioning-require" disabled={submitting || !itemId} onClick={() => setConfirming(true)}>
            Make required
          </Button>
          <Button variant="secondary" data-testid="admin-provisioning-unrequire" disabled={submitting || !itemId} onClick={() => run("unrequire")}>
            Make optional
          </Button>
        </div>
        {result && <p data-testid="admin-provisioning-result" className="text-green-700 mt-2">{result}</p>}
        {error && <p role="alert" className="text-red-600 mt-2">{error}</p>}
      </div>
      <ConfirmDialog
        open={confirming}
        title="Make this item required?"
        message={`No user in this org will be able to disable "${selectedItem?.display_name ?? itemId}" afterward, org-wide, until it's demoted back.`}
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
