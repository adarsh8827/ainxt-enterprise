// SPDX-License-Identifier: MIT
// Info-popover fix (2026-09-29): the "ⓘ" icon shown on the chat input's
// attached-skill chip and on each skill row in the "/" menu. Renders
// entirely from the `skill` object already in memory (the same list
// useEcosystemChatSkills() fetched for the "/"/"+" menus, extended with
// `license`/`source` -- see services/ecosystem/resolver_service.py's
// get_effective_capabilities()) -- deliberately makes ZERO network calls
// of its own, so opening it can never trigger a model/gate call. Matches
// EcosystemPlusMenu.jsx's own conventions: @heroicons/react (not
// lucide-react, this initiative's own icon-set rule), pointerdown-outside
// to close.
import { useEffect, useRef, useState } from "react";
import { InformationCircleIcon } from "@heroicons/react/24/outline";

// Item 3's "typeSlug" for skill items (services/ecosystem/config_service.py's
// _ROUTE_SLUGS = {"skill": "skills", ...}) -- the Marketplace detail route
// is always /marketplace/<slug>/<namespace> (packages/ecosystem-ui's own
// routing.ts). Skills are the only item type this popover ever renders for
// today (the "/" menu and chat chip are skill-only), so this is hardcoded
// rather than plumbed through as a prop for a type that can't occur here.
const MARKETPLACE_ITEM_TYPE_SLUG = "skills";

export default function SkillInfoPopover({ skill, className = "" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  if (!skill) return null;

  const marketplaceHref = `/marketplace/${MARKETPLACE_ITEM_TYPE_SLUG}/${encodeURIComponent(skill.namespace)}`;

  return (
    <span ref={ref} className={`relative inline-flex ${className}`}>
      <button
        type="button"
        data-testid="skill-info-icon"
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}
        title={`About ${skill.display_name}`}
        aria-label={`About ${skill.display_name}`}
        className="cursor-pointer text-gray-400 hover:text-gray-600"
      >
        <InformationCircleIcon width={13} height={13} />
      </button>
      {open && (
        <div
          data-testid="skill-info-popover"
          onClick={(e) => e.stopPropagation()}
          className="absolute z-30 bottom-full mb-1 left-0 w-64 bg-white border border-gray-200 rounded-lg shadow-xl p-3 text-left"
        >
          <div className="text-xs font-semibold text-gray-800">{skill.display_name}</div>
          {skill.description && (
            <div className="mt-1 text-[11px] text-gray-600 leading-relaxed">{skill.description}</div>
          )}
          <dl className="mt-2 space-y-1">
            <div className="flex gap-1 text-[11px]">
              <dt className="text-gray-400 shrink-0">How to use:</dt>
              <dd className="text-gray-700 font-mono">{skill.slash_command}</dd>
            </div>
            {skill.source && (
              <div className="flex gap-1 text-[11px]">
                <dt className="text-gray-400 shrink-0">Source:</dt>
                <dd className="text-gray-700 truncate">{skill.source}</dd>
              </div>
            )}
            {skill.license && (
              <div className="flex gap-1 text-[11px]">
                <dt className="text-gray-400 shrink-0">License:</dt>
                <dd className="text-gray-700">{skill.license}</dd>
              </div>
            )}
          </dl>
          <a
            href={marketplaceHref}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="mt-2 inline-block text-[11px] font-medium text-indigo-600 hover:text-indigo-700"
          >
            Open in Marketplace →
          </a>
        </div>
      )}
    </span>
  );
}
