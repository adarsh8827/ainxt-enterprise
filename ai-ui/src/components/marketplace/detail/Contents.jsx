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
import ReactMarkdown from "react-markdown";
import { EyeIcon, CodeBracketIcon } from "@heroicons/react/24/outline";
import { useHost } from "../lib/context/HostContext";
import "./markdown-body.css";
const SKILL_MD = "SKILL.md";
// Mirrors AgentStudio/backend/skill_factory/pipeline.py's own
// parse_frontmatter() exactly -- deliberately PyYAML-free, simple
// `key: value` line parsing only (that module's own documented reason:
// no heavier dependency for a handful of scalar fields). Kept as a
// separate, tiny client-side copy rather than a shared package, matching
// services/ecosystem/_agentstudio_interop.py's own precedent of never
// re-deriving that module's parsing rules -- there is no existing
// client-side equivalent to reuse (checked before writing this).
function parseSkillMdFrontmatter(content) {
  const trimmed = content.trim();
  const match = /^---\n([\s\S]*?)\n---/.exec(trimmed);
  if (!match) return {
    frontmatter: null,
    body: content
  };
  const frontmatter = {};
  for (const line of match[1].split("\n")) {
    const kv = /^(\w[\w-]*):\s*(.*)$/.exec(line);
    if (!kv) continue;
    const key = kv[1];
    const value = kv[2].trim().replace(/^["']|["']$/g, "");
    if (key === "name" || key === "description" || key === "license") frontmatter[key] = value;
  }
  const body = trimmed.slice(match[0].length).replace(/^\n+/, "");
  return {
    frontmatter,
    body
  };
}
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
function isMarkdown(name) {
  return name.toLowerCase().endsWith(".md");
}
function isDarkBackground(bgHex) {
  const hex = bgHex.replace("#", "");
  if (hex.length !== 6) return false;
  const r = parseInt(hex.slice(0, 2), 16);
  const g = parseInt(hex.slice(2, 4), 16);
  const b = parseInt(hex.slice(4, 6), 16);
  return (r * 299 + g * 587 + b * 114) / 1000 < 128;
}
export function Contents({
  item
}) {
  const theme = useHost().theme;
  const files = useMemo(() => manifestToFiles(item), [item]);
  const [selected, setSelected] = useState(0);
  // Default view depends on the FILE, so it must be re-derived whenever
  // the selection changes rather than staying pinned to whatever the
  // first file's default was.
  const [view, setView] = useState(isMarkdown(files[0].name) ? "preview" : "code");
  const [langExtension, setLangExtension] = useState([]);
  const selectedFile = files[selected] ?? files[0];
  const cmTheme = isDarkBackground(theme.color.bg) ? githubDark : githubLight;
  // Code/raw view always shows selectedFile.content untouched (the exact
  // file, frontmatter included) -- only Preview parses it, and only for
  // SKILL.md itself (frontmatter is that file's own convention, not a
  // generic bundled-reference-file one).
  const parsed = useMemo(() => selectedFile.name === SKILL_MD ? parseSkillMdFrontmatter(selectedFile.content) : {
    frontmatter: null,
    body: selectedFile.content
  }, [selectedFile]);
  const selectFile = index => {
    setSelected(index);
    setView(isMarkdown(files[index].name) ? "preview" : "code");
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
  return <div data-testid="detail-tab-contents">
      <div className="flex gap-4" style={{
      minHeight: "360px"
    }}>
        <div data-testid="contents-file-tree" className="w-[200px] flex-shrink-0 border-r border-gray-200 pr-2">
          {files.map((file, i) => <button key={file.name} type="button" data-testid={`contents-file-${file.name}`} onClick={() => selectFile(i)} className={["block w-full text-left border-none cursor-pointer px-2 py-1.5 rounded font-mono text-sm", selected === i ? "text-indigo-600 bg-gray-50" : "text-gray-900 bg-none"].join(" ")}>
              {file.name}
            </button>)}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex justify-end gap-1 mb-2">
            <button type="button" data-testid="contents-view-preview" title="Preview" aria-pressed={view === "preview"} onClick={() => setView("preview")} className={toggleButtonClass(view === "preview")}>
              <EyeIcon width={16} height={16} aria-hidden="true" />
            </button>
            <button type="button" data-testid="contents-view-code" title="Code" aria-pressed={view === "code"} onClick={() => setView("code")} className={toggleButtonClass(view === "code")}>
              <CodeBracketIcon width={16} height={16} aria-hidden="true" />
            </button>
          </div>

          {view === "preview" ? <div data-testid="contents-preview" className="p-4 bg-gray-50 rounded-md text-gray-900 text-sm">
              {selectedFile.name === SKILL_MD && parsed.frontmatter ? <>
                  <dl data-testid="contents-frontmatter" className="grid gap-x-2.5 gap-y-0.5 mb-4 pb-2 border-b border-gray-200 text-xs" style={{
              gridTemplateColumns: "auto 1fr"
            }}>
                    {parsed.frontmatter.name && <><dt className="text-gray-500">Name</dt><dd className="m-0">{parsed.frontmatter.name}</dd></>}
                    {parsed.frontmatter.description && <><dt className="text-gray-500">Description</dt><dd className="m-0">{parsed.frontmatter.description}</dd></>}
                    {parsed.frontmatter.license && <><dt className="text-gray-500">License</dt><dd className="m-0">{parsed.frontmatter.license}</dd></>}
                    <dt className="text-gray-500">Category</dt><dd className="m-0">{item.category}</dd>
                  </dl>
                  <div className="eco-markdown-body"><ReactMarkdown>{parsed.body || "No content."}</ReactMarkdown></div>
                </> : isMarkdown(selectedFile.name) ? <div className="eco-markdown-body"><ReactMarkdown>{selectedFile.content || "No content."}</ReactMarkdown></div> : <pre className="whitespace-pre-wrap m-0">{selectedFile.content || "No content."}</pre>}
            </div> : <CodeMirror data-testid="contents-code" value={selectedFile.content} height="360px" theme={cmTheme} extensions={langExtension} editable={false} aria-label={`${selectedFile.name}, read-only`} />}
        </div>
      </div>
    </div>;
}
function toggleButtonClass(active) {
  return ["inline-flex items-center justify-center w-[30px] h-[30px] rounded border border-gray-200 cursor-pointer", active ? "bg-gray-50 text-indigo-600" : "bg-white text-gray-500"].join(" ");
}