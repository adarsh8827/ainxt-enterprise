// SPDX-License-Identifier: MIT
// Chip-cleanup fix (2026-09-29): pure, dependency-free helpers factored out
// of Chat.jsx's applySkillSlashCommand/handleInputChange specifically so
// the bug-fix logic (strip leftover "/name" text, detect "/name " ->
// auto-convert) is unit-testable without mounting the rest of Chat.jsx.
// Both are plain string functions -- no React, no fetch, no state.

/**
 * The "/" filter text that triggers the slash menu is only ever a menu
 * TRIGGER, never part of the message. Given input that starts with "/",
 * strips exactly the leading "/token" (up to the first space, or the
 * whole string if there's no space yet) and returns whatever's left.
 * Input that does not start with "/" (e.g. the "+" menu's "Use a skill"
 * picker invoked after the user already typed an ordinary task
 * description) is returned unchanged, so the chip attaches to existing
 * free text instead of eating it.
 *
 *   stripLeadingSlashToken("/rese")                    -> ""
 *   stripLeadingSlashToken("/research explain this")   -> "explain this"
 *   stripLeadingSlashToken("explain this")              -> "explain this"
 *   stripLeadingSlashToken("")                          -> ""
 *
 * @param {string} text
 * @returns {string}
 */
export function stripLeadingSlashToken(text) {
  if (!text || !text.startsWith("/")) return text || "";
  const spaceIdx = text.indexOf(" ");
  return spaceIdx === -1 ? "" : text.slice(spaceIdx + 1);
}

// Chat-skills UX rework (2026-10-04): selecting a skill used to attach it
// as a separate, non-text chip above the input (see git history) --
// replaced with literal "/slash-command " text inserted directly into the
// textarea, so native Backspace removes it character-by-character like
// any other text, and the same string is what actually gets sent/shown in
// the conversation (no separate chip metadata to keep in sync).
//
// Prepends "/<slashCommand> " to whatever's already in the box, first
// stripping any PRIOR leading "/token" (e.g. re-picking a different skill,
// or the "/partial" filter text that triggered the dropdown in the first
// place) via stripLeadingSlashToken above -- so the result never
// double-prefixes. Free text typed after the old token (or typed via the
// "+" menu's "Use a skill" picker with no leading "/" at all) is preserved
// after the new command.
//
//   insertSkillSlashCommand("/rese", "/research")                  -> "/research "
//   insertSkillSlashCommand("/research explain this", "/research") -> "/research explain this"
//   insertSkillSlashCommand("summarize this doc", "/research")      -> "/research summarize this doc"
//   insertSkillSlashCommand("", "/research")                        -> "/research "
//
// @param {string} currentInput
// @param {string} slashCommand - includes the leading "/", e.g. "/research"
// @returns {string}
export function insertSkillSlashCommand(currentInput, slashCommand) {
  const rest = stripLeadingSlashToken(currentInput);
  return rest ? `${slashCommand} ${rest}` : `${slashCommand} `;
}

// Matches a leading "/token" (up to the first space, or the whole string
// if there's no space yet) -- used to resolve which installed skill (if
// any) a piece of text is currently referencing, for both the live input's
// inline highlight and resolving which skill to send with the message.
// Deliberately permissive about what follows (unlike the old, now-removed
// matchAutoConvertToken, which required EXACTLY one trailing space and
// nothing else) -- a full, resolvable command should highlight/resolve
// whether or not the user has started typing a task after it yet.
//
//   resolveLeadingSkillCommand("/research", skills)             -> the skill, if slash_command === "/research"
//   resolveLeadingSkillCommand("/research explain this", skills) -> same
//   resolveLeadingSkillCommand("/rese", skills)                  -> null (partial, not a real command)
//   resolveLeadingSkillCommand("explain this", skills)           -> null (no leading slash)
//
// @param {string} text
// @param {Array<{slash_command?: string}>} skills
// @returns {object | null}
export function resolveLeadingSkillCommand(text, skills) {
  if (!text || !text.startsWith("/") || !skills || skills.length === 0) return null;
  const spaceIdx = text.indexOf(" ");
  const token = (spaceIdx === -1 ? text : text.slice(0, spaceIdx)).toLowerCase();
  return skills.find(s => (s.slash_command || "").toLowerCase() === token) || null;
}
