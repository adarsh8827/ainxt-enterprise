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
import { SparklesIcon, ArrowLeftIcon } from "@heroicons/react/24/outline";
import { API_BASE as API, authFetch } from "../config";
import { useConfirm, useToast } from "./ui/DialogProvider";
import { setNavigationGuard, clearNavigationGuard } from "../navigationGuard";

const PHASES = { INTENT: "intent", STREAMING: "streaming", PREVIEW: "preview", SUBMITTING: "submitting", DONE: "done", ERROR: "error" };
const IN_FLIGHT_PHASES = [PHASES.STREAMING, PHASES.SUBMITTING];

// Premium-pass (2026-10-05, explicit product ask: "Add button forms...
// need a proper design UI UX premium experience"): this page predates
// marketplace/Button.jsx and hand-rolled its own button classes --
// `rounded-lg` + flat `bg-indigo-600` instead of this app's real
// `rounded` + `brand-grad` primary-button convention every OTHER
// create-flow (CreateForm/UploadFlow/ImportFlow, all via Button.jsx) now
// uses. This page lives outside the marketplace package (a host-level
// route, not part of the portable package), so it matches those exact
// classes locally rather than importing a package-internal component
// across that boundary.
const PRIMARY_BTN_CLASS = "inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded text-sm font-medium transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-default text-white brand-grad hover:opacity-70";
const SECONDARY_BTN_CLASS = "inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded text-sm font-medium transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-default text-gray-700 bg-white border border-gray-300 hover:bg-gray-100";

function newIdempotencyKey() {
  return (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export default function CreateSkillWithAiPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { confirm } = useConfirm();
  const { toast } = useToast();
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
      // Real bug found live (2026-10-06, user report): Create-with-AI's
      // own draft-submit goes through the same fast-path gate as Write
      // for a private, no-files skill -- the real verdict is already
      // known here, but this always showed a plain success toast
      // regardless of it. See CreateForm.jsx's identical fix for the
      // full rationale.
      if (submitBody.status === "blocked") {
        toast.error(`"${draftContent.display_name}" failed verification — check the Verification tab for details.`);
      } else {
        toast.success(`"${draftContent.display_name}" created.`);
      }
    } catch (err) {
      const message = err.message || "Couldn't save this skill.";
      setError(message);
      setPhase(PHASES.PREVIEW);
      toast.error(message);
    }
  }

  // pb-48 safe-area slack -- see Marketplace.jsx's own comment (round 6,
  // 2026-10-03): guarantees scrollable room past the last element so a
  // viewport-height edge case (e.g. the OS taskbar overlapping the
  // browser's reported content area) never eats the final buttons.
  return (
    <div className="h-full overflow-y-auto px-6 pt-6 pb-48">
      <div className="max-w-[640px]">
        {!IN_FLIGHT_PHASES.includes(phase) && (
          <button type="button" onClick={handleLeave} className="inline-flex items-center gap-1.5 bg-none border-none cursor-pointer text-gray-500 hover:text-gray-700 mb-4 transition-colors">
            <ArrowLeftIcon width={16} height={16} aria-hidden="true" /> Back
          </button>
        )}
        <div className="flex items-center gap-2 mb-1">
          <SparklesIcon width={20} height={20} className="text-indigo-500" />
          <h2 className="text-xl font-semibold text-gray-900 m-0">Create a skill with AI</h2>
        </div>
        <p className="text-sm text-gray-500 mt-0 mb-5">Describe what you want, review the draft, then publish.</p>

        {phase === PHASES.INTENT && (
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">What should this skill do?</label>
            <textarea
              value={intent}
              onChange={(e) => setIntent(e.target.value)}
              rows={5}
              autoFocus
              placeholder="e.g. Summarize meeting notes into action items with owners and deadlines"
              className="w-full resize-none border border-gray-300 rounded px-3 py-2 text-sm text-gray-900 outline-none focus:border-indigo-300"
            />
            <div className="flex justify-end gap-2 mt-4">
              <button type="button" onClick={goToSkills} className={SECONDARY_BTN_CLASS}>
                Cancel
              </button>
              <button
                type="button"
                onClick={handleGenerate}
                disabled={!intent.trim()}
                className={PRIMARY_BTN_CLASS}
              >
                Generate
              </button>
            </div>
          </div>
        )}

        {phase === PHASES.STREAMING && (
          <div>
            {/* Premium-pass (2026-10-05): plain stacked text lines read as
                a debug log, not a premium "working on it" moment -- a
                spinner + the latest line leading, with earlier lines
                still visible but muted, reads as real progress instead. */}
            <div className="flex items-center gap-2 text-sm text-gray-700 mb-2">
              <svg className="animate-spin text-indigo-500" width={16} height={16} viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.25" />
                <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
              </svg>
              <span className="font-medium">{progressLines[progressLines.length - 1] || "Starting…"}</span>
            </div>
            {progressLines.length > 1 && <div className="text-xs text-gray-400 space-y-0.5 mb-4 ml-6">
                {progressLines.slice(0, -1).map((line, i) => <div key={i}>{line}</div>)}
              </div>}
            <button type="button" onClick={handleLeave} className={SECONDARY_BTN_CLASS}>
              Cancel
            </button>
          </div>
        )}

        {phase === PHASES.PREVIEW && draftContent && (
          <div>
            <h3 className="text-sm font-semibold text-gray-800 mt-0 mb-3">Review the draft</h3>
            <div className="space-y-3">
              <Field label="Name">
                <input value={draftContent.display_name || ""} onChange={(e) => updateField("display_name", e.target.value)} className="w-full bg-white border border-gray-300 rounded px-3 py-2 text-sm text-gray-900 outline-none focus:border-indigo-300" />
              </Field>
              <Field label="Description">
                <textarea value={draftContent.description || ""} onChange={(e) => updateField("description", e.target.value)} rows={2} className="w-full resize-none bg-white border border-gray-300 rounded px-3 py-2 text-sm text-gray-900 outline-none focus:border-indigo-300" />
              </Field>
              <Field label="Namespace (publisher/name)">
                <input value={draftContent.namespace || ""} onChange={(e) => updateField("namespace", e.target.value)} className="w-full bg-white border border-gray-300 rounded px-3 py-2 text-sm text-gray-900 outline-none focus:border-indigo-300" />
              </Field>
              <Field label="License">
                <select value={draftContent.license || "MIT"} onChange={(e) => updateField("license", e.target.value)} className="w-full bg-white border border-gray-300 rounded px-3 py-2 text-sm text-gray-900 outline-none focus:border-indigo-300">
                  <option value="MIT">MIT</option>
                  <option value="Apache-2.0">Apache-2.0</option>
                </select>
              </Field>
              <details className="text-xs text-gray-500">
                <summary className="cursor-pointer">Instructions preview</summary>
                <pre className="whitespace-pre-wrap mt-1 bg-gray-50 border border-gray-200 rounded-md p-2 max-h-40 overflow-y-auto">{draftContent.instructions}</pre>
              </details>
            </div>
            {error && <p role="alert" className="bg-red-50 text-red-700 border border-red-200 rounded-md px-3 py-2 text-sm mt-3">{error}</p>}
            <div className="flex justify-end gap-2 mt-6 pt-5 border-t border-gray-100">
              <button type="button" onClick={goToSkills} className={SECONDARY_BTN_CLASS}>Cancel</button>
              <button
                type="button"
                onClick={handleConfirm}
                disabled={!draftContent.namespace}
                className={PRIMARY_BTN_CLASS}
              >
                Save Skill
              </button>
            </div>
          </div>
        )}

        {phase === PHASES.SUBMITTING && (
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <svg className="animate-spin text-indigo-500" width={16} height={16} viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.25" />
              <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
            </svg>
            Saving…
          </div>
        )}

        {phase === PHASES.DONE && jobStatus && (
          <div className="text-sm">
            <StatusCard status={jobStatus.status} />
            <div className="flex justify-end mt-4">
              <button type="button" onClick={goToSkills} className={PRIMARY_BTN_CLASS}>Done</button>
            </div>
          </div>
        )}

        {phase === PHASES.ERROR && (
          <div>
            <p role="alert" className="bg-red-50 text-red-700 border border-red-200 rounded-md px-3 py-2 text-sm mb-4">{error}</p>
            <div className="flex gap-2">
              <button type="button" onClick={() => setPhase(PHASES.INTENT)} className={SECONDARY_BTN_CLASS}>Try again</button>
              <button type="button" onClick={goToSkills} className={SECONDARY_BTN_CLASS}>Cancel</button>
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
      <span className="block text-xs font-medium text-gray-600 mb-1">{label}</span>
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
