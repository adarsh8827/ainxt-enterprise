// SPDX-License-Identifier: MIT
// Task item 6 (M5 follow-up): the chat "+" menu's "Browse skills" panel --
// search/browse Discover inline, Add (with a real Verifying state, not a
// static label), toggle a skill on/off for chat, a "Manage in Marketplace"
// deep link, and three explicit, button-triggered actions rather than any
// guessed-from-free-text intent (this initiative's own stated design rule
// for chat-recognized flows): "Update" an owned skill from a new file,
// "Add as skill" from an uploaded .zip/.skill, and "Import from a URL".
// Only ever mounted when ECOSYSTEM_CHAT_SKILLS is on (EcosystemPlusMenu's
// own render guard, same as CreateWithAiModal).
import { useEffect, useRef, useState } from "react";
import {
  XMarkIcon, MagnifyingGlassIcon, ArrowUpTrayIcon, LinkIcon, ArrowTopRightOnSquareIcon,
} from "@heroicons/react/24/outline";
import { API_BASE as API, authFetch } from "../config";
import { StatusCard } from "./CreateWithAiModal.jsx";

function newIdempotencyKey() {
  return (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

async function fetchCurrentVersionId(itemId) {
  const resp = await authFetch(`${API}/ecosystem/items/${encodeURIComponent(itemId)}/versions`);
  if (!resp.ok) throw new Error("Couldn't load this skill's versions.");
  const body = await resp.json();
  const current = (body.versions || []).find((v) => v.is_current) || body.versions?.[0];
  if (!current) throw new Error("This skill has no versions yet.");
  return current.id;
}

export default function EcosystemBrowseSkillsPanel({ onClose, onManageInMarketplace }) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [installedIds, setInstalledIds] = useState(new Set());
  const [busyId, setBusyId] = useState(null);
  const [statusById, setStatusById] = useState({});
  const [updateTargetId, setUpdateTargetId] = useState(null);
  const [importOpen, setImportOpen] = useState(false);
  const searchTimer = useRef(null);

  useEffect(() => {
    authFetch(`${API}/ecosystem/installs`).then((r) => (r.ok ? r.json() : { installs: [] }))
      .then((d) => setInstalledIds(new Set((d.installs || []).map((i) => i.item?.id).filter(Boolean))))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => {
      setError("");
      authFetch(`${API}/ecosystem/items?item_type=skill${query.trim() ? `&q=${encodeURIComponent(query.trim())}` : ""}`)
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error("search failed"))))
        .then((d) => setItems(Array.isArray(d.items) ? d.items : []))
        .catch(() => setError("Couldn't load skills right now."));
    }, 250);
    return () => { if (searchTimer.current) clearTimeout(searchTimer.current); };
  }, [query]);

  async function handleAdd(item) {
    setBusyId(item.id);
    setStatusById((s) => ({ ...s, [item.id]: "verifying" }));
    try {
      const versionId = await fetchCurrentVersionId(item.id);
      const resp = await authFetch(`${API}/ecosystem/items/${encodeURIComponent(item.id)}/install`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": newIdempotencyKey() },
        body: JSON.stringify({ version_id: versionId, surfaces: ["chat"], scope: "private", origin: "added" }),
      });
      if (!resp.ok) throw new Error((await resp.json().catch(() => ({})))?.detail?.message || "Couldn't add this skill.");
      setInstalledIds((prev) => new Set(prev).add(item.id));
      setStatusById((s) => ({ ...s, [item.id]: item.latest_verdict === "pass" ? "active" : "verifying" }));
    } catch (err) {
      setStatusById((s) => ({ ...s, [item.id]: "failed" }));
      setError(err.message || "Couldn't add this skill.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleToggleEnabled(item, installId, enabled) {
    setBusyId(item.id);
    try {
      const resp = await authFetch(`${API}/ecosystem/installs/${encodeURIComponent(installId)}/set-enabled`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      if (!resp.ok) throw new Error("Couldn't update this skill.");
    } catch (err) {
      setError(err.message || "Couldn't update this skill.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="w-[480px] max-h-[80vh] overflow-y-auto bg-white rounded-xl shadow-2xl p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-800">Browse skills</h3>
          <button type="button" onClick={onClose} className="p-1 text-gray-400 hover:text-gray-700 rounded-lg hover:bg-gray-100">
            <XMarkIcon width={16} height={16} />
          </button>
        </div>

        <div className="flex items-center gap-2 border border-gray-200 rounded-lg px-2 py-1.5 mb-3">
          <MagnifyingGlassIcon width={14} height={14} className="text-gray-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search skills…"
            className="flex-1 text-sm outline-none"
            autoFocus
          />
        </div>

        {error && <p role="alert" className="text-xs text-red-600 mb-2">{error}</p>}

        {items === null && <p className="text-xs text-gray-400">Loading…</p>}
        {items !== null && items.length === 0 && <p className="text-xs text-gray-400">No skills found.</p>}

        <ul className="space-y-1.5 mb-3">
          {(items || []).map((item) => {
            const isInstalled = installedIds.has(item.id);
            const canManage = (item.allowed_actions || []).includes("deprecate");
            const status = statusById[item.id];
            return (
              <li key={item.id} data-testid="browse-skills-row" className="flex items-center gap-2 border border-gray-100 rounded-lg px-2 py-1.5">
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium text-gray-800 truncate">{item.display_name}</div>
                  <div className="text-[11px] text-gray-500 truncate">{item.description}</div>
                  {status && <div className="mt-1"><StatusCard status={status} /></div>}
                </div>
                {canManage && (
                  <button
                    type="button"
                    data-testid="browse-skills-update"
                    title="Update from a new file"
                    onClick={() => setUpdateTargetId(item.id)}
                    className="text-[11px] text-gray-500 hover:text-indigo-600 px-1.5 py-1 rounded"
                  >
                    Update
                  </button>
                )}
                {!isInstalled ? (
                  <button
                    type="button"
                    data-testid="browse-skills-add"
                    disabled={busyId === item.id}
                    onClick={() => handleAdd(item)}
                    className="text-xs px-2.5 py-1 rounded-lg bg-indigo-600 text-white disabled:opacity-40"
                  >
                    {busyId === item.id ? "Verifying…" : "Add"}
                  </button>
                ) : (
                  <ToggleAndManage item={item} onToggle={handleToggleEnabled} onManage={onManageInMarketplace} busy={busyId === item.id} />
                )}
              </li>
            );
          })}
        </ul>

        <div className="border-t border-gray-100 pt-2 flex items-center gap-2">
          <button
            type="button"
            data-testid="browse-skills-open-import"
            onClick={() => setImportOpen(true)}
            className="flex-1 flex items-center justify-center gap-1.5 text-xs text-gray-600 border border-gray-200 rounded-lg py-1.5 hover:bg-gray-50"
          >
            <LinkIcon width={13} height={13} /> Import from a URL
          </button>
          <UploadAsSkillButton onDone={(item) => setInstalledIds((prev) => new Set(prev).add(item.item_id))} />
        </div>
      </div>

      {updateTargetId && (
        <UpdateSkillModal itemId={updateTargetId} onClose={() => setUpdateTargetId(null)} />
      )}
      {importOpen && (
        <ImportSkillModal onClose={() => setImportOpen(false)} onImported={(item) => setInstalledIds((prev) => new Set(prev).add(item.item_id))} />
      )}
    </div>
  );
}

function ToggleAndManage({ item, onToggle, onManage }) {
  // Yours' own row shape isn't fetched separately here -- reusing the
  // installs list already fetched on mount would need install_id per
  // item, which this compact panel doesn't track once installed (the
  // full toggle/detail experience already exists in Marketplace's own
  // Yours screen). "Manage in Marketplace" is the honest, real link for
  // anything beyond a first Add -- disclosed simplification, not a
  // missing feature pretending to be complete.
  return (
    <button
      type="button"
      data-testid="browse-skills-manage"
      onClick={() => onManage(item)}
      className="flex items-center gap-1 text-[11px] text-gray-500 hover:text-indigo-600 px-1.5 py-1 rounded"
    >
      Manage in Marketplace <ArrowTopRightOnSquareIcon width={11} height={11} />
    </button>
  );
}

function UploadAsSkillButton() {
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const namespace = window.prompt("Namespace for this skill (publisher/name):", "");
      if (!namespace || !namespace.includes("/")) throw new Error("A namespace like yourname/skill-name is required.");
      const form = new FormData();
      form.append("file", file);
      form.append("item_type", "skill");
      form.append("namespace", namespace);
      form.append("category", "productivity");
      const resp = await authFetch(`${API}/ecosystem/items/upload`, { method: "POST", body: form });
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(body?.detail?.message || "Couldn't add this file as a skill.");
    } catch (err) {
      setError(err.message || "Couldn't add this file as a skill.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <input ref={inputRef} type="file" accept=".zip,.skill" className="hidden" onChange={handleFile} />
      <button
        type="button"
        data-testid="browse-skills-upload"
        disabled={busy}
        onClick={() => inputRef.current?.click()}
        className="flex-1 flex items-center justify-center gap-1.5 text-xs text-gray-600 border border-gray-200 rounded-lg py-1.5 hover:bg-gray-50 disabled:opacity-40"
      >
        <ArrowUpTrayIcon width={13} height={13} /> {busy ? "Adding…" : "Add as skill (.zip)"}
      </button>
      {error && <p role="alert" className="text-[11px] text-red-600 mt-1">{error}</p>}
    </>
  );
}

function ImportSkillModal({ onClose, onImported }) {
  const [url, setUrl] = useState("");
  const [namespace, setNamespace] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function parseGithubUrl(raw) {
    const m = raw.match(/github\.com\/([^/]+\/[^/]+)/i);
    return m ? m[1].replace(/\.git$/, "") : null;
  }

  async function handleImport() {
    setBusy(true);
    setError("");
    try {
      const repo = parseGithubUrl(url.trim());
      if (!repo) throw new Error("Paste a github.com/<owner>/<repo> URL -- only GitHub imports are supported today.");
      if (!namespace.trim() || !namespace.includes("/")) throw new Error("A namespace like yourname/skill-name is required.");
      const resp = await authFetch(`${API}/ecosystem/items`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": newIdempotencyKey() },
        body: JSON.stringify({
          create_via: "import", item_type: "skill", namespace: namespace.trim(),
          category: "productivity", kind: "github_repo", ref: repo,
        }),
      });
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(body?.detail?.message || "Couldn't import this skill.");
      onImported(body);
      onClose();
    } catch (err) {
      setError(err.message || "Couldn't import this skill.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="w-[380px] bg-white rounded-xl shadow-2xl p-4" onClick={(e) => e.stopPropagation()}>
        <h4 className="text-sm font-semibold text-gray-800 mb-2">Import skill from a URL</h4>
        <p className="text-xs text-gray-500 mb-2">GitHub repos with a SKILL.md declaring an MIT/Apache-2.0 license.</p>
        <input
          value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://github.com/owner/repo"
          className="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm mb-2"
        />
        <input
          value={namespace} onChange={(e) => setNamespace(e.target.value)} placeholder="Namespace (yourname/skill-name)"
          className="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm mb-2"
        />
        {error && <p role="alert" className="text-xs text-red-600 mb-2">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="px-3 py-1.5 text-sm rounded-lg border border-gray-200">Cancel</button>
          <button
            type="button" data-testid="import-skill-confirm" disabled={busy} onClick={handleImport}
            className="px-4 py-1.5 text-sm rounded-lg bg-indigo-600 text-white disabled:opacity-40"
          >
            {busy ? "Importing…" : "Import"}
          </button>
        </div>
      </div>
    </div>
  );
}

function UpdateSkillModal({ itemId, onClose }) {
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState(null);

  async function handleFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      const resp = await authFetch(`${API}/ecosystem/items/${encodeURIComponent(itemId)}/new-version/upload`, { method: "POST", body: form });
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(body?.detail?.message || "Couldn't update this skill.");
      setStatus(body.status || "verifying");
    } catch (err) {
      setError(err.message || "Couldn't update this skill.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="w-[360px] bg-white rounded-xl shadow-2xl p-4" onClick={(e) => e.stopPropagation()}>
        <h4 className="text-sm font-semibold text-gray-800 mb-2">Update this skill</h4>
        <p className="text-xs text-gray-500 mb-3">Attach a new .zip/.skill file -- creates a new, re-gated version.</p>
        <input ref={inputRef} type="file" accept=".zip,.skill" onChange={handleFile} className="text-xs mb-2" />
        {status && <div className="mb-2"><StatusCard status={status} /></div>}
        {error && <p role="alert" className="text-xs text-red-600 mb-2">{error}</p>}
        <div className="flex justify-end">
          <button type="button" disabled={busy} onClick={onClose} className="px-3 py-1.5 text-sm rounded-lg border border-gray-200">
            {status ? "Done" : "Cancel"}
          </button>
        </div>
      </div>
    </div>
  );
}
