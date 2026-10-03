// SPDX-License-Identifier: MIT
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// test.globals is deliberately false (ai-ui/vite.config.js) -- @testing-library/
// react's own auto-cleanup only self-registers when it detects a GLOBAL
// afterEach, which doesn't exist here, so register it explicitly instead
// of turning on globals just for this one behavior.
afterEach(() => cleanup());

// jsdom implements neither Range.getClientRects() nor Element.getClientRects()
// (a documented jsdom gap, not a bug in our code) -- CodeMirror 6's cursor/
// selection-layer measurement pass (EditContent.jsx, item A3's editor) calls
// both on every render and throws without this, as harmless-but-noisy
// console errors that never fail an assertion. Stubbed to empty, real DOM
// behavior only matters in the real browser E2E specs.
if (typeof Range !== "undefined" && !Range.prototype.getClientRects) {
  Range.prototype.getClientRects = () => ({ length: 0, item: () => null, [Symbol.iterator]: [][Symbol.iterator] });
}
if (typeof Element !== "undefined" && !Element.prototype.getClientRects) {
  Element.prototype.getClientRects = () => ({ length: 0, item: () => null, [Symbol.iterator]: [][Symbol.iterator] });
}
