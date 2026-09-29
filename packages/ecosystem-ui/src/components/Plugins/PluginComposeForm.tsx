// SPDX-License-Identifier: MIT
// Admin authoring form: pick existing items to bundle into a plugin via
// POST /ecosystem/items/{id}/plugin-compose (docs/ecosystem/
// PLUGINS_PHASE_PLAN.md §4). Only skills/connectors/mcp_servers are
// pickable here -- those are the three part kinds with a real EcosystemItem
// source to list from (`GET /ecosystem/items?item_type=...`); commands/
// agents/hooks have no such catalog anywhere in this codebase to pick from
// (confirmed: neither is an ItemType), so this form submits them as empty
// arrays rather than fabricating a picker for data that doesn't exist yet.
//
// Not self-gated to admins -- matches AdvancedMcpServers.tsx's own
// established precedent (docs/ecosystem/CONNECTORS_PHASE_PLAN.md §1 item 6's
// comment on TypeTabs.tsx): no backend "policy allows this" signal exists
// as a config field yet, so the HOST is responsible for only rendering this
// form for an admin/developer, same as that component.
import { useEffect, useState } from "react";
import type { ItemSummary, PluginComposeResult } from "../../types";
import { useEcosystemClient } from "../../context/HostContext";

type PickKind = "skills" | "connectors" | "mcp_servers";
const KIND_ITEM_TYPE: Record<PickKind, ItemSummary["item_type"]> = {
  skills: "skill", connectors: "connector", mcp_servers: "mcp_server",
};
const KIND_LABEL: Record<PickKind, string> = { skills: "Skills", connectors: "Connectors", mcp_servers: "MCP servers" };

function PickerSection({ kind, candidates, selected, onToggle }: {
  kind: PickKind;
  candidates: ItemSummary[];
  selected: Set<string>;
  onToggle: (namespace: string) => void;
}) {
  return (
    <div style={{ marginBottom: "var(--eco-space-md)" }}>
      <h4 style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textPrimary)" }}>{KIND_LABEL[kind]}</h4>
      {candidates.length === 0 ? (
        <p style={{ color: "var(--eco-color-textMuted)", fontSize: "var(--eco-font-sizeXs)" }}>None available.</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0, maxHeight: "160px", overflowY: "auto" }}>
          {candidates.map((item) => (
            <li key={item.namespace}>
              <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "var(--eco-font-sizeSm)", padding: "2px 0" }}>
                <input
                  type="checkbox"
                  data-testid={`plugin-compose-pick-${kind}`}
                  checked={selected.has(item.namespace)}
                  onChange={() => onToggle(item.namespace)}
                />
                {item.display_name} <span style={{ color: "var(--eco-color-textMuted)", fontFamily: "monospace", fontSize: "var(--eco-font-sizeXs)" }}>{item.namespace}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function PluginComposeForm({ pluginItemId, onComposed }: { pluginItemId: string; onComposed?: (result: PluginComposeResult) => void }) {
  const client = useEcosystemClient();
  const [candidates, setCandidates] = useState<Record<PickKind, ItemSummary[]> | null>(null);
  const [selected, setSelected] = useState<Record<PickKind, Set<string>>>({ skills: new Set(), connectors: new Set(), mcp_servers: new Set() });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    // Three explicit calls (not a .map() over a PickKind[] array) so the
    // tuple destructure below keeps each element's real type -- mapping
    // over a same-typed array loses the fixed-length tuple shape and every
    // element widens to `T | undefined` under this project's
    // noUncheckedIndexedAccess setting.
    Promise.all([
      client.listItems({ item_type: KIND_ITEM_TYPE.skills, limit: 200 }),
      client.listItems({ item_type: KIND_ITEM_TYPE.connectors, limit: 200 }),
      client.listItems({ item_type: KIND_ITEM_TYPE.mcp_servers, limit: 200 }),
    ]).then(([skills, connectors, mcpServers]) => {
      if (!alive) return;
      setCandidates({ skills: skills.items, connectors: connectors.items, mcp_servers: mcpServers.items });
    });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggle = (kind: PickKind, namespace: string) => {
    setSelected((prev) => {
      const next = new Set(prev[kind]);
      if (next.has(namespace)) next.delete(namespace); else next.add(namespace);
      return { ...prev, [kind]: next };
    });
  };

  const handleSubmit = () => {
    if (!candidates) return;
    setBusy(true);
    setError(null);
    const partsFor = (kind: PickKind) =>
      candidates[kind].filter((i) => selected[kind].has(i.namespace)).map((i) => ({ namespace: i.namespace, display_name: i.display_name }));
    client.composePlugin(pluginItemId, {
      skills: partsFor("skills"), connectors: partsFor("connectors"), mcp_servers: partsFor("mcp_servers"),
      commands: [], agents: [], hooks: [],
    })
      .then((result) => onComposed?.(result))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Couldn't compose this plugin."))
      .finally(() => setBusy(false));
  };

  if (!candidates) return <div data-testid="plugin-compose-loading">Loading…</div>;

  const totalSelected = selected.skills.size + selected.connectors.size + selected.mcp_servers.size;

  return (
    <div data-testid="plugin-compose-form">
      <PickerSection kind="skills" candidates={candidates.skills} selected={selected.skills} onToggle={(ns) => toggle("skills", ns)} />
      <PickerSection kind="connectors" candidates={candidates.connectors} selected={selected.connectors} onToggle={(ns) => toggle("connectors", ns)} />
      <PickerSection kind="mcp_servers" candidates={candidates.mcp_servers} selected={selected.mcp_servers} onToggle={(ns) => toggle("mcp_servers", ns)} />
      {error && <p role="alert" style={{ color: "var(--eco-color-danger)", fontSize: "var(--eco-font-sizeSm)" }}>{error}</p>}
      <button type="button" data-testid="plugin-compose-submit" disabled={busy || totalSelected === 0} onClick={handleSubmit}>
        {busy ? "Composing…" : `Compose plugin (${totalSelected} part${totalSelected === 1 ? "" : "s"})`}
      </button>
    </div>
  );
}
