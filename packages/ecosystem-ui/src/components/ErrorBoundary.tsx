// SPDX-License-Identifier: MIT
// A single bad row/response must never blank the whole marketplace screen
// for a host that doesn't already wrap this package in its own error
// boundary. Host-agnostic (no host callback required) -- a "Try again"
// button just re-mounts its children, since every screen already re-fetches
// on mount. Kept intentionally minimal: this package's own component tree
// is small and shallow, so React's default per-subtree boundary semantics
// are enough without a logging/reporting hook.
import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: unknown;
}

export class EcosystemErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: unknown): State {
    return { error };
  }

  override render() {
    if (this.state.error) {
      return (
        <div
          data-testid="ecosystem-error-boundary"
          role="alert"
          style={{ padding: "var(--eco-space-lg)", color: "var(--eco-color-textSecondary)" }}
        >
          <div>Something went wrong loading the marketplace.</div>
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            style={{ marginTop: "var(--eco-space-sm)", cursor: "pointer" }}
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
