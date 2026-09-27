// SPDX-License-Identifier: MIT
// Task F-7 (M5 UI-parity review, item A4 follow-up): scope + surface
// toggles + an inline warning-finding banner (shown when the item's
// latest verdict is 'warn' -- a 'fail' verdict never reaches this dialog
// at all, since 'install' is absent from allowed_actions for a blocked
// item, per items_service.compute_allowed_actions()).
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
import type { ItemDetail, InstallScope } from "../../types";
import { useEcosystemClient } from "../../context/HostContext";
import { useConfig } from "../../hooks/useEcosystemConfig";
import { SurfaceToggles } from "../SurfaceToggles";

// Gated by config.caller_permissions, never by role/product features
// alone (CONTRACTS.md §8's own "caller_permissions" rule) -- "shared"
// needs marketplace:share, "org"/"required" need marketplace:provision.
// "org"/"required" are additionally admin-only *by design*, matching the
// reference mock's own "Admins only" framing for that option.
const BASE_SCOPES: Array<{ value: InstallScope; label: string }> = [
  { value: "private", label: "Just me" },
];
const SHARE_SCOPE: { value: InstallScope; label: string } = { value: "shared", label: "Share with teammates" };
const PROVISION_SCOPES: Array<{ value: InstallScope; label: string }> = [
  { value: "org", label: "Everyone in org" },
  { value: "required", label: "Required (can't be removed)" },
];

export function AddDialog({ item, versionId, defaultSurfaces, onClose, onInstalled }: {
  item: ItemDetail; versionId: string; defaultSurfaces: string[];
  onClose: () => void; onInstalled: () => void;
}) {
  const client = useEcosystemClient();
  const config = useConfig();
  const installScopes: Array<{ value: InstallScope; label: string }> = [
    ...BASE_SCOPES,
    ...(config.caller_permissions.can_share ? [SHARE_SCOPE] : []),
    ...(config.caller_permissions.can_provision ? PROVISION_SCOPES : []),
  ];
  const hasScopeChoice = installScopes.length > 1;
  const [scope, setScope] = useState<InstallScope>("private");
  const [surfaces, setSurfaces] = useState<string[]>(defaultSurfaces);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // "org"/"required" land in Yours.tsx's "Org provisioned"/"Required"
  // groups (GROUP_ORDER, keyed by origin) rather than "Added from
  // Discover" -- matching what the scope choice actually represents.
  // "private"/"shared" keep the existing "added" origin unchanged.
  const originFor = (s: InstallScope): string => (s === "org" ? "provisioned" : s === "required" ? "required" : "added");

  const handleAdd = () => {
    setSubmitting(true);
    setError(null);
    const idempotencyKey = `install-${item.id}-${Date.now()}`;
    client.install(item.id, { version_id: versionId, surfaces, scope, origin: originFor(scope) }, idempotencyKey)
      .then(() => { onInstalled(); onClose(); })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to add this item."))
      .finally(() => setSubmitting(false));
  };

  return (
    <div
      data-testid="add-dialog"
      role="dialog"
      aria-modal="true"
      style={{ position: "fixed", inset: 0, background: "var(--eco-color-overlay)", display: "flex", alignItems: "flex-start", justifyContent: "center", overflowY: "auto", padding: "40px 16px", zIndex: 100 }}
    >
      {/* alignItems:"flex-start" + the overlay's own overflowY:"auto" (rather
          than centering) is deliberate: a centered flex child taller than the
          viewport gets its top clipped with no way to scroll to it in some
          browsers -- top-aligned content in a scrollable container never has
          that problem, at the minor cost of not being perfectly vertically
          centered when it's short enough to fit. */}
      <div style={{ background: "var(--eco-color-bg)", borderRadius: "var(--eco-radius-lg)", padding: "var(--eco-space-lg)", width: "420px", flexShrink: 0 }}>
        <h3 style={{ marginTop: 0, color: "var(--eco-color-textPrimary)" }}>Add {item.display_name}</h3>

        {item.latest_verdict === "warn" && (
          <div data-testid="add-dialog-warning-banner" style={{ background: "var(--eco-color-warningBg)", color: "var(--eco-color-warning)", padding: "var(--eco-space-sm)", borderRadius: "var(--eco-radius-md)", marginBottom: "var(--eco-space-md)", fontSize: "var(--eco-font-sizeSm)" }}>
            This item passed verification with a warning. Review the Verification tab before adding it.
          </div>
        )}

        {hasScopeChoice && (
          <>
            <fieldset style={{ border: "none", padding: 0, marginBottom: "var(--eco-space-md)" }}>
              <legend style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)", padding: 0 }}>Scope</legend>
              {installScopes.map((s) => (
                <label key={s.value} style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textPrimary)" }}>
                  <input type="radio" name="scope" value={s.value} checked={scope === s.value} onChange={() => setScope(s.value)} />
                  {s.label}
                </label>
              ))}
            </fieldset>

            <div style={{ marginBottom: "var(--eco-space-md)" }}>
              <div style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)", marginBottom: "4px" }}>Surfaces</div>
              <SurfaceToggles enabledSurfaces={surfaces} onChange={setSurfaces} />
            </div>
          </>
        )}

        {error && <p role="alert" style={{ color: "var(--eco-color-danger)", fontSize: "var(--eco-font-sizeSm)" }}>{error}</p>}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: "var(--eco-space-sm)" }}>
          <button type="button" onClick={onClose} style={{ padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", cursor: "pointer" }}>
            Cancel
          </button>
          <button
            type="button"
            data-testid="add-dialog-confirm"
            disabled={submitting}
            onClick={handleAdd}
            style={{ padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "none", background: "var(--eco-color-accentSkill)", color: "var(--eco-color-accentSkillText)", cursor: "pointer" }}
          >
            {submitting ? "Adding…" : hasScopeChoice ? "Add" : "Continue"}
          </button>
        </div>
      </div>
    </div>
  );
}
