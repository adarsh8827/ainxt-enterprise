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
    authFetch(`${API}/ecosystem/capabilities?surface=chat`)
      .then((r) => (r.ok ? r.json() : { skills: [] }))
      .then((d) => { if (!cancelled) setSkills(Array.isArray(d?.skills) ? d.skills : []); })
      .catch(() => { if (!cancelled) setSkills([]); });
    return () => { cancelled = true; };
  }, [enabled]);

  return { enabled, skills: enabled ? skills : [] };
}
