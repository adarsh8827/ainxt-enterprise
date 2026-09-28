// SPDX-License-Identifier: MIT
// Item 7 (usage proof): the chat UI must show a small "Using skill: <name>"
// chip on a message where a skill was actually applied.
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import MessageMeta from "./MessageMeta";

const BASE_MSG = { role: "assistant", streaming: false };

afterEach(() => {
  cleanup();
});

describe("MessageMeta — skill-used chip", () => {
  it("renders a 'Using skill: <name>' chip when msg.skillUsed is set", () => {
    render(<MessageMeta msg={{ ...BASE_MSG, skillUsed: { name: "acme/meeting-notes", display_name: "Meeting Notes" } }} />);
    expect(screen.getByText(/Using skill: Meeting Notes/i)).toBeInTheDocument();
  });

  it("falls back to the raw name when display_name is missing", () => {
    render(<MessageMeta msg={{ ...BASE_MSG, skillUsed: { name: "acme/meeting-notes" } }} />);
    expect(screen.getByText(/Using skill: acme\/meeting-notes/i)).toBeInTheDocument();
  });

  it("renders nothing at all (not even the chip row) when no skill was used and no other meta exists", () => {
    const { container } = render(<MessageMeta msg={BASE_MSG} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("does not render the chip for a message with no skillUsed even when other meta exists", () => {
    render(<MessageMeta msg={{ ...BASE_MSG, modelLabel: "claude" }} />);
    expect(screen.queryByText(/Using skill:/i)).not.toBeInTheDocument();
  });
});
