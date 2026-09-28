// SPDX-License-Identifier: MIT
// Task F-11: the Create-with-AI staged flow -- intent -> SSE progress
// (task B-14's POST /ecosystem/drafts) -> preview/edit card -> confirm
// (PATCH + POST .../submit) -> status card. Only ever mounted when
// ECOSYSTEM_CHAT_SKILLS is on (Chat.jsx's own render guard); this
// component assumes that's already true.
import { useState } from "react";
import { XMarkIcon, SparklesIcon } from "@heroicons/react/24/outline";
import { API_BASE as API, authFetch } from "../config";

const PHASES = { INTENT: "intent", STREAMING: "streaming", PREVIEW: "preview", SUBMITTING: "submitting", DONE: "done", ERROR: "error" };

function newIdempotencyKey() {
  return (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export default function CreateWithAiModal({ onClose, onCreated, initialIntent }) {
  // initialIntent: item 6's "Save this as a skill" from a conversation --
  // seeds the intent textarea from the triggering message's own content
  // (an explicit user action, e.g. the message action bar's "Save as a
  // skill" button, never a guess at intent from free text) so the user
  // only has to review/edit it, not retype it from scratch.
  const [phase, setPhase] = useState(PHASES.INTENT);
  const [intent, setIntent] = useState(initialIntent || "");
  const [progressLines, setProgressLines] = useState([]);
  const [draftId, setDraftId] = useState(null);
  const [draftContent, setDraftContent] = useState(null);
  const [error, setError] = useState("");
  const [jobStatus, setJobStatus] = useState(null);

  async function handleGenerate() {
    const trimmed = intent.trim();
    if (!trimmed) return;
    setPhase(PHASES.STREAMING);
    setProgressLines([]);
    setError("");

    try {
      const resp = await authFetch(`${API}/ecosystem/drafts`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": newIdempotencyKey() },
        body: JSON.stringify({ item_type: "skill", intent: trimmed }),
      });
      if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder("utf-8", { fatal: false });
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data: ")) continue;
          let frame;
          try { frame = JSON.parse(line.slice(6)); } catch { continue; }

          if (frame.stage === "created") {
            setDraftId(frame.data?.draft_id || null);
          } else if (frame.stage === "error") {
            setError(frame.text || "Generation failed.");
            setPhase(PHASES.ERROR);
          } else if (frame.stage === "draft_ready") {
            setDraftContent(frame.data?.draft?.draft_content || null);
            setPhase(PHASES.PREVIEW);
          } else if (frame.text) {
            setProgressLines((prev) => [...prev, frame.text]);
          }
        }
      }
    } catch (err) {
      setError(err.message || "Couldn't generate a draft.");
      setPhase(PHASES.ERROR);
    }
  }

  function updateField(field, value) {
    setDraftContent((prev) => ({ ...(prev || {}), [field]: value }));
  }

  async function handleConfirm() {
    if (!draftId || !draftContent) return;
    setPhase(PHASES.SUBMITTING);
    setError("");
    try {
      const patchResp = await authFetch(`${API}/ecosystem/drafts/${draftId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          namespace: draftContent.namespace,
          display_name: draftContent.display_name,
          description: draftContent.description,
          category: draftContent.category,
          license: draftContent.license || "MIT",
        }),
      });
      if (!patchResp.ok) throw new Error("Couldn't save your edits.");

      const submitResp = await authFetch(`${API}/ecosystem/drafts/${draftId}/submit`, {
        method: "POST",
        headers: { "Idempotency-Key": newIdempotencyKey() },
      });
      const submitBody = await submitResp.json().catch(() => ({}));
      if (!submitResp.ok) throw new Error(submitBody?.detail?.message || "Couldn't save this skill.");

      setJobStatus({ status: submitBody.status || "verifying", jobId: submitBody.gate_run_id });
      setPhase(PHASES.DONE);
      if (onCreated) onCreated(submitBody);
    } catch (err) {
      setError(err.message || "Couldn't save this skill.");
      setPhase(PHASES.PREVIEW);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="w-[520px] max-h-[80vh] overflow-y-auto bg-white rounded-xl shadow-2xl p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-800">
            <SparklesIcon width={16} height={16} className="text-indigo-500" />
            Create a skill with AI
          </h3>
          <button type="button" onClick={onClose} className="p-1 text-gray-400 hover:text-gray-700 rounded-lg hover:bg-gray-100">
            <XMarkIcon width={16} height={16} />
          </button>
        </div>

        {phase === PHASES.INTENT && (
          <div>
            <p className="text-xs text-gray-500 mb-2">Describe what you want this skill to do.</p>
            <textarea
              value={intent}
              onChange={(e) => setIntent(e.target.value)}
              rows={4}
              autoFocus
              placeholder="e.g. Summarize meeting notes into action items with owners and deadlines"
              className="w-full resize-none border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-indigo-400"
            />
            <div className="flex justify-end mt-3">
              <button
                type="button"
                onClick={handleGenerate}
                disabled={!intent.trim()}
                className="px-4 py-1.5 text-sm rounded-lg bg-indigo-600 text-white disabled:opacity-40"
              >
                Generate
              </button>
            </div>
          </div>
        )}

        {phase === PHASES.STREAMING && (
          <div className="text-xs text-gray-600 space-y-1">
            {progressLines.map((line, i) => <div key={i}>{line}</div>)}
            {progressLines.length === 0 && <div>Starting…</div>}
          </div>
        )}

        {phase === PHASES.PREVIEW && draftContent && (
          <div className="space-y-2">
            <Field label="Name">
              <input value={draftContent.display_name || ""} onChange={(e) => updateField("display_name", e.target.value)} className="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm" />
            </Field>
            <Field label="Description">
              <textarea value={draftContent.description || ""} onChange={(e) => updateField("description", e.target.value)} rows={2} className="w-full resize-none border border-gray-200 rounded-lg px-2 py-1.5 text-sm" />
            </Field>
            <Field label="Namespace (publisher/name)">
              <input value={draftContent.namespace || ""} onChange={(e) => updateField("namespace", e.target.value)} className="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm" />
            </Field>
            <Field label="License">
              <select value={draftContent.license || "MIT"} onChange={(e) => updateField("license", e.target.value)} className="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm">
                <option value="MIT">MIT</option>
                <option value="Apache-2.0">Apache-2.0</option>
              </select>
            </Field>
            <details className="text-xs text-gray-500">
              <summary className="cursor-pointer">Instructions preview</summary>
              <pre className="whitespace-pre-wrap mt-1 bg-gray-50 rounded-lg p-2 max-h-40 overflow-y-auto">{draftContent.instructions}</pre>
            </details>
            <div className="flex justify-end gap-2 pt-2">
              <button type="button" onClick={onClose} className="px-3 py-1.5 text-sm rounded-lg border border-gray-200">Cancel</button>
              <button
                type="button"
                onClick={handleConfirm}
                disabled={!draftContent.namespace}
                className="px-4 py-1.5 text-sm rounded-lg bg-indigo-600 text-white disabled:opacity-40"
              >
                Save Skill
              </button>
            </div>
          </div>
        )}

        {phase === PHASES.SUBMITTING && <div className="text-xs text-gray-500">Saving…</div>}

        {phase === PHASES.DONE && jobStatus && (
          <div className="text-sm">
            <StatusCard status={jobStatus.status} />
            <div className="flex justify-end mt-3">
              <button type="button" onClick={onClose} className="px-4 py-1.5 text-sm rounded-lg bg-indigo-600 text-white">Done</button>
            </div>
          </div>
        )}

        {phase === PHASES.ERROR && (
          <div>
            <p className="text-xs text-red-600 mb-2">{error}</p>
            <button type="button" onClick={() => setPhase(PHASES.INTENT)} className="px-3 py-1.5 text-sm rounded-lg border border-gray-200">Try again</button>
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="block text-[11px] text-gray-500 mb-0.5">{label}</span>
      {children}
    </label>
  );
}

/** Status card: verifying/private/shared/org/warning/blocked+reason
 * (task F-11's own spec). `status` here is the async-envelope value
 * (CONTRACTS.md §5): "verifying"|"active"|"warn"|"blocked"|"failed". */
export function StatusCard({ status, reason }) {
  const map = {
    verifying: { label: "Verifying…", color: "text-blue-600 bg-blue-50" },
    active: { label: "Live", color: "text-green-700 bg-green-50" },
    warn: { label: "Live with a warning", color: "text-amber-700 bg-amber-50" },
    blocked: { label: "Blocked", color: "text-red-700 bg-red-50" },
    failed: { label: "Failed", color: "text-red-700 bg-red-50" },
  };
  const entry = map[status] || map.verifying;
  return (
    <div className={`rounded-lg px-3 py-2 ${entry.color}`}>
      <div className="font-medium">{entry.label}</div>
      {reason && <div className="text-xs mt-0.5">{reason}</div>}
    </div>
  );
}
