// SPDX-License-Identifier: MIT
// Task M5 (Ecosystem Marketplace) — end-to-end specs for the 7 named
// scenarios in docs/ecosystem/SKILLS_PHASE_PLAN.md's Tests section.
//
// Uses the `chrome` channel (a system-installed Chrome) rather than
// Playwright's own bundled Chromium — this environment's network egress
// blocks Playwright's browser-binary CDN download
// (cdn.playwright.dev), so `npx playwright install chromium` cannot
// complete here. If your environment CAN reach that CDN, either channel
// works; `npx playwright install chromium` remains the documented
// zero-dependency path for CI/other machines.
//
// These specs need a real backend (ENABLE_ECOSYSTEM_MARKETPLACE=true,
// ECOSYSTEM_CHAT_SKILLS=true, a gate-worker running) and ai-ui's own dev
// server — see docs/ecosystem/TESTING_GUIDE.md's Playwright section for
// the full setup. This config does NOT start either server itself
// (unlike a typical Playwright `webServer` block) because both need
// non-default env/flags this config can't safely assume — start them
// per the guide, then point PLAYWRIGHT_BASE_URL at your own ai-ui dev
// server if it's not on the default port.
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false, // shared org/user fixtures — specs mutate shared state (installs, org policy)
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: 'list',
  timeout: 30_000,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5175',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], channel: 'chrome' },
    },
  ],
});
