// SPDX-License-Identifier: MIT
// Real bug found live: Discover cards had no install-state indicator at
// all -- every card looked identical whether installed or not, matching
// the user's own "Yours and Discover look the same" complaint.
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Card } from "./Card";
import { HostProvider } from "../context/HostContext";
import { EcosystemConfigProvider } from "../hooks/useEcosystemConfig";
import { MOCK_ITEMS, MOCK_CONFIG } from "../client/fixtures";
import { __resetInstallTrackingForTests } from "../installTracking";
import { __resetInstallStoreForTests } from "../installStore";
import type { EcosystemClient } from "../client/EcosystemClient";
import type { AllowedAction, ItemVersion } from "../types";

// installTracking.ts's own store is module-level (by design -- it must
// survive a real component unmount/remount, item 2's whole point), which
// means it's also shared across every test in this file. Reset it after
// each test so one test's tracked install can never leak into another's
// (several tests below intentionally reuse the same fixture item ids).
// installStore.ts (install-state-consistency round, 2026-09-29) is the
// same kind of module-level, cross-test-leaking store -- same reset rule.
afterEach(() => { __resetInstallTrackingForTests(); __resetInstallStoreForTests(); });

const NOT_INSTALLED = MOCK_ITEMS[0]!; // allowed_actions includes "install", install_id null
const INSTALLED = { ...NOT_INSTALLED, install_id: "install-1", enabled: true };

// install()'s own response is now the async-envelope Job shape (item 2,
// 2026-09-29 live-test round) -- a private install never widens the gate,
// so its job_id falls back to an already-resolved run and this is already
// terminal on the very first response/poll.
const JOB_ALREADY_TERMINAL = {
  job_id: "job-terminal", status: "active" as const, item_id: "item-1", version_id: "v1",
  gate_run_id: null, error: null, install_id: "install-1",
};

function renderCard(item = NOT_INSTALLED, client: Partial<EcosystemClient> = {}, onInstalled = () => {}) {
  return render(
    <HostProvider value={{ client: client as unknown as EcosystemClient, layout: "full", router: { path: "/", navigate: () => {} } }}>
      <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
        <Card item={item} onOpen={() => {}} onInstalled={onInstalled} />
      </EcosystemConfigProvider>
    </HostProvider>,
  );
}

describe("Card", () => {
  it("shows a quick Add button for an installable, not-yet-installed item", () => {
    renderCard();
    expect(screen.getByTestId("card-quick-add")).toBeInTheDocument();
    expect(screen.queryByTestId("card-installed-badge")).not.toBeInTheDocument();
  });

  it("shows an Added badge, not the Add button, once install_id is set", () => {
    renderCard(INSTALLED);
    expect(screen.getByTestId("card-installed-badge")).toBeInTheDocument();
    expect(screen.queryByTestId("card-quick-add")).not.toBeInTheDocument();
  });

  it("shows neither control when the server never offered 'install' (blocked/no-permission items)", () => {
    renderCard({ ...NOT_INSTALLED, allowed_actions: ["report"] });
    expect(screen.queryByTestId("card-quick-add")).not.toBeInTheDocument();
    expect(screen.queryByTestId("card-installed-badge")).not.toBeInTheDocument();
  });

  it("clicking quick-add installs with the current version, private scope, every allowed surface -- and never opens the card", async () => {
    // Real bug found live: this used to hardcode surfaces: ["chat"]
    // regardless of what other surfaces the caller's product profile
    // allows -- now defaults to every surface config.surfaces lists
    // (MOCK_CONFIG's own chat/agent_studio/desktop).
    const onOpen = vi.fn();
    // install() now resolves with the async-envelope Job shape (item 2,
    // 2026-09-29 live-test round: install_item()'s own response), not a
    // bare install row -- QuickAddButton's own attachInstallJob() reads
    // job.job_id off this.
    const install = vi.fn().mockResolvedValue(JOB_ALREADY_TERMINAL);
    const getJob = vi.fn().mockResolvedValue(JOB_ALREADY_TERMINAL);
    const getVersions = vi.fn().mockResolvedValue([{ id: "v1", is_current: true } as ItemVersion]);
    render(
      <HostProvider value={{ client: { install, getJob, getVersions } as unknown as EcosystemClient, layout: "full", router: { path: "/", navigate: () => {} } }}>
        <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
          <Card item={NOT_INSTALLED} onOpen={onOpen} />
        </EcosystemConfigProvider>
      </HostProvider>,
    );
    fireEvent.click(screen.getByTestId("card-quick-add"));
    await waitFor(() => expect(install).toHaveBeenCalledWith(
      NOT_INSTALLED.id,
      { version_id: "v1", surfaces: ["chat", "agent_studio", "desktop"], scope: "private", origin: "added" },
      expect.any(String),
    ));
    expect(onOpen).not.toHaveBeenCalled();
  });

  // Item 1 (2026-09-28 live-testing round): a card's title must always be
  // the server-computed display_name, never a raw namespace/publisher
  // identifier, even when the namespace itself looks unfriendly (a
  // crawled item's namespace is a technical `publisher/name` slug that's
  // still shown elsewhere -- RiskSidePanel's metadata list -- just never
  // as the primary title here).
  it("titles the card with display_name, never the raw namespace", () => {
    const item = { ...NOT_INSTALLED, namespace: "google-labs-code/react-native", display_name: "React Native" };
    renderCard(item);
    expect(screen.getByTitle("React Native")).toHaveTextContent("React Native");
    expect(screen.queryByText("google-labs-code/react-native")).not.toBeInTheDocument();
  });

  // Item 2 (2026-09-28 live-testing round): the catalog crawler tags
  // product-gated items (e.g. Stitch-sourced skills) with a
  // `needs-<product>` tag -- confirm it's actually rendered on the card,
  // not just carried in the API response with nowhere to show up.
  it("shows a Needs <Product> badge for a Stitch-sourced item's needs-stitch tag", () => {
    renderCard({ ...NOT_INSTALLED, tags: ["design", "needs-stitch", "account-required"] });
    expect(screen.getByTestId("needs-product-badge")).toHaveTextContent("Needs Stitch");
  });

  it("shows no Needs <Product> badge for an item with no such tag", () => {
    renderCard({ ...NOT_INSTALLED, tags: ["design"] });
    expect(screen.queryByTestId("needs-product-badge")).not.toBeInTheDocument();
  });

  // Real bug found live via the backend team's own real-Chrome screenshot
  // (docs/ecosystem/design/LLD/gate.md's catalog-checking round): a
  // catalog item nobody has added yet (item_scope === "central_index",
  // latest_version === null) showed "Verifying..." -- backend's
  // latest_verdict defaults to "pending" when no version/gate run exists,
  // which VerdictBadge renders as "Verifying...". No gate run exists for
  // this state at all; it must show "Catalog checks passed" instead.
  const NOT_YET_ADDED_CATALOG_ITEM = {
    ...NOT_INSTALLED, item_scope: "central_index" as const, latest_version: null, latest_verdict: "pending" as const,
  };

  describe("a not-yet-added catalog item (item_scope central_index, no version yet)", () => {
    it("shows 'Catalog checks passed', never 'Verifying...'", () => {
      renderCard(NOT_YET_ADDED_CATALOG_ITEM);
      expect(screen.getByTestId("catalog-checks-passed-badge")).toHaveTextContent("Catalog checks passed");
      expect(screen.queryByTestId("verdict-badge")).not.toBeInTheDocument();
    });

    it("a genuinely mid-install item (real version, verdict pending) still shows Verifying, not Catalog checks passed", () => {
      renderCard({ ...NOT_INSTALLED, latest_version: "1.0.0", latest_verdict: "pending" });
      expect(screen.getByTestId("verdict-badge")).toHaveTextContent("Verifying");
      expect(screen.queryByTestId("catalog-checks-passed-badge")).not.toBeInTheDocument();
    });

    it("+ Add installs without ever calling getVersions -- there is no version to look up yet", async () => {
      const install = vi.fn().mockResolvedValue(JOB_ALREADY_TERMINAL);
      const getJob = vi.fn().mockResolvedValue(JOB_ALREADY_TERMINAL);
      const getVersions = vi.fn().mockResolvedValue([]);
      render(
        <HostProvider value={{ client: { install, getJob, getVersions } as unknown as EcosystemClient, layout: "full", router: { path: "/", navigate: () => {} } }}>
          <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
            <Card item={NOT_YET_ADDED_CATALOG_ITEM} onOpen={() => {}} />
          </EcosystemConfigProvider>
        </HostProvider>,
      );
      fireEvent.click(screen.getByTestId("card-quick-add"));
      await waitFor(() => expect(install).toHaveBeenCalledWith(
        NOT_YET_ADDED_CATALOG_ITEM.id,
        { version_id: undefined, surfaces: ["chat", "agent_studio", "desktop"], scope: "private", origin: "added" },
        expect.any(String),
      ));
      expect(getVersions).not.toHaveBeenCalled();
    });
  });

  // Item 2 (2026-09-29 live-test round, real user report): "'Adding…'
  // becomes 'Retry' when I switch to Yours and back. Install state must
  // be server-driven ... Navigating away must not cancel or fail an
  // install." Discover <-> Yours is a full unmount/remount of this whole
  // card (CatalogScreen.tsx renders one or the other, never both) -- this
  // is that exact scenario, proving the remounted card derives its status
  // from a fresh server GET (client.getJob(), polled by
  // installTracking.ts's useInstallStatus), never from local state that
  // was lost on unmount.
  describe("surviving an unmount + remount mid-install (item 2)", () => {
    it("still shows Adding… on remount while the job is genuinely still verifying, then resolves once a FRESH poll (not the original POST promise) reports it done", async () => {
      const item = { ...NOT_INSTALLED, id: "mid-install-item" };
      const onInstalled = vi.fn();
      const install = vi.fn().mockResolvedValue({
        job_id: "job-mid-install", status: "verifying", item_id: item.id, version_id: "v1",
        gate_run_id: null, error: null, install_id: "install-mid",
      });
      const getVersions = vi.fn().mockResolvedValue([{ id: "v1", is_current: true } as ItemVersion]);
      // Controlled explicitly (not by call count -- the real 2s poll
      // interval can legitimately tick more than once in real wall-clock
      // time under a slower/busier test run, which made an earlier,
      // call-count-based version of this test flaky) -- stays "verifying"
      // for every poll, no matter how many, until the test itself flips
      // it below, well after the remount. Only the REMOUNTED instance's
      // own poll (not the original mount's, whose interval is cleared on
      // unmount) can ever observe the flip.
      let jobStatus: "verifying" | "active" = "verifying";
      let getJobCalls = 0;
      const getJob = vi.fn().mockImplementation(() => {
        getJobCalls += 1;
        return Promise.resolve({
          job_id: "job-mid-install", status: jobStatus,
          item_id: null, version_id: "v1", gate_run_id: null, error: null,
        });
      });
      const client = { install, getVersions, getJob } as unknown as EcosystemClient;

      const first = render(
        <HostProvider value={{ client, layout: "full", router: { path: "/", navigate: () => {} } }}>
          <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
            <Card item={item} onOpen={() => {}} onInstalled={onInstalled} />
          </EcosystemConfigProvider>
        </HostProvider>,
      );

      fireEvent.click(screen.getByTestId("card-quick-add"));
      await waitFor(() => expect(install).toHaveBeenCalled());
      await waitFor(() => expect(screen.getByTestId("card-quick-add")).toHaveTextContent("Adding…"));
      // The original mount's own poll has run at least once and found the
      // job still verifying (jobStatus is only flipped below, well after
      // the remount).
      await waitFor(() => expect(getJobCalls).toBeGreaterThanOrEqual(1));

      // Discover -> Yours: this card (and everything in it, including any
      // local component state QuickAddButton might otherwise have held)
      // fully unmounts.
      first.unmount();

      // The job resolves server-side right after navigating away --
      // flipped here, between unmount and the remount below, so only the
      // REMOUNTED instance's own fresh poll (its effect's immediate
      // poll() call on mount, not waiting for the 2s interval) can ever
      // observe it. The original mount's own interval was cleared on
      // unmount and could never have seen this regardless.
      const callsBeforeFlip = getJobCalls;
      jobStatus = "active";

      // Yours -> Discover: a completely FRESH Card instance mounts for
      // the SAME item. No React state survives this remount -- only
      // installTracking.ts's own module-level store (and its
      // sessionStorage backup) does.
      render(
        <HostProvider value={{ client, layout: "full", router: { path: "/", navigate: () => {} } }}>
          <EcosystemConfigProvider initialConfig={MOCK_CONFIG}>
            <Card item={item} onOpen={() => {}} onInstalled={onInstalled} />
          </EcosystemConfigProvider>
        </HostProvider>,
      );

      // The real bug this guards: before this fix, the remounted card had
      // no way to distinguish "still installing" from "never started" or
      // "failed," and fell back to a fresh "Add" (inviting a duplicate,
      // conflicting install) or, per the live report, a false "Retry" --
      // never a real signal from the server. Its very FIRST render still
      // reads "Adding…" (sessionStorage/module-store-derived, no poll has
      // run yet for THIS instance), never "Retry".
      expect(screen.getByTestId("card-quick-add")).toHaveTextContent("Adding…");
      expect(screen.queryByText("Retry")).not.toBeInTheDocument();

      // Its own immediate poll (a real GET, never the original,
      // already-settled POST promise) then resolves it.
      await waitFor(() => expect(onInstalled).toHaveBeenCalled());
      expect(getJobCalls).toBeGreaterThan(callsBeforeFlip);
    });

    it("never shows Retry on a plain remount with no failure -- only a REAL server-reported failure does", async () => {
      // No install ever attempted for this item in this render -- a bare
      // remount (e.g. of a totally unrelated card that merely shares the
      // same page) must default to a plain "Add", never "Retry": there is
      // no tracked entry for it in installTracking.ts's store at all.
      const item = { ...NOT_INSTALLED, id: "never-touched-item" };
      renderCard(item);
      expect(screen.getByTestId("card-quick-add")).toHaveTextContent("Add");
      expect(screen.queryByText("Retry")).not.toBeInTheDocument();
    });
  });

  describe("install-state-consistency round (2026-09-29)", () => {
    // Real bug: Discover's own card used to render a read-only "Added"
    // badge with no way to uninstall from Discover at all (the user's
    // own explicit test requirement: "uninstall from Discover works").
    // Deliberately realistic here -- allowed_actions does NOT include
    // "install" alongside "uninstall" (a real backend never offers both
    // for the same fetch, since you can't install what's already
    // installed). An earlier version of this fixture DID include both,
    // which accidentally masked a real bug (reported live right after
    // this round shipped): clicking uninstall made the whole footer go
    // BLANK instead of reverting to "+ Add", because installStore.ts's
    // applyInstallOverride() patched install_id but never touched
    // allowed_actions, so Card.tsx's own `!allowed_actions.includes(
    // "install") -> render nothing` gate used the stale, pre-uninstall
    // allowed_actions. Fixed in installStore.ts; this fixture now stays
    // realistic so a regression here would actually be caught again.
    const REMOVABLE_INSTALLED = { ...NOT_INSTALLED, install_id: "install-removable-1", enabled: true, allowed_actions: ["uninstall", "report"] as AllowedAction[] };
    const LOCKED_INSTALLED = { ...NOT_INSTALLED, install_id: "install-locked-1", enabled: true, allowed_actions: ["report"] as AllowedAction[] };

    it("shows a real, clickable uninstall control when the server allows it, and uninstalling it calls client.uninstall", async () => {
      const uninstall = vi.fn().mockResolvedValue(undefined);
      const onInstalled = vi.fn();
      renderCard(REMOVABLE_INSTALLED, { uninstall }, onInstalled);
      const button = screen.getByTestId("card-uninstall");
      expect(button).toHaveTextContent("Added");
      fireEvent.click(button);
      await waitFor(() => expect(uninstall).toHaveBeenCalledWith("install-removable-1"));
      // The button itself flips to "+ Add" once the store is patched --
      // no remount, no parent refetch needed for THIS card to self-correct.
      await waitFor(() => expect(screen.getByTestId("card-quick-add")).toBeInTheDocument());
      expect(onInstalled).toHaveBeenCalled();
    });

    it("locks to the plain read-only badge (no uninstall control) when the server doesn't offer uninstall -- matches InstalledMenu's own required-install convention", () => {
      renderCard(LOCKED_INSTALLED);
      expect(screen.getByTestId("card-installed-badge")).toHaveTextContent("Added");
      expect(screen.queryByTestId("card-uninstall")).not.toBeInTheDocument();
    });

    it("an uninstall targeting an install that's already gone (NOT_FOUND) refreshes to Add instead of failing silently", async () => {
      const uninstall = vi.fn().mockRejectedValue(Object.assign(new Error("no such install"), { code: "NOT_FOUND" }));
      // Realistic real-server response for a confirmed-uninstalled item --
      // allowed_actions no longer includes "uninstall", but DOES include
      // "install" again (found live: an earlier version of this mock left
      // allowed_actions unchanged, which only "passed" by coincidence
      // before applyInstallOverride() trusted the server's own real
      // allowed_actions here instead of a client-side heuristic).
      const getItem = vi.fn().mockResolvedValue({
        ...REMOVABLE_INSTALLED, install_id: null, enabled: null, install_scope: null, install_surfaces: null,
        allowed_actions: ["install", "report"] as AllowedAction[],
      });
      const onInstalled = vi.fn();
      renderCard(REMOVABLE_INSTALLED, { uninstall, getItem }, onInstalled);
      fireEvent.click(screen.getByTestId("card-uninstall"));
      await waitFor(() => expect(getItem).toHaveBeenCalledWith(REMOVABLE_INSTALLED.id));
      await waitFor(() => expect(screen.getByTestId("card-quick-add")).toBeInTheDocument());
      expect(onInstalled).toHaveBeenCalled();
    });

    it("an uninstall that fails for a real (non-NOT_FOUND) reason shows Retry, never a silent no-op", async () => {
      const uninstall = vi.fn().mockRejectedValue(new Error("Uninstall requires marketplace:admin_sources"));
      renderCard(REMOVABLE_INSTALLED, { uninstall });
      fireEvent.click(screen.getByTestId("card-uninstall"));
      await waitFor(() => expect(screen.getByTestId("card-uninstall")).toHaveTextContent("Retry"));
    });

    it("a mutation applied elsewhere (installStore.setInstallState, simulating a different screen/tab) updates this already-mounted card immediately -- no remount or refetch needed", async () => {
      renderCard(REMOVABLE_INSTALLED);
      expect(screen.getByTestId("card-uninstall")).toBeInTheDocument();

      // Simulates what Yours.tsx's own InstalledMenu onUninstall now does
      // on a successful uninstall -- this card never re-fetched anything,
      // never remounted; only the shared store changed.
      const { setInstallState } = await import("../installStore");
      setInstallState(REMOVABLE_INSTALLED.id, { install_id: null });

      await waitFor(() => expect(screen.getByTestId("card-quick-add")).toBeInTheDocument());
      expect(screen.queryByTestId("card-uninstall")).not.toBeInTheDocument();
    });
  });
});
