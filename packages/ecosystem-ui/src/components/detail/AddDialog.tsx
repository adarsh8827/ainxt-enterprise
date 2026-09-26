// SPDX-License-Identifier: MIT
// Task F-7: scope + surface toggles + an inline warning-finding banner
// (shown when the item's latest verdict is 'warn' -- a 'fail' verdict
// never reaches this dialog at all, since 'install' is absent from
// allowed_actions for a blocked item, per items_service.compute_allowed_actions()).
import { useState } from "react";
import type { ItemDetail } from "../../types";
import { useEcosystemClient } from "../../context/HostContext";
import { SurfaceToggles } from "../SurfaceToggles";

const INSTALL_SCOPES: Array<{ value: "private" | "shared" | "org"; label: string }> = [
  { value: "private", label: "Just me" },
  { value: "shared", label: "Share with teammates" },
  { value: "org", label: "Everyone in org" },
];

export function AddDialog({ item, versionId, defaultSurfaces, onClose, onInstalled }: {
  item: ItemDetail; versionId: string; defaultSurfaces: string[];
  onClose: () => void; onInstalled: () => void;
}) {
  const client = useEcosystemClient();
  const [scope, setScope] = useState<"private" | "shared" | "org">("private");
  const [surfaces, setSurfaces] = useState<string[]>(defaultSurfaces);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAdd = () => {
    setSubmitting(true);
    setError(null);
    const idempotencyKey = `install-${item.id}-${Date.now()}`;
    client.install(item.id, { version_id: versionId, surfaces, scope, origin: "added" }, idempotencyKey)
      .then(() => { onInstalled(); onClose(); })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to add this item."))
      .finally(() => setSubmitting(false));
  };

  return (
    <div
      data-testid="add-dialog"
      role="dialog"
      aria-modal="true"
      style={{ position: "fixed", inset: 0, background: "var(--eco-color-overlay)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}
    >
      <div style={{ background: "var(--eco-color-bg)", borderRadius: "var(--eco-radius-lg)", padding: "var(--eco-space-lg)", width: "420px" }}>
        <h3 style={{ marginTop: 0, color: "var(--eco-color-textPrimary)" }}>Add {item.display_name}</h3>

        {item.latest_verdict === "warn" && (
          <div data-testid="add-dialog-warning-banner" style={{ background: "var(--eco-color-warningBg)", color: "var(--eco-color-warning)", padding: "var(--eco-space-sm)", borderRadius: "var(--eco-radius-md)", marginBottom: "var(--eco-space-md)", fontSize: "var(--eco-font-sizeSm)" }}>
            This item passed verification with a warning. Review the Verification tab before adding it.
          </div>
        )}

        <fieldset style={{ border: "none", padding: 0, marginBottom: "var(--eco-space-md)" }}>
          <legend style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)", padding: 0 }}>Scope</legend>
          {INSTALL_SCOPES.map((s) => (
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
            {submitting ? "Adding…" : "Add"}
          </button>
        </div>
      </div>
    </div>
  );
}
