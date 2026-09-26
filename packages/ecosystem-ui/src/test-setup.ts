// SPDX-License-Identifier: MIT
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// test.globals is deliberately false (vite.config.ts) -- @testing-library/
// react's own auto-cleanup only self-registers when it detects a GLOBAL
// afterEach, which doesn't exist here, so register it explicitly instead
// of turning on globals just for this one behavior.
afterEach(() => cleanup());
