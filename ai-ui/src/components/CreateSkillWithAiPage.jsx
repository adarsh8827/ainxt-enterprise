// SPDX-License-Identifier: MIT
// Task F-11, page conversion (user-flow QA round 2, 2026-10-03): this used
// to be CreateWithAiModal.jsx, a fixed-overlay modal with a backdrop-click
// and an X button that both called onClose with zero in-flight guard --
// clicking either mid-generation (SSE streaming) or mid-save (PATCH+POST)
// silently discarded everything, no confirmation, no warning. Converted to
// a real routed page instead, matching "Write a skill"'s own page-based
// flow (CreateForm.tsx, reached at /marketplace/skills/new) -- no backdrop
// to misclick, no X button, a window.onbeforeunload guard during the two
// risky phases (STREAMING/SUBMITTING) for tab-close/refresh. The internal
// phase state machine and fetch logic are unchanged from the modal version
// (it works correctly, verified live) -- only the chrome changed.
//
// Moved from a bare top-level /create-skill-with-ai to
// /marketplace/skills/new/ai in round 8 (2026-10-03, real user question:
// "it should be conditional rendering like Write skill or upload skill,
// not a new url") -- see App.jsx's own Route comment for the full
// reasoning, including a second, separate sidebar-highlighting bug this
// fixed for free. Still rendered by ai-ui directly (not folded into the
// marketplace package's own RouteSwitch) -- the package has no LLM-backed
// drafting UI of its own, by design (same reason onCreateWithAi is a
// host-supplied callback at all).
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { SparklesIcon } from "@heroicons/react/24/outline";
import { API_BASE as API, authFetch } from "../config";
import { useConfirm } from "./ui/DialogProvider";
import { setNavigationGuard, clearNavigationGuard } from "../navigationGuard";

const PHASES = { INTENT: "intent", STREAMING: "streaming", PREVIEW: "preview", SUBMITTING: "submitting", DONE: "done", ERROR: "error" };
const IN_FLIGHT_PHASES = [PHASES.STREAMING, PHASES.SUBMITTING];

function newIdempotencyKey() {
  return (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export default function CreateSkillWithAiPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { confirm } = useConfirm();
  // initialIntent: "Save this as a skill" seeds the intent from the
  // triggering message's own content, passed via navigate(path, { state })
  // since this is now a real route, not a prop (mirrors the modal
  // version's own initialIntent prop, same source: Chat.jsx's message
  // action bar).
  const initialIntent = location.state?.initialIntent || "";

  const [phase, setPhase] = useState(PHASES.INTENT);
  const [intent, setIntent] = useState(initialIntent);
  const [progressLines, setProgressLines] = useState([]);
  const [draftId, setDraftId] = useState(null);
  const [draftContent, setDraftContent] = useState(null);
  const [error, setError] = useState("");
  const [jobStatus, setJobStatus] = useState(null);

  // Tab close/refresh during generation or save would otherwise silently
  // lose the in-progress draft with no warning at all -- the same class of
  // gap the backdrop/X removal above fixes for in-app navigation.
  useEffect(() => {
    function handleBeforeUnload(e) {
      if (!IN_FLIGHT_PHASES.includes(phase)) return;
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [phase]);

  function goToSkills() {
    navigate("/marketplace/skills");
  }

  // `phase` closed over directly would go stale the instant this function
  // reference is captured once below (navigationGuard registers it on
  // mount, not on every phase change) -- a ref always reads the CURRENT
  // phase at the moment a sidebar click actually happens.
  const phaseRef = useRef(phase);
  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  async function confirmLeaveIfInFlight() {
    if (!IN_FLIGHT_PHASES.includes(phaseRef.current)) return true;
    return await confirm({
      title: "Leave without saving?",
      message: "This skill is still being generated. Leaving now will lose this draft.",
      confirmLabel: "Leave",
      variant: "danger",
    });
  }

  async function handleLeave() {
    const ok = await confirmLeaveIfInFlight();
    if (!ok) return;
    goToSkills();
  }

  // User-flow QA round 8 (2026-10-03, real user question: "user clicks
  // any other sidemenu, what will happen?"): registers this page's own
  // leave-guard with App.jsx's setView() -- see navigationGuard.js's own
  // header comment for why a shared module, not react-router's useBlocker,
  // is what's used here. Registered once (confirmLeaveIfInFlight reads
  // phaseRef, not phase, so it never goes stale) and cleared on unmount so
  // leaving this page any other way doesn't leave a stale guard blocking
  // every future navigation in the app.
  useEffect(() => {
    setNavigationGuard(confirmLeaveIfInFlight);
    return () => clearNavigationGuard();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- confirmLeaveIfInFlight closes over `confirm` (from context) and phaseRef (a stable ref object); registering once on mount is correct, not stale.
  }, []);

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
    } catch (err) {
      setError(err.message || "Couldn't save this skill.");
      setPhase(PHASES.PREVIEW);
    }
  }

  // pb-48 safe-area slack -- see Marketplace.jsx's own comment (round 6,
  // 2026-10-03): guarantees scrollable room past the last element so a
  // viewport-height edge case (e.g. the OS taskbar overlapping the
  // browser's reported content area) never eats the final buttons.
  return (
    <div className="h-full overflow-y-auto px-6 pt-6 pb-48">
      <div className="max-w-[640px]">
        <div className="flex items-center gap-2 mb-5">
          <SparklesIcon width={20} height={20} className="text-indigo-500" />
          <h2 className="text-xl font-semibold text-gray-900">Create a skill with AI</h2>
        </div>

        {phase === PHASES.INTENT && (
          <div>
            <p className="text-sm text-gray-500 mb-2">Describe what you want this skill to do.</p>
            <textarea
              value={intent}
              onChange={(e) => setIntent(e.target.value)}
              rows={5}
              autoFocus
              placeholder="e.g. Summarize meeting notes into action items with owners and deadlines"
              className="w-full resize-none border border-gray-200 rounded-lg p-3 text-sm outline-none focus:border-indigo-400"
            />
            <div className="flex justify-end gap-2 mt-4">
              <button type="button" onClick={goToSkills} className="px-4 py-2 text-sm font-medium rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-100">
                Cancel
              </button>
              <button
                type="button"
                onClick={handleGenerate}
                disabled={!intent.trim()}
                className="px-4 py-2 text-sm font-medium rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 disabled:hover:bg-indigo-600"
              >
                Generate
              </button>
            </div>
          </div>
        )}

        {phase === PHASES.STREAMING && (
          <div>
            <div className="text-sm text-gray-600 space-y-1 mb-4">
              {progressLines.map((line, i) => <div key={i}>{line}</div>)}
              {progressLines.length === 0 && <div>Starting…</div>}
            </div>
            <button type="button" onClick={handleLeave} className="px-4 py-2 text-sm font-medium rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-100">
              Cancel
            </button>
          </div>
        )}

        {phase === PHASES.PREVIEW && draftContent && (
          <div className="space-y-3">
            <Field label="Name">
              <input value={draftContent.display_name || ""} onChange={(e) => updateField("display_name", e.target.value)} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
            </Field>
            <Field label="Description">
              <textarea value={draftContent.description || ""} onChange={(e) => updateField("description", e.target.value)} rows={2} className="w-full resize-none border border-gray-200 rounded-lg px-3 py-2 text-sm" />
            </Field>
            <Field label="Namespace (publisher/name)">
              <input value={draftContent.namespace || ""} onChange={(e) => updateField("namespace", e.target.value)} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
            </Field>
            <Field label="License">
              <select value={draftContent.license || "MIT"} onChange={(e) => updateField("license", e.target.value)} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm">
                <option value="MIT">MIT</option>
                <option value="Apache-2.0">Apache-2.0</option>
              </select>
            </Field>
            <details className="text-xs text-gray-500">
              <summary className="cursor-pointer">Instructions preview</summary>
              <pre className="whitespace-pre-wrap mt-1 bg-gray-50 rounded-lg p-2 max-h-40 overflow-y-auto">{draftContent.instructions}</pre>
            </details>
            {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
            <div className="flex justify-end gap-2 pt-2">
              <button type="button" onClick={goToSkills} className="px-4 py-2 text-sm font-medium rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-100">Cancel</button>
              <button
                type="button"
                onClick={handleConfirm}
                disabled={!draftContent.namespace}
                className="px-4 py-2 text-sm font-medium rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 disabled:hover:bg-indigo-600"
              >
                Save Skill
              </button>
            </div>
          </div>
        )}

        {phase === PHASES.SUBMITTING && <div className="text-sm text-gray-500">Saving…</div>}

        {phase === PHASES.DONE && jobStatus && (
          <div className="text-sm">
            <StatusCard status={jobStatus.status} />
            <div className="flex justify-end mt-4">
              <button type="button" onClick={goToSkills} className="px-4 py-2 text-sm font-medium rounded-lg bg-indigo-600 text-white hover:bg-indigo-700">Done</button>
            </div>
          </div>
        )}

        {phase === PHASES.ERROR && (
          <div>
            <p className="text-sm text-red-600 mb-3">{error}</p>
            <div className="flex gap-2">
              <button type="button" onClick={() => setPhase(PHASES.INTENT)} className="px-4 py-2 text-sm font-medium rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-100">Try again</button>
              <button type="button" onClick={goToSkills} className="px-4 py-2 text-sm font-medium rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-100">Cancel</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="block text-sm text-gray-500 mb-1">{label}</span>
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
