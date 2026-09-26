// SPDX-License-Identifier: MIT
// Task F-7: rollback calls installs_service.rollback (B-10) -- immutable
// version rows, "Edit" always creates a new version, never mutates one in
// place (CONFIG_AND_PRODUCTS.md §7 item 11).
import { useEffect, useState } from "react";
import type { ItemVersion } from "../../types";
import { useEcosystemClient } from "../../context/HostContext";
import { VerdictBadge } from "../Badges";

export function Versions({ itemId, installId, canRollback }: { itemId: string; installId: string | null; canRollback: boolean }) {
  const client = useEcosystemClient();
  const [versions, setVersions] = useState<ItemVersion[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    client.getVersions(itemId).then((v) => { if (!cancelled) setVersions(v); });
    return () => { cancelled = true; };
  }, [client, itemId]);

  if (versions === null) return <div data-testid="detail-tab-versions-loading">Loading versions…</div>;

  return (
    <div data-testid="detail-tab-versions">
      {versions.map((v) => (
        <div key={v.id} data-testid="version-row" style={{ display: "flex", alignItems: "center", gap: "var(--eco-space-sm)", padding: "var(--eco-space-sm) 0", borderBottom: "1px solid var(--eco-color-border)" }}>
          <span style={{ fontFamily: "monospace", color: "var(--eco-color-textPrimary)" }}>{v.version}</span>
          {v.is_current && <span style={{ fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-accentSkill)" }}>current</span>}
          <VerdictBadge verdict={v.gate_verdict} />
          <span style={{ marginLeft: "auto", fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textMuted)" }}>
            {v.created_at ? new Date(v.created_at).toLocaleDateString() : ""}
          </span>
          {!v.is_current && canRollback && installId && (
            <button
              type="button"
              data-testid="rollback-button"
              onClick={() => client.rollbackInstall(installId, v.id)}
              style={{ background: "none", border: "1px solid var(--eco-color-border)", borderRadius: "var(--eco-radius-sm)", cursor: "pointer", fontSize: "var(--eco-font-sizeXs)" }}
            >
              Roll back to this version
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
