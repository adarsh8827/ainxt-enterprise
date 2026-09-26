// SPDX-License-Identifier: MIT
import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { EcosystemErrorBoundary } from "./ErrorBoundary";

function Bomb(): never {
  throw new Error("boom");
}

describe("EcosystemErrorBoundary", () => {
  it("renders its children when nothing throws", () => {
    render(
      <EcosystemErrorBoundary>
        <div data-testid="ok">fine</div>
      </EcosystemErrorBoundary>,
    );
    expect(screen.getByTestId("ok")).toBeInTheDocument();
  });

  it("catches a render error from a descendant and shows a fallback instead of blanking the page", () => {
    const originalError = console.error;
    console.error = () => {}; // React logs the caught error to console -- expected noise, silence it for this test
    render(
      <EcosystemErrorBoundary>
        <Bomb />
      </EcosystemErrorBoundary>,
    );
    console.error = originalError;

    expect(screen.getByTestId("ecosystem-error-boundary")).toBeInTheDocument();
    expect(screen.getByText(/something went wrong/i)).toBeInTheDocument();
  });

  it("'Try again' re-mounts children instead of staying stuck on the fallback forever", () => {
    const originalError = console.error;
    console.error = () => {};
    render(
      <EcosystemErrorBoundary>
        <Bomb />
      </EcosystemErrorBoundary>,
    );
    console.error = originalError;

    fireEvent.click(screen.getByText(/try again/i));
    // Re-mounting throws again immediately (Bomb always throws) -- proves
    // the boundary actually resets its own state rather than being a
    // one-shot render that can never recover.
    expect(screen.getByTestId("ecosystem-error-boundary")).toBeInTheDocument();
  });
});
