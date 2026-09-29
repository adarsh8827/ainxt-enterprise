// SPDX-License-Identifier: MIT
// Per-surface toggles/chip-cleanup round (2026-09-29): real-screenshot
// verification for Items 1 and 2 --
//   1. picking a skill from the "/" menu leaves ONLY the chip in the
//      input, never leftover "/skill-name" text alongside it.
//   2. the "ⓘ" info-icon popover opens with real skill metadata and the
//      sent message bubble still shows the chip.
// Uses the same throwaway e2e-test-org fixture user/skill (helpers.ts)
// every other Ecosystem E2E spec in this suite uses.
import { test, expect } from '@playwright/test';
import { loginAs, USER_A, createResolvedSkill } from './helpers';

test.describe('Chat skill chip + info popover -- real screenshots', () => {
  test('picking a skill from the "/" menu leaves only the chip, no leftover slash text; info popover opens; sent bubble keeps the chip', async ({ page, context }) => {
    await page.setViewportSize({ width: 1366, height: 900 });
    await loginAs(context, USER_A);

    const displayName = `Chip Round Screenshot Skill ${Date.now()}`;
    const { itemId, namespace } = await createResolvedSkill(context.request, { displayName });
    const slashCommand = `/${namespace.split('/')[1]}`;

    await page.goto('/portal/');
    // Same established pattern as installed-appears-in-chat-without-
    // reload.spec.ts (task 6/B-16/F-11) -- a bare "/" opens the menu
    // unconditionally, listing every installed chat-surface skill,
    // without needing to start a fresh chat first.
    const input = page.locator('#chat-input');
    await expect(input).toBeVisible({ timeout: 15_000 });

    // The "/" menu caps at 8 skills (Chat.jsx's own skillMatches.slice(0,8))
    // -- this shared e2e fixture account has accumulated more than 8
    // installed skills over the test suite's lifetime, so a BARE "/"
    // would show the menu but not necessarily THIS run's own skill (it
    // sorts by namespace, and a bare "/" doesn't filter). Filtering by
    // this skill's own unique slash-command prefix (its namespace
    // includes a timestamp+random suffix, so this is never ambiguous)
    // narrows the match down to just this one skill regardless of how
    // many others exist.
    await input.fill(slashCommand.slice(0, -2));
    const menuRow = page.getByText(displayName).first();
    await expect(menuRow).toBeVisible({ timeout: 10_000 });

    // Pick the skill from the menu -- the real bug this round fixed: the
    // input used to keep the leftover "/partial-command" text alongside
    // the new chip. Assert the box holds ONLY the chip now.
    await menuRow.click();
    const chip = page.locator('.bg-blue-50', { hasText: displayName });
    await expect(chip).toBeVisible({ timeout: 5_000 });
    await expect(input).toHaveValue('');
    await page.screenshot({ path: 'e2e/screenshots/chat-round-chip-no-leftover-text.png' });

    // Info popover -- zero model/gate calls, just already-fetched skill
    // metadata (description/how-to-use/source/license) + "Open in
    // Marketplace". data-testid="skill-info-icon" is the chip's own "ⓘ".
    await chip.getByTestId('skill-info-icon').click();
    await expect(page.getByTestId('skill-info-popover')).toBeVisible();
    await expect(page.getByTestId('skill-info-popover')).toContainText(slashCommand);
    await expect(page.getByTestId('skill-info-popover')).toContainText('Open in Marketplace');
    await page.screenshot({ path: 'e2e/screenshots/chat-round-info-popover-open.png' });
    await page.keyboard.press('Escape').catch(() => {});
    await page.mouse.click(10, 10); // close the popover (outside-click)

    // Send with the chip attached + real typed task text -- the sent
    // bubble keeps its own chip.
    await input.click();
    await input.pressSequentially('summarize this for me', { delay: 5 });
    await page.keyboard.press('Enter');
    const sentBubbleChip = page.locator('.bg-blue-50', { hasText: displayName }).last();
    await expect(sentBubbleChip).toBeVisible({ timeout: 15_000 });
    await page.screenshot({ path: 'e2e/screenshots/chat-round-sent-bubble-with-chip.png' });

    await page.request.post(`/ainxt/v1/api/ecosystem/items/${encodeURIComponent(itemId)}/delete-draft`).catch(() => {});
  });
});
