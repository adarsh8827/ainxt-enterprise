// SPDX-License-Identifier: MIT
// Task F-11: chat "+" menu. Chat-menu simplification (2026-10-04, explicit
// product ask: "as of now we should show only Browse Skills, Use skill,
// like how claude showing") -- "Create a skill with AI" and the
// Plugin/Connector/MCP-server "Coming soon" stubs are removed from this
// menu for now (not deleted platform-wide: Create-with-AI is still reachable
// from the Marketplace's own Add menu). Only renders at all when
// ECOSYSTEM_CHAT_SKILLS is on -- @heroicons/react, no lucide-react (this
// initiative's own icon-set rule).
import { useEffect, useMemo, useRef, useState } from "react";
import { PlusIcon, MagnifyingGlassIcon, BoltIcon, ChevronRightIcon } from "@heroicons/react/24/outline";
import { isEcosystemChatSkillsEnabled } from "../hooks/useEcosystemChatSkills";

// Above this many installed skills, scrolling a flat list stops being a
// reasonable way to find one -- show a type-to-filter box instead (matching
// the product ask: "like how claude showing").
const SEARCH_THRESHOLD = 8;

// Chat-skills UX rework (2026-10-04): "Use a skill" now inserts literal
// "/slash-command " text into the input (via onUseSkill) instead of
// attaching a separate chip. `skills` is the same installed-skill list the
// "/" menu already renders (task F-11's useEcosystemChatSkills hook) --
// passed in rather than fetched again here.
// Shared classes for every row button: default outline removed (the
// browser's built-in focus ring looked like a stray dark border) and
// replaced with the same soft background used on hover, so keyboard focus
// and mouse hover look identical -- no extra "focus" visual language needed.
const ROW_FOCUS = "outline-none focus:bg-gray-50 focus:text-gray-900";
const SKILL_ROW_FOCUS = "outline-none focus:bg-indigo-50 focus:text-indigo-700";

export default function EcosystemPlusMenu({ onBrowseSkills, onUseSkill, skills, disabled }) {
  const [open, setOpen] = useState(false);
  const [skillPickerOpen, setSkillPickerOpen] = useState(false);
  const [skillFilter, setSkillFilter] = useState("");
  const ref = useRef(null);
  const skillSearchRef = useRef(null);

  const showSkillSearch = (skills?.length || 0) > SEARCH_THRESHOLD;
  const filteredSkills = useMemo(() => {
    if (!showSkillSearch || !skillFilter.trim()) return skills || [];
    const q = skillFilter.trim().toLowerCase();
    return (skills || []).filter((s) => s.display_name.toLowerCase().includes(q));
  }, [skills, skillFilter, showSkillSearch]);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (e) => { if (!ref.current?.contains(e.target)) { setOpen(false); setSkillPickerOpen(false); } };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  // Reset the filter whenever the picker is collapsed/closed so it starts
  // fresh next time, rather than showing a stale filtered view.
  useEffect(() => {
    if (!skillPickerOpen) setSkillFilter("");
  }, [skillPickerOpen]);

  // Focus the first row as soon as the menu opens, so arrow keys work
  // immediately without an extra Tab press first.
  useEffect(() => {
    if (!open) return;
    ref.current?.querySelector('[role="menu"] button')?.focus();
  }, [open]);

  // Once the skill list expands, hand focus straight to the search box (when
  // there is one) so the user can start typing immediately -- arrow keys
  // from there already flow into the filtered rows (see handleMenuKeyDown).
  useEffect(() => {
    if (skillPickerOpen && showSkillSearch) skillSearchRef.current?.focus();
  }, [skillPickerOpen, showSkillSearch]);

  // Up/Down roves focus across whichever rows are currently in the DOM
  // (the skill list only exists once "Use a skill" is expanded) instead of
  // tracking a separate active-index -- real DOM focus means Enter/Space
  // activate the focused row for free, no extra key handling needed.
  function handleMenuKeyDown(e) {
    if (e.key === "Escape") {
      setOpen(false);
      setSkillPickerOpen(false);
      return;
    }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const rows = Array.from(ref.current?.querySelectorAll('[role="menu"] button') || []);
    if (rows.length === 0) return;
    const currentIndex = rows.indexOf(document.activeElement);
    // currentIndex is -1 when focus is on the search box (not a button) --
    // Down should land on the first row, Up on the last, not wrap oddly.
    const nextIndex = currentIndex === -1
      ? (e.key === "ArrowDown" ? 0 : rows.length - 1)
      : e.key === "ArrowDown"
        ? (currentIndex + 1) % rows.length
        : (currentIndex - 1 + rows.length) % rows.length;
    rows[nextIndex]?.focus();
  }

  if (!isEcosystemChatSkillsEnabled()) return null;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={disabled}
        title="Add a skill"
        className="cursor-pointer p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition disabled:opacity-40 outline-none focus:bg-gray-100 focus:text-gray-600"
      >
        <PlusIcon width={16} height={16} />
      </button>
      {open && (
        <div
          role="menu"
          onKeyDown={handleMenuKeyDown}
          className="absolute bottom-full mb-2 left-0 w-60 bg-white border border-gray-100 rounded-xl shadow-lg ring-1 ring-black/5 z-20 overflow-hidden py-1"
        >
          {onBrowseSkills && (
            <button
              type="button"
              role="menuitem"
              onClick={() => { setOpen(false); onBrowseSkills(); }}
              className={`w-full flex items-center gap-2.5 text-left px-3 py-2 mx-1 my-0.5 rounded-lg text-[13px] font-medium text-gray-700 hover:bg-gray-50 hover:text-gray-900 transition-colors cursor-pointer ${ROW_FOCUS}`}
              style={{ width: "calc(100% - 0.5rem)" }}
            >
              <MagnifyingGlassIcon width={15} height={15} className="text-gray-400 shrink-0" />
              Browse skills
            </button>
          )}
          {onUseSkill && skills && skills.length > 0 && (
            <>
              <button
                type="button"
                role="menuitem"
                onClick={() => setSkillPickerOpen((o) => !o)}
                className={`w-full flex items-center gap-2.5 text-left px-3 py-2 mx-1 my-0.5 rounded-lg text-[13px] font-medium text-gray-700 hover:bg-gray-50 hover:text-gray-900 transition-colors cursor-pointer ${ROW_FOCUS}`}
                style={{ width: "calc(100% - 0.5rem)" }}
              >
                <BoltIcon width={15} height={15} className="text-indigo-500 shrink-0" />
                <span className="flex-1">Use a skill</span>
                <ChevronRightIcon
                  width={13}
                  height={13}
                  className={`text-gray-300 shrink-0 transition-transform ${skillPickerOpen ? "rotate-90" : ""}`}
                />
              </button>
              {skillPickerOpen && (
                <div className="border-t border-gray-50 mt-0.5">
                  {showSkillSearch && (
                    <div className="px-2 pt-1.5 pb-1">
                      <input
                        ref={skillSearchRef}
                        type="text"
                        value={skillFilter}
                        onChange={(e) => setSkillFilter(e.target.value)}
                        placeholder={`Search ${skills.length} skills…`}
                        className="w-full px-2.5 py-1.5 text-[13px] rounded-lg border border-gray-200 bg-gray-50 outline-none focus:border-indigo-300 focus:bg-white transition-colors placeholder-gray-400"
                      />
                    </div>
                  )}
                  <div className="max-h-56 overflow-y-auto py-1 px-1">
                    {filteredSkills.length === 0 ? (
                      <p className="px-3 py-2 text-[13px] text-gray-400">No skills match "{skillFilter}"</p>
                    ) : (
                      filteredSkills.map((s) => (
                        <button
                          key={s.namespace}
                          type="button"
                          role="menuitem"
                          onClick={() => { setOpen(false); setSkillPickerOpen(false); onUseSkill(s); }}
                          title={s.display_name}
                          className={`w-full flex items-center gap-2.5 text-left px-3 py-1.5 my-0.5 rounded-lg text-[13px] text-gray-700 hover:bg-indigo-50 hover:text-indigo-700 transition-colors cursor-pointer ${SKILL_ROW_FOCUS}`}
                        >
                          <span className="w-1.5 h-1.5 rounded-full bg-indigo-300 shrink-0" />
                          <span className="truncate">{s.display_name}</span>
                        </button>
                      ))
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
