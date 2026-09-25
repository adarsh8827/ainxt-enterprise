// SPDX-License-Identifier: MIT
// Marketplace local data store — UI-first phase.
//
// This Marketplace is a fresh, standalone feature: it does not read from or
// write to any pre-existing skill/connector/plugin system in this codebase
// (not the in-memory mcp_registry, not the SkillRecord governance table, not
// connector_definitions, not curated_plugins.json, not anything Agent Studio
// uses). None of those are touched by this file or by Marketplace.jsx.
//
// Until a real backend for THIS feature is built, everything created through
// the Marketplace UI is persisted to localStorage in the shape a future API
// would return. Every function here is already the "data layer" contract
// (list/get/create/update/remove) a real fetch()-based version would have —
// swapping the bodies for HTTP calls later shouldn't require touching any
// caller in Marketplace.jsx.

const KEYS = {
  skills: "ainxt.marketplace2.skills",
  connectors: "ainxt.marketplace2.connectors",
  plugins: "ainxt.marketplace2.plugins",
  installed: "ainxt.marketplace2.installed",
};

function read(key) {
  try { return JSON.parse(localStorage.getItem(key) || "[]"); } catch { return []; }
}
function write(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage full/unavailable — ignore */ }
}
function uid() {
  return crypto.randomUUID ? crypto.randomUUID() : `id-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export const SKILL_CATEGORIES = [
  "Engineering", "Sales", "Marketing", "Legal", "Finance",
  "HR", "Support", "Productivity", "Data & Analytics", "Design", "Other",
];
export const CONNECTOR_CATEGORIES = ["Productivity", "Communication", "Developer Tools", "CRM", "Data", "Other"];

// ── SKILL.md format ────────────────────────────────────────────────────────
// Modelled on the same shape Claude's own Agent Skills use: a YAML
// frontmatter block (---...---) with required `name` and `description`
// fields, followed by a markdown body that becomes the skill's instructions.
// This is enforced client-side only for now — see the note at the top of
// this file about the UI-first phase.
export const SKILL_MD_EXAMPLE = `---
name: my-skill-name
description: One or two sentences on what this skill does and when to use it.
---

# Instructions

Explain step by step what the model should do when this skill is used.
Be specific about expected inputs and the shape of the output.
`;

/**
 * Parse a SKILL.md file's text content.
 * Returns { valid: true, name, description, instructions } on success, or
 * { valid: false, errors: string[] } listing every problem found — the
 * caller shows these directly in the UI rather than a generic failure.
 */
export function parseSkillMarkdown(raw) {
  const errors = [];
  const text = String(raw || "");

  const fmMatch = text.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (!fmMatch) {
    return {
      valid: false,
      errors: [
        "The file must start with a YAML frontmatter block delimited by --- lines, e.g.:",
        "---\nname: my-skill-name\ndescription: ...\n---",
      ],
    };
  }
  const [, frontmatterRaw, body] = fmMatch;

  const fm = {};
  frontmatterRaw.split(/\r?\n/).forEach((line) => {
    const m = line.match(/^([a-zA-Z_-]+):\s*(.*)$/);
    if (m) fm[m[1].trim()] = m[2].trim().replace(/^["']|["']$/g, "");
  });

  // Plain human-readable names ("Weekly status report") are valid — Claude's
  // own skill names aren't slugs, so this only rejects an empty value.
  if (!fm.name) errors.push('Missing required frontmatter field: "name".');
  if (!fm.description) errors.push('Missing required frontmatter field: "description".');
  if (!body || !body.trim()) errors.push("No instructions found in the file body (the markdown content below the closing --- ).");

  if (errors.length) return { valid: false, errors };
  return { valid: true, name: fm.name, description: fm.description, instructions: body.trim() };
}

/** The inverse of parseSkillMarkdown — reconstructs a canonical SKILL.md
 * from a stored skill object, for the Contents tab's preview/raw view and
 * its download button. */
export function buildSkillMarkdown(skill) {
  return `---\nname: ${skill.name}\ndescription: ${skill.description}\n---\n\n${skill.instructions || ""}\n`;
}

export const SKILL_ICONS = ["🧠", "📝", "🔍", "📊", "🛡️", "🧪", "🗂️", "📚", "💡", "🚀"];
export const CONNECTOR_ICONS = ["🔗", "📧", "💬", "📁", "🗓️", "🏢", "🐙", "🎫", "☁️", "🔐"];
export const PLUGIN_ICONS = ["🧩", "📦", "⚙️", "🛠️", "🎁", "🧰", "🪄", "🔧", "📇", "🗃️"];

function makeCrud(key, defaults) {
  return {
    list: () => read(key),
    get: (id) => read(key).find((x) => x.id === id) || null,
    create: (data) => {
      const items = read(key);
      const item = {
        id: uid(),
        createdAt: Date.now(),
        updatedAt: Date.now(),
        installs: 0,
        version: 1,
        author: "You",
        ...defaults,
        ...data,
      };
      items.unshift(item);
      write(key, items);
      return item;
    },
    update: (id, patch) => {
      const items = read(key).map((x) => (x.id === id ? { ...x, ...patch, updatedAt: Date.now() } : x));
      write(key, items);
      return items.find((x) => x.id === id) || null;
    },
    remove: (id) => {
      write(key, read(key).filter((x) => x.id !== id));
      const installed = readInstalled();
      installed.delete(`skill:${id}`); installed.delete(`connector:${id}`); installed.delete(`plugin:${id}`);
      writeInstalled(installed);
    },
  };
}

export const skillsStore = makeCrud(KEYS.skills, { tags: [], instructions: "", files: [] });
export const connectorsStore = makeCrud(KEYS.connectors, { tags: [], authType: "api_key", baseUrl: "" });
export const pluginsStore = makeCrud(KEYS.plugins, { tags: [], skillIds: [], connectorIds: [] });

const STORE_BY_KIND = { skill: skillsStore, connector: connectorsStore, plugin: pluginsStore };
export function storeFor(kind) { return STORE_BY_KIND[kind]; }

function readInstalled() {
  try { return new Set(JSON.parse(localStorage.getItem(KEYS.installed) || "[]")); } catch { return new Set(); }
}
function writeInstalled(set) { write(KEYS.installed, [...set]); }

export function isInstalled(kind, id) { return readInstalled().has(`${kind}:${id}`); }

export function toggleInstalled(kind, id) {
  const set = readInstalled();
  const key = `${kind}:${id}`;
  const store = STORE_BY_KIND[kind];
  const item = store.get(id);
  if (!item) return false;
  if (set.has(key)) {
    set.delete(key);
    store.update(id, { installs: Math.max(0, (item.installs || 0) - 1) });
  } else {
    set.add(key);
    store.update(id, { installs: (item.installs || 0) + 1 });
  }
  writeInstalled(set);
  return set.has(key);
}

// ---- Seed data, refreshed on every load ----
// Clearly first-party example content — distinguishable from anything a real
// user creates. Uses STABLE ids and upserts on every module load rather than
// a one-time flag: this feature is still being actively designed, so seed
// *content* changes from one code update to the next need to actually reach
// a browser that already visited the app once — a one-time flag would freeze
// that browser on whatever seed shape existed the first time it loaded.
// Real user-created items always get random ids (see makeCrud/uid above), so
// they never collide with these and are never touched by this refresh.
//
// Skills below are marked `thirdParty: true` with invented, non-real vendor
// names (deliberately not real companies — see the "Skills from third
// parties" section in Marketplace.jsx, whose legal/compatibility check
// modal assumes an unaffiliated outside publisher). Connectors/plugins are
// still plain "AiNxt Team" first-party examples for now — the yours/
// third-party split hasn't been extended to those tabs yet.
function upsertSeed(store, id, data) {
  const existing = store.get(id);
  if (existing) {
    // Keep installs/createdAt "organic" across refreshes; refresh everything
    // else so content edits in this file actually show up.
    return store.update(id, { ...data, installs: existing.installs, createdAt: existing.createdAt });
  }
  return store.create({ id, ...data });
}

function refreshSeedData() {
  const daysAgo = (n) => Date.now() - n * 86400000;
  const team = "AiNxt Team";

  upsertSeed(skillsStore, "seed-skill-meeting-notes", {
    name: "Meeting Notes Summarizer", category: "Productivity", icon: "📝", author: "BrightOps", thirdParty: true, createdAt: daysAgo(2),
    description: "Turns a raw meeting transcript into a structured summary with decisions and action items.",
    tags: ["meetings", "summarization"],
    instructions: "Given a meeting transcript, extract: 1) key decisions, 2) action items with an owner and due date, 3) open questions. Keep the summary under 200 words and use bullet points.",
    installs: 18,
  });
  upsertSeed(skillsStore, "seed-skill-sql-explainer", {
    name: "SQL Query Explainer", category: "Data & Analytics", icon: "📊", author: "QueryLens", thirdParty: true, createdAt: daysAgo(5),
    description: "Explains what a SQL query does in plain English, and flags likely performance issues.",
    tags: ["sql", "data"],
    instructions: "Given a SQL query, explain step by step what it returns, note any missing indexes or full-table scans, and suggest one concrete optimization if applicable.",
    installs: 11,
  });
  upsertSeed(skillsStore, "seed-skill-contract-clause", {
    name: "Contract Clause Reviewer", category: "Legal", icon: "🛡️", author: "ClauseGuard", thirdParty: true, createdAt: daysAgo(9),
    description: "Flags unusual or risky clauses in a contract draft against common enterprise norms.",
    tags: ["contracts", "risk"],
    instructions: "Given a contract clause, identify whether it deviates from standard enterprise terms (liability caps, termination notice, indemnity), and explain the risk in one sentence.",
    installs: 6,
  });
  const bugTriager = upsertSeed(skillsStore, "seed-skill-bug-triager", {
    name: "Bug Report Triager", category: "Engineering", icon: "🧪", author: "BrightOps", thirdParty: true, createdAt: daysAgo(1),
    description: "Classifies an incoming bug report by severity and suggests the likely owning team.",
    tags: ["engineering", "triage"],
    instructions: "Given a bug report, output: severity (P1-P4), likely affected component, and a one-line reproduction summary.",
    installs: 3,
  });
  upsertSeed(skillsStore, "seed-skill-invoice-extractor", {
    name: "Invoice Data Extractor", category: "Finance", icon: "🧠", author: "LedgerFlow", thirdParty: true, createdAt: daysAgo(6),
    description: "Pulls vendor, line items, and totals out of an invoice PDF or image into structured fields.",
    tags: ["finance", "invoices"],
    instructions: "Given invoice text or OCR output, extract vendor name, invoice number, line items (description, quantity, unit price), and the total due. Flag if the total doesn't match the sum of line items.",
    installs: 9,
  });
  upsertSeed(skillsStore, "seed-skill-sentiment-analyzer", {
    name: "Customer Sentiment Analyzer", category: "Support", icon: "💡", author: "PulseMetrics", thirdParty: true, createdAt: daysAgo(3),
    description: "Scores a support ticket or review for sentiment and urgency, and suggests a response tone.",
    tags: ["support", "sentiment"],
    instructions: "Given customer text, output: sentiment (positive/neutral/negative), urgency (low/medium/high), and one sentence suggesting the tone of the reply.",
    installs: 14,
  });

  upsertSeed(connectorsStore, "seed-connector-wiki", {
    name: "Internal Wiki", category: "Productivity", icon: "📁", author: team, createdAt: daysAgo(4),
    description: "Search and read pages from your team's internal wiki.",
    tags: ["docs"], authType: "api_key", baseUrl: "https://wiki.internal.example.com/api",
    installs: 9,
  });
  const ticketing = upsertSeed(connectorsStore, "seed-connector-ticketing", {
    name: "Ticketing System", category: "Developer Tools", icon: "🎫", author: team, createdAt: daysAgo(7),
    description: "Look up and comment on tickets in your team's issue tracker.",
    tags: ["tickets"], authType: "oauth2", baseUrl: "https://tickets.internal.example.com",
    installs: 14,
  });
  upsertSeed(connectorsStore, "seed-connector-calendar", {
    name: "Team Calendar", category: "Productivity", icon: "🗓️", author: team, createdAt: daysAgo(3),
    description: "Check availability and upcoming meetings for the team.",
    tags: ["calendar"], authType: "oauth2", baseUrl: "https://calendar.internal.example.com",
    installs: 5,
  });

  upsertSeed(pluginsStore, "seed-plugin-engineering-bundle", {
    name: "Engineering Bundle", category: "Engineering", icon: "🧰", author: team, createdAt: daysAgo(1),
    description: "Everything for daily engineering work: bug triage plus your ticketing system, in one install.",
    tags: ["engineering"], skillIds: [bugTriager.id], connectorIds: [ticketing.id],
    installs: 7,
  });
}
refreshSeedData();
