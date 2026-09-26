// SPDX-License-Identifier: MIT
// Task F-6: Yours' empty state -- two CTAs, Discover + Create.
export function EmptyState({ message, onDiscover, onCreate }: {
  message: string; onDiscover: () => void; onCreate: () => void;
}) {
  return (
    <div data-testid="yours-empty-state" style={{ textAlign: "center", padding: "var(--eco-space-xl)", color: "var(--eco-color-textSecondary)" }}>
      <p>{message}</p>
      <div style={{ display: "flex", gap: "var(--eco-space-sm)", justifyContent: "center", marginTop: "var(--eco-space-md)" }}>
        <button
          type="button"
          data-testid="empty-state-discover"
          onClick={onDiscover}
          style={{ padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", cursor: "pointer" }}
        >
          Browse Discover
        </button>
        <button
          type="button"
          data-testid="empty-state-create"
          onClick={onCreate}
          style={{ padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "none", background: "var(--eco-color-accentSkill)", color: "var(--eco-color-accentSkillText)", cursor: "pointer" }}
        >
          Create your own
        </button>
      </div>
    </div>
  );
}
