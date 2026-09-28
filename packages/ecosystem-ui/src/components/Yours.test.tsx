// SPDX-License-Identifier: MIT
// Regression test for a real crash found live: "Cannot read properties of
// undefined (reading 'allowed_actions')" -- CONTRACTS.md §9 documents
// `item` as always present on an Install, but a backend regression once
// shipped a row without one. This component must never crash the whole
// screen over one bad row -- it renders a small "unavailable" placeholder
// instead. A custom minimal client (not MockEcosystemClient, which always
// builds well-formed installs from real items) is used here specifically
// to construct that otherwise-impossible-via-the-mock shape.
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Yours } from "./Yours";
import { HostProvider } from "../context/HostContext";
import { EcosystemConfigProvider } from "../hooks/useEcosystemConfig";
import { MOCK_CONFIG, MOCK_DETAILS } from "../client/fixtures";
import { LIGHT_TOKENS } from "../theme";
import type { EcosystemClient } from "../client/EcosystemClient";
import type { AllowedAction, Install } from "../types";

function renderYoursWith(installs: Install[]) {
  const client = {
    getInstalls: () => Promise.resolve({ installs, legacy_items: [], has_any: installs.length > 0, next_cursor: null }),
  } as unknown as EcosystemClient;
  return render(
    <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
      <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
        <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} />
      </EcosystemConfigProvider>
    </HostProvider>,
  );
}

const WELL_FORMED_ITEM = Object.values(MOCK_DETAILS)[0]!;
const WELL_FORMED_INSTALL: Install = {
  install_id: "install-1", item: WELL_FORMED_ITEM, version_id: "v1", scope: "private", origin: "added",
  installed_by: "user-1", installed_for: "user-1", enabled: true, surfaces: ["chat"],
  auto_update: false, installed_at: new Date().toISOString(),
};

describe("Yours", () => {
  it("renders a well-formed install row normally", async () => {
    renderYoursWith([WELL_FORMED_INSTALL]);
    expect(await screen.findByText(WELL_FORMED_ITEM.display_name)).toBeInTheDocument();
  });

  it("renders an 'unavailable' placeholder instead of crashing when a row's item is missing", async () => {
    const brokenInstall = { ...WELL_FORMED_INSTALL, install_id: "install-broken", item: null as unknown as Install["item"] };
    renderYoursWith([brokenInstall, WELL_FORMED_INSTALL]);

    expect(await screen.findByTestId("yours-install-row-unavailable")).toBeInTheDocument();
    expect(screen.getByText(/no longer available/i)).toBeInTheDocument();
    // The other, well-formed row still renders -- one bad row never blanks the rest.
    expect(screen.getByText(WELL_FORMED_ITEM.display_name)).toBeInTheDocument();
  });

  function renderYoursWithQuery(installs: Install[], query: string) {
    const client = {
      getInstalls: () => Promise.resolve({ installs, legacy_items: [], has_any: installs.length > 0, next_cursor: null }),
    } as unknown as EcosystemClient;
    return render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} query={query} />
        </EcosystemConfigProvider>
      </HostProvider>,
    );
  }

  it("a query filters rows by name+description, matching the reference mock's own yoursView()", async () => {
    const other: Install = {
      ...WELL_FORMED_INSTALL,
      install_id: "install-2",
      item: { ...WELL_FORMED_ITEM, id: "item-other", namespace: "acme/other", display_name: "Totally Different Thing" },
    };
    renderYoursWithQuery([WELL_FORMED_INSTALL, other], WELL_FORMED_ITEM.display_name);
    await screen.findByText(WELL_FORMED_ITEM.display_name);
    expect(screen.queryByText("Totally Different Thing")).not.toBeInTheDocument();
  });

  it("a query matching nothing shows a 'none of yours match' message instead of an empty screen", async () => {
    renderYoursWithQuery([WELL_FORMED_INSTALL], "zzz-no-match-anywhere");
    expect(await screen.findByTestId("yours-no-matches")).toBeInTheDocument();
  });

  it("a broken (item-less) row always stays visible even when a query is active -- it has nothing to match against", async () => {
    const brokenInstall = { ...WELL_FORMED_INSTALL, install_id: "install-broken", item: null as unknown as Install["item"] };
    renderYoursWithQuery([brokenInstall], "zzz-no-match-anywhere");
    expect(await screen.findByTestId("yours-install-row-unavailable")).toBeInTheDocument();
  });

  it("the 'unavailable' row's Remove button uninstalls it", async () => {
    const uninstall = vi.fn().mockResolvedValue(undefined);
    const brokenInstall = { ...WELL_FORMED_INSTALL, install_id: "install-broken", item: null as unknown as Install["item"] };
    const client = {
      getInstalls: () => Promise.resolve({ installs: [brokenInstall], legacy_items: [], has_any: true, next_cursor: null }),
      uninstall,
    } as unknown as EcosystemClient;
    render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>,
    );
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.click(await screen.findByText(/remove/i));
    expect(uninstall).toHaveBeenCalledWith("install-broken");
  });

  // Task 4 (live user report): surface checkboxes previously called a
  // no-op onChange -- these prove the real endpoint is called, and that a
  // failed call rolls the checkbox back rather than leaving the UI lying
  // about the server's actual state.
  it("toggling a surface calls setSurfaces with the full new surfaces list (optimistic)", async () => {
    const setSurfaces = vi.fn().mockResolvedValue(undefined);
    const client = {
      getInstalls: () => Promise.resolve({ installs: [WELL_FORMED_INSTALL], legacy_items: [], has_any: true, next_cursor: null }),
      setSurfaces,
    } as unknown as EcosystemClient;
    render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>,
    );
    const { fireEvent } = await import("@testing-library/react");
    const desktopToggle = (await screen.findAllByTestId("surface-toggle")).find(
      (el) => el.getAttribute("data-surface") === "desktop",
    )!;
    // Rebuilt as a toggle-chip button (2026-09-27, item 5) -- the chip
    // itself is the clickable element now, not a label wrapping a hidden
    // checkbox input.
    fireEvent.click(desktopToggle);
    expect(setSurfaces).toHaveBeenCalledWith("install-1", ["chat", "desktop"]);
  });

  // Item 1 (M5 UI-polish review): "Delete permanently" is a hard, unconfirmable-
  // by-a-single-click destructive action -- must go through ConfirmDialog,
  // and only actually call deleteDraft once the user confirms.
  it("Delete permanently opens a confirm dialog and only calls deleteDraft after confirming", async () => {
    const deleteDraft = vi.fn().mockResolvedValue(undefined);
    const deletableItem = { ...WELL_FORMED_ITEM, allowed_actions: ["delete_draft", "report"] as AllowedAction[], has_other_installs: false };
    const install: Install = { ...WELL_FORMED_INSTALL, item: deletableItem };
    const client = {
      getInstalls: () => Promise.resolve({ installs: [install], legacy_items: [], has_any: true, next_cursor: null }),
      deleteDraft,
    } as unknown as EcosystemClient;
    render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} layout="list" />
        </EcosystemConfigProvider>
      </HostProvider>,
    );
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.click(await screen.findByTestId("detail-installed-trigger"));
    fireEvent.click(await screen.findByText("Delete permanently"));
    // Confirmed the dialog opened and deleteDraft has NOT fired yet.
    expect(await screen.findByTestId("confirm-dialog")).toBeInTheDocument();
    expect(deleteDraft).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));
    expect(deleteDraft).toHaveBeenCalledWith(deletableItem.id);
  });

  it("Delete permanently is not offered, and Retire is offered instead with an explanatory note, when the item has other installs", async () => {
    const sharedItem = { ...WELL_FORMED_ITEM, allowed_actions: ["deprecate", "report"] as AllowedAction[], has_other_installs: true };
    const install: Install = { ...WELL_FORMED_INSTALL, item: sharedItem };
    const client = {
      getInstalls: () => Promise.resolve({ installs: [install], legacy_items: [], has_any: true, next_cursor: null }),
    } as unknown as EcosystemClient;
    render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} layout="list" />
        </EcosystemConfigProvider>
      </HostProvider>,
    );
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.click(await screen.findByTestId("detail-installed-trigger"));
    expect(screen.queryByText("Delete permanently")).not.toBeInTheDocument();
    expect(await screen.findByTestId("detail-installed-menu-retire-note")).toBeInTheDocument();
    expect(screen.getByText("Retire")).toBeInTheDocument();
  });

  it("defaults to grid layout and switches every install row's data-layout attribute when list is requested", async () => {
    const { rerender } = render(
      <HostProvider value={{ client: { getInstalls: () => Promise.resolve({ installs: [WELL_FORMED_INSTALL], legacy_items: [], has_any: true, next_cursor: null }) } as unknown as EcosystemClient, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>,
    );
    expect(await screen.findByTestId("yours-install-row")).toHaveAttribute("data-layout", "grid");

    rerender(
      <HostProvider value={{ client: { getInstalls: () => Promise.resolve({ installs: [WELL_FORMED_INSTALL], legacy_items: [], has_any: true, next_cursor: null }) } as unknown as EcosystemClient, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} layout="list" />
        </EcosystemConfigProvider>
      </HostProvider>,
    );
    expect(await screen.findByTestId("yours-install-row")).toHaveAttribute("data-layout", "list");
  });

  it("rolls the checkbox back if the setSurfaces call fails", async () => {
    const setSurfaces = vi.fn().mockRejectedValue(new Error("network error"));
    const client = {
      getInstalls: () => Promise.resolve({ installs: [WELL_FORMED_INSTALL], legacy_items: [], has_any: true, next_cursor: null }),
      setSurfaces,
    } as unknown as EcosystemClient;
    render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>,
    );
    const { fireEvent, waitFor } = await import("@testing-library/react");
    const desktopToggle = (await screen.findAllByTestId("surface-toggle")).find(
      (el) => el.getAttribute("data-surface") === "desktop",
    )!;
    fireEvent.click(desktopToggle); // optimistic: checked immediately
    expect(desktopToggle).toHaveAttribute("aria-checked", "true");
    await waitFor(() => expect(desktopToggle).toHaveAttribute("aria-checked", "false")); // rolled back once the promise rejects
  });

  // Item 3 (2026-09-28 live-testing round): a card with several surface
  // chips AND a longer name/description must still never wrap its footer
  // onto a second line -- surface-toggles' own flexWrap flipped from
  // "wrap" to "nowrap" (SurfaceToggles.tsx) is the fix; this pins it
  // against exactly the stress case the user hit (many surfaces, long
  // content), not just the short happy-path fixture.
  it("grid layout's surface-chips row never wraps, even with many surfaces and a long name/description", async () => {
    const longItem = {
      ...WELL_FORMED_ITEM,
      display_name: "A Really Quite Long Skill Name That Could Push The Footer Wide",
      description: "A very long description that spans multiple lines of text, stress-testing the footer layout under grid-mode rendering with several surfaces enabled at once.",
    };
    const install: Install = { ...WELL_FORMED_INSTALL, item: longItem, surfaces: ["chat", "agent_studio", "desktop"] };
    renderYoursWith([install]);
    const surfaceContainer = await screen.findByTestId("surface-toggles");
    expect(surfaceContainer).toHaveStyle({ flexWrap: "nowrap" });
  });

  // Item 3: "Installed ▾" (grid mode) must render at the exact same
  // padding/font-size as Discover's own "+ Add" (QuickAddButton in
  // Card.tsx) -- a real bug found live had it noticeably larger once an
  // item got installed. List mode keeps the roomier default size
  // (untouched by this fix -- its own layout has different concerns).
  it("grid layout's Installed trigger renders at the same compact size as Discover's + Add button", async () => {
    renderYoursWith([WELL_FORMED_INSTALL]);
    const trigger = await screen.findByTestId("detail-installed-trigger");
    expect(trigger).toHaveStyle({ padding: "2px 8px", fontSize: "var(--eco-font-sizeXs)" });
  });

  it("list layout's Installed trigger keeps the roomier default size, not the grid-mode compact one", async () => {
    const client = {
      getInstalls: () => Promise.resolve({ installs: [WELL_FORMED_INSTALL], legacy_items: [], has_any: true, next_cursor: null }),
    } as unknown as EcosystemClient;
    render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} layout="list" />
        </EcosystemConfigProvider>
      </HostProvider>,
    );
    const trigger = await screen.findByTestId("detail-installed-trigger");
    expect(trigger).toHaveStyle({ padding: "8px 12px" });
  });
});
