// SPDX-License-Identifier: MIT
// Item A3 ("Edit skill code is missing"): file-tree + editor for an
// owned item's SKILL.md + bundled files. Save always creates a new,
// immutable version (never mutates the current one in place) via
// POST /ecosystem/items/{id}/new-version (CONTRACTS.md §10.1) -- the same
// endpoint item 6's chat "Update my <skill>" flow already uses, so
// Marketplace's Edit tab and chat's "Update this skill" share one backend
// path and one "bump my own install on pass" behavior.
//
// License is a first-class field here, not something parsed out of the
// SKILL.md text: create_service.add_version_to_existing_item() never
// parses frontmatter from `content.instructions` (that only happens for
// uploaded .zip/.skill files, via _agentstudio_interop.parse_skill_md_frontmatter);
// it reads a separate top-level `license` request field, falling back to
// the item's current license if omitted. A `license:` line embedded in
// SKILL.md's own text would have zero effect on the actual gate/license
// check on this path -- this editor intentionally never parses one out,
// since doing so would show a control Save silently ignores.
import { useEffect, useMemo, useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { githubDark, githubLight } from "@uiw/codemirror-theme-github";
import { LanguageDescription } from "@codemirror/language";
import { languages } from "@codemirror/language-data";
import { PlusIcon, TrashIcon, PencilIcon } from "@heroicons/react/24/outline";
import { useEcosystemClient, useHost } from "../lib/context/HostContext";
import { Button } from "../Button";
const SKILL_MD = "SKILL.md";
const ALLOWED_LICENSES_HINT = "MIT/Apache-2.0-compatible (matches license_policy.py's own rule)";
function manifestToFiles(item) {
  const manifest = item.manifest;
  const bundled = Object.entries(manifest.files ?? {}).map(([name, content]) => ({
    name,
    content
  }));
  return [{
    name: SKILL_MD,
    content: manifest.instructions ?? ""
  }, ...bundled];
}

/** Mirrors services/ecosystem/license_policy.py's is_allowed_license() --
 * client-side UX feedback only, the server is the real gate either way. */
function isAllowedLicense(license) {
  const normalized = license.trim().toLowerCase();
  return normalized.length > 0 && (normalized.includes("mit") || normalized.includes("apache"));
}

/** Mirrors this codebase's own zip path-traversal hygiene (create_service.py's
 * upload parsing) -- the first surface in this package where a human types a
 * raw file name directly, so the same rule applies here too. */
function isSafeNewFileName(name, existing) {
  const trimmed = name.trim();
  if (!trimmed) return "File name can't be empty.";
  if (trimmed === SKILL_MD) return `"${SKILL_MD}" already exists.`;
  if (trimmed.includes("..") || trimmed.startsWith("/") || trimmed.includes("\\")) return "File name can't contain \"..\", \"/\", or \"\\\".";
  if (existing.some(f => f.name === trimmed)) return `A file named "${trimmed}" already exists.`;
  return null;
}
function isDarkBackground(bgHex) {
  const hex = bgHex.replace("#", "");
  if (hex.length !== 6) return false;
  const r = parseInt(hex.slice(0, 2), 16);
  const g = parseInt(hex.slice(2, 4), 16);
  const b = parseInt(hex.slice(4, 6), 16);
  return (r * 299 + g * 587 + b * 114) / 1000 < 128;
}
export function EditContent({
  item,
  onSaved,
  onDirtyChange
}) {
  const client = useEcosystemClient();
  const theme = useHost().theme;
  // User-flow QA round 5 (2026-10-03, real user question: "do we have
  // save, cancel button? will it work"): there was a working Save but no
  // Cancel at all -- switching tabs or clicking Back mid-edit silently
  // discarded edits with zero warning, the same class of bug the
  // Create-with-AI page already got a leave-confirmation for. `initial`
  // is this editor's own undo baseline -- Cancel resets to it, and it
  // also becomes the new baseline after a successful Save (the parent's
  // `item` prop doesn't update synchronously with the new version, so
  // re-deriving from `item` on save wouldn't reflect what was just saved).
  const [initial, setInitial] = useState(() => ({
    files: manifestToFiles(item),
    license: item.license
  }));
  const [files, setFiles] = useState(initial.files);
  const [selected, setSelected] = useState(0);
  const [license, setLicense] = useState(initial.license);
  const [addingFile, setAddingFile] = useState(false);
  const [newFileName, setNewFileName] = useState("");
  const [addFileError, setAddFileError] = useState(null);
  const [renaming, setRenaming] = useState(null);
  const [renameValue, setRenameValue] = useState("");
  const [renameError, setRenameError] = useState(null);
  const [langExtension, setLangExtension] = useState([]);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [saved, setSaved] = useState(false);
  // Tiered license policy (ECOSYSTEM_PLAN.md §11.2, task C): a disallowed
  // license is no longer a dead end here either -- the server decides
  // whether it's Tier 3 (private, needs acknowledgement) or Tier 2 (already
  // shared, needs the org's own allowed_licenses_shared list to permit it)
  // via a real LICENSE_ACKNOWLEDGEMENT_REQUIRED / LICENSE_NOT_ALLOWED_BY_ORG_POLICY
  // response -- this editor doesn't know the item's install footprint, so
  // it reacts to that response rather than trying to guess client-side.
  const [ackReason, setAckReason] = useState(null);
  const [licenseAcknowledged, setLicenseAcknowledged] = useState(false);
  const [orgPolicyBlockedReason, setOrgPolicyBlockedReason] = useState(null);
  const cmTheme = isDarkBackground(theme.color.bg) ? githubDark : githubLight;
  // files[0] (SKILL.md) is seeded in the initial state and never removed
  // (handleDeleteFile only targets i > 0) -- always defined in practice.
  const selectedFile = files[selected] ?? files[0];
  const isDirty = useMemo(() => license !== initial.license || JSON.stringify(files) !== JSON.stringify(initial.files), [files, license, initial]);
  useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);
  // Only this unmount (navigating away while still dirty, i.e. the user
  // chose "Leave" on the parent's confirmation) needs to clear the flag it
  // raised -- a normal unmount after Save already reset isDirty to false
  // itself, so this is a no-op in that case.
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);
  const handleCancel = () => {
    setFiles(initial.files);
    setLicense(initial.license);
    setSelected(0);
    setSaveError(null);
    setSaved(false);
    setAckReason(null);
    setLicenseAcknowledged(false);
    setOrgPolicyBlockedReason(null);
  };
  useEffect(() => {
    let cancelled = false;
    const desc = LanguageDescription.matchFilename(languages, selectedFile.name);
    if (!desc) {
      setLangExtension([]);
      return;
    }
    desc.load().then(support => {
      if (!cancelled) setLangExtension([support]);
    });
    return () => {
      cancelled = true;
    };
  }, [selectedFile.name]);
  const validationError = useMemo(() => {
    // A disallowed license alone no longer blocks Save outright (task C) --
    // it may still be fine under Tier 2/3, decided server-side. It only
    // blocks here once the server has actually said acknowledgement is
    // required and the caller hasn't checked the box yet.
    if (ackReason === "acknowledgement_required" && !licenseAcknowledged) {
      return `License must be ${ALLOWED_LICENSES_HINT}, or acknowledge you're responsible for complying with it.`;
    }
    if (!files[0]?.content.trim()) return `${SKILL_MD} can't be empty.`;
    return null;
  }, [ackReason, licenseAcknowledged, files]);
  const updateSelectedContent = content => {
    setFiles(f => f.map((file, i) => i === selected ? {
      ...file,
      content
    } : file));
    setSaved(false);
  };
  const handleAddFile = () => {
    const err = isSafeNewFileName(newFileName, files);
    if (err) {
      setAddFileError(err);
      return;
    }
    const name = newFileName.trim();
    setFiles(f => [...f, {
      name,
      content: ""
    }]);
    setSelected(files.length);
    setNewFileName("");
    setAddFileError(null);
    setAddingFile(false);
    setSaved(false);
  };
  const handleStartRename = index => {
    setRenaming(index);
    setRenameValue(files[index]?.name ?? "");
    setRenameError(null);
  };
  const handleConfirmRename = () => {
    if (renaming === null) return;
    const err = isSafeNewFileName(renameValue, files.filter((_, i) => i !== renaming));
    if (err) {
      setRenameError(err);
      return;
    }
    const name = renameValue.trim();
    setFiles(f => f.map((file, i) => i === renaming ? {
      ...file,
      name
    } : file));
    setRenaming(null);
    setRenameError(null);
    setSaved(false);
  };
  const handleDeleteFile = index => {
    if (typeof window !== "undefined" && !window.confirm(`Remove ${files[index]?.name}? This can't be undone until you save.`)) return;
    setFiles(f => f.filter((_, i) => i !== index));
    setSelected(s => s >= index ? Math.max(0, s - 1) : s);
    setSaved(false);
  };
  const handleSave = () => {
    if (validationError) return;
    setSaving(true);
    setSaveError(null);
    setOrgPolicyBlockedReason(null);
    const content = {
      instructions: files[0]?.content ?? "",
      files: files.slice(1)
    };
    client.createNewVersion(item.id, content, license, {
      licenseAcknowledged
    }).then(() => {
      setSaved(true);
      setAckReason(null);
      setInitial({
        files,
        license
      });
      onSaved();
    }).catch(e => {
      const code = e?.code;
      const reason = e?.details?.reason;
      if (code === "LICENSE_ACKNOWLEDGEMENT_REQUIRED") {
        setAckReason(reason === "missing_license" ? "missing_license" : "acknowledgement_required");
      } else if (code === "LICENSE_NOT_ALLOWED_BY_ORG_POLICY") {
        setOrgPolicyBlockedReason("This item is already shared/provisioned, and its license isn't on this org's allowed list -- an admin can add it in Marketplace policy settings.");
      } else {
        setSaveError(e instanceof Error ? e.message : "Couldn't save this version.");
      }
    }).finally(() => setSaving(false));
  };
  return <div data-testid="detail-tab-edit-content">
      <div className="mb-4">
        <label className="block text-xs text-gray-500 mb-1">
          License
          <input data-testid="edit-content-license" value={license} onChange={e => {
          setLicense(e.target.value);
          setSaved(false);
          setAckReason(null);
          setLicenseAcknowledged(false);
        }} className={inputClass} />
        </label>
        {!isAllowedLicense(license) && !ackReason && <p className="text-gray-500 text-xs mt-1 mb-0">
            Not MIT/Apache-2.0-compatible -- Save to find out whether this item's current scope allows it.
          </p>}
        {ackReason === "acknowledgement_required" && <div data-testid="edit-content-license-ack-prompt" className="mt-1">
            <p role="alert" className="text-red-600 text-xs mt-0 mb-1.5">
              License must be {ALLOWED_LICENSES_HINT}, or acknowledge you're responsible for complying with it.
            </p>
            <label className="flex items-center gap-1.5 text-xs">
              <input type="checkbox" data-testid="edit-content-license-acknowledge" checked={licenseAcknowledged} onChange={e => setLicenseAcknowledged(e.target.checked)} />
              I'm responsible for complying with this license
            </label>
          </div>}
        {orgPolicyBlockedReason && <p role="alert" data-testid="edit-content-org-policy-blocked" className="text-red-600 text-xs mt-1 mb-0">
            {orgPolicyBlockedReason}
          </p>}
      </div>

      <div className="flex gap-4" style={{
      minHeight: "360px"
    }}>
        <div data-testid="edit-content-file-tree" className="w-[200px] flex-shrink-0 border-r border-gray-200 pr-2">
          {files.map((file, i) => <div key={file.name} className="flex items-center gap-1">
              {renaming === i ? <>
                  <input data-testid={`edit-content-rename-input-${i}`} value={renameValue} onChange={e => setRenameValue(e.target.value)} onKeyDown={e => {
              if (e.key === "Enter") handleConfirmRename();
              if (e.key === "Escape") setRenaming(null);
            }} className={[inputClass, "flex-1 py-1"].join(" ")} autoFocus />
                  <button type="button" data-testid={`edit-content-rename-confirm-${i}`} onClick={handleConfirmRename} className={iconButtonClass}>✓</button>
                </> : <>
                  <button type="button" data-testid={`edit-content-file-${file.name}`} onClick={() => setSelected(i)} className={["flex-1 text-left border-none cursor-pointer px-2 py-1.5 rounded font-mono text-sm", selected === i ? "text-indigo-600 bg-gray-50" : "text-gray-900 bg-none"].join(" ")}>
                    {file.name}
                  </button>
                  {i > 0 && <>
                      <button type="button" data-testid={`edit-content-rename-${i}`} title="Rename" onClick={() => handleStartRename(i)} className={iconButtonClass}>
                        <PencilIcon width={14} height={14} aria-hidden="true" />
                      </button>
                      <button type="button" data-testid={`edit-content-delete-${i}`} title="Remove" onClick={() => handleDeleteFile(i)} className={iconButtonClass}>
                        <TrashIcon width={14} height={14} aria-hidden="true" />
                      </button>
                    </>}
                </>}
            </div>)}
          {renameError && <p role="alert" className="text-red-600 text-xs">{renameError}</p>}

          {addingFile ? <div className="flex gap-1 mt-2">
              <input data-testid="edit-content-new-file-name" value={newFileName} onChange={e => setNewFileName(e.target.value)} onKeyDown={e => {
            if (e.key === "Enter") handleAddFile();
            if (e.key === "Escape") setAddingFile(false);
          }} placeholder="references/notes.md" className={[inputClass, "flex-1 py-1"].join(" ")} autoFocus />
              <button type="button" data-testid="edit-content-new-file-confirm" onClick={handleAddFile} className={iconButtonClass}>✓</button>
            </div> : <button type="button" data-testid="edit-content-add-file" onClick={() => {
          setAddingFile(true);
          setAddFileError(null);
        }} className="flex items-center gap-1 mt-2 bg-none border border-dashed border-gray-300 rounded-md px-2 py-1.5 cursor-pointer text-gray-500 hover:text-gray-700 hover:bg-gray-50 text-xs w-full transition-colors">
              <PlusIcon width={14} height={14} aria-hidden="true" /> Add file
            </button>}
          {addFileError && <p role="alert" className="text-red-600 text-xs">{addFileError}</p>}
        </div>

        <div className="flex-1 min-w-0">
          <CodeMirror data-testid="edit-content-editor" value={selectedFile.content} height="360px" theme={cmTheme} extensions={langExtension} onChange={updateSelectedContent} aria-label={`Editing ${selectedFile.name}`} />
        </div>
      </div>

      {saveError && <p role="alert" className="text-red-600 mt-4">{saveError}</p>}
      {saved && <p role="status" data-testid="edit-content-saved-banner" className="text-green-700 mt-4">
          Saved as a new version — it's now verifying. Check the Versions tab for its status.
        </p>}

      <div className="mt-4 flex gap-2">
        <Button data-testid="edit-content-save" disabled={saving || Boolean(validationError)} loading={saving} onClick={handleSave}>
          {saving ? "Saving…" : "Save as new version"}
        </Button>
        <Button variant="secondary" data-testid="edit-content-cancel" disabled={saving || !isDirty} onClick={handleCancel}>
          Cancel
        </Button>
      </div>
    </div>;
}
const inputClass = "w-full bg-white border border-gray-300 rounded px-3 py-2 text-sm text-gray-900 focus:outline-none focus-visible:outline-none! focus:border-indigo-300";
const iconButtonClass = "bg-none border-none cursor-pointer text-gray-500 hover:text-gray-700 inline-flex items-center p-0.5 transition-colors";