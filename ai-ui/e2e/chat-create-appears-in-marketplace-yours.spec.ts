// SPDX-License-Identifier: MIT
// Item 6 E2E spec: "created in chat -> appears in Marketplace Yours."
// create-in-chat.spec.ts already proves the slow, real-LLM Create-with-AI
// generation UI flow end to end; duplicating that ~150s flow here just to
// re-derive the same resulting item would be expensive and redundant.
// This spec's own job is a DIFFERENT concern -- Marketplace-side
// visibility -- so it reaches the same end state (a resolved, chat-
// created item, origin="created") via the same API helper every other
// spec in this suite uses for setup, then verifies the real Marketplace
// UI's Yours screen shows it under "Created by me," a UI-level assertion
// create-in-chat.spec.ts itself never makes (it checks via the API only).
import { test, expect } from '@playwright/test';
import { loginAs, USER_A, createResolvedSkill } from './helpers';

test('a chat-created skill appears in Marketplace Yours under "Created by me"', async ({ page, context }) => {
  await loginAs(context, USER_A);

  const displayName = `Chat Create Yours Test ${Date.now()}`;
  await createResolvedSkill(context.request, { displayName });

  await page.goto('/marketplace/skills');
  // CatalogScreen.tsx picks Yours automatically once has_any is true
  // (which it now is, for this user/type) -- click the toggle anyway,
  // idempotently, rather than assume that default-view timing.
  const yoursToggle = page.getByTestId('view-toggle-yours');
  await expect(yoursToggle).toBeVisible({ timeout: 15_000 });
  await yoursToggle.click();

  const group = page.locator('[data-testid="yours-group"][data-group-label="Created by me"]');
  await expect(group.getByText(displayName)).toBeVisible({ timeout: 15_000 });
});
