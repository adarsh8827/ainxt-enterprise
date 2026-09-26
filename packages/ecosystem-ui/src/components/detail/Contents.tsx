// SPDX-License-Identifier: MIT
// Renders the pinned version's manifest -- instructions body + any
// declared bundled files. No execution happens here; this is a read-only
// view (skill_view/read_skill_file, task B-15, are the runtime path).
import type { ItemDetail } from "../../types";

export function Contents({ item }: { item: ItemDetail }) {
  const manifest = item.manifest as { instructions?: string; files?: Record<string, string> };
  return (
    <div data-testid="detail-tab-contents">
      <h4 style={{ color: "var(--eco-color-textPrimary)" }}>Instructions</h4>
      <pre style={{ whiteSpace: "pre-wrap", background: "var(--eco-color-surface)", padding: "var(--eco-space-md)", borderRadius: "var(--eco-radius-md)", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textPrimary)" }}>
        {manifest.instructions ?? "No instructions declared."}
      </pre>
      {manifest.files && Object.keys(manifest.files).length > 0 && (
        <>
          <h4 style={{ color: "var(--eco-color-textPrimary)" }}>Bundled files</h4>
          <ul>
            {Object.keys(manifest.files).map((path) => (
              <li key={path} style={{ fontFamily: "monospace", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}>{path}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
