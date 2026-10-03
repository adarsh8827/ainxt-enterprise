// SPDX-License-Identifier: MIT
// Contents tab replacement for a plugin item (docs/ecosystem/
// PLUGINS_PHASE_PLAN.md §4). A plugin's manifest is a set of REFERENCES to
// other, independently-gated items -- not embedded file content -- so
// there is nothing for the generic Contents.tsx (SKILL.md + bundled files,
// detail/Contents.tsx's own manifestToFiles()) to show; that component
// assumes a skill-shaped manifest and would render a bogus empty
// "SKILL.md" for a plugin. This is a grouped reference list instead, not a
// file browser -- disclosed explicitly rather than overclaiming a preview
// that doesn't exist for this item type.

import { PluginPartsList } from "./PluginPartsList";
const EMPTY_PARTS = {
  skills: [],
  commands: [],
  agents: [],
  connectors: [],
  mcp_servers: [],
  hooks: []
};
function Section({
  title,
  count,
  children
}) {
  return <div className="mb-6">
      <h3 className="text-sm text-gray-900">{title} ({count})</h3>
      {children}
    </div>;
}
export function PluginContentsSummary({
  item
}) {
  const parts = item.manifest.parts ?? EMPTY_PARTS;
  return <div data-testid="plugin-contents-summary">
      <p className="text-gray-500 text-sm mt-0">
        This plugin bundles the items below. Each keeps its own version and gate history --
        open one to see its real content.
      </p>
      <Section title="Skills" count={parts.skills.length}>
        <PluginPartsList parts={parts.skills} routeSlug="skills" emptyLabel="No skills bundled." />
      </Section>
      <Section title="Connectors" count={parts.connectors.length}>
        <PluginPartsList parts={parts.connectors} routeSlug="connectors" emptyLabel="No connectors bundled." />
      </Section>
      <Section title="MCP servers" count={parts.mcp_servers.length}>
        <PluginPartsList parts={parts.mcp_servers} routeSlug="mcp" emptyLabel="No MCP servers bundled." />
      </Section>
      <Section title="Commands" count={parts.commands.length}>
        <PluginPartsList parts={parts.commands} emptyLabel="No commands bundled." />
      </Section>
      <Section title="Agents" count={parts.agents.length}>
        <PluginPartsList parts={parts.agents} emptyLabel="No agents bundled." />
      </Section>
      <Section title="Hooks" count={parts.hooks.length}>
        <PluginPartsList parts={parts.hooks} emptyLabel="No hooks bundled." />
      </Section>
    </div>;
}