// SPDX-License-Identifier: MIT

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithHost } from "./test-utils";
import { Detail } from "@marketplace/Detail";
import { HostProvider } from "@marketplace/lib/context/HostContext";
import { EcosystemConfigProvider } from "@marketplace/lib/hooks/useEcosystemConfig";
import { MOCK_ITEMS, MOCK_DETAILS, MOCK_CONFIG } from "@marketplace/lib/client/fixtures";
import { __resetInstallTrackingForTests } from "@marketplace/lib/installTracking";
import { __resetInstallStoreForTests } from "@marketplace/lib/installStore";
import { LIGHT_TOKENS } from "@marketplace/lib/theme";
// See Card.test.tsx's own identical comment -- installTracking.ts's store
// is module-level by design (item 2) and therefore shared across every
// test in this file too. installStore.ts (install-state-consistency
// round, 2026-09-29) is the same kind of module-level store.
afterEach(() => {
  __resetInstallTrackingForTests();
  __resetInstallStoreForTests();
});
function renderWithClient(client, ui, router = {
  path: "/skills",
  navigate: () => {}
}) {
  return render(<HostProvider value={{
    client,
    theme: LIGHT_TOKENS,
    layout: "full",
    router
  }}>
      <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>{ui}</EcosystemConfigProvider>
    </HostProvider>);
}
describe("Detail", () => {
  it("has no Copy Link control (removed -- Back + the address bar already cover it)", async () => {
    const item = MOCK_ITEMS[0];
    renderWithHost(<Detail idOrNamespace={item.id} typeSlug="skills" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("detail-back")).toBeInTheDocument());
    expect(screen.queryByTestId("detail-copy-link")).not.toBeInTheDocument();
  });
  it("a caller with no scope choice installs on a single click, with no dialog ever appearing", async () => {
    const item = MOCK_ITEMS[0];
    renderWithHost(<Detail idOrNamespace={item.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: {
        config: {
          ...MOCK_CONFIG,
          caller_permissions: {
            can_share: false,
            can_provision: false
          }
        }
      }
    });
    const addButton = await screen.findByTestId("detail-add-button");
    await waitFor(() => expect(addButton).not.toBeDisabled());
    fireEvent.click(addButton);

    // No dialog ever mounts for this caller/item combination -- checked
    // immediately, since a zero-latency mock client resolves install()
    // before a later assertion could tell "never showed" apart from
    // "showed then closed already".
    expect(screen.queryByTestId("add-dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByTestId("detail-add-error")).not.toBeInTheDocument());
  });

  // Item 2 (2026-09-29 live-test round, real user report): same fix as
  // Card.test.tsx's own "surviving an unmount + remount mid-install" --
  // Detail.tsx's single-click Add (doQuickInstall) is a genuinely
  // different code path from Card.tsx's QuickAddButton, so it gets its
  // own regression test rather than assuming the shared hook alone proves
  // both call sites.
  it("Detail's own Add button survives an unmount + remount mid-install, deriving status from a fresh server poll", async () => {
    const item = {
      ...MOCK_DETAILS["item-exec-assistant"],
      id: "detail-mid-install-item",
      install_id: null,
      enabled: null,
      install_scope: null,
      install_surfaces: null,
      allowed_actions: ["install"]
    };
    const install = vi.fn().mockResolvedValue({
      job_id: "detail-job-mid-install",
      status: "verifying",
      item_id: item.id,
      version_id: "v1",
      gate_run_id: null,
      error: null,
      install_id: "detail-install-mid"
    });
    // Controlled explicitly (not by call count -- see Card.test.tsx's own
    // identical comment: the real 2s poll interval can legitimately tick
    // more than once in real wall-clock time under a slower/busier test
    // run). Only flipped below, well after the remount.
    let jobStatus = "verifying";
    let getJobCalls = 0;
    const getJob = vi.fn().mockImplementation(() => {
      getJobCalls += 1;
      return Promise.resolve({
        job_id: "detail-job-mid-install",
        status: jobStatus,
        item_id: null,
        version_id: "v1",
        gate_run_id: null,
        error: null
      });
    });
    const client = {
      getItem: () => Promise.resolve(item),
      getVersions: () => Promise.resolve([{
        id: "v1",
        is_current: true
      }]),
      install,
      getJob
    };
    // No scope choice (can_share/can_provision both false) -- Add installs
    // directly (doQuickInstall), no dialog, matching the button this test
    // actually exercises.
    const noScopeChoiceConfig = {
      ...MOCK_CONFIG,
      caller_permissions: {
        can_share: false,
        can_provision: false
      }
    };
    const renderDetail = () => render(<HostProvider value={{
      client,
      theme: LIGHT_TOKENS,
      layout: "full",
      router: {
        path: "/skills",
        navigate: () => {}
      }
    }}>
        <EcosystemConfigProvider initialConfig={noScopeChoiceConfig}>
          <Detail idOrNamespace={item.id} typeSlug="skills" onBack={() => {}} />
        </EcosystemConfigProvider>
      </HostProvider>);
    const first = renderDetail();
    const addButton = await screen.findByTestId("detail-add-button");
    await waitFor(() => expect(addButton).not.toBeDisabled());
    fireEvent.click(addButton);
    await waitFor(() => expect(install).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByTestId("detail-add-button")).toHaveTextContent("Adding…"));
    await waitFor(() => expect(getJobCalls).toBeGreaterThanOrEqual(1));

    // Detail's own "Back" (or navigating elsewhere entirely) unmounts
    // this whole page.
    first.unmount();

    // Navigating back to this same item -- a completely fresh Detail
    // mount, no React state survives it. The job is STILL genuinely
    // verifying at this point -- this remount's very first render must
    // still read "Adding…" from installTracking.ts's module store/
    // sessionStorage. The real bug this guards: before this fix, a
    // remount had no way to distinguish "still installing" from "never
    // started" or "failed," and fell back to a fresh "Add" (inviting a
    // duplicate, conflicting install) or, per the live report, a false
    // "Retry."
    renderDetail();
    const remountedAddButton = await screen.findByTestId("detail-add-button");
    expect(remountedAddButton).toHaveTextContent("Adding…");
    expect(screen.queryByTestId("detail-add-error")).not.toBeInTheDocument();

    // The job resolves server-side now -- only the REMOUNTED instance's
    // own fresh poll (a real GET on its own 2s interval, installTracking.
    // ts's POLL_INTERVAL_MS) can ever observe this; the original mount's
    // interval was cleared on unmount. Never the original, already-
    // settled POST promise.
    jobStatus = "active";
    await waitFor(() => expect(screen.getByTestId("detail-add-button")).not.toHaveTextContent("Adding…"), {
      timeout: 4000
    });
  }, 10000);
  it("a caller with can_share (who_can_share policy allows it) sees the Add dialog -- a real scope choice exists", async () => {
    // Sharing is policy-driven (product correction, 2026-09-27): can_share
    // true means a real scope choice exists (Just me vs. Share with
    // teammates), so the dialog opens rather than installing on one click.
    const item = MOCK_ITEMS[0];
    renderWithHost(<Detail idOrNamespace={item.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: {
        config: {
          ...MOCK_CONFIG,
          caller_permissions: {
            can_share: true,
            can_provision: false
          }
        }
      }
    });
    const addButton = await screen.findByTestId("detail-add-button");
    await waitFor(() => expect(addButton).not.toBeDisabled());
    fireEvent.click(addButton);
    expect(await screen.findByTestId("add-dialog")).toBeInTheDocument();
  });
  it("a caller WITH a real scope choice (marketplace:provision) still sees the Add dialog", async () => {
    const item = MOCK_ITEMS[0];
    renderWithHost(<Detail idOrNamespace={item.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: {
        config: {
          ...MOCK_CONFIG,
          caller_permissions: {
            can_share: false,
            can_provision: true
          }
        }
      }
    });
    const addButton = await screen.findByTestId("detail-add-button");
    await waitFor(() => expect(addButton).not.toBeDisabled());
    fireEvent.click(addButton);
    expect(await screen.findByTestId("add-dialog")).toBeInTheDocument();
  });
  it("a warn-verdict item still shows a confirm before installing, even with no scope choice", async () => {
    const warned = {
      ...MOCK_DETAILS["item-exec-assistant"],
      id: "item-warn-for-detail-test",
      latest_verdict: "warn",
      allowed_actions: ["install"]
    };
    renderWithHost(<Detail idOrNamespace={warned.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: {
        items: [warned],
        config: {
          ...MOCK_CONFIG,
          caller_permissions: {
            can_share: false,
            can_provision: false
          }
        }
      }
    });
    const addButton = await screen.findByTestId("detail-add-button");
    await waitFor(() => expect(addButton).not.toBeDisabled());
    fireEvent.click(addButton);
    const dialog = await screen.findByTestId("add-dialog");
    expect(dialog).toHaveTextContent(/warning/i);
    expect(dialog.querySelector('[data-testid="add-dialog-confirm"]')).toHaveTextContent("Continue");
  });
  it("shows the blocked banner for a failed-verdict item and hides the Add button", async () => {
    renderWithHost(<Detail idOrNamespace="item-quick-scraper" typeSlug="skills" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("detail-blocked-banner")).toBeInTheDocument());
    expect(screen.queryByTestId("detail-add-button")).not.toBeInTheDocument();
  });

  // Relocated from Card.test.jsx (card density pass, 2026-10-05): Card.jsx
  // no longer renders trust/verdict/new/compatibility/needs-product badges
  // at all (moved to Detail-only, to keep the catalog grid minimal) --
  // Detail.jsx's own rendering of them was never touched, but this specific
  // regression test (confirming a Stitch-sourced item's needs-stitch tag
  // actually reaches a visible badge, not just the API response -- a real
  // bug found live, 2026-09-28) only existed on the Card side. Moved here
  // so the underlying fix stays covered somewhere.
  it("shows a Needs <Product> badge for a Stitch-sourced item's needs-stitch tag", async () => {
    const stitchItem = {
      ...MOCK_DETAILS["item-exec-assistant"],
      id: "item-needs-stitch",
      tags: ["design", "needs-stitch", "account-required"]
    };
    renderWithHost(<Detail idOrNamespace={stitchItem.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: {
        items: [stitchItem]
      }
    });
    expect(await screen.findByTestId("needs-product-badge")).toHaveTextContent("Needs Stitch");
  });

  // Real bug found live via the backend team's own real-Chrome screenshot,
  // DOM-level (not just visual) confirmation of a genuinely `disabled`
  // Add button (docs/ecosystem/design/LLD/gate.md's catalog-checking
  // round): a not-yet-added catalog item (item_scope central_index, no
  // version yet) has no version to resolve currentVersionId from --
  // getVersions() legitimately returns [] for this state (real backend
  // behavior, matched by MockEcosystemClient's own fidelity fix), which
  // used to leave the Add button permanently disabled.
  describe("a not-yet-added catalog item (item_scope central_index, no version yet)", () => {
    const notYetAdded = {
      ...MOCK_DETAILS["item-exec-assistant"],
      id: "item-not-yet-added-catalog",
      item_scope: "central_index",
      latest_version: null,
      latest_verdict: "pending",
      allowed_actions: ["install"]
    };
    it("shows 'Catalog checks passed', never 'Verifying...'", async () => {
      renderWithHost(<Detail idOrNamespace={notYetAdded.id} typeSlug="skills" onBack={() => {}} />, {
        clientOptions: {
          items: [notYetAdded]
        }
      });
      expect(await screen.findByTestId("catalog-checks-passed-badge")).toHaveTextContent("Catalog checks passed");
      expect(screen.queryByTestId("verdict-badge")).not.toBeInTheDocument();
    });
    it("Add is enabled, not disabled -- clicking it installs with no version_id", async () => {
      const {
        client
      } = renderWithHost(<Detail idOrNamespace={notYetAdded.id} typeSlug="skills" onBack={() => {}} />, {
        clientOptions: {
          items: [notYetAdded],
          config: {
            ...MOCK_CONFIG,
            caller_permissions: {
              can_share: false,
              can_provision: false
            }
          }
        }
      });
      const addButton = await screen.findByTestId("detail-add-button");
      expect(addButton).not.toBeDisabled();
      const install = vi.spyOn(client, "install");
      fireEvent.click(addButton);
      await waitFor(() => expect(install).toHaveBeenCalledWith(notYetAdded.id, expect.objectContaining({
        version_id: undefined
      }), expect.any(String)));
    });
    it("a caller with a real scope choice still gets a working Add dialog (not a silently-dead click)", async () => {
      renderWithHost(<Detail idOrNamespace={notYetAdded.id} typeSlug="skills" onBack={() => {}} />, {
        clientOptions: {
          items: [notYetAdded],
          config: {
            ...MOCK_CONFIG,
            caller_permissions: {
              can_share: true,
              can_provision: false
            }
          }
        }
      });
      const addButton = await screen.findByTestId("detail-add-button");
      expect(addButton).not.toBeDisabled();
      fireEvent.click(addButton);
      expect(await screen.findByTestId("add-dialog")).toBeInTheDocument();
    });
  });
  it("Back button invokes onBack", async () => {
    const onBack = vi.fn();
    const item = MOCK_ITEMS[0];
    renderWithHost(<Detail idOrNamespace={item.id} typeSlug="skills" onBack={onBack} />);
    await waitFor(() => expect(screen.getByTestId("detail-back")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("detail-back"));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  // Item A3 ("Edit skill code is missing") -- an owned item gets an Edit
  // tab and never the "Copy to my skills" button; a read-only item (not
  // owned/administered) gets the reverse. The two are mutually exclusive,
  // driven entirely by allowed_actions' `edit_content` (items_service.py's
  // compute_allowed_actions()), never inferred from trust_tier/publisher.
  // Item 2 (M5 UI-polish round): "Copy to my skills" removed entirely --
  // a read-only item now just shows nothing in the header action slot if
  // it's not installed (no `install` in allowed_actions either, since a
  // built-in/other-owned item was never offered a real Add-for-yourself
  // path -- this package's own compute_allowed_actions() only grants
  // `install` for a genuinely add-able item).
  it("shows the Edit tab for an item allowed_actions marks edit_content, and Installed ▾ once actually installed", async () => {
    const owned = {
      ...MOCK_DETAILS["item-exec-assistant"],
      id: "item-owned-for-detail-test",
      allowed_actions: ["edit_content", "disable", "uninstall", "report"],
      install_id: "install-owned-1",
      enabled: true
    };
    renderWithHost(<Detail idOrNamespace={owned.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: {
        items: [owned]
      }
    });
    await waitFor(() => expect(screen.getByTestId("detail-tab-trigger-edit")).toBeInTheDocument());
    expect(screen.getByTestId("detail-installed-trigger")).toBeInTheDocument();
    expect(screen.queryByTestId("detail-add-button")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("detail-tab-trigger-edit"));
    expect(await screen.findByTestId("detail-tab-edit-content")).toBeInTheDocument();
  });

  // User-flow QA round 5 (2026-10-03, real user question: "do we have
  // save, cancel button? will it work"): switching tabs or clicking Back
  // while an edit was in-flight used to discard it with zero warning --
  // the same class of bug Create-with-AI already got a leave-confirmation
  // for. EditContent.tsx reports its own dirty state up via onDirtyChange.
  it("switching away from Edit while mid-edit confirms first, then discards the edit on confirm", async () => {
    const owned = {
      ...MOCK_DETAILS["item-exec-assistant"],
      id: "item-owned-for-detail-test-leave",
      allowed_actions: ["edit_content", "disable", "uninstall", "report"],
      install_id: "install-owned-leave",
      enabled: true
    };
    renderWithHost(<Detail idOrNamespace={owned.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: {
        items: [owned]
      }
    });
    fireEvent.click(await screen.findByTestId("detail-tab-trigger-edit"));
    await screen.findByTestId("detail-tab-edit-content");
    fireEvent.change(screen.getByTestId("edit-content-license"), {
      target: {
        value: "GPL-3.0-only"
      }
    });
    fireEvent.click(screen.getByTestId("detail-tab-trigger-overview"));
    // Still on the Edit tab -- the switch doesn't happen until confirmed.
    expect(screen.getByTestId("detail-tab-edit-content")).toBeInTheDocument();
    expect(screen.queryByTestId("detail-tab-overview")).not.toBeInTheDocument();
    fireEvent.click(await screen.findByTestId("confirm-dialog-confirm"));
    expect(await screen.findByTestId("detail-tab-overview")).toBeInTheDocument();
  });
  it("clicking Back while mid-edit confirms first instead of silently leaving", async () => {
    const owned = {
      ...MOCK_DETAILS["item-exec-assistant"],
      id: "item-owned-for-detail-test-leave-back",
      allowed_actions: ["edit_content", "disable", "uninstall", "report"],
      install_id: "install-owned-leave-back",
      enabled: true
    };
    const onBack = vi.fn();
    renderWithHost(<Detail idOrNamespace={owned.id} typeSlug="skills" onBack={onBack} />, {
      clientOptions: {
        items: [owned]
      }
    });
    fireEvent.click(await screen.findByTestId("detail-tab-trigger-edit"));
    await screen.findByTestId("detail-tab-edit-content");
    fireEvent.change(screen.getByTestId("edit-content-license"), {
      target: {
        value: "GPL-3.0-only"
      }
    });
    fireEvent.click(screen.getByTestId("detail-back"));
    expect(onBack).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByTestId("confirm-dialog-confirm"));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
  it("switching away from Edit with no unsaved changes never shows a confirmation", async () => {
    const owned = {
      ...MOCK_DETAILS["item-exec-assistant"],
      id: "item-owned-for-detail-test-no-leave",
      allowed_actions: ["edit_content", "disable", "uninstall", "report"],
      install_id: "install-owned-no-leave",
      enabled: true
    };
    renderWithHost(<Detail idOrNamespace={owned.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: {
        items: [owned]
      }
    });
    fireEvent.click(await screen.findByTestId("detail-tab-trigger-edit"));
    await screen.findByTestId("detail-tab-edit-content");
    fireEvent.click(screen.getByTestId("detail-tab-trigger-overview"));
    expect(screen.queryByTestId("confirm-dialog-confirm")).not.toBeInTheDocument();
    expect(await screen.findByTestId("detail-tab-overview")).toBeInTheDocument();
  });
  it("a not-yet-installed read-only item has no Edit tab and no header action at all", async () => {
    const item = MOCK_ITEMS[0];
    renderWithHost(<Detail idOrNamespace={item.id} typeSlug="skills" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("detail-screen")).toBeInTheDocument());
    expect(screen.queryByTestId("detail-tab-trigger-edit")).not.toBeInTheDocument();
    expect(screen.queryByTestId("detail-installed-trigger")).not.toBeInTheDocument();
    // This fixture has "install" in allowed_actions (not yet installed), so Add shows.
    expect(screen.getByTestId("detail-add-button")).toBeInTheDocument();
  });
  it("hides Add and Installed ▾ for a blocked (failed-verdict) item", async () => {
    renderWithHost(<Detail idOrNamespace="item-quick-scraper" typeSlug="skills" onBack={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("detail-blocked-banner")).toBeInTheDocument());
    expect(screen.queryByTestId("detail-add-button")).not.toBeInTheDocument();
    expect(screen.queryByTestId("detail-installed-trigger")).not.toBeInTheDocument();
  });
  it("an installed item shows 'Installed ▾' instead of Add, opening a menu with Manage in Yours / Enable-Disable / Versions & rollback / Uninstall", async () => {
    const item = MOCK_ITEMS[0];
    const installed = {
      ...(MOCK_DETAILS[item.id] ?? MOCK_DETAILS["item-exec-assistant"]),
      install_id: "install-1",
      enabled: true,
      install_scope: "private",
      install_surfaces: ["chat"],
      allowed_actions: ["disable", "uninstall", "report"]
    };
    renderWithHost(<Detail idOrNamespace={installed.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: {
        items: [installed]
      }
    });
    const trigger = await screen.findByTestId("detail-installed-trigger");
    expect(screen.queryByTestId("detail-add-button")).not.toBeInTheDocument();
    fireEvent.click(trigger);
    const menu = await screen.findByTestId("detail-installed-menu");
    expect(menu).toHaveTextContent("Manage in Yours");
    expect(menu).toHaveTextContent("Disable"); // currently enabled
    expect(menu).toHaveTextContent("Versions & rollback");
    expect(menu).toHaveTextContent("Uninstall");
  });
  it("a required install locks Uninstall with an explanation instead of hiding it silently", async () => {
    const installed = {
      ...MOCK_DETAILS["item-exec-assistant"],
      install_id: "install-required-1",
      enabled: true,
      install_scope: "required",
      install_surfaces: ["chat"],
      allowed_actions: ["uninstall", "report"]
    };
    renderWithHost(<Detail idOrNamespace={installed.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: {
        items: [installed]
      }
    });
    fireEvent.click(await screen.findByTestId("detail-installed-trigger"));
    const menu = await screen.findByTestId("detail-installed-menu");
    expect(menu).not.toHaveTextContent(/^Uninstall$/m);
    const lockedItem = screen.getByText("Required");
    expect(lockedItem.closest("button")).toBeDisabled();
    expect(menu).toHaveTextContent(/required by your admin/i);
  });
  it("toggling Disable from the Installed ▾ menu confirms first, then calls setEnabled for the caller's own install", async () => {
    const installed = {
      ...MOCK_DETAILS["item-exec-assistant"],
      install_id: "install-1",
      enabled: true,
      install_scope: "private",
      install_surfaces: ["chat"],
      allowed_actions: ["disable", "uninstall", "report"]
    };
    const setEnabled = vi.fn().mockResolvedValue(undefined);
    const client = {
      getItem: () => Promise.resolve(installed),
      getVersions: () => Promise.resolve([]),
      setEnabled
    };
    renderWithClient(client, <Detail idOrNamespace={installed.id} typeSlug="skills" onBack={() => {}} />);
    fireEvent.click(await screen.findByTestId("detail-installed-trigger"));
    fireEvent.click(await screen.findByText("Disable"));
    // Disabling now confirms first (user-flow QA round 2, 2026-10-03).
    expect(setEnabled).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByTestId("confirm-dialog-confirm"));
    await waitFor(() => expect(setEnabled).toHaveBeenCalledWith("install-1", false));
  });
  it("Versions & rollback switches to the Versions tab", async () => {
    const installed = {
      ...MOCK_DETAILS["item-exec-assistant"],
      install_id: "install-1",
      enabled: true,
      install_scope: "private",
      install_surfaces: ["chat"],
      allowed_actions: ["disable", "uninstall", "rollback", "report"]
    };
    renderWithHost(<Detail idOrNamespace={installed.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: {
        items: [installed]
      }
    });
    fireEvent.click(await screen.findByTestId("detail-installed-trigger"));
    fireEvent.click(await screen.findByText("Versions & rollback"));
    await waitFor(() => expect(screen.getByTestId("detail-tab-trigger-versions")).toHaveAttribute("aria-selected", "true"));
  });
  it("Uninstall from the Installed ▾ menu confirms first, then calls uninstall for the caller's own install", async () => {
    const installed = {
      ...MOCK_DETAILS["item-exec-assistant"],
      install_id: "install-1",
      enabled: true,
      install_scope: "private",
      install_surfaces: ["chat"],
      allowed_actions: ["disable", "uninstall", "report"]
    };
    const uninstall = vi.fn().mockResolvedValue(undefined);
    const client = {
      getItem: () => Promise.resolve(installed),
      getVersions: () => Promise.resolve([]),
      uninstall
    };
    renderWithClient(client, <Detail idOrNamespace={installed.id} typeSlug="skills" onBack={() => {}} />);
    fireEvent.click(await screen.findByTestId("detail-installed-trigger"));
    fireEvent.click(await screen.findByText("Uninstall"));
    // Uninstalling now confirms first (user-flow QA round 2, 2026-10-03).
    expect(uninstall).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByTestId("confirm-dialog-confirm"));
    await waitFor(() => expect(uninstall).toHaveBeenCalledWith("install-1"));
  });
  it("Overview shows How to use / enabled surfaces for an installed skill, and header metadata moved to the side panel", async () => {
    const installed = {
      ...MOCK_DETAILS["item-exec-assistant"],
      install_id: "install-1",
      enabled: true,
      install_scope: "private",
      install_surfaces: ["chat", "desktop"],
      allowed_actions: ["disable", "uninstall", "report"]
    };
    renderWithHost(<Detail idOrNamespace={installed.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: {
        items: [installed]
      }
    });
    await screen.findByTestId("detail-tab-overview");
    expect(screen.getByTestId("overview-how-to-use")).toHaveTextContent(`/${installed.namespace.split("/")[1]}`);
    expect(screen.getByTestId("overview-enabled-surfaces")).toHaveTextContent("Chat");
    expect(screen.getByTestId("overview-enabled-surfaces")).toHaveTextContent("Desktop");

    // Header no longer duplicates namespace/license/version -- only the
    // side panel's "Item details" list carries them now.
    expect(screen.getByTestId("detail-metadata")).toHaveTextContent(installed.namespace);
  });

  // Real confusion found live (2026-10-06, user report): "Enabled for:
  // Chat" used to render purely off install_surfaces, with zero connection
  // to whether the INSTALLED version's own verdict actually allows real
  // usage (resolver_service.py's own, separately-fixed bar) -- a failed
  // install claimed to work in chat right next to a banner saying it was
  // blocked.
  it("notes 'not currently usable' when the installed version's own verdict has failed, even though surfaces are still configured", async () => {
    const installed = {
      ...MOCK_DETAILS["item-exec-assistant"],
      install_id: "install-1",
      enabled: true,
      install_scope: "private",
      install_surfaces: ["chat"],
      installed_version: "1.0.1",
      installed_verdict: "fail",
      latest_version: "1.0.1",
      latest_verdict: "fail",
      allowed_actions: ["disable", "uninstall", "report"]
    };
    renderWithHost(<Detail idOrNamespace={installed.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: { items: [installed] }
    });
    await screen.findByTestId("detail-tab-overview");
    expect(screen.getByTestId("overview-enabled-surfaces")).toHaveTextContent(/not currently usable/i);
  });

  // Real confusion found live (2026-10-06, user report: "if its blocked
  // when open on skill details page how people will get to know why...
  // what about old version, even it will confuse"): the banner used to
  // be driven by item.latest_verdict (the NEWEST version) even when the
  // caller's own install was pinned to an older, perfectly-fine version.
  it("shows the real red blocked banner (with a link to Verification) when the INSTALLED version itself failed", async () => {
    const installed = {
      ...MOCK_DETAILS["item-exec-assistant"],
      install_id: "install-1",
      enabled: true,
      install_scope: "private",
      install_surfaces: ["chat"],
      installed_version: "1.0.1",
      installed_verdict: "fail",
      latest_version: "1.0.1",
      latest_verdict: "fail",
      allowed_actions: ["disable", "uninstall", "report"]
    };
    renderWithHost(<Detail idOrNamespace={installed.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: { items: [installed] }
    });
    const banner = await screen.findByTestId("detail-blocked-banner");
    expect(banner).toHaveTextContent("1.0.1");
    expect(banner).toHaveTextContent(/failed verification/i);
    expect(screen.queryByTestId("detail-newer-version-failed-banner")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText(/see why, in verification/i));
    expect(await screen.findByTestId("detail-tab-verification")).toBeInTheDocument();
  });

  it("shows only the softer amber notice (never the red blocked banner) when a NEWER version failed but the installed version is still fine", async () => {
    const installed = {
      ...MOCK_DETAILS["item-exec-assistant"],
      install_id: "install-1",
      enabled: true,
      install_scope: "private",
      install_surfaces: ["chat"],
      installed_version: "1.0.1",
      installed_verdict: "pass",
      latest_version: "1.0.2",
      latest_verdict: "fail",
      allowed_actions: ["disable", "uninstall", "report"]
    };
    renderWithHost(<Detail idOrNamespace={installed.id} typeSlug="skills" onBack={() => {}} />, {
      clientOptions: { items: [installed] }
    });
    const notice = await screen.findByTestId("detail-newer-version-failed-banner");
    expect(notice).toHaveTextContent("1.0.2");
    expect(notice).toHaveTextContent("1.0.1");
    expect(notice).toHaveTextContent(/unaffected/i);
    expect(screen.queryByTestId("detail-blocked-banner")).not.toBeInTheDocument();
  });
});