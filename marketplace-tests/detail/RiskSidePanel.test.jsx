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

describe("RiskSidePanel -- Version line", () => {
  // Real confusion found live (2026-10-06, user report: "what about old
  // version, even it will confuse"): this field always showed
  // item.latest_version -- the item's NEWEST version, regardless of
  // which version the caller's own install was actually pinned to.
  it("shows just the plain version when not installed (no installed_version to compare against)", () => {
    const item = { ...BASE, install_id: null, latest_version: "2.0.0" };
    render(<RiskSidePanel item={item} />);
    expect(screen.getByTestId("detail-metadata")).toHaveTextContent("2.0.0");
    expect(screen.getByTestId("detail-metadata")).not.toHaveTextContent("installed");
  });
  it("shows just the plain version when installed and it matches the latest version", () => {
    const item = { ...BASE, install_id: "install-1", installed_version: "2.0.0", installed_verdict: "pass", latest_version: "2.0.0" };
    render(<RiskSidePanel item={item} />);
    const text = screen.getByTestId("detail-metadata").textContent ?? "";
    expect(text).toContain("2.0.0");
    expect(text).not.toContain("installed");
    expect(text).not.toContain("latest");
  });
  it("spells out BOTH versions explicitly when the installed version differs from the latest one, instead of silently showing only one", () => {
    const item = { ...BASE, install_id: "install-1", installed_version: "1.0.1", installed_verdict: "pass", latest_version: "1.0.2" };
    render(<RiskSidePanel item={item} />);
    const text = screen.getByTestId("detail-metadata").textContent ?? "";
    expect(text).toContain("1.0.1");
    expect(text).toContain("(installed)");
    expect(text).toContain("1.0.2");
    expect(text).toContain("(latest)");
  });
});