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
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { githubDark, githubLight } from "@uiw/codemirror-theme-github";
import { LanguageDescription } from "@codemirror/language";
import { languages } from "@codemirror/language-data";
import type { Extension } from "@codemirror/state";
import { PlusIcon, TrashIcon, PencilIcon } from "@heroicons/react/24/outline";
import type { ItemDetail } from "../../types";
import { useEcosystemClient, useHost } from "../../context/HostContext";

interface EditableFile {
  name: string;
  content: string;
}

const SKILL_MD = "SKILL.md";
const ALLOWED_LICENSES_HINT = "MIT/Apache-2.0-compatible (matches license_policy.py's own rule)";

function manifestToFiles(item: ItemDetail): EditableFile[] {
  const manifest = item.manifest as { instructions?: string; files?: Record<string, string> };
  const bundled = Object.entries(manifest.files ?? {}).map(([name, content]) => ({ name, content }));
  return [{ name: SKILL_MD, content: manifest.instructions ?? "" }, ...bundled];
}

/** Mirrors services/ecosystem/license_policy.py's is_allowed_license() --
 * client-side UX feedback only, the server is the real gate either way. */
function isAllowedLicense(license: string): boolean {
  const normalized = license.trim().toLowerCase();
  return normalized.length > 0 && (normalized.includes("mit") || normalized.includes("apache"));
}

/** Mirrors this codebase's own zip path-traversal hygiene (create_service.py's
 * upload parsing) -- the first surface in this package where a human types a
 * raw file name directly, so the same rule applies here too. */
function isSafeNewFileName(name: string, existing: EditableFile[]): string | null {
  const trimmed = name.trim();
  if (!trimmed) return "File name can't be empty.";
  if (trimmed === SKILL_MD) return `"${SKILL_MD}" already exists.`;
  if (trimmed.includes("..") || trimmed.startsWith("/") || trimmed.includes("\\")) return "File name can't contain \"..\", \"/\", or \"\\\".";
  if (existing.some((f) => f.name === trimmed)) return `A file named "${trimmed}" already exists.`;
  return null;
}

function isDarkBackground(bgHex: string): boolean {
  const hex = bgHex.replace("#", "");
  if (hex.length !== 6) return false;
  const r = parseInt(hex.slice(0, 2), 16);
  const g = parseInt(hex.slice(2, 4), 16);
  const b = parseInt(hex.slice(4, 6), 16);
  return (r * 299 + g * 587 + b * 114) / 1000 < 128;
}

export function EditContent({ item, onSaved }: { item: ItemDetail; onSaved: () => void }) {
  const client = useEcosystemClient();
  const theme = useHost().theme;
  const [files, setFiles] = useState<EditableFile[]>(() => manifestToFiles(item));
  const [selected, setSelected] = useState(0);
  const [license, setLicense] = useState(item.license);
  const [addingFile, setAddingFile] = useState(false);
  const [newFileName, setNewFileName] = useState("");
  const [addFileError, setAddFileError] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
  const [langExtension, setLangExtension] = useState<Extension[]>([]);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  // Tiered license policy (ECOSYSTEM_PLAN.md §11.2, task C): a disallowed
  // license is no longer a dead end here either -- the server decides
  // whether it's Tier 3 (private, needs acknowledgement) or Tier 2 (already
  // shared, needs the org's own allowed_licenses_shared list to permit it)
  // via a real LICENSE_ACKNOWLEDGEMENT_REQUIRED / LICENSE_NOT_ALLOWED_BY_ORG_POLICY
  // response -- this editor doesn't know the item's install footprint, so
  // it reacts to that response rather than trying to guess client-side.
  const [ackReason, setAckReason] = useState<"acknowledgement_required" | "missing_license" | null>(null);
  const [licenseAcknowledged, setLicenseAcknowledged] = useState(false);
  const [orgPolicyBlockedReason, setOrgPolicyBlockedReason] = useState<string | null>(null);

  const cmTheme = isDarkBackground(theme.color.bg) ? githubDark : githubLight;
  // files[0] (SKILL.md) is seeded in the initial state and never removed
  // (handleDeleteFile only targets i > 0) -- always defined in practice.
  const selectedFile = files[selected] ?? files[0]!;

  useEffect(() => {
    let cancelled = false;
    const desc = LanguageDescription.matchFilename(languages, selectedFile.name);
    if (!desc) {
      setLangExtension([]);
      return;
    }
    desc.load().then((support) => { if (!cancelled) setLangExtension([support]); });
    return () => { cancelled = true; };
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

  const updateSelectedContent = (content: string) => {
    setFiles((f) => f.map((file, i) => (i === selected ? { ...file, content } : file)));
    setSaved(false);
  };

  const handleAddFile = () => {
    const err = isSafeNewFileName(newFileName, files);
    if (err) { setAddFileError(err); return; }
    const name = newFileName.trim();
    setFiles((f) => [...f, { name, content: "" }]);
    setSelected(files.length);
    setNewFileName("");
    setAddFileError(null);
    setAddingFile(false);
    setSaved(false);
  };

  const handleStartRename = (index: number) => {
    setRenaming(index);
    setRenameValue(files[index]?.name ?? "");
    setRenameError(null);
  };

  const handleConfirmRename = () => {
    if (renaming === null) return;
    const err = isSafeNewFileName(renameValue, files.filter((_, i) => i !== renaming));
    if (err) { setRenameError(err); return; }
    const name = renameValue.trim();
    setFiles((f) => f.map((file, i) => (i === renaming ? { ...file, name } : file)));
    setRenaming(null);
    setRenameError(null);
    setSaved(false);
  };

  const handleDeleteFile = (index: number) => {
    if (typeof window !== "undefined" && !window.confirm(`Remove ${files[index]?.name}? This can't be undone until you save.`)) return;
    setFiles((f) => f.filter((_, i) => i !== index));
    setSelected((s) => (s >= index ? Math.max(0, s - 1) : s));
    setSaved(false);
  };

  const handleSave = () => {
    if (validationError) return;
    setSaving(true);
    setSaveError(null);
    setOrgPolicyBlockedReason(null);
    const content = { instructions: files[0]?.content ?? "", files: files.slice(1) };
    client.createNewVersion(item.id, content, license, { licenseAcknowledged })
      .then(() => { setSaved(true); setAckReason(null); onSaved(); })
      .catch((e: unknown) => {
        const code = (e as { code?: string })?.code;
        const reason = (e as { details?: { reason?: string } })?.details?.reason;
        if (code === "LICENSE_ACKNOWLEDGEMENT_REQUIRED") {
          setAckReason(reason === "missing_license" ? "missing_license" : "acknowledgement_required");
        } else if (code === "LICENSE_NOT_ALLOWED_BY_ORG_POLICY") {
          setOrgPolicyBlockedReason("This item is already shared/provisioned, and its license isn't on this org's allowed list -- an admin can add it in Marketplace policy settings.");
        } else {
          setSaveError(e instanceof Error ? e.message : "Couldn't save this version.");
        }
      })
      .finally(() => setSaving(false));
  };

  return (
    <div data-testid="detail-tab-edit-content">
      <div style={{ marginBottom: "var(--eco-space-md)" }}>
        <label style={{ display: "block", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)", marginBottom: "4px" }}>
          License
          <input
            data-testid="edit-content-license"
            value={license}
            onChange={(e) => { setLicense(e.target.value); setSaved(false); setAckReason(null); setLicenseAcknowledged(false); }}
            style={inputStyle}
          />
        </label>
        {!isAllowedLicense(license) && !ackReason && (
          <p style={{ color: "var(--eco-color-textSecondary)", fontSize: "var(--eco-font-sizeXs)", margin: "4px 0 0" }}>
            Not MIT/Apache-2.0-compatible -- Save to find out whether this item's current scope allows it.
          </p>
        )}
        {ackReason === "acknowledgement_required" && (
          <div data-testid="edit-content-license-ack-prompt" style={{ marginTop: "4px" }}>
            <p role="alert" style={{ color: "var(--eco-color-danger)", fontSize: "var(--eco-font-sizeXs)", margin: "0 0 6px" }}>
              License must be {ALLOWED_LICENSES_HINT}, or acknowledge you're responsible for complying with it.
            </p>
            <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "var(--eco-font-sizeXs)" }}>
              <input type="checkbox" data-testid="edit-content-license-acknowledge" checked={licenseAcknowledged} onChange={(e) => setLicenseAcknowledged(e.target.checked)} />
              I'm responsible for complying with this license
            </label>
          </div>
        )}
        {orgPolicyBlockedReason && (
          <p role="alert" data-testid="edit-content-org-policy-blocked" style={{ color: "var(--eco-color-danger)", fontSize: "var(--eco-font-sizeXs)", margin: "4px 0 0" }}>
            {orgPolicyBlockedReason}
          </p>
        )}
      </div>

      <div style={{ display: "flex", gap: "var(--eco-space-md)", minHeight: "360px" }}>
        <div data-testid="edit-content-file-tree" style={{ width: "200px", flexShrink: 0, borderRight: "1px solid var(--eco-color-border)", paddingRight: "var(--eco-space-sm)" }}>
          {files.map((file, i) => (
            <div key={file.name} style={{ display: "flex", alignItems: "center", gap: "4px" }}>
              {renaming === i ? (
                <>
                  <input
                    data-testid={`edit-content-rename-input-${i}`}
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") handleConfirmRename(); if (e.key === "Escape") setRenaming(null); }}
                    style={{ ...inputStyle, flex: 1, padding: "4px" }}
                    autoFocus
                  />
                  <button type="button" data-testid={`edit-content-rename-confirm-${i}`} onClick={handleConfirmRename} style={iconButtonStyle}>✓</button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    data-testid={`edit-content-file-${file.name}`}
                    onClick={() => setSelected(i)}
                    style={{
                      flex: 1, textAlign: "left", border: "none", cursor: "pointer",
                      padding: "6px 8px", borderRadius: "var(--eco-radius-sm)", fontFamily: "monospace",
                      fontSize: "var(--eco-font-sizeSm)",
                      color: selected === i ? "var(--eco-color-accentSkill)" : "var(--eco-color-textPrimary)",
                      background: selected === i ? "var(--eco-color-surface)" : "none",
                    }}
                  >
                    {file.name}
                  </button>
                  {i > 0 && (
                    <>
                      <button type="button" data-testid={`edit-content-rename-${i}`} title="Rename" onClick={() => handleStartRename(i)} style={iconButtonStyle}>
                        <PencilIcon width={14} height={14} aria-hidden="true" />
                      </button>
                      <button type="button" data-testid={`edit-content-delete-${i}`} title="Remove" onClick={() => handleDeleteFile(i)} style={iconButtonStyle}>
                        <TrashIcon width={14} height={14} aria-hidden="true" />
                      </button>
                    </>
                  )}
                </>
              )}
            </div>
          ))}
          {renameError && <p role="alert" style={{ color: "var(--eco-color-danger)", fontSize: "var(--eco-font-sizeXs)" }}>{renameError}</p>}

          {addingFile ? (
            <div style={{ display: "flex", gap: "4px", marginTop: "var(--eco-space-sm)" }}>
              <input
                data-testid="edit-content-new-file-name"
                value={newFileName}
                onChange={(e) => setNewFileName(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleAddFile(); if (e.key === "Escape") setAddingFile(false); }}
                placeholder="references/notes.md"
                style={{ ...inputStyle, flex: 1, padding: "4px" }}
                autoFocus
              />
              <button type="button" data-testid="edit-content-new-file-confirm" onClick={handleAddFile} style={iconButtonStyle}>✓</button>
            </div>
          ) : (
            <button
              type="button"
              data-testid="edit-content-add-file"
              onClick={() => { setAddingFile(true); setAddFileError(null); }}
              style={{ display: "flex", alignItems: "center", gap: "4px", marginTop: "var(--eco-space-sm)", background: "none", border: "1px dashed var(--eco-color-border)", borderRadius: "var(--eco-radius-md)", padding: "6px 8px", cursor: "pointer", color: "var(--eco-color-textSecondary)", fontSize: "var(--eco-font-sizeXs)", width: "100%" }}
            >
              <PlusIcon width={14} height={14} aria-hidden="true" /> Add file
            </button>
          )}
          {addFileError && <p role="alert" style={{ color: "var(--eco-color-danger)", fontSize: "var(--eco-font-sizeXs)" }}>{addFileError}</p>}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <CodeMirror
            data-testid="edit-content-editor"
            value={selectedFile.content}
            height="360px"
            theme={cmTheme}
            extensions={langExtension}
            onChange={updateSelectedContent}
            aria-label={`Editing ${selectedFile.name}`}
          />
        </div>
      </div>

      {saveError && <p role="alert" style={{ color: "var(--eco-color-danger)", marginTop: "var(--eco-space-md)" }}>{saveError}</p>}
      {saved && (
        <p role="status" data-testid="edit-content-saved-banner" style={{ color: "var(--eco-color-success)", marginTop: "var(--eco-space-md)" }}>
          Saved as a new version — it's now verifying. Check the Versions tab for its status.
        </p>
      )}

      <div style={{ marginTop: "var(--eco-space-md)" }}>
        <button
          type="button"
          data-testid="edit-content-save"
          disabled={saving || Boolean(validationError)}
          onClick={handleSave}
          style={{
            padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "none",
            background: "var(--eco-color-accentSkill)", color: "var(--eco-color-accentSkillText)",
            cursor: saving || validationError ? "default" : "pointer",
            opacity: saving || validationError ? 0.6 : 1,
          }}
        >
          {saving ? "Saving…" : "Save as new version"}
        </button>
      </div>
    </div>
  );
}

const inputStyle: CSSProperties = {
  width: "100%", padding: "8px", borderRadius: "var(--eco-radius-sm)", border: "1px solid var(--eco-color-border)",
  background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)", fontSize: "var(--eco-font-sizeSm)",
};
const iconButtonStyle: CSSProperties = {
  background: "none", border: "none", cursor: "pointer", color: "var(--eco-color-textSecondary)",
  display: "inline-flex", alignItems: "center", padding: "2px",
};
