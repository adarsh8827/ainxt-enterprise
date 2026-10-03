// SPDX-License-Identifier: MIT
// The one interface every screen in this package depends on -- never a
// direct fetch() call from a component. RealEcosystemClient.ts is the
// fetch-based implementation consuming the live backend
// (docs/ecosystem/CONTRACTS.md §17); MockEcosystemClient.ts is a
// fixture-backed implementation for Storybook/component tests, validated
// against the same generated OpenAPI spec in CI (task B-17's contract
// test, CONTRACTS.md §16 point 2).

export class EcosystemApiError extends Error {
  constructor(code, message, retryable, details) {
    super(message);
    this.code = code;
    this.retryable = retryable;
    this.details = details;
  }
}