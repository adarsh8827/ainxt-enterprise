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
  // Tiered license policy (ECOSYSTEM_PLAN.md §11.2, Tier 3) -- a private
  // upload with a disallowed/missing license isn't a dead end any more;
  // it needs one more explicit confirmation, not a second full submit.
  const [ackReason, setAckReason] = useState<"acknowledgement_required" | "missing_license" | null>(null);
  const [licenseAcknowledged, setLicenseAcknowledged] = useState(false);
  const [selfAuthored, setSelfAuthored] = useState(false);
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
    // Only sent once the caller has actually confirmed one of these --
    // never sent true just because the fields exist and are unchecked.
    if (licenseAcknowledged) form.append("license_acknowledged", "true");
    if (selfAuthored) form.append("self_authored", "true");
    client.uploadItem(form, `upload-${namespace}-${Date.now()}`)
      .then((result) => { setAckReason(null); onUploaded(result.item_id); })
      .catch((e: unknown) => {
        const code = (e as { code?: string })?.code;
        const reason = (e as { details?: { reason?: string } })?.details?.reason;
        if (code === "LICENSE_ACKNOWLEDGEMENT_REQUIRED") {
          setAckReason(reason === "missing_license" ? "missing_license" : "acknowledgement_required");
        } else if (code === "LICENSE_NOT_ALLOWED") {
          setBlockedReason("This bundle's declared license isn't MIT/Apache-2.0-compatible and can't be uploaded.");
        } else if (code === "LICENSE_NOT_ALLOWED_BY_ORG_POLICY") {
          setBlockedReason("This bundle's declared license isn't on this org's allowed list and can't be uploaded here.");
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

      {ackReason === "acknowledgement_required" && (
        <div data-testid="upload-ack-prompt" role="alert" style={{ background: "var(--eco-color-warningBg)", color: "var(--eco-color-textPrimary)", padding: "var(--eco-space-sm)", borderRadius: "var(--eco-radius-md)", marginTop: "var(--eco-space-sm)" }}>
          <p style={{ margin: "0 0 6px" }}>This bundle's declared license isn't MIT/Apache-2.0-compatible. You can still save it to your own private space, but you're responsible for complying with its license.</p>
          <label style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <input type="checkbox" data-testid="upload-license-acknowledge" checked={licenseAcknowledged} onChange={(e) => setLicenseAcknowledged(e.target.checked)} />
            I'm responsible for complying with this license
          </label>
        </div>
      )}

      {ackReason === "missing_license" && (
        <div data-testid="upload-ack-prompt" role="alert" style={{ background: "var(--eco-color-warningBg)", color: "var(--eco-color-textPrimary)", padding: "var(--eco-space-sm)", borderRadius: "var(--eco-radius-md)", marginTop: "var(--eco-space-sm)" }}>
          <p style={{ margin: "0 0 6px" }}>This bundle's SKILL.md doesn't declare a license.</p>
          <label style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <input type="checkbox" data-testid="upload-self-authored" checked={selfAuthored} onChange={(e) => setSelfAuthored(e.target.checked)} />
            This is self-authored — default its license to MIT
          </label>
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
          type="button" data-testid="upload-submit"
          disabled={
            !file || !namespace.includes("/") || submitting
            || (ackReason === "acknowledgement_required" && !licenseAcknowledged)
            || (ackReason === "missing_license" && !selfAuthored)
          }
          onClick={handleSubmit}
          style={{ padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "none", background: "var(--eco-color-accentSkill)", color: "var(--eco-color-accentSkillText)", cursor: "pointer" }}
        >
          {submitting ? "Uploading…" : "Upload"}
        </button>
      </div>
    </div>
  );
}
