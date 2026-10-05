// SPDX-License-Identifier: MIT
// Task F-9: Upload flow -- ported UX from the merged frontend's
// SkillUploadPage (drag-and-drop, per-file validation, zip/.skill preview)
// with mandatory-license validation added. Calls POST /ecosystem/items/upload
// (task B-6) -- server-side unzip/path-traversal/zip-bomb guards are the
// real enforcement; this client-side check is only a fast, friendly
// pre-flight, never trusted as the actual validation.
import { useRef, useState } from "react";
import { ArrowUpTrayIcon, ArrowLeftIcon, DocumentIcon, XMarkIcon } from "@heroicons/react/24/outline";
import { useEcosystemClient } from "../lib/context/HostContext";
import { useConfig } from "../lib/hooks/useEcosystemConfig";
import { Button } from "../Button";
import { useOptionalToast } from "../lib/useOptionalToast";
const MAX_SIZE_BYTES = 5 * 1024 * 1024;
const inputClass = "w-full bg-white border border-gray-300 rounded px-3 py-2 text-sm text-gray-900 focus:outline-none focus-visible:outline-none! focus:border-indigo-300";
export function UploadFlow({
  itemType,
  onUploaded,
  onCancel
}) {
  const client = useEcosystemClient();
  const config = useConfig();
  const toast = useOptionalToast();
  const [file, setFile] = useState(null);
  const [namespace, setNamespace] = useState("");
  const [category, setCategory] = useState(config.taxonomy.categories[0] ?? "");
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [blockedReason, setBlockedReason] = useState(null);
  // Tiered license policy (ECOSYSTEM_PLAN.md §11.2, Tier 3) -- a private
  // upload with a disallowed/missing license isn't a dead end any more;
  // it needs one more explicit confirmation, not a second full submit.
  const [ackReason, setAckReason] = useState(null);
  const [licenseAcknowledged, setLicenseAcknowledged] = useState(false);
  const [selfAuthored, setSelfAuthored] = useState(false);
  const inputRef = useRef(null);
  const validateAndSetFile = candidate => {
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
  const handleDrop = e => {
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
    client.uploadItem(form, `upload-${namespace}-${Date.now()}`).then(result => {
      setAckReason(null);
      toast.success(`"${file.name}" uploaded.`);
      onUploaded(result.item_id);
    }).catch(e => {
      const code = e?.code;
      const reason = e?.details?.reason;
      if (code === "LICENSE_ACKNOWLEDGEMENT_REQUIRED") {
        setAckReason(reason === "missing_license" ? "missing_license" : "acknowledgement_required");
      } else if (code === "LICENSE_NOT_ALLOWED") {
        const message = "This bundle's declared license isn't MIT/Apache-2.0-compatible and can't be uploaded.";
        setBlockedReason(message);
        toast.error(message);
      } else if (code === "LICENSE_NOT_ALLOWED_BY_ORG_POLICY") {
        const message = "This bundle's declared license isn't on this org's allowed list and can't be uploaded here.";
        setBlockedReason(message);
        toast.error(message);
      } else {
        const message = e instanceof Error ? e.message : "Couldn't upload this bundle.";
        setError(message);
        toast.error(message);
      }
    }).finally(() => setSubmitting(false));
  };
  return <div data-testid="upload-flow" className="max-w-[560px]">
      <button type="button" onClick={onCancel} className="inline-flex items-center gap-1.5 bg-none border-none cursor-pointer text-gray-500 hover:text-gray-700 mb-4 transition-colors">
        <ArrowLeftIcon width={16} height={16} aria-hidden="true" /> Back
      </button>
      <div className="flex items-center gap-2 mb-1">
        <ArrowUpTrayIcon width={20} height={20} className="text-indigo-500" aria-hidden="true" />
        <h2 className="text-xl font-semibold text-gray-900 m-0">Upload a {itemType}</h2>
      </div>
      <p className="text-sm text-gray-500 mt-0 mb-5">Bring an existing .zip or .skill bundle and publish it as-is.</p>

      {/* Premium-pass (2026-10-05): was a plain bordered box with text only
          -- an icon (swapping to a filled check once a valid file is
          picked) plus a visible "Browse files" affordance reads as a real
          upload control instead of a placeholder-looking box. */}
      <div data-testid="upload-dropzone" onDragOver={e => {
      e.preventDefault();
      setDragging(true);
    }} onDragLeave={() => setDragging(false)} onDrop={handleDrop} onClick={() => inputRef.current?.click()} className={["border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors", dragging ? "border-indigo-400 bg-indigo-50/50" : file ? "border-emerald-300 bg-emerald-50/40" : "border-gray-300 hover:border-gray-400 hover:bg-gray-50"].join(" ")}>
        {file ? <div className="flex items-center justify-center gap-2 text-emerald-700">
            <DocumentIcon width={20} height={20} aria-hidden="true" />
            <span data-testid="upload-filename" className="text-sm font-medium">{file.name}</span>
            <button type="button" onClick={e => {
            e.stopPropagation();
            setFile(null);
          }} title="Remove" className="inline-flex items-center justify-center p-0.5 rounded-full text-emerald-700 hover:bg-emerald-100 transition-colors">
              <XMarkIcon width={14} height={14} aria-hidden="true" />
            </button>
          </div> : <div className="text-gray-500">
            <ArrowUpTrayIcon width={24} height={24} className="mx-auto mb-2 text-gray-400" aria-hidden="true" />
            <p className="m-0 text-sm">Drag a .zip or .skill bundle here, or <span className="text-indigo-600 font-medium">browse files</span></p>
            <p className="m-0 mt-1 text-xs text-gray-400">Up to {MAX_SIZE_BYTES / 1024 / 1024}MB</p>
          </div>}
        <input ref={inputRef} type="file" accept=".zip,.skill" hidden onChange={e => {
        const f = e.target.files?.[0];
        if (f) validateAndSetFile(f);
      }} />
      </div>

      {error && <p role="alert" className="bg-red-50 text-red-700 border border-red-200 rounded-md px-3 py-2 text-sm mt-3">{error}</p>}

      {blockedReason && <div data-testid="upload-blocked-banner" role="alert" className="bg-red-50 text-red-600 border border-red-200 p-2 rounded mt-2 text-sm">
          {blockedReason}
        </div>}

      {ackReason === "acknowledgement_required" && <div data-testid="upload-ack-prompt" role="alert" className="bg-amber-50 text-amber-700 border border-amber-200 p-2 rounded mt-2 text-sm">
          <p className="mt-0 mb-1.5">This bundle's declared license isn't MIT/Apache-2.0-compatible. You can still save it to your own private space, but you're responsible for complying with its license.</p>
          <label className="flex items-center gap-1.5">
            <input type="checkbox" data-testid="upload-license-acknowledge" checked={licenseAcknowledged} onChange={e => setLicenseAcknowledged(e.target.checked)} />
            I'm responsible for complying with this license
          </label>
        </div>}

      {ackReason === "missing_license" && <div data-testid="upload-ack-prompt" role="alert" className="bg-amber-50 text-amber-700 border border-amber-200 p-2 rounded mt-2 text-sm">
          <p className="mt-0 mb-1.5">This bundle's SKILL.md doesn't declare a license.</p>
          <label className="flex items-center gap-1.5">
            <input type="checkbox" data-testid="upload-self-authored" checked={selfAuthored} onChange={e => setSelfAuthored(e.target.checked)} />
            This is self-authored — default its license to MIT
          </label>
        </div>}

      <h3 className="text-sm font-semibold text-gray-800 mt-6 mb-3">Identity</h3>
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Namespace (publisher/name)</label>
        <input data-testid="upload-namespace" className={inputClass} value={namespace} onChange={e => setNamespace(e.target.value)} placeholder="acme/my-skill" />
      </div>

      <div className="mt-4">
        <label className="block text-xs font-medium text-gray-600 mb-1">Category</label>
        <select data-testid="upload-category" className={inputClass} value={category} onChange={e => setCategory(e.target.value)}>
          {config.taxonomy.categories.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      <div className="flex gap-2 mt-6 pt-5 border-t border-gray-100">
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button variant="primary" data-testid="upload-submit" disabled={!file || !namespace.includes("/") || submitting || ackReason === "acknowledgement_required" && !licenseAcknowledged || ackReason === "missing_license" && !selfAuthored} loading={submitting} onClick={handleSubmit}>
          {submitting ? "Uploading…" : "Upload"}
        </Button>
      </div>
    </div>;
}