// SPDX-License-Identifier: MIT
// Task F-11 + page conversion (user-flow QA round 2, 2026-10-03): ported
// from CreateWithAiModal.test.jsx when the modal became a real page
// (/marketplace/skills/new/ai) -- the internal SSE/PATCH/submit logic is
// unchanged, only the chrome (no more onClose/onCreated props, routing
// instead) and the render harness (needs a Router + ConfirmProvider now).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import "@testing-library/jest-dom/vitest";

vi.mock("../config", () => ({
  API_BASE: "/ainxt/v1/api",
  authFetch: vi.fn(),
}));

import { authFetch } from "../config";
import CreateSkillWithAiPage from "./CreateSkillWithAiPage.jsx";
import { ConfirmProvider, ToastProvider } from "./ui/DialogProvider.jsx";
import { confirmNavigationAllowed, clearNavigationGuard } from "../navigationGuard";

function sseBodyFrom(frames) {
  const text = frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");
  let sent = false;
  return {
    getReader() {
      return {
        read() {
          if (sent) return Promise.resolve({ done: true, value: undefined });
          sent = true;
          return Promise.resolve({ done: false, value: new TextEncoder().encode(text) });
        },
      };
    },
  };
}

function renderPage({ initialIntent } = {}) {
  const entry = initialIntent !== undefined
    ? { pathname: "/marketplace/skills/new/ai", state: { initialIntent } }
    : "/marketplace/skills/new/ai";
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <ToastProvider>
        <ConfirmProvider>
          <CreateSkillWithAiPage />
        </ConfirmProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => authFetch.mockReset());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  // navigationGuard.js is a module-level singleton (same reason
  // installTracking.ts/catalogCache.ts reset themselves in their own
  // tests) -- an unmount via cleanup() above already clears it in real
  // usage (the registering effect's own cleanup), but belt-and-suspenders
  // here keeps a failed/aborted test from leaking a stale guard into the
  // next one.
  clearNavigationGuard();
});

describe("CreateSkillWithAiPage", () => {
  it("renders as a plain page -- no overlay/backdrop, no close (X) button", () => {
    renderPage();
    expect(screen.getByText("Create a skill with AI")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /close/i })).not.toBeInTheDocument();
  });

  it("streams progress then shows the preview card populated from the final draft_ready frame", async () => {
    authFetch.mockResolvedValueOnce({
      ok: true,
      body: sseBodyFrom([
        { stage: "created", text: "", data: { draft_id: "draft-1" } },
        { stage: "intent", text: "Understanding…", data: null },
        {
          stage: "draft_ready",
          text: "Draft ready to review.",
          data: { draft: { id: "draft-1", draft_content: { display_name: "Exec Assistant", description: "d", namespace: "", license: "MIT", instructions: "do x" } } },
        },
      ]),
    });

    renderPage();
    fireEvent.change(screen.getByPlaceholderText(/summarize meeting notes/i), { target: { value: "help me draft memos" } });
    fireEvent.click(screen.getByRole("button", { name: /generate/i }));

    await waitFor(() => expect(screen.getByDisplayValue("Exec Assistant")).toBeInTheDocument());

    const [url, options] = authFetch.mock.calls[0];
    expect(url).toBe("/ainxt/v1/api/ecosystem/drafts");
    expect(options.method).toBe("POST");
    expect(options.headers["Idempotency-Key"]).toBeTruthy();
    expect(JSON.parse(options.body)).toEqual({ item_type: "skill", intent: "help me draft memos" });
  });

  it("confirm step PATCHes the edited fields then POSTs submit, and shows the resulting status", async () => {
    authFetch
      .mockResolvedValueOnce({
        ok: true,
        body: sseBodyFrom([
          { stage: "created", text: "", data: { draft_id: "draft-2" } },
          {
            stage: "draft_ready",
            text: "",
            data: { draft: { id: "draft-2", draft_content: { display_name: "Memo Bot", description: "d", namespace: "", license: "MIT", instructions: "x" } } },
          },
        ]),
      })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ draft_content: { namespace: "acme/memo-bot" } }) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: "verifying", gate_run_id: "gr-1" }) });

    renderPage();
    fireEvent.change(screen.getByPlaceholderText(/summarize meeting notes/i), { target: { value: "memo helper" } });
    fireEvent.click(screen.getByRole("button", { name: /generate/i }));

    await waitFor(() => expect(screen.getByDisplayValue("Memo Bot")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/namespace/i), { target: { value: "acme/memo-bot" } });
    fireEvent.click(screen.getByRole("button", { name: /save skill/i }));

    await waitFor(() => expect(screen.getByText(/verifying/i)).toBeInTheDocument());

    const [patchUrl, patchOptions] = authFetch.mock.calls[1];
    expect(patchUrl).toBe("/ainxt/v1/api/ecosystem/drafts/draft-2");
    expect(patchOptions.method).toBe("PATCH");
    expect(JSON.parse(patchOptions.body).namespace).toBe("acme/memo-bot");

    const [submitUrl, submitOptions] = authFetch.mock.calls[2];
    expect(submitUrl).toBe("/ainxt/v1/api/ecosystem/drafts/draft-2/submit");
    expect(submitOptions.method).toBe("POST");
    expect(submitOptions.headers["Idempotency-Key"]).toBeTruthy();
  });

  it("a stream 'error' frame shows the error state with a retry option", async () => {
    authFetch.mockResolvedValueOnce({
      ok: true,
      body: sseBodyFrom([{ stage: "error", text: "Generation failed.", data: null }]),
    });

    renderPage();
    fireEvent.change(screen.getByPlaceholderText(/summarize meeting notes/i), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: /generate/i }));

    await waitFor(() => expect(screen.getByText("Generation failed.")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("item 6: initialIntent (from router state) seeds the intent textarea (e.g. 'Save this as a skill' from a conversation)", () => {
    renderPage({ initialIntent: "Summarize weekly standup notes into action items." });
    expect(screen.getByPlaceholderText(/summarize meeting notes/i)).toHaveValue("Summarize weekly standup notes into action items.");
  });

  it("leaving mid-generation (Cancel during streaming) asks for confirmation before discarding the draft", async () => {
    let resolveRead;
    authFetch.mockResolvedValueOnce({
      ok: true,
      body: {
        getReader() {
          return { read: () => new Promise((resolve) => { resolveRead = resolve; }) };
        },
      },
    });

    renderPage();
    fireEvent.change(screen.getByPlaceholderText(/summarize meeting notes/i), { target: { value: "anything" } });
    fireEvent.click(screen.getByRole("button", { name: /generate/i }));

    const cancelBtn = await screen.findByRole("button", { name: /cancel/i });
    fireEvent.click(cancelBtn);

    expect(await screen.findByText(/leave without saving/i)).toBeInTheDocument();
    // Never actually resolved the stream -- just confirming the guard fired.
    resolveRead?.({ done: true, value: undefined });
  });

  // User-flow QA round 8 (2026-10-03, real user question: "user clicks
  // any other sidemenu, what will happen?"): this page registers a
  // navigationGuard.js guard so App.jsx's setView() -- the one path every
  // SIDEBAR click goes through -- also respects the in-flight confirm,
  // not just this page's own Cancel button.
  it("registers a navigation guard while idle that allows leaving with no confirmation needed", () => {
    renderPage();
    expect(screen.getByText("Create a skill with AI")).toBeInTheDocument();
    return expect(confirmNavigationAllowed()).resolves.toBe(true);
  });

  it("registers a navigation guard that blocks a sidebar-style navigation attempt while streaming, until the user confirms", async () => {
    let resolveRead;
    authFetch.mockResolvedValueOnce({
      ok: true,
      body: { getReader() { return { read: () => new Promise((resolve) => { resolveRead = resolve; }) }; } },
    });

    renderPage();
    fireEvent.change(screen.getByPlaceholderText(/summarize meeting notes/i), { target: { value: "anything" } });
    fireEvent.click(screen.getByRole("button", { name: /generate/i }));
    await screen.findByText("Starting…");

    // Simulates App.jsx's setView() asking "is it safe to navigate away
    // right now?" -- exactly what a sidebar click does, completely
    // independent of this page's own Cancel button.
    const allowedPromise = confirmNavigationAllowed();
    expect(await screen.findByText(/leave without saving/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^leave$/i }));
    expect(await allowedPromise).toBe(true);

    resolveRead?.({ done: true, value: undefined });
  });

  it("clears its navigation guard on unmount -- leaving any other way never leaves a stale guard blocking the next page", async () => {
    let resolveRead;
    authFetch.mockResolvedValueOnce({
      ok: true,
      body: { getReader() { return { read: () => new Promise((resolve) => { resolveRead = resolve; }) }; } },
    });

    const { unmount } = renderPage();
    fireEvent.change(screen.getByPlaceholderText(/summarize meeting notes/i), { target: { value: "anything" } });
    fireEvent.click(screen.getByRole("button", { name: /generate/i }));
    await screen.findByText("Starting…");

    unmount();
    resolveRead?.({ done: true, value: undefined });
    await expect(confirmNavigationAllowed()).resolves.toBe(true);
  });
});
