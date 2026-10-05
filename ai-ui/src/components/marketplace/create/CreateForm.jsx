// SPDX-License-Identifier: MIT
// Task F-9: Write flow -- ported UX from the merged frontend's
// SkillFormPage (ai-ui/src/components/Marketplace.jsx's inline component
// at the time of porting), with a mandatory license field added (MIT
// default, CONFIG_AND_PRODUCTS.md §7 item 5). Calls create_service's real
// endpoint (task B-6) via POST /ecosystem/items -- never localStorage.
//
// Full Tailwind pass (2026-10-03, user ask: "form fields like write skill...
// refer ProductManager.jsx"): every label/input/select rewritten to that
// file's own exact classes (`block text-xs text-gray-500 mb-1` labels,
// `w-full bg-white border border-gray-300 rounded px-3 py-2 text-sm
// focus:outline-none focus:border-indigo-300` fields) instead of
// var(--eco-*) + Form.css.
import { useState } from "react";
import { PencilIcon, ArrowLeftIcon } from "@heroicons/react/24/outline";
import { useEcosystemClient } from "../lib/context/HostContext";
import { useConfig } from "../lib/hooks/useEcosystemConfig";
import { LineNumberedTextarea } from "./LineNumberedTextarea";
import { Button } from "../Button";
import { useOptionalToast } from "../lib/useOptionalToast";
const ALLOWED_LICENSES = ["MIT", "Apache-2.0"];
const inputClass = "w-full bg-white border border-gray-300 rounded px-3 py-2 text-sm text-gray-900 focus:outline-none focus-visible:outline-none! focus:border-indigo-300";
// Premium-pass (2026-10-05, explicit product ask: "Add button forms...
// need a proper design UI UX premium experience"): the shared section-
// heading convention this whole package already uses elsewhere
// (CategorySection.jsx's own comment has the full rationale) -- a plain
// field label is one tier below this; this marks a logical GROUP of
// fields, the same way "Created by me (N)" marks a group of cards.
const sectionHeadingClass = "text-sm font-semibold text-gray-800 mt-6 mb-3 first:mt-0";
export function CreateForm({
  itemType,
  onCreated,
  onCancel,
  canProvision
}) {
  const client = useEcosystemClient();
  const config = useConfig();
  const toast = useOptionalToast();
  const [namespace, setNamespace] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState(config.taxonomy.categories[0] ?? "");
  const [license, setLicense] = useState("MIT");
  const [instructions, setInstructions] = useState("");
  const [files, setFiles] = useState([]);
  const [provisionScope, setProvisionScope] = useState("private");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
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
  const licenseGateSatisfied = isPrivate ? licenseAllowed || (needsAcknowledgement ? licenseAcknowledged : needsSelfAuthored ? selfAuthored : true) : licenseAllowed;
  const canSubmit = namespace.includes("/") && displayName.trim() && description.trim() && instructions.trim() && licenseGateSatisfied;
  const handleAddFile = () => setFiles(f => [...f, {
    name: `file-${f.length + 1}.md`,
    content: ""
  }]);
  const handleFileChange = (index, field, value) => {
    setFiles(f => f.map((file, i) => i === index ? {
      ...file,
      [field]: value
    } : file));
  };
  const handleRemoveFile = index => setFiles(f => f.filter((_, i) => i !== index));
  const handleSubmit = () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    const payload = {
      create_via: "write",
      item_type: itemType,
      namespace,
      display_name: displayName,
      description,
      category,
      license,
      content: {
        instructions,
        files
      },
      // Real bug found live: hardcoded ["chat"] regardless of what other
      // surfaces the caller's own product profile allows -- default to
      // every surface config.surfaces lists.
      surfaces: config.surfaces.map(s => s.key),
      ...(canProvision && provisionScope !== "private" ? {
        provision_scope: provisionScope
      } : {}),
      ...(needsAcknowledgement ? {
        license_acknowledged: licenseAcknowledged
      } : {}),
      ...(needsSelfAuthored ? {
        self_authored: selfAuthored
      } : {})
    };
    client.createItem(payload, `create-${namespace}-${Date.now()}`).then(result => {
      toast.success(`"${displayName}" created.`);
      onCreated(result.item_id);
    }).catch(e => {
      const message = e instanceof Error ? e.message : "Couldn't create this item.";
      setError(message);
      toast.error(message);
    }).finally(() => setSubmitting(false));
  };
  return <div data-testid="create-form" className="max-w-[640px]">
      <button type="button" onClick={onCancel} className="inline-flex items-center gap-1.5 bg-none border-none cursor-pointer text-gray-500 hover:text-gray-700 mb-4 transition-colors">
        <ArrowLeftIcon width={16} height={16} aria-hidden="true" /> Back
      </button>
      <div className="flex items-center gap-2 mb-1">
        <PencilIcon width={20} height={20} className="text-indigo-500" aria-hidden="true" />
        <h2 className="text-xl font-semibold text-gray-900 m-0">Write a new {itemType}</h2>
      </div>
      <p className="text-sm text-gray-500 mt-0 mb-5">Describe it, write its instructions, and publish straight from here.</p>

      <h3 className={sectionHeadingClass}>Identity</h3>
      <Field label="Namespace (publisher/name)">
        <input data-testid="create-form-namespace" className={inputClass} value={namespace} onChange={e => setNamespace(e.target.value)} placeholder="acme/my-skill" />
      </Field>
      <Field label="Display name">
        <input data-testid="create-form-display-name" className={inputClass} value={displayName} onChange={e => setDisplayName(e.target.value)} />
      </Field>
      <Field label="Description">
        <input data-testid="create-form-description" className={inputClass} value={description} onChange={e => setDescription(e.target.value)} />
      </Field>
      <Field label="Category">
        <select data-testid="create-form-category" className={inputClass} value={category} onChange={e => setCategory(e.target.value)}>
          {config.taxonomy.categories.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      </Field>

      <h3 className={sectionHeadingClass}>License</h3>
      <Field label="License">
        {customLicense ? <input data-testid="create-form-license-custom" className={inputClass} value={license} onChange={e => {
        setLicense(e.target.value);
        setLicenseAcknowledged(false);
        setSelfAuthored(false);
      }} placeholder="e.g. GPL-3.0-only, or leave blank" /> : <select data-testid="create-form-license" className={inputClass} value={license} onChange={e => setLicense(e.target.value)}>
            {ALLOWED_LICENSES.map(l => <option key={l} value={l}>{l}</option>)}
          </select>}
        {isPrivate && <button type="button" data-testid="create-form-license-toggle-custom" onClick={() => {
        setCustomLicense(v => !v);
        setLicense(customLicense ? "MIT" : license);
      }} className="bg-none border-none text-indigo-600 hover:opacity-70 cursor-pointer text-xs py-1">
            {customLicense ? "Use MIT/Apache-2.0 instead" : "This item uses a different license"}
          </button>}
        {!isPrivate && !licenseAllowed && <p role="alert" className="text-red-600 text-xs">Only MIT/Apache-2.0-compatible licenses are allowed.</p>}
        {needsAcknowledgement && <div data-testid="create-form-license-ack-prompt" className="mt-1.5">
            <p className="mb-1.5 mt-0 text-xs text-gray-500">
              {license} isn't MIT/Apache-2.0-compatible. You can still save it to your own private space.
            </p>
            <label className="flex items-center gap-1.5 text-xs text-gray-900">
              <input type="checkbox" data-testid="create-form-license-acknowledge" checked={licenseAcknowledged} onChange={e => setLicenseAcknowledged(e.target.checked)} />
              I'm responsible for complying with this license
            </label>
          </div>}
        {needsSelfAuthored && <div data-testid="create-form-license-self-authored-prompt" className="mt-1.5">
            <label className="flex items-center gap-1.5 text-xs text-gray-900">
              <input type="checkbox" data-testid="create-form-license-self-authored" checked={selfAuthored} onChange={e => setSelfAuthored(e.target.checked)} />
              This is self-authored — default its license to MIT
            </label>
          </div>}
      </Field>

      <h3 className={sectionHeadingClass}>Instructions &amp; files</h3>
      <Field label="Instructions">
        <LineNumberedTextarea value={instructions} onChange={setInstructions} placeholder="What should the model do when this skill is invoked?" />
      </Field>

      <Field label="Supporting files">
        {files.map((file, i) => <div key={i} className="flex gap-2 mb-2">
            <input className={[inputClass, "w-40"].join(" ")} value={file.name} onChange={e => handleFileChange(i, "name", e.target.value)} />
            <textarea className={[inputClass, "flex-1"].join(" ")} value={file.content} onChange={e => handleFileChange(i, "content", e.target.value)} rows={2} />
            <button type="button" onClick={() => handleRemoveFile(i)} className="bg-none border-none text-red-400 hover:text-red-600 cursor-pointer text-sm transition-colors">Remove</button>
          </div>)}
        <button type="button" data-testid="create-form-add-file" onClick={handleAddFile} className="bg-none border border-dashed border-gray-300 rounded px-3 py-1.5 cursor-pointer text-gray-500 hover:text-gray-700 hover:bg-gray-50 text-sm transition-colors">
          + Add file
        </button>
      </Field>

      {canProvision && <>
          <h3 className={sectionHeadingClass}>Visibility</h3>
          <Field label="Who should get this by default?">
            <select data-testid="create-form-provision-scope" className={inputClass} value={provisionScope} onChange={e => setProvisionScope(e.target.value)}>
              <option value="private">Just me</option>
              <option value="org_default_on">Everyone in org (default-on)</option>
              <option value="required">Required</option>
            </select>
          </Field>
        </>}

      {error && <p role="alert" className="bg-red-50 text-red-700 border border-red-200 rounded-md px-3 py-2 text-sm mt-4">{error}</p>}

      <div className="flex gap-2 mt-6 pt-5 border-t border-gray-100">
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button variant="primary" data-testid="create-form-submit" disabled={!canSubmit} loading={submitting} onClick={handleSubmit}>
          {submitting ? "Creating…" : "Create"}
        </Button>
      </div>
    </div>;
}
function Field({
  label,
  children
}) {
  return <div className="mb-4">
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      {children}
    </div>;
}
