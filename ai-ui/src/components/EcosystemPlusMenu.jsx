// SPDX-License-Identifier: MIT
// Task F-11: chat "+" menu -- Skills active (Create with AI), other item
// types shown disabled "Coming soon" (matching CONTRACTS.md §8's own
// item_types[].state convention, rather than omitting them). Only renders
// at all when ECOSYSTEM_CHAT_SKILLS is on -- @heroicons/react, no
// lucide-react (this initiative's own icon-set rule).
import { useEffect, useRef, useState } from "react";
import { PlusIcon, SparklesIcon, MagnifyingGlassIcon, BoltIcon } from "@heroicons/react/24/outline";
import { isEcosystemChatSkillsEnabled } from "../hooks/useEcosystemChatSkills";

const COMING_SOON_TYPES = [
  { key: "plugin", label: "Plugin" },
  { key: "connector", label: "Connector" },
  { key: "mcp_server", label: "MCP server" },
];

// Chat-skills task, 2026-09-28: "Use a skill" picker -- attaches a skill as
// a chip (via onUseSkill) without the user typing a leading "/name". `skills`
// is the same installed-skill list the "/" menu already renders (task F-11's
// useEcosystemChatSkills hook) -- passed in rather than fetched again here.
export default function EcosystemPlusMenu({ onCreateWithAi, onBrowseSkills, onUseSkill, skills, disabled }) {
  const [open, setOpen] = useState(false);
  const [skillPickerOpen, setSkillPickerOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (e) => { if (!ref.current?.contains(e.target)) { setOpen(false); setSkillPickerOpen(false); } };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  if (!isEcosystemChatSkillsEnabled()) return null;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={disabled}
        title="Add a skill"
        className="cursor-pointer p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition disabled:opacity-40"
      >
        <PlusIcon width={16} height={16} />
      </button>
      {open && (
        <div className="absolute bottom-full mb-1 left-0 w-56 bg-white border border-gray-200 rounded-lg shadow-xl z-20 overflow-hidden">
          <button
            type="button"
            onClick={() => { setOpen(false); onCreateWithAi(); }}
            className="w-full flex items-center gap-2 text-left px-3 py-2 text-xs font-medium text-gray-800 hover:bg-gray-50"
          >
            <SparklesIcon width={14} height={14} className="text-indigo-500" />
            Create a skill with AI…
          </button>
          {onBrowseSkills && (
            <button
              type="button"
              onClick={() => { setOpen(false); onBrowseSkills(); }}
              className="w-full flex items-center gap-2 text-left px-3 py-2 text-xs font-medium text-gray-800 hover:bg-gray-50"
            >
              <MagnifyingGlassIcon width={14} height={14} className="text-gray-500" />
              Browse skills
            </button>
          )}
          {onUseSkill && skills && skills.length > 0 && (
            <>
              <button
                type="button"
                onClick={() => setSkillPickerOpen((o) => !o)}
                className="w-full flex items-center gap-2 text-left px-3 py-2 text-xs font-medium text-gray-800 hover:bg-gray-50"
              >
                <BoltIcon width={14} height={14} className="text-emerald-500" />
                Use a skill…
              </button>
              {skillPickerOpen && (
                <div className="max-h-48 overflow-y-auto border-t border-gray-100">
                  {skills.map((s) => (
                    <button
                      key={s.namespace}
                      type="button"
                      onClick={() => { setOpen(false); setSkillPickerOpen(false); onUseSkill(s); }}
                      className="w-full flex flex-col items-start text-left px-4 py-1.5 hover:bg-gray-50"
                    >
                      <span className="text-xs font-medium text-gray-800 truncate">{s.display_name}</span>
                      <span className="text-[11px] text-gray-500 truncate">{s.description}</span>
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
          <div className="border-t border-gray-100" />
          {COMING_SOON_TYPES.map((t) => (
            <div
              key={t.key}
              className="flex items-center justify-between px-3 py-2 text-xs text-gray-400 cursor-default"
              title="Coming soon"
            >
              <span>Add {t.label}</span>
              <span className="text-[10px] uppercase tracking-wide">Soon</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
