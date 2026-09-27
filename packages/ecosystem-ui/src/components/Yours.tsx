// SPDX-License-Identifier: MIT
// Task F-6: 6 groups -- 5 client-side-grouped by Install.origin
// (CONTRACTS.md §9), plus a 6th, read-only "Available from existing
// skills" group rendered directly from legacy_items (never a synthesized
// Install row). Kebab menu contents are exactly allowed_actions -- no
// client-side inference of what a caller can do (F-6's own test rule).
import { useCallback, useEffect, useState } from "react";
import type { Install, ItemSummary, LegacyItem } from "../types";
import { useEcosystemClient, useI18n } from "../context/HostContext";
import { ItemIcon } from "./ItemIcon";
import { TrustBadge } from "./Badges";
import { RequiredLock } from "./RequiredLock";
import { SurfaceToggles } from "./SurfaceToggles";
import { KebabMenu, buildKebabActions } from "./KebabMenu";
import { InstalledMenu } from "./detail/InstalledMenu";
import { EmptyState } from "./EmptyState";

/** Active/Disabled/Verifying/Blocked -- composed from install.enabled +
 * item.status/latest_verdict, since no single field carries this today.
 * Priority: a caller-disabled install always shows as Disabled even if
 * the underlying item would otherwise read as Active (their own choice
 * should read back to them first); Blocked (retired/failed) and
 * Verifying (still gating) only matter for an ENABLED install. */
function statusChip(item: ItemSummary, enabled: boolean): { label: string; tone: "success" | "muted" | "warning" | "danger" } {
  if (!enabled) return { label: "Disabled", tone: "muted" };
  if (item.status === "yanked" || item.status === "deprecated" || item.latest_verdict === "fail") {
    return { label: "Blocked", tone: "danger" };
  }
  if (item.latest_verdict === "pending") return { label: "Verifying", tone: "warning" };
  return { label: "Active", tone: "success" };
}

function StatusChip({ item, enabled }: { item: ItemSummary; enabled: boolean }) {
  const { label, tone } = statusChip(item, enabled);
  const colorVar = { success: "--eco-color-success", muted: "--eco-color-textMuted", warning: "--eco-color-warning", danger: "--eco-color-danger" }[tone];
  return (
    <span
      data-testid="yours-status-chip"
      data-status={label}
      style={{
        fontSize: "var(--eco-font-sizeXs)", padding: "2px 8px", borderRadius: "var(--eco-radius-full)",
        color: `var(${colorVar})`, border: `1px solid var(${colorVar})`,
      }}
    >
      {label}
    </span>
  );
}

const GROUP_ORDER: Array<{ origin: Install["origin"]; label: string }> = [
  { origin: "created", label: "Created by me" },
  { origin: "shared", label: "Shared with me" },
  { origin: "provisioned", label: "Org provisioned" },
  { origin: "required", label: "Required" },
  { origin: "added", label: "Added from Discover" },
];

export function Yours({ itemType, onOpen, onCreate, onDiscover, query = "" }: {
  itemType: string;
  onOpen: (item: ItemSummary) => void;
  onCreate: () => void;
  onDiscover: () => void;
  /** CatalogScreen's Toolbar search box -- matches the reference mock's own
   * yoursView() (`S.q` filters both Discover and Yours by name+description). */
  query?: string;
}) {
  const client = useEcosystemClient();
  const strings = useI18n();
  const [installs, setInstalls] = useState<Install[] | null>(null);
  const [legacyItems, setLegacyItems] = useState<LegacyItem[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    client.getInstalls(itemType)
      .then((res) => {
        if (cancelled) return;
        setInstalls(res.installs);
        setLegacyItems(res.legacy_items);
      })
      .catch((e) => { if (!cancelled) setError(e); });
    return () => { cancelled = true; };
  }, [client, itemType, refreshKey]);

  if (error) return <div data-testid="yours-error" role="alert">Couldn't load your items. Please try again.</div>;
  if (installs === null) return <div data-testid="yours-loading">{strings.verifying}</div>;

  if (installs.length === 0 && legacyItems.length === 0) {
    return <EmptyState message={strings.empty_yours} onDiscover={onDiscover} onCreate={onCreate} />;
  }

  // A row with no `item` (see the defensive check in InstallRow below) has
  // no name/description to match against -- it always stays visible rather
  // than silently disappearing behind a search that can't see it.
  const q = query.trim().toLowerCase();
  const matchesQuery = (name: string, description: string) => !q || `${name} ${description}`.toLowerCase().includes(q);
  const filteredInstalls = installs.filter((i) => !i.item || matchesQuery(i.item.display_name, i.item.description));
  const filteredLegacy = legacyItems.filter((l) => matchesQuery(l.item.display_name, l.item.description));

  if (q && filteredInstalls.length === 0 && filteredLegacy.length === 0) {
    return <p data-testid="yours-no-matches" style={{ color: "var(--eco-color-textMuted)" }}>None of your {itemType}s match &ldquo;{query}&rdquo;.</p>;
  }

  return (
    <div data-testid="yours-screen">
      {GROUP_ORDER.map(({ origin, label }) => {
        const rows = filteredInstalls.filter((i) => i.origin === origin);
        // "Created by me" is the one group with a friendly, actionable
        // empty hint -- every other empty group just renders nothing
        // (unchanged behavior), since "share/provision/require something"
        // isn't a self-serve action the way "create a skill" is.
        if (rows.length === 0) {
          if (origin !== "created" || q) return null;
          return (
            <section key={origin} data-testid="yours-group-empty-hint" style={{ marginBottom: "var(--eco-space-lg)" }}>
              <h3 style={{ fontSize: "var(--eco-font-sizeLg)", color: "var(--eco-color-textPrimary)" }}>{label} (0)</h3>
              <p style={{ color: "var(--eco-color-textSecondary)", fontSize: "var(--eco-font-sizeSm)", margin: "4px 0 8px" }}>
                You haven&apos;t created anything yet.
              </p>
              <button
                type="button"
                onClick={onCreate}
                style={{ background: "none", border: "1px solid var(--eco-color-border)", borderRadius: "var(--eco-radius-md)", padding: "6px 12px", color: "var(--eco-color-accentSkill)", cursor: "pointer", fontSize: "var(--eco-font-sizeSm)" }}
              >
                Create a skill
              </button>
            </section>
          );
        }
        return (
          <InstallGroup key={origin} label={label} rows={rows} onOpen={onOpen} client={client} onChanged={refresh} />
        );
      })}
      {filteredLegacy.length > 0 && (
        <section data-testid="yours-legacy-group" style={{ marginBottom: "var(--eco-space-lg)" }}>
          <h3 style={{ fontSize: "var(--eco-font-sizeLg)", color: "var(--eco-color-textPrimary)" }}>Available from existing skills</h3>
          {filteredLegacy.map((legacy) => (
            <div
              key={legacy.item.id}
              data-testid="yours-legacy-row"
              style={{ display: "flex", alignItems: "center", gap: "var(--eco-space-sm)", padding: "var(--eco-space-sm) 0", borderBottom: "1px solid var(--eco-color-border)" }}
            >
              <ItemIcon iconUrl={legacy.item.icon_url} namespace={legacy.item.namespace} displayName={legacy.item.display_name} size={28} />
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, color: "var(--eco-color-textPrimary)" }}>{legacy.item.display_name}</div>
              </div>
              <button
                type="button"
                data-testid="yours-legacy-open"
                onClick={() => onOpen(legacy.item)}
                style={{ background: "none", border: "none", color: "var(--eco-color-accentSkill)", cursor: "pointer" }}
              >
                Open
              </button>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}

function InstallGroup({ label, rows, onOpen, client, onChanged }: {
  label: string; rows: Install[]; onOpen: (item: ItemSummary) => void;
  client: ReturnType<typeof useEcosystemClient>; onChanged: () => void;
}) {
  return (
    <section data-testid="yours-group" data-group-label={label} style={{ marginBottom: "var(--eco-space-lg)" }}>
      <h3 style={{ fontSize: "var(--eco-font-sizeLg)", color: "var(--eco-color-textPrimary)" }}>{label} ({rows.length})</h3>
      {rows.map((install) => (
        <InstallRow key={install.install_id} install={install} onOpen={onOpen} client={client} onChanged={onChanged} />
      ))}
    </section>
  );
}

function InstallRow({ install, onOpen, client, onChanged }: {
  install: Install; onOpen: (item: ItemSummary) => void;
  client: ReturnType<typeof useEcosystemClient>; onChanged: () => void;
}) {
  // Local, optimistically-updated copy of the install's surfaces (task 4:
  // the checkboxes need to flip immediately on click, before the real
  // PATCH round-trips) -- must be declared before the early return below
  // so this hook always runs in the same order (rules of hooks), even
  // though it's meaningless for the `!install.item` branch.
  const [surfaces, setSurfaces] = useState(install.surfaces);
  useEffect(() => setSurfaces(install.surfaces), [install.surfaces]);

  // Defensive: CONTRACTS.md §9 documents `item` as always present on a
  // real Install row, and the backend is expected to guarantee that --
  // but a row this tolerant check can't protect against (a backend
  // regression, a future endpoint change) must never blank the whole
  // screen for every OTHER row too. One bad row shows "unavailable"
  // instead of crashing the list.
  if (!install.item) {
    return (
      <div
        data-testid="yours-install-row-unavailable"
        data-install-id={install.install_id}
        style={{ display: "flex", alignItems: "center", gap: "var(--eco-space-sm)", padding: "var(--eco-space-sm) 0", borderBottom: "1px solid var(--eco-color-border)", color: "var(--eco-color-textSecondary)" }}
      >
        <div style={{ flex: 1 }}>This item is no longer available.</div>
        <button
          type="button"
          onClick={() => client.uninstall(install.install_id).then(onChanged)}
          style={{ background: "none", border: "none", color: "var(--eco-color-accentSkill)", cursor: "pointer" }}
        >
          Remove
        </button>
      </div>
    );
  }

  // "Installed ▾" carries the primary, common actions (matches Detail.tsx's
  // own InstalledMenu, reused here for visual consistency between the two
  // screens); the kebab keeps only what InstalledMenu doesn't cover
  // (report/deprecate/delete_draft/unshare -- rarer, secondary actions).
  const kebabActions = buildKebabActions(install.item.allowed_actions, {
    report: () => client.reportItem(install.item.id, "reported from Yours"),
    deprecate: () => client.deprecateItem(install.item.id).then(onChanged),
    delete_draft: () => client.deleteDraft(install.item.id).then(onChanged),
  });
  const required = install.scope === "required";

  return (
    <div
      data-testid="yours-install-row"
      data-install-id={install.install_id}
      style={{ display: "flex", alignItems: "center", gap: "var(--eco-space-sm)", padding: "var(--eco-space-sm) 0", borderBottom: "1px solid var(--eco-color-border)" }}
    >
      <ItemIcon iconUrl={install.item.icon_url} namespace={install.item.namespace} displayName={install.item.display_name} size={28} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <button
            type="button"
            onClick={() => onOpen(install.item)}
            style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontWeight: 600, color: "var(--eco-color-textPrimary)" }}
          >
            {install.item.display_name}
          </button>
          {required && <RequiredLock />}
          <TrustBadge tier={install.item.trust_tier} />
          <StatusChip item={install.item} enabled={install.enabled} />
        </div>
        <div
          data-testid="yours-row-description"
          style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
        >
          {install.item.description}
        </div>
        <SurfaceToggles
          enabledSurfaces={surfaces}
          disabled={required}
          onChange={(next) => {
            const previous = surfaces;
            setSurfaces(next); // optimistic -- flips the chip immediately
            client.setSurfaces(install.install_id, next).catch(() => setSurfaces(previous)); // roll back on error
          }}
        />
      </div>
      <InstalledMenu
        enabled={install.enabled}
        required={required}
        onToggleEnabled={(next) => client.setEnabled(install.install_id, next).then(onChanged)}
        // No tab deep-link exists yet -- opens Detail on its default tab;
        // the user clicks "Versions" themselves once there (disclosed
        // simplification, not a full deep-link).
        onViewVersions={() => onOpen(install.item)}
        onUninstall={() => client.uninstall(install.install_id).then(onChanged)}
      />
      {kebabActions.length > 0 && <KebabMenu actions={kebabActions} />}
    </div>
  );
}
