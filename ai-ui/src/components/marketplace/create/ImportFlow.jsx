// SPDX-License-Identifier: MIT
// Task F-9: Import flow (new -- no merged-frontend precedent to port).
// Backs /marketplace/:typeSlug/import. Only github_repo/well_known have
// real server-side adapters (task I, pre-M3) -- every other SourceKind
// value still 501s server-side (create_service.create_via_import()'s own
// disclosed NotImplementedError for kinds beyond those two), so this form
// only offers the two working kinds rather than exposing dead options.
//
// Full Tailwind pass (2026-10-03): rewritten to literal Tailwind classes,
// matching create/CreateForm.jsx's/UploadFlow.jsx's own exact conventions
// (same inputClass string, same Button usage) instead of var(--eco-*).
import { useState } from "react";
import { CodeBracketIcon, ArrowLeftIcon } from "@heroicons/react/24/outline";
import { useEcosystemClient } from "../lib/context/HostContext";
import { useConfig } from "../lib/hooks/useEcosystemConfig";
import { Button } from "../Button";
import { useOptionalToast } from "../lib/useOptionalToast";
const IMPORT_KINDS = [{
  value: "github_repo",
  label: "GitHub repository",
  refHint: "owner/repo or owner/repo@branch"
}, {
  value: "well_known",
  label: "Well-known index entry",
  refHint: "domain/skill_slug"
}];
const inputClass = "w-full bg-white border border-gray-300 rounded px-3 py-2 text-sm text-gray-900 focus:outline-none focus-visible:outline-none! focus:border-indigo-300";
export function ImportFlow({
  itemType,
  onImported,
  onCancel
}) {
  const client = useEcosystemClient();
  const config = useConfig();
  const toast = useOptionalToast();
  const [kind, setKind] = useState("github_repo");
  const [ref, setRef] = useState("");
  const [namespace, setNamespace] = useState("");
  const [category, setCategory] = useState(config.taxonomy.categories[0] ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [blockedReason, setBlockedReason] = useState(null);
  const selectedKind = IMPORT_KINDS.find(k => k.value === kind);
  const canSubmit = ref.trim().length > 0 && namespace.includes("/");
  const handleSubmit = () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    setBlockedReason(null);
    const payload = {
      create_via: "import",
      item_type: itemType,
      namespace,
      category,
      kind,
      ref
    };
    client.createItem(payload, `import-${namespace}-${Date.now()}`).then(result => {
      toast.success(`"${namespace}" imported.`);
      onImported(result.item_id);
    }).catch(e => {
      const code = e?.code;
      if (code === "LICENSE_NOT_ALLOWED") {
        const message = "The source's declared license isn't MIT/Apache-2.0-compatible -- rejected before fetching any content.";
        setBlockedReason(message);
        toast.error(message);
      } else {
        const message = e instanceof Error ? e.message : "Couldn't import from this source.";
        setError(message);
        toast.error(message);
      }
    }).finally(() => setSubmitting(false));
  };
  return <div data-testid="import-flow" className="max-w-[560px]">
      <button type="button" onClick={onCancel} className="inline-flex items-center gap-1.5 bg-none border-none cursor-pointer text-gray-500 hover:text-gray-700 mb-4 transition-colors">
        <ArrowLeftIcon width={16} height={16} aria-hidden="true" /> Back
      </button>
      <div className="flex items-center gap-2 mb-1">
        <CodeBracketIcon width={20} height={20} className="text-indigo-500" aria-hidden="true" />
        <h2 className="text-xl font-semibold text-gray-900 m-0">Import a {itemType}</h2>
      </div>
      <p className="text-sm text-gray-500 mt-0 mb-5">Pull one in from GitHub or a well-known index entry.</p>

      <h3 className="text-sm font-semibold text-gray-800 mt-0 mb-3">Source</h3>
      <div className="mb-4">
        <label className="block text-xs font-medium text-gray-600 mb-1">Source</label>
        <select data-testid="import-kind" className={inputClass} value={kind} onChange={e => setKind(e.target.value)}>
          {IMPORT_KINDS.map(k => <option key={k.value} value={k.value}>{k.label}</option>)}
        </select>
      </div>

      <div className="mb-4">
        <label className="block text-xs font-medium text-gray-600 mb-1">Reference</label>
        <input data-testid="import-ref" className={inputClass} value={ref} onChange={e => setRef(e.target.value)} placeholder={selectedKind.refHint} />
      </div>

      <h3 className="text-sm font-semibold text-gray-800 mt-6 mb-3">Identity</h3>
      <div className="mb-4">
        <label className="block text-xs font-medium text-gray-600 mb-1">Namespace (publisher/name)</label>
        <input data-testid="import-namespace" className={inputClass} value={namespace} onChange={e => setNamespace(e.target.value)} placeholder="acme/imported-tool" />
      </div>

      <div className="mb-4">
        <label className="block text-xs font-medium text-gray-600 mb-1">Category</label>
        <select data-testid="import-category" className={inputClass} value={category} onChange={e => setCategory(e.target.value)}>
          {config.taxonomy.categories.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      {error && <p role="alert" className="bg-red-50 text-red-700 border border-red-200 rounded-md px-3 py-2 text-sm">{error}</p>}
      {blockedReason && <div data-testid="import-blocked-banner" role="alert" className="bg-red-50 text-red-700 border border-red-200 rounded-md px-3 py-2 text-sm">
          {blockedReason}
        </div>}

      <div className="flex gap-2 mt-6 pt-5 border-t border-gray-100">
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button variant="primary" data-testid="import-submit" disabled={!canSubmit || submitting} loading={submitting} onClick={handleSubmit}>
          {submitting ? "Importing…" : "Import"}
        </Button>
      </div>
    </div>;
}
