// SPDX-License-Identifier: MIT
// Read-only file browser for an item's pinned version -- SKILL.md +
// any bundled files, full content already embedded in the manifest (no
// extra fetch needed). Was a bare <pre> dump of instructions plus a
// plain filename list with no content shown for bundled files at all;
// rebuilt as a two-pane file-tree + viewer with a preview/code toggle,
// matching the same file-tree pattern EditContent.tsx already uses for
// an owned item's editor, but read-only (no add/rename/delete). No
// execution happens here either way; this is a view, not the runtime
// path (skill_view/read_skill_file, task B-15, is that).
import { useEffect, useMemo, useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { githubDark, githubLight } from "@uiw/codemirror-theme-github";
import { LanguageDescription } from "@codemirror/language";
import { languages } from "@codemirror/language-data";
import type { Extension } from "@codemirror/state";
import ReactMarkdown from "react-markdown";
import { EyeIcon, CodeBracketIcon } from "@heroicons/react/24/outline";
import type { ItemDetail } from "../../types";
import { useHost } from "../../context/HostContext";

const SKILL_MD = "SKILL.md";

interface ContentFile {
  name: string;
  content: string;
}

interface ParsedSkillMd {
  frontmatter: { name?: string; description?: string; license?: string } | null;
  body: string;
}

// Mirrors AgentStudio/backend/skill_factory/pipeline.py's own
// parse_frontmatter() exactly -- deliberately PyYAML-free, simple
// `key: value` line parsing only (that module's own documented reason:
// no heavier dependency for a handful of scalar fields). Kept as a
// separate, tiny client-side copy rather than a shared package, matching
// services/ecosystem/_agentstudio_interop.py's own precedent of never
// re-deriving that module's parsing rules -- there is no existing
// client-side equivalent to reuse (checked before writing this).
function parseSkillMdFrontmatter(content: string): ParsedSkillMd {
  const trimmed = content.trim();
  const match = /^---\n([\s\S]*?)\n---/.exec(trimmed);
  if (!match) return { frontmatter: null, body: content };

  const frontmatter: { name?: string; description?: string; license?: string } = {};
  for (const line of match[1]!.split("\n")) {
    const kv = /^(\w[\w-]*):\s*(.*)$/.exec(line);
    if (!kv) continue;
    const key = kv[1]!;
    const value = kv[2]!.trim().replace(/^["']|["']$/g, "");
    if (key === "name" || key === "description" || key === "license") frontmatter[key] = value;
  }
  const body = trimmed.slice(match[0].length).replace(/^\n+/, "");
  return { frontmatter, body };
}

function manifestToFiles(item: ItemDetail): ContentFile[] {
  const manifest = item.manifest as { instructions?: string; files?: Record<string, string> };
  const bundled = Object.entries(manifest.files ?? {}).map(([name, content]) => ({ name, content }));
  return [{ name: SKILL_MD, content: manifest.instructions ?? "" }, ...bundled];
}

function isMarkdown(name: string): boolean {
  return name.toLowerCase().endsWith(".md");
}

function isDarkBackground(bgHex: string): boolean {
  const hex = bgHex.replace("#", "");
  if (hex.length !== 6) return false;
  const r = parseInt(hex.slice(0, 2), 16);
  const g = parseInt(hex.slice(2, 4), 16);
  const b = parseInt(hex.slice(4, 6), 16);
  return (r * 299 + g * 587 + b * 114) / 1000 < 128;
}

type ViewMode = "preview" | "code";

export function Contents({ item }: { item: ItemDetail }) {
  const theme = useHost().theme;
  const files = useMemo(() => manifestToFiles(item), [item]);
  const [selected, setSelected] = useState(0);
  // Default view depends on the FILE, so it must be re-derived whenever
  // the selection changes rather than staying pinned to whatever the
  // first file's default was.
  const [view, setView] = useState<ViewMode>(isMarkdown(files[0]!.name) ? "preview" : "code");
  const [langExtension, setLangExtension] = useState<Extension[]>([]);

  const selectedFile = files[selected] ?? files[0]!;
  const cmTheme = isDarkBackground(theme.color.bg) ? githubDark : githubLight;
  // Code/raw view always shows selectedFile.content untouched (the exact
  // file, frontmatter included) -- only Preview parses it, and only for
  // SKILL.md itself (frontmatter is that file's own convention, not a
  // generic bundled-reference-file one).
  const parsed = useMemo(
    () => (selectedFile.name === SKILL_MD ? parseSkillMdFrontmatter(selectedFile.content) : { frontmatter: null, body: selectedFile.content }),
    [selectedFile],
  );

  const selectFile = (index: number) => {
    setSelected(index);
    setView(isMarkdown(files[index]!.name) ? "preview" : "code");
  };

  useEffect(() => {
    let cancelled = false;
    const desc = LanguageDescription.matchFilename(languages, selectedFile.name);
    if (!desc) { setLangExtension([]); return; }
    desc.load().then((support) => { if (!cancelled) setLangExtension([support]); });
    return () => { cancelled = true; };
  }, [selectedFile.name]);

  return (
    <div data-testid="detail-tab-contents">
      <div style={{ display: "flex", gap: "var(--eco-space-md)", minHeight: "360px" }}>
        <div data-testid="contents-file-tree" style={{ width: "200px", flexShrink: 0, borderRight: "1px solid var(--eco-color-border)", paddingRight: "var(--eco-space-sm)" }}>
          {files.map((file, i) => (
            <button
              key={file.name}
              type="button"
              data-testid={`contents-file-${file.name}`}
              onClick={() => selectFile(i)}
              style={{
                display: "block", width: "100%", textAlign: "left", border: "none", cursor: "pointer",
                padding: "6px 8px", borderRadius: "var(--eco-radius-sm)", fontFamily: "monospace",
                fontSize: "var(--eco-font-sizeSm)",
                color: selected === i ? "var(--eco-color-accentSkill)" : "var(--eco-color-textPrimary)",
                background: selected === i ? "var(--eco-color-surface)" : "none",
              }}
            >
              {file.name}
            </button>
          ))}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: "4px", marginBottom: "var(--eco-space-sm)" }}>
            <button
              type="button"
              data-testid="contents-view-preview"
              title="Preview"
              aria-pressed={view === "preview"}
              onClick={() => setView("preview")}
              style={toggleButtonStyle(view === "preview")}
            >
              <EyeIcon width={16} height={16} aria-hidden="true" />
            </button>
            <button
              type="button"
              data-testid="contents-view-code"
              title="Code"
              aria-pressed={view === "code"}
              onClick={() => setView("code")}
              style={toggleButtonStyle(view === "code")}
            >
              <CodeBracketIcon width={16} height={16} aria-hidden="true" />
            </button>
          </div>

          {view === "preview" ? (
            <div
              data-testid="contents-preview"
              style={{ padding: "var(--eco-space-md)", background: "var(--eco-color-surface)", borderRadius: "var(--eco-radius-md)", color: "var(--eco-color-textPrimary)", fontSize: "var(--eco-font-sizeSm)" }}
            >
              {selectedFile.name === SKILL_MD && parsed.frontmatter ? (
                <>
                  <dl data-testid="contents-frontmatter" style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "2px 10px", margin: "0 0 var(--eco-space-md)", paddingBottom: "var(--eco-space-sm)", borderBottom: "1px solid var(--eco-color-border)", fontSize: "var(--eco-font-sizeXs)" }}>
                    {parsed.frontmatter.name && (<><dt style={{ color: "var(--eco-color-textSecondary)" }}>Name</dt><dd style={{ margin: 0 }}>{parsed.frontmatter.name}</dd></>)}
                    {parsed.frontmatter.description && (<><dt style={{ color: "var(--eco-color-textSecondary)" }}>Description</dt><dd style={{ margin: 0 }}>{parsed.frontmatter.description}</dd></>)}
                    {parsed.frontmatter.license && (<><dt style={{ color: "var(--eco-color-textSecondary)" }}>License</dt><dd style={{ margin: 0 }}>{parsed.frontmatter.license}</dd></>)}
                    <dt style={{ color: "var(--eco-color-textSecondary)" }}>Category</dt><dd style={{ margin: 0 }}>{item.category}</dd>
                  </dl>
                  <ReactMarkdown>{parsed.body || "No content."}</ReactMarkdown>
                </>
              ) : isMarkdown(selectedFile.name) ? (
                <ReactMarkdown>{selectedFile.content || "No content."}</ReactMarkdown>
              ) : (
                <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{selectedFile.content || "No content."}</pre>
              )}
            </div>
          ) : (
            <CodeMirror
              data-testid="contents-code"
              value={selectedFile.content}
              height="360px"
              theme={cmTheme}
              extensions={langExtension}
              editable={false}
              aria-label={`${selectedFile.name}, read-only`}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function toggleButtonStyle(active: boolean) {
  return {
    display: "inline-flex", alignItems: "center", justifyContent: "center",
    width: "30px", height: "30px", borderRadius: "var(--eco-radius-sm)",
    border: "1px solid var(--eco-color-border)", cursor: "pointer",
    background: active ? "var(--eco-color-surface)" : "var(--eco-color-bg)",
    color: active ? "var(--eco-color-accentSkill)" : "var(--eco-color-textSecondary)",
  };
}
