// SPDX-License-Identifier: MIT
// A single bad row/response must never blank the whole marketplace screen
// for a host that doesn't already wrap this package in its own error
// boundary. Host-agnostic (no host callback required) -- a "Try again"
// button just re-mounts its children, since every screen already re-fetches
// on mount. Kept intentionally minimal: this package's own component tree
// is small and shallow, so React's default per-subtree boundary semantics
// are enough without a logging/reporting hook.
import { Component } from "react";
export class EcosystemErrorBoundary extends Component {
  state = {
    error: null
  };
  static getDerivedStateFromError(error) {
    return {
      error
    };
  }
  render() {
    if (this.state.error) {
      return <div data-testid="ecosystem-error-boundary" role="alert" className="p-6 text-gray-500">
          <div>Something went wrong loading the marketplace.</div>
          <button type="button" onClick={() => this.setState({
          error: null
        })} className="mt-2 cursor-pointer">
            Try again
          </button>
        </div>;
    }
    return this.props.children;
  }
}