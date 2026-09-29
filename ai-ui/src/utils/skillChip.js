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

// Matches ONLY "/token" immediately followed by exactly one trailing
// space, with nothing else in the string -- i.e. the box holds nothing
// but a just-typed slash command and the space that follows it. A second
// word ("/research answer ") does NOT match, since \S+ can't cross the
// internal space and the pattern is anchored at both ends.
const _TRAILING_SPACE_RE = /^(\/\S+) $/;

/**
 * Given the live textarea value, returns the lowercased "/token" (with
 * its leading slash) if the value is EXACTLY that token followed by one
 * trailing space -- the shape that should auto-convert to a skill chip,
 * same end state as picking the skill from the menu. Returns null for
 * anything else (multi-word input, no trailing space yet, empty, etc.),
 * so the caller's existing "/" menu-filter behavior is untouched.
 *
 *   matchAutoConvertToken("/research ")            -> "/research"
 *   matchAutoConvertToken("/research answer ")     -> null
 *   matchAutoConvertToken("/rese")                 -> null
 *   matchAutoConvertToken("")                       -> null
 *
 * @param {string} value
 * @returns {string | null}
 */
export function matchAutoConvertToken(value) {
  const match = _TRAILING_SPACE_RE.exec(value || "");
  return match ? match[1].toLowerCase() : null;
}
