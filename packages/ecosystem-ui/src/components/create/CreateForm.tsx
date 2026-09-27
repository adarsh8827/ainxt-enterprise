// SPDX-License-Identifier: MIT
// Task F-9: Write flow -- ported UX from the merged frontend's
// SkillFormPage (ai-ui/src/components/Marketplace.jsx's inline component
// at the time of porting), with a mandatory license field added (MIT
// default, CONFIG_AND_PRODUCTS.md §7 item 5). Calls create_service's real
// endpoint (task B-6) via POST /ecosystem/items -- never localStorage.
import { useState, type CSSProperties, type ReactNode } from "react";
import type { CreateWritePayload, ItemType, ProvisionScope } from "../../types";
import { useEcosystemClient } from "../../context/HostContext";
import { useConfig } from "../../hooks/useEcosystemConfig";
import { LineNumberedTextarea } from "./LineNumberedTextarea";

const ALLOWED_LICENSES = ["MIT", "Apache-2.0"];

export function CreateForm({ itemType, onCreated, onCancel, canProvision }: {
  itemType: ItemType; onCreated: (itemId: string) => void; onCancel: () => void; canProvision: boolean;
}) {
  const client = useEcosystemClient();
  const config = useConfig();
  const [namespace, setNamespace] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState(config.taxonomy.categories[0] ?? "");
  const [license, setLicense] = useState("MIT");
  const [instructions, setInstructions] = useState("");
  const [files, setFiles] = useState<Array<{ name: string; content: string }>>([]);
  const [provisionScope, setProvisionScope] = useState<ProvisionScope>("private");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [licenseAcknowledged, setLicenseAcknowledged] = useState(false);
  const [selfAuthored, setSelfAuthored] = useState(false);
  // Tiered license policy (ECOSYSTEM_PLAN.md §11.2): "Just me" (private,
  // the default) may declare any license via free text -- Tier 3 handles
  // it server-side. Any other provisionScope stays on the strict
  // MIT/Apache-2.0-only dropdown, since Tier 2's org-approved list isn't
  // something this generic form fetches/surfaces (server still enforces
  // it either way -- this is a client-side hint, not the real gate).
  const isPrivate = provisionScope === "private";
  const [customLicense, setCustomLicense] = useState(false);

  const licenseAllowed = ALLOWED_LICENSES.includes(license);
  const needsAcknowledgement = isPrivate && customLicense && license.trim() && !licenseAllowed;
  const needsSelfAuthored = isPrivate && customLicense && !license.trim();
  const licenseGateSatisfied = isPrivate
    ? (licenseAllowed || (needsAcknowledgement ? licenseAcknowledged : needsSelfAuthored ? selfAuthored : true))
    : licenseAllowed;
  const canSubmit = namespace.includes("/") && displayName.trim() && description.trim() && instructions.trim() && licenseGateSatisfied;

  const handleAddFile = () => setFiles((f) => [...f, { name: `file-${f.length + 1}.md`, content: "" }]);
  const handleFileChange = (index: number, field: "name" | "content", value: string) => {
    setFiles((f) => f.map((file, i) => (i === index ? { ...file, [field]: value } : file)));
  };
  const handleRemoveFile = (index: number) => setFiles((f) => f.filter((_, i) => i !== index));

  const handleSubmit = () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    const payload: CreateWritePayload = {
      create_via: "write", item_type: itemType, namespace, display_name: displayName,
      description, category, license, content: { instructions, files },
      surfaces: ["chat"],
      ...(canProvision && provisionScope !== "private" ? { provision_scope: provisionScope } : {}),
      ...(needsAcknowledgement ? { license_acknowledged: licenseAcknowledged } : {}),
      ...(needsSelfAuthored ? { self_authored: selfAuthored } : {}),
    };
    client.createItem(payload, `create-${namespace}-${Date.now()}`)
      .then((result) => onCreated(result.item_id))
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't create this item."))
      .finally(() => setSubmitting(false));
  };

  return (
    <div data-testid="create-form" style={{ maxWidth: "640px" }}>
      <h2 style={{ color: "var(--eco-color-textPrimary)" }}>Write a new {itemType}</h2>

      <Field label="Namespace (publisher/name)">
        <input data-testid="create-form-namespace" value={namespace} onChange={(e) => setNamespace(e.target.value)} placeholder="acme/my-skill" style={inputStyle} />
      </Field>
      <Field label="Display name">
        <input data-testid="create-form-display-name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} style={inputStyle} />
      </Field>
      <Field label="Description">
        <input data-testid="create-form-description" value={description} onChange={(e) => setDescription(e.target.value)} style={inputStyle} />
      </Field>
      <Field label="Category">
        <select data-testid="create-form-category" value={category} onChange={(e) => setCategory(e.target.value)} style={inputStyle}>
          {config.taxonomy.categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </Field>
      <Field label="License">
        {customLicense ? (
          <input
            data-testid="create-form-license-custom" value={license}
            onChange={(e) => { setLicense(e.target.value); setLicenseAcknowledged(false); setSelfAuthored(false); }}
            placeholder="e.g. GPL-3.0-only, or leave blank" style={inputStyle}
          />
        ) : (
          <select data-testid="create-form-license" value={license} onChange={(e) => setLicense(e.target.value)} style={inputStyle}>
            {ALLOWED_LICENSES.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        )}
        {isPrivate && (
          <button
            type="button" data-testid="create-form-license-toggle-custom"
            onClick={() => { setCustomLicense((v) => !v); setLicense(customLicense ? "MIT" : license); }}
            style={{ background: "none", border: "none", color: "var(--eco-color-accentSkill)", cursor: "pointer", fontSize: "var(--eco-font-sizeXs)", padding: "4px 0" }}
          >
            {customLicense ? "Use MIT/Apache-2.0 instead" : "This item uses a different license"}
          </button>
        )}
        {!isPrivate && !licenseAllowed && (
          <p role="alert" style={{ color: "var(--eco-color-danger)", fontSize: "var(--eco-font-sizeXs)" }}>Only MIT/Apache-2.0-compatible licenses are allowed.</p>
        )}
        {needsAcknowledgement && (
          <div data-testid="create-form-license-ack-prompt" style={{ marginTop: "6px" }}>
            <p style={{ margin: "0 0 6px", fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textSecondary)" }}>
              {license} isn't MIT/Apache-2.0-compatible. You can still save it to your own private space.
            </p>
            <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "var(--eco-font-sizeXs)" }}>
              <input type="checkbox" data-testid="create-form-license-acknowledge" checked={licenseAcknowledged} onChange={(e) => setLicenseAcknowledged(e.target.checked)} />
              I'm responsible for complying with this license
            </label>
          </div>
        )}
        {needsSelfAuthored && (
          <div data-testid="create-form-license-self-authored-prompt" style={{ marginTop: "6px" }}>
            <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "var(--eco-font-sizeXs)" }}>
              <input type="checkbox" data-testid="create-form-license-self-authored" checked={selfAuthored} onChange={(e) => setSelfAuthored(e.target.checked)} />
              This is self-authored — default its license to MIT
            </label>
          </div>
        )}
      </Field>
      <Field label="Instructions">
        <LineNumberedTextarea value={instructions} onChange={setInstructions} placeholder="What should the model do when this skill is invoked?" />
      </Field>

      <Field label="Supporting files">
        {files.map((file, i) => (
          <div key={i} style={{ display: "flex", gap: "var(--eco-space-sm)", marginBottom: "var(--eco-space-sm)" }}>
            <input value={file.name} onChange={(e) => handleFileChange(i, "name", e.target.value)} style={{ ...inputStyle, width: "160px" }} />
            <textarea value={file.content} onChange={(e) => handleFileChange(i, "content", e.target.value)} rows={2} style={{ ...inputStyle, flex: 1 }} />
            <button type="button" onClick={() => handleRemoveFile(i)} style={{ background: "none", border: "none", color: "var(--eco-color-danger)", cursor: "pointer" }}>Remove</button>
          </div>
        ))}
        <button type="button" data-testid="create-form-add-file" onClick={handleAddFile} style={{ background: "none", border: "1px dashed var(--eco-color-border)", borderRadius: "var(--eco-radius-md)", padding: "6px 12px", cursor: "pointer", color: "var(--eco-color-textSecondary)" }}>
          + Add file
        </button>
      </Field>

      {canProvision && (
        <Field label="Who should get this by default?">
          <select data-testid="create-form-provision-scope" value={provisionScope} onChange={(e) => setProvisionScope(e.target.value as ProvisionScope)} style={inputStyle}>
            <option value="private">Just me</option>
            <option value="org_default_on">Everyone in org (default-on)</option>
            <option value="required">Required</option>
          </select>
        </Field>
      )}

      {error && <p role="alert" style={{ color: "var(--eco-color-danger)" }}>{error}</p>}

      <div style={{ display: "flex", gap: "var(--eco-space-sm)", marginTop: "var(--eco-space-md)" }}>
        <button type="button" onClick={onCancel} style={secondaryButtonStyle}>Cancel</button>
        <button type="button" data-testid="create-form-submit" disabled={!canSubmit || submitting} onClick={handleSubmit} style={primaryButtonStyle}>
          {submitting ? "Creating…" : "Create"}
        </button>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={{ marginBottom: "var(--eco-space-md)" }}>
      <label style={{ display: "block", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)", marginBottom: "4px" }}>{label}</label>
      {children}
    </div>
  );
}

const inputStyle: CSSProperties = {
  width: "100%", padding: "8px", borderRadius: "var(--eco-radius-sm)", border: "1px solid var(--eco-color-border)",
  background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)", fontSize: "var(--eco-font-sizeSm)",
};
const primaryButtonStyle: CSSProperties = {
  padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "none",
  background: "var(--eco-color-accentSkill)", color: "var(--eco-color-accentSkillText)", cursor: "pointer",
};
const secondaryButtonStyle: CSSProperties = {
  padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "1px solid var(--eco-color-border)",
  background: "var(--eco-color-bg)", cursor: "pointer",
};
