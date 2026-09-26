// SPDX-License-Identifier: MIT
// Ported UX from the merged frontend's SkillFormPage (now
// ai-ui/src/components/Marketplace.jsx's inline LineNumberedTextarea,
// lines ~970-992 at the time this was ported) -- structure/behavior only,
// rewritten against this package's own theme tokens, not copied verbatim.
import { useRef, type UIEvent } from "react";

export function LineNumberedTextarea({ value, onChange, placeholder, rows = 14 }: {
  value: string; onChange: (value: string) => void; placeholder?: string; rows?: number;
}) {
  const lineNumbersRef = useRef<HTMLDivElement>(null);
  const lineCount = Math.max(value.split("\n").length, rows);

  const syncScroll = (e: UIEvent<HTMLTextAreaElement>) => {
    if (lineNumbersRef.current) lineNumbersRef.current.scrollTop = e.currentTarget.scrollTop;
  };

  return (
    <div
      data-testid="line-numbered-textarea"
      style={{ display: "flex", border: "1px solid var(--eco-color-border)", borderRadius: "var(--eco-radius-md)", overflow: "hidden", fontFamily: "monospace", fontSize: "var(--eco-font-sizeSm)" }}
    >
      <div
        ref={lineNumbersRef}
        aria-hidden="true"
        style={{ padding: "8px 6px", textAlign: "right", color: "var(--eco-color-textMuted)", background: "var(--eco-color-surface)", userSelect: "none", overflow: "hidden", height: `${rows * 20}px` }}
      >
        {Array.from({ length: lineCount }, (_, i) => <div key={i} style={{ lineHeight: "20px" }}>{i + 1}</div>)}
      </div>
      <textarea
        value={value}
        placeholder={placeholder}
        rows={rows}
        onChange={(e) => onChange(e.target.value)}
        onScroll={syncScroll}
        style={{ flex: 1, border: "none", outline: "none", resize: "vertical", padding: "8px", lineHeight: "20px", color: "var(--eco-color-textPrimary)", background: "var(--eco-color-bg)" }}
      />
    </div>
  );
}
