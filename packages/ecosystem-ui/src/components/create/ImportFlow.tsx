// SPDX-License-Identifier: MIT
// Task F-9: Import flow (new -- no merged-frontend precedent to port).
// Backs /marketplace/:typeSlug/import. Only github_repo/well_known have
// real server-side adapters (task I, pre-M3) -- every other SourceKind
// value still 501s server-side (create_service.create_via_import()'s own
// disclosed NotImplementedError for kinds beyond those two), so this form
// only offers the two working kinds rather than exposing dead options.
import { useState } from "react";
import type { CreateImportPayload, ItemType } from "../../types";
import { useEcosystemClient } from "../../context/HostContext";
import { useConfig } from "../../hooks/useEcosystemConfig";

const IMPORT_KINDS: Array<{ value: "github_repo" | "well_known"; label: string; refHint: string }> = [
  { value: "github_repo", label: "GitHub repository", refHint: "owner/repo or owner/repo@branch" },
  { value: "well_known", label: "Well-known index entry", refHint: "domain/skill_slug" },
];

export function ImportFlow({ itemType, onImported, onCancel }: {
  itemType: ItemType; onImported: (itemId: string) => void; onCancel: () => void;
}) {
  const client = useEcosystemClient();
  const config = useConfig();
  const [kind, setKind] = useState<"github_repo" | "well_known">("github_repo");
  const [ref, setRef] = useState("");
  const [namespace, setNamespace] = useState("");
  const [category, setCategory] = useState(config.taxonomy.categories[0] ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [blockedReason, setBlockedReason] = useState<string | null>(null);

  const selectedKind = IMPORT_KINDS.find((k) => k.value === kind)!;
  const canSubmit = ref.trim().length > 0 && namespace.includes("/");

  const handleSubmit = () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    setBlockedReason(null);
    const payload: CreateImportPayload = { create_via: "import", item_type: itemType, namespace, category, kind, ref };
    client.createItem(payload, `import-${namespace}-${Date.now()}`)
      .then((result) => onImported(result.item_id))
      .catch((e: unknown) => {
        const code = (e as { code?: string })?.code;
        if (code === "LICENSE_NOT_ALLOWED") {
          setBlockedReason("The source's declared license isn't MIT/Apache-2.0-compatible -- rejected before fetching any content.");
        } else {
          setError(e instanceof Error ? e.message : "Couldn't import from this source.");
        }
      })
      .finally(() => setSubmitting(false));
  };

  return (
    <div data-testid="import-flow" style={{ maxWidth: "560px" }}>
      <h2 style={{ color: "var(--eco-color-textPrimary)" }}>Import a {itemType}</h2>

      <div style={{ marginBottom: "var(--eco-space-md)" }}>
        <label style={{ display: "block", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)", marginBottom: "4px" }}>Source</label>
        <select data-testid="import-kind" value={kind} onChange={(e) => setKind(e.target.value as "github_repo" | "well_known")} style={{ width: "100%", padding: "8px", borderRadius: "var(--eco-radius-sm)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)" }}>
          {IMPORT_KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
        </select>
      </div>

      <div style={{ marginBottom: "var(--eco-space-md)" }}>
        <label style={{ display: "block", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)", marginBottom: "4px" }}>Reference</label>
        <input data-testid="import-ref" value={ref} onChange={(e) => setRef(e.target.value)} placeholder={selectedKind.refHint} style={{ width: "100%", padding: "8px", borderRadius: "var(--eco-radius-sm)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)" }} />
      </div>

      <div style={{ marginBottom: "var(--eco-space-md)" }}>
        <label style={{ display: "block", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)", marginBottom: "4px" }}>Namespace (publisher/name)</label>
        <input data-testid="import-namespace" value={namespace} onChange={(e) => setNamespace(e.target.value)} placeholder="acme/imported-tool" style={{ width: "100%", padding: "8px", borderRadius: "var(--eco-radius-sm)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)" }} />
      </div>

      <div style={{ marginBottom: "var(--eco-space-md)" }}>
        <label style={{ display: "block", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)", marginBottom: "4px" }}>Category</label>
        <select data-testid="import-category" value={category} onChange={(e) => setCategory(e.target.value)} style={{ width: "100%", padding: "8px", borderRadius: "var(--eco-radius-sm)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)" }}>
          {config.taxonomy.categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      {error && <p role="alert" style={{ color: "var(--eco-color-danger)", fontSize: "var(--eco-font-sizeSm)" }}>{error}</p>}
      {blockedReason && (
        <div data-testid="import-blocked-banner" role="alert" style={{ background: "var(--eco-color-dangerBg)", color: "var(--eco-color-danger)", padding: "var(--eco-space-sm)", borderRadius: "var(--eco-radius-md)" }}>
          {blockedReason}
        </div>
      )}

      <div style={{ display: "flex", gap: "var(--eco-space-sm)", marginTop: "var(--eco-space-md)" }}>
        <button type="button" onClick={onCancel} style={{ padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", cursor: "pointer" }}>Cancel</button>
        <button
          type="button" data-testid="import-submit" disabled={!canSubmit || submitting} onClick={handleSubmit}
          style={{ padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "none", background: "var(--eco-color-accentSkill)", color: "var(--eco-color-accentSkillText)", cursor: "pointer" }}
        >
          {submitting ? "Importing…" : "Import"}
        </button>
      </div>
    </div>
  );
}
