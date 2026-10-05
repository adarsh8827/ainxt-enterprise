// SPDX-License-Identifier: MIT
// The "+ Add" menu (CONTRACTS.md §8): every entry always renders (never
// omitted), for every item type -- an entry for a not-yet-`available`
// type (Plugin/Connector/MCP server this phase) renders disabled with a
// "Coming soon" label rather than being hidden or swapped out, per §8's
// own documented rule ("no install/add actions rendered anywhere for
// it... including the '+ Add' menu (whose corresponding entries... render
// disabled with a 'Coming soon' label rather than being omitted")).
// Admin entries are hidden outright (not just disabled) for a caller
// without marketplace:provision -- config.caller_permissions is the only
// signal this ever gates on, never role/product inferred client-side.
//
// Full Tailwind pass (2026-10-03): trigger/menu items rewritten to literal
// Tailwind classes matching Button.jsx's own primary treatment and
// KnowledgeBase.jsx's dropdown-row hover (`hover:bg-gray-100`) instead of
// var(--eco-*) CSS custom properties.
import { useRef, useState } from "react";
import { PlusIcon, SparklesIcon, PencilIcon, ArrowUpTrayIcon, CodeBracketIcon, PuzzlePieceIcon, LinkIcon, GlobeAltIcon, ShieldCheckIcon } from "@heroicons/react/24/outline";
import { useConfig } from "./lib/hooks/useEcosystemConfig";
import { useHost } from "./lib/context/HostContext";
import { adminPath } from "./lib/routing";
import { PopoverAnchor } from "./PopoverAnchor";
const menuItemClass = disabled => ["flex items-center gap-2 w-full text-left px-3 py-2 text-sm transition-colors", disabled ? "text-gray-400 cursor-default" : "text-gray-700 hover:bg-gray-100 cursor-pointer"].join(" ");
export function AddMenu({
  activeSlug,
  onSelect,
  onCreateWithAi
}) {
  const config = useConfig();
  const {
    router
  } = useHost();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef(null);
  const active = config.item_types.find(t => t.slug === activeSlug);
  const isAvailable = active?.state === "available";
  const skillEntries = [{
    action: "new",
    icon: PencilIcon,
    label: "Write a skill",
    enabledFeature: config.features.write
  }, {
    action: "upload",
    icon: ArrowUpTrayIcon,
    label: "Upload (.zip / .skill)",
    enabledFeature: config.features.upload
  }, {
    action: "import",
    icon: CodeBracketIcon,
    label: "Import from GitHub / URL",
    enabledFeature: config.features.import_url
  }];
  // Always rendered, every type, regardless of activeSlug -- these are
  // NOT alternates for whichever type tab happens to be active; they are
  // the other 3 types' own entries, always disabled this phase.
  const comingSoonEntries = [{
    key: "mcp_server",
    icon: PuzzlePieceIcon,
    label: "Add MCP server"
  }, {
    key: "connector",
    icon: LinkIcon,
    label: "Add connector"
  }, {
    key: "plugin",
    icon: GlobeAltIcon,
    label: "Add plugin"
  }];
  const showAdmin = config.caller_permissions.can_provision;
  // BUG-03 fix: who_can_add="admins_only" was never enforced here at all --
  // Create with AI / Write / Upload / Import stayed fully clickable for a
  // non-admin caller, who could fill out an entire form before the
  // backend's own, already-correct 403 POLICY_FORBIDDEN surfaced. Same
  // admin-bypass pattern config_service.py's own caller_permissions.
  // can_share already uses for the identical who_can_share policy --
  // marketplace:provision always passes regardless of the policy value.
  const creationRestricted = config.policy_summary.who_can_add === "admins_only" && !config.caller_permissions.can_provision;
  const creationRestrictedTitle = "Only admins can add items in this org";
  return <div className="relative flex-shrink-0">
      {/* Toolbar icon-consistency pass (2026-10-05, explicit product ask:
          "filter, sort, add button, keep all three as icons on hover it
          will has slight bg, with same size, so that looks consistent"):
          dropped the "Add" text label and brand-grad fill from the
          theme-alignment round just before this one -- that round made
          this match ProductManager.jsx's own small filled primary button,
          but the actual ask this round is for Add to visually match its
          own two toolbar siblings (Filter/Sort), not an unrelated
          page's primary CTA. Same `p-1.5 rounded-md hover:bg-gray-100`
          classes as FilterPopover.jsx/SortPopover.jsx, same 18px icon --
          all three triggers are now visually identical in size and hover
          behavior. title="Add" keeps a native tooltip + accessible name
          now that there's no visible text, matching Filter/Sort's own
          title-only pattern. */}
      <button ref={triggerRef} type="button" data-testid="add-menu-trigger" title="Add" onClick={() => setOpen(o => !o)} className="inline-flex items-center justify-center p-1.5 rounded-md text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-colors cursor-pointer flex-shrink-0">
        <PlusIcon width={18} height={18} aria-hidden="true" />
      </button>
      <PopoverAnchor anchorRef={triggerRef} open={open} align="right" onRequestClose={() => setOpen(false)}>
        <div role="menu" data-testid="add-menu" className="min-w-[240px] bg-white border border-gray-200 rounded-md shadow-lg" onMouseLeave={() => setOpen(false)}>
          {isAvailable && config.features.create_with_ai && onCreateWithAi && <button type="button" role="menuitem" data-testid="add-menu-create-with-ai" disabled={creationRestricted} title={creationRestricted ? creationRestrictedTitle : undefined} onClick={() => {
          if (creationRestricted) return;
          onCreateWithAi();
          setOpen(false);
        }} className={menuItemClass(creationRestricted)}>
              <SparklesIcon width={16} height={16} aria-hidden="true" /> Create with AI
            </button>}
          {isAvailable && skillEntries.map(entry => {
          const disabled = !entry.enabledFeature || creationRestricted;
          const Icon = entry.icon;
          return <button key={entry.action} type="button" role="menuitem" data-testid={`add-menu-${entry.action}`} disabled={disabled} title={creationRestricted && entry.enabledFeature ? creationRestrictedTitle : undefined} onClick={() => {
            if (!disabled) {
              onSelect(entry.action);
              setOpen(false);
            }
          }} className={menuItemClass(disabled)}>
                <Icon width={16} height={16} aria-hidden="true" /> {entry.label}
              </button>;
        })}
          <div className="border-t border-gray-100" />
          {comingSoonEntries.map(entry => {
          const Icon = entry.icon;
          return <button key={entry.key} type="button" role="menuitem" data-testid={`add-menu-${entry.key}-coming-soon`} disabled title="Coming soon" className={menuItemClass(true)}>
                <Icon width={16} height={16} aria-hidden="true" />
                <span className="flex-1">{entry.label}</span>
                <span className="text-xs">Coming soon</span>
              </button>;
        })}
          {showAdmin && <>
              <div className="border-t border-gray-100" />
              <div className="px-3 py-1.5 text-xs text-gray-400 uppercase tracking-wide">
                Admin
              </div>
              <button type="button" role="menuitem" data-testid="add-menu-add-source" disabled title="Not yet available" className={menuItemClass(true)}>
                <GlobeAltIcon width={16} height={16} aria-hidden="true" />
                <span className="flex-1">Add source</span>
                <span className="text-xs">Coming soon</span>
              </button>
              <button type="button" role="menuitem" data-testid="add-menu-provision-for-org" onClick={() => {
            setOpen(false);
            router.navigate(adminPath("provisioning"));
          }} className={menuItemClass(false)}>
                <ShieldCheckIcon width={16} height={16} aria-hidden="true" /> Provision for org
              </button>
            </>}
        </div>
      </PopoverAnchor>
    </div>;
}
