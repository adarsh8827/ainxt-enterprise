// SPDX-License-Identifier: MIT
// M5 E2E spec 5/7: upload a GPL-licensed SKILL.md -> blocked with the
// specific license reason shown (F-9/B-8). Runs synchronously at
// creation time (license_stage's own pre-check, docs/ecosystem/
// CONTRACTS.md §10) -- no gate-worker or LLM dependency, unlike most of
// this file's siblings.
import JSZip from 'jszip';
import { test, expect } from '@playwright/test';
import { loginAs, USER_A } from './helpers';

async function buildGplSkillZip(): Promise<Buffer> {
  const zip = new JSZip();
  zip.file('SKILL.md', '---\nname: quick-scraper\nlicense: GPL-3.0-only\ndescription: A scraper utility.\n---\nBody text.');
  return zip.generateAsync({ type: 'nodebuffer' });
}

test('uploading a GPL-licensed bundle is blocked with the specific license reason', async ({ page, context }) => {
  await loginAs(context, USER_A);
  await page.goto('/portal/marketplace/skills/upload');

  await expect(page.getByTestId('upload-flow')).toBeVisible({ timeout: 15_000 });

  const zipBuffer = await buildGplSkillZip();
  await page.setInputFiles('input[type="file"]', {
    name: 'quick-scraper.skill', mimeType: 'application/zip', buffer: zipBuffer,
  });
  await page.getByTestId('upload-namespace').fill(`e2e-test-org/quick-scraper-${Date.now()}`);
  await page.getByTestId('upload-submit').click();

  const blockedBanner = page.getByTestId('upload-blocked-banner');
  await expect(blockedBanner).toBeVisible({ timeout: 15_000 });
  await expect(blockedBanner).toHaveText(/MIT\/Apache-2\.0/);
  await expect(page.getByRole('alert').filter({ hasText: /couldn't upload/i })).toHaveCount(0);
});
