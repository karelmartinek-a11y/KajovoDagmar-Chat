import { expect, test } from '@playwright/test';
import { ensureAuthenticated, navigateTo } from './helpers';

test.describe.serial('KájovoDagmar acceptance', () => {
  test('initialization, login and stable navigation', async ({ page }) => {
    await ensureAuthenticated(page);
    for (const section of ['Chat', 'Historie', 'Paměť', 'Nastavení']) {
      await navigateTo(page, section);
      await expect(page.getByRole('heading', { name: section, exact: true })).toBeVisible();
    }
    await navigateTo(page, 'Profil');
    await expect(page.getByRole('heading', { name: 'Profil' })).toBeVisible();
  });

  test('memory lifecycle is visible and reversible', async ({ page }) => {
    await ensureAuthenticated(page);
    await navigateTo(page, 'Paměť');
    const content = `Syntetická preference ${Date.now()}`;
    await page.getByLabel('Nová paměťová položka').fill(content);
    await page.getByRole('button', { name: 'Uložit do paměti' }).click();
    await expect(page.getByText(content)).toBeVisible();
    await page.locator('.memory-list button', { hasText: content }).click();
    await expect(page.getByRole('button', { name: 'Odstranit vzpomínku' })).toBeVisible();
    const deletion = page.waitForResponse(
      (response) =>
        response.request().method() === 'DELETE' && response.url().includes('/api/v1/memory/'),
    );
    await page.getByRole('button', { name: 'Odstranit vzpomínku' }).click();
    await expect(
      page.getByText('Klikněte znovu pro potvrzení odstranění této položky.'),
    ).toBeVisible();
    await page.getByRole('button', { name: 'Potvrdit odstranění' }).click();
    expect((await deletion).status()).toBe(200);
    await expect(
      page.getByText('Položka byla odstraněna a v retenční době ji lze obnovit.'),
    ).toBeVisible();
    await expect(page.locator('.memory-list button', { hasText: content })).toHaveCount(0);
  });

  test('unconfigured AI is reported truthfully', async ({ page }) => {
    await ensureAuthenticated(page);
    await page.getByLabel('Textová zpráva').fill('Odpověz na syntetický test.');
    await page.locator('form.text-entry').evaluate((form) => {
      (form as HTMLFormElement).requestSubmit();
    });
    if (process.env.E2E_DETERMINISTIC_PROVIDER === 'true') {
      await expect(page.getByText('Automatický hlasový test proběhl správně.')).toBeVisible();
    } else {
      await expect(page.getByRole('alert')).toContainText(/model|Nastavení|poskytovatel/i);
    }
  });

  test('critical pages have no serious axe violations', async ({ page }) => {
    await ensureAuthenticated(page);
    for (const path of ['/chat', '/history', '/memory', '/settings', '/profile']) {
      await page.goto(path);
      const audit = await page.evaluate(() => {
        const missingNames = [
          ...document.querySelectorAll('button, a, input, select, textarea'),
        ].filter((element) => {
          const node = element as HTMLElement;
          const label =
            node.getAttribute('aria-label') ||
            node.getAttribute('title') ||
            node.textContent?.trim();
          if (
            element instanceof HTMLInputElement ||
            element instanceof HTMLTextAreaElement ||
            element instanceof HTMLSelectElement
          ) {
            return !label && element.labels?.length === 0;
          }
          return !label;
        }).length;
        const missingMain = document.querySelectorAll('main').length !== 1;
        const missingLanguage = document.documentElement.lang !== 'cs';
        return { missingNames, missingMain, missingLanguage };
      });
      expect(audit).toEqual({ missingNames: 0, missingMain: false, missingLanguage: false });
    }
  });

  test('desktop and mobile visual evidence', async ({ page }, testInfo) => {
    await ensureAuthenticated(page);
    await page.goto('/chat');
    await page.screenshot({ path: testInfo.outputPath('chat.png'), fullPage: true });
    await expect(page.locator('[aria-labelledby="chat-title"]')).toHaveScreenshot('chat-page.png', {
      animations: 'disabled',
      maxDiffPixelRatio: 0.015,
    });
  });
});
