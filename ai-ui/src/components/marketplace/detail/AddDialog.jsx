// SPDX-License-Identifier: MIT
// Task F-7 (M5 UI-parity review, item A4 follow-up): scope + an inline
// warning-finding banner (shown when the item's latest verdict is 'warn'
// -- a 'fail' verdict never reaches this dialog at all, since 'install'
// is absent from allowed_actions for a blocked item, per
// items_service.compute_allowed_actions()).
//
// Per-surface toggles round (2026-09-29): the "Surfaces" toggle fieldset
// that used to live here is gone -- installs always take `defaultSurfaces`
// (the org's product-profile-allowed set, computed by the caller --
// Detail.tsx's own config.surfaces) verbatim now, with no per-install
// manual override in this normal-user-facing dialog. An admin who needs
// to adjust a specific install's surfaces afterward uses the "Advanced"
// section on the Detail page instead (Item 3's own admin-only override,
// EcosystemClient.setSurfaces -- unreachable from here on purpose).
//
// Only rendered at all when there's a real decision to make: Detail.tsx
// now installs directly, with no dialog, whenever the caller has no
// scope choice (no marketplace:share/marketplace:provision) AND the item
// has no warning to acknowledge -- matching the reference screenshots'
// own "Add is one button, no form" pattern for the common case. This
// component still exists for the two cases that DO need it: a caller who
// genuinely can choose a wider scope (installScopes.length > 1), and/or
// an item whose verdict needs acknowledging first -- in the latter case
// alone, with no real scope choice, it renders as a bare warning +
// Cancel/Continue (screenshot 3's own shape), no scope radio or surface
// toggles at all, since there's nothing to choose.
import { useState } from "react";
import { XMarkIcon } from "@heroicons/react/24/outline";
import { useEcosystemClient } from "../lib/context/HostContext";
import { useConfig } from "../lib/hooks/useEcosystemConfig";
import { Button } from "../Button";

// Gated by config.caller_permissions, never by role/product features
// alone (CONTRACTS.md §8's own "caller_permissions" rule). Sharing is
// policy-driven (product correction, 2026-09-27): can_share reflects the
// org's own who_can_share policy (default "all_users") OR
// marketplace:provision, resolved server-side
// (config_service.get_effective_config()) -- never inferred from role
// client-side. "org"/"required" (org-wide provisioning) stay
// marketplace:provision-only, a separate, stricter tier.
const BASE_SCOPES = [{
  value: "private",
  label: "Just me"
}];
const SHARE_SCOPE = {
  value: "shared",
  label: "Share with teammates"
};
const PROVISION_SCOPES = [{
  value: "org",
  label: "Everyone in org"
}, {
  value: "required",
  label: "Required (can't be removed)"
}];
export function AddDialog({
  item,
  versionId,
  defaultSurfaces,
  onClose,
  onInstalled
}) {
  const client = useEcosystemClient();
  const config = useConfig();
  const installScopes = [...BASE_SCOPES, ...(config.caller_permissions.can_share ? [SHARE_SCOPE] : []), ...(config.caller_permissions.can_provision ? PROVISION_SCOPES : [])];
  const hasScopeChoice = installScopes.length > 1;
  const [scope, setScope] = useState("private");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  // "org"/"required" land in Yours.tsx's "Org provisioned"/"Required"
  // groups (GROUP_ORDER, keyed by origin) rather than "Added from
  // Discover" -- matching what the scope choice actually represents.
  // "private"/"shared" keep the existing "added" origin unchanged.
  const originFor = s => s === "org" ? "provisioned" : s === "required" ? "required" : "added";
  const handleAdd = () => {
    setSubmitting(true);
    setError(null);
    const idempotencyKey = `install-${item.id}-${Date.now()}`;
    client.install(item.id, {
      version_id: versionId,
      surfaces: defaultSurfaces,
      scope,
      origin: originFor(scope)
    }, idempotencyKey).then(() => {
      onInstalled();
      onClose();
    }).catch(e => setError(e instanceof Error ? e.message : "Failed to add this item.")).finally(() => setSubmitting(false));
  };
  return <div data-testid="add-dialog" role="dialog" aria-modal="true" className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-start justify-center overflow-y-auto py-10 px-4 z-[100]">
      {/* items-start + the overlay's own overflow-y-auto (rather than
          centering) is deliberate: a centered flex child taller than the
          viewport gets its top clipped with no way to scroll to it in some
          browsers -- top-aligned content in a scrollable container never has
          that problem, at the minor cost of not being perfectly vertically
          centered when it's short enough to fit. */}
      <div className="bg-white rounded-lg shadow-xl w-[420px] flex-shrink-0 overflow-hidden">
        {/* Header/body/footer split (user-flow QA round, 2026-10-03) to match
            ai-ui's own ConfirmDialog (DialogProvider.jsx): a bold title row
            with an explicit close button, rather than relying on "Cancel"
            alone to dismiss. */}
        <div className="flex items-start justify-between px-6 pt-6 pb-4">
          <h3 className="m-0 text-base font-semibold text-gray-900">Add {item.display_name}</h3>
          <button type="button" aria-label="Close" onClick={onClose} className="inline-flex p-1 ml-2 rounded-md border-none bg-none text-gray-400 hover:bg-gray-100 hover:text-gray-700 cursor-pointer transition-colors">
            <XMarkIcon width={18} height={18} aria-hidden="true" />
          </button>
        </div>

        <div className="px-6 pb-6">
          {item.latest_verdict === "warn" && <div data-testid="add-dialog-warning-banner" className="bg-amber-50 text-amber-700 p-2 rounded-md mb-4 text-sm">
              This item passed verification with a warning. Review the Verification tab before adding it.
            </div>}

          {hasScopeChoice && <fieldset className="border-none p-0 mb-4">
              <legend className="text-sm text-gray-500 p-0">Scope</legend>
              {installScopes.map(s => <label key={s.value} className="flex items-center gap-1.5 text-sm text-gray-900">
                  <input type="radio" name="scope" value={s.value} checked={scope === s.value} onChange={() => setScope(s.value)} />
                  {s.label}
                </label>)}
            </fieldset>}

          {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
        </div>

        {/* Footer band (surface bg + top border), matching ai-ui's own
            ConfirmDialog footer instead of buttons floating with no
            separation from the body. */}
        <div className="flex justify-end gap-2 px-6 py-4 bg-gray-50 border-t border-gray-200">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button variant="primary" data-testid="add-dialog-confirm" loading={submitting} onClick={handleAdd}>
            {submitting ? "Adding…" : hasScopeChoice ? "Add" : "Continue"}
          </Button>
        </div>
      </div>
    </div>;
}