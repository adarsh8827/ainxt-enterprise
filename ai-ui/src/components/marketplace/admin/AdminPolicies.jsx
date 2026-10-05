// SPDX-License-Identifier: MIT
// Task F-13: who-can-add/allowed-sources/auto-update, calling B-19's
// GET/PUT /ecosystem/policy (task M4 backend prerequisites -- these
// endpoints didn't exist until this same milestone added them).
import { useEffect, useState } from "react";
import { useEcosystemClient } from "../lib/context/HostContext";
import { useOptionalToast } from "../lib/useOptionalToast";
import { LoadingState } from "../LoadingState";

/** Tier 2 of the tiered license policy (ECOSYSTEM_PLAN.md §11.2) is a
 * free-form comma-separated list here rather than a fixed checkbox set --
 * an admin can opt into any SPDX identifier, not just a pre-enumerated
 * handful. MIT/Apache-2.0 are always effectively allowed regardless
 * (Tier 1 is checked first, server-side), so removing them from this list
 * narrows nothing -- shown here as-is rather than silently re-added, so
 * the admin sees exactly what they saved. */
function parseLicenseList(text) {
  return text.split(",").map(s => s.trim()).filter(Boolean);
}
export function AdminPolicies() {
  const client = useEcosystemClient();
  const toast = useOptionalToast();
  const [policy, setPolicy] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  // User-flow QA round 8 (2026-10-03, audit finding): save() had no
  // .catch() at all -- a failed save left `policy` holding its own
  // pre-save value (setPolicy(the-resolved-response) simply never ran),
  // so a radio/checkbox/blur that failed server-side just silently
  // reverted with zero indication anything went wrong. Separate from
  // `error` above (the load failure, which replaces this whole screen)
  // -- a save failure should surface without blanking out an already-
  // loaded, otherwise-usable policy screen.
  const [saveError, setSaveError] = useState(null);
  const [licenseListText, setLicenseListText] = useState("");
  useEffect(() => {
    let cancelled = false;
    client.getPolicy().then(p => {
      if (cancelled) return;
      setPolicy(p);
      setLicenseListText(p.allowed_licenses_shared.join(", "));
    }).catch(e => setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, [client]);
  if (error) return <div role="alert" data-testid="admin-policies-error">{error}</div>;
  if (!policy) return <div data-testid="admin-policies-loading"><LoadingState /></div>;
  const save = patch => {
    setSaving(true);
    setSaveError(null);
    // Admin-polish pass (2026-10-05): this was the ONLY feedback path for
    // every radio/checkbox/input save on this screen -- a successful save
    // had literally no visible confirmation at all (no inline text, no
    // toast), unlike AdminProvisioning/AdminFeatured/AdminForceDisable's
    // own inline `status` paragraphs. toast.success here is the first
    // success feedback this screen has ever shown.
    client.setPolicy(patch).then(p => {
      setPolicy(p);
      toast.success("Saved.");
    }).catch(e => {
      const message = e instanceof Error ? e.message : "Couldn't save this change.";
      setSaveError(message);
      toast.error(message);
    }).finally(() => setSaving(false));
  };
  return <div data-testid="admin-policies">
      <h2 className="text-xl font-semibold text-gray-900 mb-3">Marketplace policy</h2>

      {saveError && <p role="alert" data-testid="admin-policies-save-error" className="text-red-600 text-sm">{saveError}</p>}

      <fieldset className="border-none p-0 mb-4">
        <legend className="text-sm text-gray-500">Who can add items</legend>
        {["all_users", "admins_only"].map(v => <label key={v} className="flex items-center gap-1.5 text-gray-900">
            <input type="radio" name="who_can_add" value={v} checked={policy.who_can_add === v} disabled={saving} onChange={() => save({
          who_can_add: v
        })} />
            {v === "all_users" ? "All authenticated users" : "Admins only"}
          </label>)}
      </fieldset>

      {/* BUG-02 fix: the Sources tab's own footer text already claimed
          "who-can-add/share are managed on the Policies tab" -- the backend
          (PUT /ecosystem/policy {who_can_share}) already worked, this
          control just never existed anywhere, making that footer text a
          lie. Same shape as "Who can add items" above. */}
      <fieldset className="border-none p-0 mb-4">
        <legend className="text-sm text-gray-500">Who can share their own items</legend>
        {["all_users", "admins_only"].map(v => <label key={v} className="flex items-center gap-1.5 text-gray-900">
            <input type="radio" name="who_can_share" value={v} checked={policy.who_can_share === v} disabled={saving} onChange={() => save({
          who_can_share: v
        })} />
            {v === "all_users" ? "All authenticated users" : "Admins only"}
          </label>)}
      </fieldset>

      <label className="flex items-center gap-1.5 text-gray-900">
        <input type="checkbox" data-testid="admin-policies-auto-update" checked={policy.auto_update_default} disabled={saving} onChange={e => save({
        auto_update_default: e.target.checked
      })} />
        Auto-update installs by default
      </label>

      <div className="mt-4">
        <label className="block text-sm text-gray-500 mb-1">
          Licenses allowed once shared/provisioned/required
        </label>
        <input data-testid="admin-policies-allowed-licenses-shared" value={licenseListText} disabled={saving} onChange={e => setLicenseListText(e.target.value)} onBlur={() => save({
        allowed_licenses_shared: parseLicenseList(licenseListText)
      })} placeholder="MIT, Apache-2.0" className="w-full bg-white border border-gray-300 rounded px-3 py-2 text-sm text-gray-900 focus:outline-none focus-visible:outline-none! focus:border-indigo-300" />
        <p className="text-xs text-gray-500 mt-1 mb-0">
          Comma-separated SPDX identifiers. MIT/Apache-2.0 are always allowed regardless of this list.
        </p>
      </div>
    </div>;
}