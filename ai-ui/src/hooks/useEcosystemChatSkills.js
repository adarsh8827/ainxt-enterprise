// SPDX-License-Identifier: MIT
// Task F-11: fetches the installed-skill index for the chat "/" menu and
// "+" menu, from the real backend (GET /ecosystem/capabilities?surface=chat
// -- task B-11's resolver). Gated by a build-time flag so "flag off ->
// Chat.jsx behaves exactly as before" is provably true (zero extra
// network calls), matching the same VITE_* build-time-flag convention
// established for AgentStudio's CatalogPicker.jsx (task B-24) -- and the
// same fix for the same Vite gotcha: read as a function, not a
// module-level const, so it stays mockable in tests (vi.stubEnv() patches
// the live import.meta.env object, but only takes effect for reads that
// happen AFTER the stub, not for a const already evaluated at import time).
import { useEffect, useState } from "react";
import { API_BASE as API, authFetch } from "../config";

export function isEcosystemChatSkillsEnabled() {
  return import.meta.env.VITE_ECOSYSTEM_CHAT_SKILLS === "true";
}

/**
 * @returns {{ enabled: boolean, skills: Array<{namespace: string, display_name: string, description: string, slash_command: string}> }}
 */
export function useEcosystemChatSkills() {
  const enabled = isEcosystemChatSkillsEnabled();
  const [skills, setSkills] = useState([]);

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    const fetchSkills = () =>
      authFetch(`${API}/ecosystem/capabilities?surface=chat`)
        .then((r) => (r.ok ? r.json() : { skills: [] }))
        .then((d) => { if (!cancelled) setSkills(Array.isArray(d?.skills) ? d.skills : []); })
        .catch(() => { if (!cancelled) setSkills([]); });
    fetchSkills();

    // Item 6's own E2E requirement: "added in Marketplace -> appears in
    // chat '/' menu without reload." GET /ecosystem/events/stream (task
    // B-13) already broadcasts every ecosystem.changed event for the
    // caller's org over SSE; refetching capabilities on ANY event (rather
    // than trying to filter client-side for exactly which item/surface
    // changed) is the simplest correct response -- one extra GET per
    // change, not a new push-based skills subsystem. Uses the same
    // hand-rolled fetch+ReadableStream SSE parsing already established in
    // this codebase (CreateWithAiModal.jsx) since a plain EventSource
    // can't carry the Authorization header authFetch adds.
    let abort = new AbortController();
    (async () => {
      try {
        const resp = await authFetch(`${API}/ecosystem/events/stream`, { signal: abort.signal });
        if (!resp.ok || !resp.body) return;
        const reader = resp.body.getReader();
        const decoder = new TextDecoder("utf-8", { fatal: false });
        let buffer = "";
        while (!cancelled) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split("\n\n");
          buffer = parts.pop() ?? "";
          for (const part of parts) {
            const line = part.trim();
            if (!line.startsWith("data: ")) continue; // skip ": connected"/": ping" keep-alives
            fetchSkills();
          }
        }
      } catch {
        // Stream drop/abort -- the next mount (or a manual refresh) still
        // gets the current state via fetchSkills() above; not fatal.
      }
    })();

    return () => { cancelled = true; abort.abort(); };
  }, [enabled]);

  return { enabled, skills: enabled ? skills : [] };
}
