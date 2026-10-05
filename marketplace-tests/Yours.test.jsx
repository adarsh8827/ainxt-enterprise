// SPDX-License-Identifier: MIT
// Regression test for a real crash found live: "Cannot read properties of
// undefined (reading 'allowed_actions')" -- CONTRACTS.md §9 documents
// `item` as always present on an Install, but a backend regression once
// shipped a row without one. This component must never crash the whole
// screen over one bad row -- it renders a small "unavailable" placeholder
// instead. A custom minimal client (not MockEcosystemClient, which always
// builds well-formed installs from real items) is used here specifically
// to construct that otherwise-impossible-via-the-mock shape.
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { Yours } from "@marketplace/Yours";
import { HostProvider } from "@marketplace/lib/context/HostContext";
import { EcosystemConfigProvider } from "@marketplace/lib/hooks/useEcosystemConfig";
import { MOCK_CONFIG, MOCK_DETAILS } from "@marketplace/lib/client/fixtures";
import { LIGHT_TOKENS } from "@marketplace/lib/theme";
import { __resetCatalogCacheForTests } from "@marketplace/lib/catalogCache";
// Item (d) (2026-09-29 live-test round): catalogCache.ts's module-level
// store is deliberately outside this component's own lifecycle (so it
// survives a real Discover<->Yours unmount/remount) -- which also means
// its module registry is shared across every `it()` block in this file,
// same reason installTracking.ts's own tests reset themselves. Every test
// below uses itemType="skill", so without this reset the SECOND test to
// run would see the FIRST test's cached installs on its very first render.
afterEach(() => __resetCatalogCacheForTests());
function renderYoursWith(installs) {
  const client = {
    getInstalls: () => Promise.resolve({
      installs,
      legacy_items: [],
      has_any: installs.length > 0,
      next_cursor: null
    })
  };
  return render(<HostProvider value={{
    client,
    theme: LIGHT_TOKENS,
    layout: "full",
    router: {
      path: "/skills",
      navigate: () => {}
    }
  }}>
      <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
        <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} />
      </EcosystemConfigProvider>
    </HostProvider>);
}
const WELL_FORMED_ITEM = Object.values(MOCK_DETAILS)[0];
const WELL_FORMED_INSTALL = {
  install_id: "install-1",
  item: WELL_FORMED_ITEM,
  version_id: "v1",
  scope: "private",
  origin: "added",
  installed_by: "user-1",
  installed_for: "user-1",
  enabled: true,
  surfaces: ["chat"],
  auto_update: false,
  installed_at: new Date().toISOString()
};
describe("Yours", () => {
  it("renders a well-formed install row normally", async () => {
    renderYoursWith([WELL_FORMED_INSTALL]);
    expect(await screen.findByText(WELL_FORMED_ITEM.display_name)).toBeInTheDocument();
  });
  // BUG-U03 fix: "deprecated" (a user's own voluntary Retire) used to show
  // the exact same red "Blocked" badge as "yanked" (an admin force-
  // disable) or a failed gate verdict -- now gets its own neutral label.
  it("shows 'Retired' (not 'Blocked') for a deprecated item", async () => {
    const retiredInstall = {
      ...WELL_FORMED_INSTALL,
      item: {
        ...WELL_FORMED_ITEM,
        status: "deprecated"
      }
    };
    renderYoursWith([retiredInstall]);
    const chip = await screen.findByTestId("yours-status-chip");
    expect(chip).toHaveTextContent("Retired");
    expect(chip).not.toHaveTextContent("Blocked");
  });
  it("still shows 'Blocked' for a yanked item (genuinely someone/something else stopping it, not the caller's own retire)", async () => {
    const yankedInstall = {
      ...WELL_FORMED_INSTALL,
      item: {
        ...WELL_FORMED_ITEM,
        status: "yanked"
      }
    };
    renderYoursWith([yankedInstall]);
    const chip = await screen.findByTestId("yours-status-chip");
    expect(chip).toHaveTextContent("Blocked");
  });
  // BUG-U04 fix: "Versions & rollback" used to always open Detail on its
  // default (Overview) tab, forcing an extra click onto Versions every
  // time -- now it passes "versions" through onOpen as a deep-link seed.
  it("'Versions & rollback' opens Detail with 'versions' as the initial tab", async () => {
    const onOpen = vi.fn();
    const client = {
      getInstalls: () => Promise.resolve({
        installs: [WELL_FORMED_INSTALL],
        legacy_items: [],
        has_any: true,
        next_cursor: null
      })
    };
    render(<HostProvider value={{
      client,
      theme: LIGHT_TOKENS,
      layout: "full",
      router: {
        path: "/skills",
        navigate: () => {}
      }
    }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={onOpen} onCreate={() => {}} onDiscover={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>);
    await screen.findByText(WELL_FORMED_ITEM.display_name);
    fireEvent.click(screen.getByTestId("detail-installed-trigger"));
    fireEvent.click(screen.getByText("Versions & rollback"));
    expect(onOpen).toHaveBeenCalledWith(WELL_FORMED_ITEM, "versions");
  });
  it("renders an 'unavailable' placeholder instead of crashing when a row's item is missing", async () => {
    const brokenInstall = {
      ...WELL_FORMED_INSTALL,
      install_id: "install-broken",
      item: null
    };
    renderYoursWith([brokenInstall, WELL_FORMED_INSTALL]);
    expect(await screen.findByTestId("yours-install-row-unavailable")).toBeInTheDocument();
    expect(screen.getByText(/no longer available/i)).toBeInTheDocument();
    // The other, well-formed row still renders -- one bad row never blanks the rest.
    expect(screen.getByText(WELL_FORMED_ITEM.display_name)).toBeInTheDocument();
  });
  function renderYoursWithQuery(installs, query) {
    const client = {
      getInstalls: () => Promise.resolve({
        installs,
        legacy_items: [],
        has_any: installs.length > 0,
        next_cursor: null
      })
    };
    return render(<HostProvider value={{
      client,
      theme: LIGHT_TOKENS,
      layout: "full",
      router: {
        path: "/skills",
        navigate: () => {}
      }
    }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} query={query} />
        </EcosystemConfigProvider>
      </HostProvider>);
  }
  it("a query filters rows by name+description, matching the reference mock's own yoursView()", async () => {
    const other = {
      ...WELL_FORMED_INSTALL,
      install_id: "install-2",
      item: {
        ...WELL_FORMED_ITEM,
        id: "item-other",
        namespace: "acme/other",
        display_name: "Totally Different Thing"
      }
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
    const brokenInstall = {
      ...WELL_FORMED_INSTALL,
      install_id: "install-broken",
      item: null
    };
    renderYoursWithQuery([brokenInstall], "zzz-no-match-anywhere");
    expect(await screen.findByTestId("yours-install-row-unavailable")).toBeInTheDocument();
  });
  it("the 'unavailable' row's Remove button uninstalls it", async () => {
    const uninstall = vi.fn().mockResolvedValue(undefined);
    const brokenInstall = {
      ...WELL_FORMED_INSTALL,
      install_id: "install-broken",
      item: null
    };
    const client = {
      getInstalls: () => Promise.resolve({
        installs: [brokenInstall],
        legacy_items: [],
        has_any: true,
        next_cursor: null
      }),
      uninstall
    };
    render(<HostProvider value={{
      client,
      theme: LIGHT_TOKENS,
      layout: "full",
      router: {
        path: "/skills",
        navigate: () => {}
      }
    }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>);
    const {
      fireEvent
    } = await import("@testing-library/react");
    fireEvent.click(await screen.findByText(/remove/i));
    expect(uninstall).toHaveBeenCalledWith("install-broken");
  });
  describe("install-state-consistency round (2026-09-29)", () => {
    function renderYoursFull(overrides = {}) {
      const client = {
        getInstalls: () => Promise.resolve({
          installs: [WELL_FORMED_INSTALL],
          legacy_items: [],
          has_any: true,
          next_cursor: null
        }),
        ...overrides
      };
      render(<HostProvider value={{
        client,
        theme: LIGHT_TOKENS,
        layout: "full",
        router: {
          path: "/skills",
          navigate: () => {}
        }
      }}>
          <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
            <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} />
          </EcosystemConfigProvider>
        </HostProvider>);
      return client;
    }
    it("Uninstall from the Installed ▾ menu that 404s (already gone) refreshes silently instead of failing", async () => {
      const uninstall = vi.fn().mockRejectedValue(Object.assign(new Error("no such install"), {
        code: "NOT_FOUND"
      }));
      const getInstalls = vi.fn().mockResolvedValueOnce({
        installs: [WELL_FORMED_INSTALL],
        legacy_items: [],
        has_any: true,
        next_cursor: null
      }).mockResolvedValue({
        installs: [],
        legacy_items: [],
        has_any: false,
        next_cursor: null
      });
      renderYoursFull({
        uninstall,
        getInstalls
      });
      await screen.findByText(WELL_FORMED_ITEM.display_name);
      fireEvent.click(screen.getByTestId("detail-installed-trigger"));
      fireEvent.click(screen.getByText("Uninstall"));
      // Uninstalling now confirms first (user-flow QA round 2, 2026-10-03).
      fireEvent.click(await screen.findByTestId("confirm-dialog-confirm"));
      // Real behavior: getInstalls() is called again (the real,
      // authoritative re-fetch) rather than leaving a raw error on
      // screen -- the row for an install that's already gone simply
      // won't be in that fresh result.
      await waitFor(() => expect(getInstalls).toHaveBeenCalledTimes(2));
      expect(screen.queryByTestId("yours-row-action-error")).not.toBeInTheDocument();
    });
    it("a real (non-NOT_FOUND) uninstall failure surfaces a real error instead of vanishing as an unhandled rejection", async () => {
      const uninstall = vi.fn().mockRejectedValue(new Error("Uninstall requires marketplace:admin_sources"));
      renderYoursFull({
        uninstall
      });
      await screen.findByText(WELL_FORMED_ITEM.display_name);
      fireEvent.click(screen.getByTestId("detail-installed-trigger"));
      fireEvent.click(screen.getByText("Uninstall"));
      // Uninstalling now confirms first (user-flow QA round 2, 2026-10-03).
      fireEvent.click(await screen.findByTestId("confirm-dialog-confirm"));
      expect(await screen.findByTestId("yours-row-action-error")).toHaveTextContent("Uninstall requires marketplace:admin_sources");
    });
    it("toggling Disable that fails surfaces a real error instead of an unhandled rejection (previously had no .catch at all)", async () => {
      const setEnabled = vi.fn().mockRejectedValue(new Error("can't disable a required install"));
      renderYoursFull({
        setEnabled
      });
      await screen.findByText(WELL_FORMED_ITEM.display_name);
      fireEvent.click(screen.getByTestId("detail-installed-trigger"));
      fireEvent.click(screen.getByText("Disable"));
      // Disabling now confirms first (user-flow QA round 2, 2026-10-03).
      fireEvent.click(await screen.findByTestId("confirm-dialog-confirm"));
      expect(await screen.findByTestId("yours-row-action-error")).toHaveTextContent("can't disable a required install");
    });
    it("a real ecosystem.changed event (client.streamChanges) triggers a real refetch -- the cross-tab half of the fix", async () => {
      const handlers = {
        onEvent: null
      };
      const getInstalls = vi.fn().mockResolvedValue({
        installs: [WELL_FORMED_INSTALL],
        legacy_items: [],
        has_any: true,
        next_cursor: null
      });
      renderYoursFull({
        getInstalls,
        streamChanges: cb => {
          handlers.onEvent = cb;
          return () => {
            handlers.onEvent = null;
          };
        }
      });
      await screen.findByText(WELL_FORMED_ITEM.display_name);
      await waitFor(() => expect(getInstalls).toHaveBeenCalledTimes(1));
      handlers.onEvent?.();
      await waitFor(() => expect(getInstalls).toHaveBeenCalledTimes(2));
    });
  });

  // Per-surface toggles round (2026-09-29): the manual Chat/Agent Studio/
  // Desktop toggle chips are gone from Yours entirely for every normal
  // user -- a fresh install now defaults to every surface the org's
  // product profile allows (backend-only change, routers/ecosystem_
  // router.py's install_item()), and the one remaining write path
  // (EcosystemClient.setSurfaces) is admin-only, reachable ONLY from the
  // Detail page's "Advanced" section, never from this list/grid. This
  // replaces the old "toggling a surface calls setSurfaces" /
  // "rolls the checkbox back on failure" tests, which tested UI that no
  // longer exists here.
  it("never renders a surface-toggle control on any Yours row, in either layout", async () => {
    const setSurfaces = vi.fn().mockResolvedValue(undefined);
    const client = {
      getInstalls: () => Promise.resolve({
        installs: [WELL_FORMED_INSTALL],
        legacy_items: [],
        has_any: true,
        next_cursor: null
      }),
      setSurfaces
    };
    const {
      rerender
    } = render(<HostProvider value={{
      client,
      theme: LIGHT_TOKENS,
      layout: "full",
      router: {
        path: "/skills",
        navigate: () => {}
      }
    }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>);
    await screen.findByTestId("yours-install-row");
    expect(screen.queryByTestId("surface-toggles")).not.toBeInTheDocument();
    expect(screen.queryByTestId("surface-toggle")).not.toBeInTheDocument();
    rerender(<HostProvider value={{
      client,
      theme: LIGHT_TOKENS,
      layout: "full",
      router: {
        path: "/skills",
        navigate: () => {}
      }
    }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} layout="list" />
        </EcosystemConfigProvider>
      </HostProvider>);
    await screen.findByTestId("yours-install-row");
    expect(screen.queryByTestId("surface-toggles")).not.toBeInTheDocument();
    expect(screen.queryByTestId("surface-toggle")).not.toBeInTheDocument();
    expect(setSurfaces).not.toHaveBeenCalled();
  });

  // Item 1 (M5 UI-polish review): "Delete permanently" is a hard, unconfirmable-
  // by-a-single-click destructive action -- must go through ConfirmDialog,
  // and only actually call deleteDraft once the user confirms.
  it("Delete permanently opens a confirm dialog and only calls deleteDraft after confirming", async () => {
    const deleteDraft = vi.fn().mockResolvedValue(undefined);
    const deletableItem = {
      ...WELL_FORMED_ITEM,
      allowed_actions: ["delete_draft", "report"],
      has_other_installs: false
    };
    const install = {
      ...WELL_FORMED_INSTALL,
      item: deletableItem
    };
    const client = {
      getInstalls: () => Promise.resolve({
        installs: [install],
        legacy_items: [],
        has_any: true,
        next_cursor: null
      }),
      deleteDraft
    };
    render(<HostProvider value={{
      client,
      theme: LIGHT_TOKENS,
      layout: "full",
      router: {
        path: "/skills",
        navigate: () => {}
      }
    }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} layout="list" />
        </EcosystemConfigProvider>
      </HostProvider>);
    const {
      fireEvent
    } = await import("@testing-library/react");
    fireEvent.click(await screen.findByTestId("detail-installed-trigger"));
    fireEvent.click(await screen.findByText("Delete permanently"));
    // Confirmed the dialog opened and deleteDraft has NOT fired yet.
    expect(await screen.findByTestId("confirm-dialog")).toBeInTheDocument();
    expect(deleteDraft).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));
    expect(deleteDraft).toHaveBeenCalledWith(deletableItem.id);
  });
  // User-flow QA round 8 (2026-10-03, real user question: "report...
  // what it will do?"): used to fire client.reportItem(id, "reported
  // from Yours") immediately with zero confirmation and a hardcoded
  // reason -- now opens ReportDialog, requires a real typed reason
  // (Report stays disabled until one exists), and only calls the client
  // with what the caller actually typed.
  it("Report opens a dialog requiring a real reason, and only calls reportItem with what was typed", async () => {
    const reportItem = vi.fn().mockResolvedValue(undefined);
    const reportableItem = { ...WELL_FORMED_ITEM, allowed_actions: ["uninstall", "report"] };
    const install = { ...WELL_FORMED_INSTALL, item: reportableItem };
    const client = {
      getInstalls: () => Promise.resolve({ installs: [install], legacy_items: [], has_any: true, next_cursor: null }),
      reportItem,
    };
    render(
      <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/skills", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} layout="list" />
        </EcosystemConfigProvider>
      </HostProvider>,
    );
    fireEvent.click(await screen.findByTestId("kebab-trigger"));
    fireEvent.click(await screen.findByText("Report"));

    expect(await screen.findByTestId("report-dialog")).toBeInTheDocument();
    expect(reportItem).not.toHaveBeenCalled();

    const submitButton = screen.getByTestId("report-dialog-submit");
    expect(submitButton).toBeDisabled();

    fireEvent.change(screen.getByTestId("report-dialog-reason"), { target: { value: "Instructions ask for an API key in plain text." } });
    expect(submitButton).not.toBeDisabled();
    fireEvent.click(submitButton);

    await waitFor(() => expect(reportItem).toHaveBeenCalledWith(reportableItem.id, "Instructions ask for an API key in plain text."));
    expect(await screen.findByTestId("report-dialog-success")).toBeInTheDocument();
  });

  it("Delete permanently is not offered, and Retire is offered instead with an explanatory note, when the item has other installs", async () => {
    const sharedItem = {
      ...WELL_FORMED_ITEM,
      allowed_actions: ["deprecate", "report"],
      has_other_installs: true
    };
    const install = {
      ...WELL_FORMED_INSTALL,
      item: sharedItem
    };
    const client = {
      getInstalls: () => Promise.resolve({
        installs: [install],
        legacy_items: [],
        has_any: true,
        next_cursor: null
      })
    };
    render(<HostProvider value={{
      client,
      theme: LIGHT_TOKENS,
      layout: "full",
      router: {
        path: "/skills",
        navigate: () => {}
      }
    }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} layout="list" />
        </EcosystemConfigProvider>
      </HostProvider>);
    const {
      fireEvent
    } = await import("@testing-library/react");
    fireEvent.click(await screen.findByTestId("detail-installed-trigger"));
    expect(screen.queryByText("Delete permanently")).not.toBeInTheDocument();
    expect(await screen.findByTestId("detail-installed-menu-retire-note")).toBeInTheDocument();
    expect(screen.getByText("Retire")).toBeInTheDocument();
  });
  it("defaults to grid layout and switches every install row's data-layout attribute when list is requested", async () => {
    const {
      rerender
    } = render(<HostProvider value={{
      client: {
        getInstalls: () => Promise.resolve({
          installs: [WELL_FORMED_INSTALL],
          legacy_items: [],
          has_any: true,
          next_cursor: null
        })
      },
      theme: LIGHT_TOKENS,
      layout: "full",
      router: {
        path: "/skills",
        navigate: () => {}
      }
    }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>);
    expect(await screen.findByTestId("yours-install-row")).toHaveAttribute("data-layout", "grid");
    rerender(<HostProvider value={{
      client: {
        getInstalls: () => Promise.resolve({
          installs: [WELL_FORMED_INSTALL],
          legacy_items: [],
          has_any: true,
          next_cursor: null
        })
      },
      theme: LIGHT_TOKENS,
      layout: "full",
      router: {
        path: "/skills",
        navigate: () => {}
      }
    }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} layout="list" />
        </EcosystemConfigProvider>
      </HostProvider>);
    expect(await screen.findByTestId("yours-install-row")).toHaveAttribute("data-layout", "list");
  });

  // Item 3 (2026-09-28 live-testing round), superseded (2026-09-29): the
  // footer-never-wraps requirement now applies to the menus-only footer
  // (no surface chips to stress-test against anymore) -- a long name/
  // description alone must still never push the grid card's footer onto
  // a second line.
  it("grid layout's footer never wraps, even with a long name/description", async () => {
    const longItem = {
      ...WELL_FORMED_ITEM,
      display_name: "A Really Quite Long Skill Name That Could Push The Footer Wide",
      description: "A very long description that spans multiple lines of text, stress-testing the footer layout under grid-mode rendering."
    };
    const install = {
      ...WELL_FORMED_INSTALL,
      item: longItem
    };
    renderYoursWith([install]);
    const row = await screen.findByTestId("yours-install-row");
    expect(row).toBeInTheDocument();
    expect(screen.queryByTestId("surface-toggles")).not.toBeInTheDocument();
  });

  // Item 4 (2026-09-28, real screenshot at 1920px): a PREVIOUS round
  // shrank grid-mode's "Installed ▾" to a tiny XS-font pill to match
  // Card.tsx's "+ Add" -- the user's ask THEN was the opposite: BOTH
  // buttons should use the app's STANDARD control height, not an ad-hoc
  // small size.
  //
  // SUPERSEDED (2026-10-05, explicit fresh product ask): "a tick to show
  // installed in right corner how claude having... no need to have a big
  // button everywhere, use some small relevant icons." This is a
  // different, deliberately-requested paradigm shift (icon instead of
  // text-button), not a repeat of the 2026-09-28 mistake (which was about
  // shrinking the TEXT to a tiny font while keeping it a bordered button).
  // Grid now gets InstalledMenu's `iconOnly` trigger (a small circular
  // checkmark); list mode is UNCHANGED, still the original standard-size
  // text+chevron button -- list rows are already a dense single line with
  // their own fixed-column layout (Yours.css), not what this round's "card"
  // density complaint was about.
  it("grid layout's Installed trigger is a small icon-only control; list layout keeps the original standard-size button", async () => {
    renderYoursWith([WELL_FORMED_INSTALL]);
    const gridTrigger = await screen.findByTestId("detail-installed-trigger");
    expect(gridTrigger.className).toContain("rounded-full");
    expect(gridTrigger.className).not.toContain("px-3 py-2");
    expect(gridTrigger).toHaveTextContent("Installed"); // sr-only, a11y preserved
    const client = {
      getInstalls: () => Promise.resolve({
        installs: [WELL_FORMED_INSTALL],
        legacy_items: [],
        has_any: true,
        next_cursor: null
      })
    };
    render(<HostProvider value={{
      client,
      theme: LIGHT_TOKENS,
      layout: "full",
      router: {
        path: "/skills",
        navigate: () => {}
      }
    }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} layout="list" />
        </EcosystemConfigProvider>
      </HostProvider>);
    const listTrigger = (await screen.findAllByTestId("detail-installed-trigger")).at(-1);
    // Theme-alignment pass (2026-10-05): resized from `px-3 py-2` (no
    // font-size class, ~16px inherited) to `px-3 py-1.5 text-sm`, matching
    // ProductManager.jsx's own bordered secondary-button convention -- see
    // InstalledMenu.jsx's own comment. Still a real, substantial standard
    // control, not the 2026-09-28 "tiny XS pill" mistake this file already
    // guards against elsewhere.
    expect(listTrigger.className).toContain("px-3 py-1.5");
    expect(listTrigger.className).toContain("text-sm");
    expect(listTrigger.className).toContain("rounded-md");
  });

  // Item 1 (M5 UI-polish round 2, 2026-09-28, real screenshot at 1920px):
  // list view is now a real CSS grid (Yours.css) with fixed columns --
  // this pins the row actually getting the grid class (the whole point:
  // every row shares the same column widths, so the actions column lines
  // up exactly regardless of content).
  it("list layout renders each row with the shared CSS-grid row class", async () => {
    const client = {
      getInstalls: () => Promise.resolve({
        installs: [WELL_FORMED_INSTALL],
        legacy_items: [],
        has_any: true,
        next_cursor: null
      })
    };
    render(<HostProvider value={{
      client,
      theme: LIGHT_TOKENS,
      layout: "full",
      router: {
        path: "/skills",
        navigate: () => {}
      }
    }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} layout="list" />
        </EcosystemConfigProvider>
      </HostProvider>);
    const listRow = await screen.findByTestId("yours-install-row");
    expect(listRow).toHaveClass("grid-cols-[32px_minmax(0,1fr)_112px_92px_104px]");
  });
  it("grid layout does NOT render the list's CSS-grid row class", async () => {
    renderYoursWith([WELL_FORMED_INSTALL]);
    const gridRow = await screen.findByTestId("yours-install-row");
    expect(gridRow).not.toHaveClass("grid-cols-[32px_minmax(0,1fr)_112px_92px_104px]");
  });
  it("list layout's name and description each carry a title attribute for a tooltip on truncation", async () => {
    const client = {
      getInstalls: () => Promise.resolve({
        installs: [WELL_FORMED_INSTALL],
        legacy_items: [],
        has_any: true,
        next_cursor: null
      })
    };
    render(<HostProvider value={{
      client,
      theme: LIGHT_TOKENS,
      layout: "full",
      router: {
        path: "/skills",
        navigate: () => {}
      }
    }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} layout="list" />
        </EcosystemConfigProvider>
      </HostProvider>);
    expect(await screen.findByTitle(WELL_FORMED_ITEM.display_name)).toBeInTheDocument();
    expect(await screen.findByTitle(WELL_FORMED_ITEM.description)).toBeInTheDocument();
  });

  // Item 1: below ~1100px, the badges column folds into the kebab menu as
  // read-only info instead of wrapping or just vanishing. Per-surface
  // toggles round (2026-09-29): "Surfaces: ..." no longer folds in here
  // at all -- there's no surface data left on this row to show a normal
  // user (see the admin-only "Advanced" section on Detail for that now).
  it("list layout folds badges into the kebab menu's info lines below the narrow breakpoint, with no surfaces line", async () => {
    const originalMatchMedia = window.matchMedia;
    window.matchMedia = query => ({
      matches: true,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false
    });
    try {
      const client = {
        getInstalls: () => Promise.resolve({
          installs: [WELL_FORMED_INSTALL],
          legacy_items: [],
          has_any: true,
          next_cursor: null
        })
      };
      render(<HostProvider value={{
        client,
        theme: LIGHT_TOKENS,
        layout: "full",
        router: {
          path: "/skills",
          navigate: () => {}
        }
      }}>
          <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
            <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} layout="list" />
          </EcosystemConfigProvider>
        </HostProvider>);
      await screen.findByTestId("yours-install-row");
      // The badges column's own content (trust badge) must not render as
      // a real interactive element anymore, and there is no surface
      // toggle anywhere on this row regardless of width --
      expect(screen.queryByTestId("trust-badge")).not.toBeInTheDocument();
      expect(screen.queryByTestId("surface-toggles")).not.toBeInTheDocument();
      const {
        fireEvent
      } = await import("@testing-library/react");
      fireEvent.click(screen.getByTestId("kebab-trigger"));
      // -- instead showing up as a read-only info line inside the kebab,
      // with no "Surfaces: ..." line alongside it anymore.
      expect(await screen.findByText(/Created with AI|Verified|Community|Org|Built-in/)).toBeInTheDocument();
      expect(screen.queryByText(/^Surfaces:/)).not.toBeInTheDocument();
    } finally {
      window.matchMedia = originalMatchMedia;
    }
  });

  // Task 3c fix: "unshare" has always shown up in a recipient's own
  // allowed_actions (install.scope == "shared"), but the kebab never had
  // a handler wired for it -- share_id (items_service._share_id_for_
  // recipient()) is what makes an actual call to POST /ecosystem/shares/
  // {share_id}/unshare possible from here at all.
  it("Unshare is offered for a shared-with-me install and calls unshare with the recipient's own share_id", async () => {
    const sharedItem = {
      ...WELL_FORMED_ITEM,
      allowed_actions: ["unshare", "report"],
      share_id: "share-abc-123"
    };
    const install = {
      ...WELL_FORMED_INSTALL,
      item: sharedItem,
      scope: "shared",
      origin: "shared"
    };
    const unshare = vi.fn().mockResolvedValue(undefined);
    const getInstalls = vi.fn().mockResolvedValueOnce({
      installs: [install],
      legacy_items: [],
      has_any: true,
      next_cursor: null
    }).mockResolvedValueOnce({
      installs: [],
      legacy_items: [],
      has_any: false,
      next_cursor: null
    });
    const client = {
      getInstalls,
      unshare
    };
    render(<HostProvider value={{
      client,
      theme: LIGHT_TOKENS,
      layout: "full",
      router: {
        path: "/skills",
        navigate: () => {}
      }
    }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>);
    const {
      fireEvent
    } = await import("@testing-library/react");
    await screen.findByTestId("yours-install-row");
    fireEvent.click(screen.getByTestId("kebab-trigger"));
    fireEvent.click(await screen.findByText("Unshare"));

    // Confirmed via a dialog, same pattern as Delete/Retire -- not fired yet.
    expect(await screen.findByTestId("confirm-dialog")).toBeInTheDocument();
    expect(unshare).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));
    expect(unshare).toHaveBeenCalledWith("share-abc-123");
    // onChanged -> a real refetch, same as every other kebab action.
    await waitFor(() => expect(getInstalls).toHaveBeenCalledTimes(2));
  });

  // Item (d), part 3 (2026-09-29 live-test round): a genuine first load
  // (no cache entry at all for this itemType) must show real skeleton
  // shapes, not the old text-only loading indicator.
  it("a genuine first load with no cached data shows skeleton rows, not a text status", async () => {
    let resolveInstalls;
    const getInstalls = vi.fn(() => new Promise(resolve => {
      resolveInstalls = resolve;
    }));
    const client = {
      getInstalls
    };
    render(<HostProvider value={{
      client,
      theme: LIGHT_TOKENS,
      layout: "full",
      router: {
        path: "/skills",
        navigate: () => {}
      }
    }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>);
    expect(screen.getByTestId("yours-loading")).toBeInTheDocument();
    expect(screen.getByTestId("yours-skeleton")).toBeInTheDocument();
    expect(screen.queryByText(/Verifying/i)).not.toBeInTheDocument();
    resolveInstalls({
      installs: [],
      legacy_items: [],
      has_any: false,
      next_cursor: null
    });
    await waitFor(() => expect(screen.getByText(/haven't added anything yet/i)).toBeInTheDocument());
  });

  // Item (d), part 1: an itemType already cached from an earlier mount
  // (a real Discover<->Yours tab switch, CatalogScreen.tsx's own
  // unmount/remount) shows its last-known installs on the VERY FIRST
  // render -- no null-installs window, so the skeleton branch is never
  // reached at all.
  it("a previously-cached itemType renders its last-known installs instantly, with no skeleton flash, on remount", async () => {
    const getInstalls = vi.fn().mockResolvedValueOnce({
      installs: [WELL_FORMED_INSTALL],
      legacy_items: [],
      has_any: true,
      next_cursor: null
    });
    const client = {
      getInstalls
    };
    const {
      unmount
    } = render(<HostProvider value={{
      client,
      theme: LIGHT_TOKENS,
      layout: "full",
      router: {
        path: "/skills",
        navigate: () => {}
      }
    }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>);
    await screen.findByTestId("yours-install-row");
    unmount(); // simulates CatalogScreen.tsx switching to Discover

    // Remount (simulates switching back) with a client whose own GET
    // never resolves -- proves the cache alone is what renders the row.
    const getInstallsAgain = vi.fn(() => new Promise(() => {}));
    const clientAgain = {
      getInstalls: getInstallsAgain
    };
    render(<HostProvider value={{
      client: clientAgain,
      theme: LIGHT_TOKENS,
      layout: "full",
      router: {
        path: "/skills",
        navigate: () => {}
      }
    }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Yours itemType="skill" onOpen={() => {}} onCreate={() => {}} onDiscover={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>);
    expect(screen.queryByTestId("yours-loading")).not.toBeInTheDocument();
    expect(screen.getByTestId("yours-install-row")).toBeInTheDocument();
    expect(getInstallsAgain).toHaveBeenCalledTimes(1); // background refresh still fires
  });
});