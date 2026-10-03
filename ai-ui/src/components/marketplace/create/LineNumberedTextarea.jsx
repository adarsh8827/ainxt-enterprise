// SPDX-License-Identifier: MIT
// Ported UX from the merged frontend's SkillFormPage (now
// ai-ui/src/components/Marketplace.jsx's inline LineNumberedTextarea,
// lines ~970-992 at the time this was ported) -- structure/behavior only,
// rewritten against this package's own theme tokens, not copied verbatim.
import { useRef } from "react";
export function LineNumberedTextarea({
  value,
  onChange,
  placeholder,
  rows = 14
}) {
  const lineNumbersRef = useRef(null);
  const lineCount = Math.max(value.split("\n").length, rows);
  const syncScroll = e => {
    if (lineNumbersRef.current) lineNumbersRef.current.scrollTop = e.currentTarget.scrollTop;
  };
  return <div data-testid="line-numbered-textarea" className="flex border border-gray-300 rounded overflow-hidden font-mono text-sm focus-within:border-indigo-300">
      <div ref={lineNumbersRef} aria-hidden="true" className="px-1.5 py-2 text-right text-gray-400 bg-gray-50 select-none overflow-hidden" style={{
      height: `${rows * 20}px`
    }}>
        {Array.from({
        length: lineCount
      }, (_, i) => <div key={i} className="leading-5">{i + 1}</div>)}
      </div>
      <textarea value={value} placeholder={placeholder} rows={rows} onChange={e => onChange(e.target.value)} onScroll={syncScroll} className="flex-1 border-none outline-none focus-visible:outline-none! resize-y px-2 py-2 leading-5 text-gray-900 bg-white" />
    </div>;
}