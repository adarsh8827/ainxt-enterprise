// SPDX-License-Identifier: MIT
// Item 6.2 (2026-09-29 live-test round, real user report): "Publisher:
// google-labs-code (user)" -- (user) used to be a hardcoded fallback that
// never checked whether the publisher is really an individual or an
// organization. Real signal (a genuine ecosystem_publishers row) still
// renders spelled out in full; no real signal (item.publisher.type ===
// null, always true for a crawled catalog item) now shows the item's real
// source instead of a guessed label.
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { RiskSidePanel } from "@marketplace/detail/RiskSidePanel";
import { MOCK_DETAILS } from "@marketplace/lib/client/fixtures";
const BASE = MOCK_DETAILS["item-exec-assistant"];
describe("RiskSidePanel -- Publisher line", () => {
  it("shows the full word '(organization)', not the raw 'org' value, for a real org-owned publisher", () => {
    const item = {
      ...BASE,
      publisher: {
        slug: "acme",
        type: "org"
      }
    };
    render(<RiskSidePanel item={item} />);
    expect(screen.getByTestId("detail-publisher")).toHaveTextContent("acme (organization)");
  });
  it("shows '(user)' for a real user-owned publisher", () => {
    const item = {
      ...BASE,
      publisher: {
        slug: "jdoe",
        type: "user"
      }
    };
    render(<RiskSidePanel item={item} />);
    expect(screen.getByTestId("detail-publisher")).toHaveTextContent("jdoe (user)");
  });

  // The real bug's own repro: a crawled catalog item (item_scope
  // 'central_index') has no ecosystem_publishers row at all -- the
  // backend now reports type: null rather than guessing "user".
  it("never guesses '(user)'/'(organization)' when the backend reports no real ownership record -- shows the real source instead", () => {
    const item = {
      ...BASE,
      publisher: {
        slug: "google-labs-code",
        type: null
      },
      source: {
        kind: "github_repo",
        url: "https://github.com/google-labs-code/react-native-codegen"
      }
    };
    render(<RiskSidePanel item={item} />);
    const text = screen.getByTestId("detail-publisher").textContent ?? "";
    expect(text).toContain("google-labs-code");
    expect(text).not.toMatch(/\(user\)/);
    expect(text).not.toMatch(/\(organization\)/);
    expect(text).toContain("GitHub");
    expect(text).toContain("github.com/google-labs-code/react-native-codegen");
  });
  it("still shows a sensible fallback (the source kind alone) when there's no real ownership record AND no source url", () => {
    const item = {
      ...BASE,
      publisher: {
        slug: "some-crawled-publisher",
        type: null
      },
      source: {
        kind: "mcp_registry",
        url: null
      }
    };
    render(<RiskSidePanel item={item} />);
    const text = screen.getByTestId("detail-publisher").textContent ?? "";
    expect(text).toContain("some-crawled-publisher");
    expect(text).toContain("MCP registry");
    expect(text).not.toMatch(/\(user\)/);
    expect(text).not.toMatch(/\(organization\)/);
  });
});