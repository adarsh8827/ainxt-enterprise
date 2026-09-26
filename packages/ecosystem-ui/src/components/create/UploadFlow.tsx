// SPDX-License-Identifier: MIT
// Task F-9: Upload flow -- ported UX from the merged frontend's
// SkillUploadPage (drag-and-drop, per-file validation, zip/.skill preview)
// with mandatory-license validation added. Calls POST /ecosystem/items/upload
// (task B-6) -- server-side unzip/path-traversal/zip-bomb guards are the
// real enforcement; this client-side check is only a fast, friendly
// pre-flight, never trusted as the actual validation.
import { useRef, useState, type DragEvent } from "react";
import type { ItemType } from "../../types";
import { useEcosystemClient } from "../../context/HostContext";
import { useConfig } from "../../hooks/useEcosystemConfig";

const MAX_SIZE_BYTES = 5 * 1024 * 1024;

export function UploadFlow({ itemType, onUploaded, onCancel }: {
  itemType: ItemType; onUploaded: (itemId: string) => void; onCancel: () => void;
}) {
  const client = useEcosystemClient();
  const config = useConfig();
  const [file, setFile] = useState<File | null>(null);
  const [namespace, setNamespace] = useState("");
  const [category, setCategory] = useState(config.taxonomy.categories[0] ?? "");
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [blockedReason, setBlockedReason] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const validateAndSetFile = (candidate: File) => {
    setError(null);
    if (!candidate.name.endsWith(".zip") && !candidate.name.endsWith(".skill")) {
      setError("Only .zip or .skill bundles are accepted.");
      return;
    }
    if (candidate.size > MAX_SIZE_BYTES) {
      setError(`Archive exceeds the ${MAX_SIZE_BYTES / 1024 / 1024}MB limit.`);
      return;
    }
    setFile(candidate);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) validateAndSetFile(dropped);
  };

  const handleSubmit = () => {
    if (!file || !namespace.includes("/")) return;
    setSubmitting(true);
    setError(null);
    setBlockedReason(null);
    const form = new FormData();
    form.append("file", file);
    form.append("item_type", itemType);
    form.append("namespace", namespace);
    form.append("category", category);
    client.uploadItem(form, `upload-${namespace}-${Date.now()}`)
      .then((result) => onUploaded(result.item_id))
      .catch((e: unknown) => {
        const code = (e as { code?: string })?.code;
        if (code === "LICENSE_NOT_ALLOWED") {
          setBlockedReason("This bundle's declared license isn't MIT/Apache-2.0-compatible and can't be uploaded.");
        } else {
          setError(e instanceof Error ? e.message : "Couldn't upload this bundle.");
        }
      })
      .finally(() => setSubmitting(false));
  };

  return (
    <div data-testid="upload-flow" style={{ maxWidth: "560px" }}>
      <h2 style={{ color: "var(--eco-color-textPrimary)" }}>Upload a {itemType}</h2>

      <div
        data-testid="upload-dropzone"
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        style={{
          border: `2px dashed ${dragging ? "var(--eco-color-accentSkill)" : "var(--eco-color-border)"}`,
          borderRadius: "var(--eco-radius-lg)", padding: "var(--eco-space-xl)", textAlign: "center",
          cursor: "pointer", color: "var(--eco-color-textSecondary)",
        }}
      >
        {file ? <span data-testid="upload-filename">{file.name}</span> : "Drag a .zip/.skill bundle here, or click to browse"}
        <input
          ref={inputRef} type="file" accept=".zip,.skill" hidden
          onChange={(e) => { const f = e.target.files?.[0]; if (f) validateAndSetFile(f); }}
        />
      </div>

      {error && <p role="alert" style={{ color: "var(--eco-color-danger)", fontSize: "var(--eco-font-sizeSm)" }}>{error}</p>}

      {blockedReason && (
        <div data-testid="upload-blocked-banner" role="alert" style={{ background: "var(--eco-color-dangerBg)", color: "var(--eco-color-danger)", padding: "var(--eco-space-sm)", borderRadius: "var(--eco-radius-md)", marginTop: "var(--eco-space-sm)" }}>
          {blockedReason}
        </div>
      )}

      <div style={{ marginTop: "var(--eco-space-md)" }}>
        <label style={{ display: "block", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)", marginBottom: "4px" }}>Namespace (publisher/name)</label>
        <input data-testid="upload-namespace" value={namespace} onChange={(e) => setNamespace(e.target.value)} placeholder="acme/my-skill" style={{ width: "100%", padding: "8px", borderRadius: "var(--eco-radius-sm)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)" }} />
      </div>

      <div style={{ marginTop: "var(--eco-space-md)" }}>
        <label style={{ display: "block", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)", marginBottom: "4px" }}>Category</label>
        <select data-testid="upload-category" value={category} onChange={(e) => setCategory(e.target.value)} style={{ width: "100%", padding: "8px", borderRadius: "var(--eco-radius-sm)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)" }}>
          {config.taxonomy.categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      <div style={{ display: "flex", gap: "var(--eco-space-sm)", marginTop: "var(--eco-space-md)" }}>
        <button type="button" onClick={onCancel} style={{ padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", cursor: "pointer" }}>Cancel</button>
        <button
          type="button" data-testid="upload-submit" disabled={!file || !namespace.includes("/") || submitting} onClick={handleSubmit}
          style={{ padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "none", background: "var(--eco-color-accentSkill)", color: "var(--eco-color-accentSkillText)", cursor: "pointer" }}
        >
          {submitting ? "Uploading…" : "Upload"}
        </button>
      </div>
    </div>
  );
}
