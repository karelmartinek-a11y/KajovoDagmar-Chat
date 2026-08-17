import { expect, test } from '@playwright/test';
import { ensureAuthenticated } from './helpers';

test.describe('Production voice smoke test', () => {
  test.skip(
    process.env.E2E_PRODUCTION_VOICE !== 'true',
    'The live provider smoke test only runs after a production deployment.',
  );

  test('login, microphone, realtime response and clean shutdown', async ({ page }) => {
    test.setTimeout(150_000);
    await ensureAuthenticated(page);

    const browserErrors: string[] = [];
    page.on('pageerror', (error) => browserErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error') browserErrors.push(message.text());
    });

    await expect(page).toHaveURL(/\/chat$/);
    await expect(page.getByRole('heading', { name: 'Chat', exact: true })).toBeVisible();

    await page.getByRole('button', { name: 'Zahájit rozhovor' }).click();
    await expect(page.getByText('Naslouchám', { exact: true })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText('Mikrofon naslouchá', { exact: true })).toBeVisible();
    await expect(page.getByText('Stav spojení: připojeno', { exact: true })).toBeVisible();

    await page.getByRole('button', { name: 'Pozastavit mikrofon' }).click();
    await expect(page.getByText('Mikrofon je pozastavený', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Obnovit mikrofon' }).click();
    await expect(page.getByText('Mikrofon naslouchá', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Pozastavit mikrofon' }).click();
    await expect(page.getByText('Mikrofon je pozastavený', { exact: true })).toBeVisible();

    const prompt = `Produkční E2E hlasového chatu ${Date.now()}: odpověz pouze slovem funguje.`;
    const assistantMessages = page.locator('article.message.assistant');
    const assistantCount = await assistantMessages.count();
    await page.getByLabel('Textová zpráva').fill(prompt);
    await page.locator('form.text-entry').evaluate((form) => {
      (form as HTMLFormElement).requestSubmit();
    });
    await expect(page.locator('article.message.user', { hasText: prompt })).toBeVisible({
      timeout: 30_000,
    });
    await expect(assistantMessages.nth(assistantCount)).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText('Naslouchám', { exact: true })).toBeVisible({ timeout: 60_000 });
    expect(await page.getByRole('alert').allTextContents()).toEqual([]);

    await page.getByRole('button', { name: 'Ukončit rozhovor' }).click();
    await expect(page.getByText('Rozhovor byl ukončen', { exact: true })).toBeVisible({
      timeout: 20_000,
    });
    expect(browserErrors).toEqual([]);
  });
});
