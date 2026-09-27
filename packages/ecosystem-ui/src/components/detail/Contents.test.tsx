// SPDX-License-Identifier: MIT
// Contents.tsx was a bare <pre> dump with no content shown for bundled
// files at all -- rebuilt as a read-only file-tree + preview/code
// viewer (reference screenshots: a file-tree list + an eye/code toggle
// on the content pane), matching EditContent.tsx's own file-tree
// pattern but non-editable.
import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Contents } from "./Contents";
import { HostProvider } from "../../context/HostContext";
import { LIGHT_TOKENS } from "../../theme";
import type { EcosystemClient } from "../../client/EcosystemClient";
import type { ItemDetail } from "../../types";
import { MOCK_DETAILS } from "../../client/fixtures";

const BASE = MOCK_DETAILS["item-exec-assistant"]!;
const ITEM: ItemDetail = {
  ...BASE,
  manifest: {
    instructions: "# Exec Assistant\n\nThis is **bold** guidance.",
    files: { "scripts/run.py": "print('hello')", "references/notes.md": "Some *notes*." },
  },
};

function renderContents(item: ItemDetail = ITEM) {
  const client = {} as unknown as EcosystemClient;
  return render(
    <HostProvider value={{ client, theme: LIGHT_TOKENS, layout: "full", router: { path: "/", navigate: () => {} } }}>
      <Contents item={item} />
    </HostProvider>,
  );
}

describe("Contents", () => {
  it("lists every file: SKILL.md plus every bundled file", () => {
    renderContents();
    expect(screen.getByTestId("contents-file-SKILL.md")).toBeInTheDocument();
    expect(screen.getByTestId("contents-file-scripts/run.py")).toBeInTheDocument();
    expect(screen.getByTestId("contents-file-references/notes.md")).toBeInTheDocument();
  });

  it("SKILL.md defaults to Preview and renders markdown, not literal asterisks", () => {
    renderContents();
    const preview = screen.getByTestId("contents-preview");
    expect(preview.querySelector("strong")).toHaveTextContent("bold");
    expect(preview.textContent).not.toContain("**bold**");
    expect(screen.getByTestId("contents-view-preview")).toHaveAttribute("aria-pressed", "true");
  });

  it("selecting a non-markdown file defaults to Code view", () => {
    renderContents();
    fireEvent.click(screen.getByTestId("contents-file-scripts/run.py"));
    expect(screen.getByTestId("contents-view-code")).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByTestId("contents-preview")).not.toBeInTheDocument();
    expect(screen.getByTestId("contents-code")).toBeInTheDocument();
  });

  it("the preview/code toggle actually switches what's rendered", () => {
    renderContents();
    expect(screen.getByTestId("contents-preview")).toBeInTheDocument();
    expect(screen.queryByTestId("contents-code")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("contents-view-code"));
    expect(screen.queryByTestId("contents-preview")).not.toBeInTheDocument();
    expect(screen.getByTestId("contents-code")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("contents-view-preview"));
    expect(screen.getByTestId("contents-preview")).toBeInTheDocument();
  });

  it("a bundled markdown file also defaults to Preview", () => {
    renderContents();
    fireEvent.click(screen.getByTestId("contents-file-references/notes.md"));
    expect(screen.getByTestId("contents-view-preview")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("contents-preview").querySelector("em")).toHaveTextContent("notes");
  });
});
