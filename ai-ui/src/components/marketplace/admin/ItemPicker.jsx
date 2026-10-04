// SPDX-License-Identifier: MIT
// UX-01 fix: Provisioning/Force-disable/Featured used to ask the admin to
// paste a raw item UUID into a bare `<input placeholder="item id">`, with
// no search, no resolved-name confirmation, and no feedback for a typo'd
// or nonexistent id beyond a late 404 (BUG-05/06/07, already fixed
// separately). Nowhere else in this package identifies an item by raw id
// -- Discover/Yours/Detail always show icon + name + badges. This reuses
// the same `GET /ecosystem/items?q=...` search the Toolbar's own search
// box calls into (client.listItems), and once an item is picked, shows
// its real icon/name/namespace -- matching AddDialog's own "Add
// {item.display_name}" pattern instead of echoing an id.
import { useEffect, useRef, useState } from "react";
import { useEcosystemClient } from "../lib/context/HostContext";
import { ItemIcon } from "../ItemIcon";
import { PopoverAnchor } from "../PopoverAnchor";

export function ItemPicker({ value, onChange, placeholder = "Search by name…", testId = "item-picker" }) {
  const client = useEcosystemClient();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const triggerRef = useRef(null);

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setResults([]);
      setLoading(false);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    const handle = setTimeout(() => {
      client.listItems({ q: trimmed, limit: 8 }).then(res => {
        if (!cancelled) setResults(res?.items ?? []);
      }).catch(() => {
        if (!cancelled) setResults([]);
      }).finally(() => {
        if (!cancelled) setLoading(false);
      });
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [client, query]);

  if (value) {
    return <div data-testid={`${testId}-selected`} className="flex items-center gap-2 border border-gray-300 rounded px-3 py-2 bg-white">
        <ItemIcon iconUrl={value.icon_url} namespace={value.namespace} displayName={value.display_name} size={22} />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-gray-900 truncate">{value.display_name}</div>
          <div className="text-xs text-gray-400 truncate">{value.namespace}</div>
        </div>
        <button type="button" data-testid={`${testId}-clear`} onClick={() => onChange(null)} className="text-xs text-indigo-600 hover:text-indigo-700 bg-none border-none cursor-pointer flex-shrink-0">
          Change
        </button>
      </div>;
  }

  const showPopover = open && (loading || results.length > 0 || query.trim().length > 0);
  return <div className="relative">
      <input ref={triggerRef} data-testid={`${testId}-input`} value={query} onChange={e => {
      setQuery(e.target.value);
      setOpen(true);
    }} onFocus={() => setOpen(true)} placeholder={placeholder} className="w-full bg-white border border-gray-300 rounded px-3 py-2 text-sm text-gray-900 focus:outline-none focus-visible:outline-none! focus:border-indigo-300" />
      <PopoverAnchor anchorRef={triggerRef} open={showPopover} align="left" onRequestClose={() => setOpen(false)}>
        <div data-testid={`${testId}-results`} role="listbox" className="min-w-[320px] max-h-64 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-md">
          {loading && <div className="px-3 py-2 text-xs text-gray-400">Searching…</div>}
          {!loading && results.map(item => <button key={item.id} type="button" data-testid="item-picker-result" role="option" onClick={() => {
          onChange(item);
          setQuery("");
          setResults([]);
          setOpen(false);
        }} className="w-full flex items-center gap-2 px-3 py-2 text-left bg-none border-none cursor-pointer hover:bg-gray-50">
              <ItemIcon iconUrl={item.icon_url} namespace={item.namespace} displayName={item.display_name} size={20} />
              <div className="flex-1 min-w-0">
                <div className="text-sm text-gray-900 truncate">{item.display_name}</div>
                <div className="text-xs text-gray-400 truncate">{item.namespace}</div>
              </div>
              <span className="text-xs text-gray-400 flex-shrink-0">{item.item_type}</span>
            </button>)}
          {!loading && results.length === 0 && query.trim() && <div data-testid={`${testId}-no-matches`} className="px-3 py-2 text-xs text-gray-400">No matches.</div>}
        </div>
      </PopoverAnchor>
    </div>;
}
