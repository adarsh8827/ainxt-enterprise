// SPDX-License-Identifier: MIT
// Task F-11: Create-with-AI staged flow. Exercises the real SSE frame
// parser (task B-14's own frame shapes: "created" / free-text progress /
// "draft_ready" / "error") against a fake ReadableStream body, then the
// PATCH + submit confirm step -- mirrors the hand-rolled SSE parsing
// convention already used elsewhere in this codebase (see Chat.jsx).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

vi.mock("../config", () => ({
  API_BASE: "/ainxt/v1/api",
  authFetch: vi.fn(),
}));

import { authFetch } from "../config";
import CreateWithAiModal from "./CreateWithAiModal.jsx";

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

beforeEach(() => authFetch.mockReset());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("CreateWithAiModal", () => {
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

    render(<CreateWithAiModal onClose={() => {}} onCreated={() => {}} />);
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

    render(<CreateWithAiModal onClose={() => {}} onCreated={() => {}} />);
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

    render(<CreateWithAiModal onClose={() => {}} onCreated={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/summarize meeting notes/i), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: /generate/i }));

    await waitFor(() => expect(screen.getByText("Generation failed.")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });
});
