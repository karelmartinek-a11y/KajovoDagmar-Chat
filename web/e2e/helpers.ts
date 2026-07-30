import type { Page } from '@playwright/test';

export const password = process.env.E2E_PASSWORD ?? 'Bezpečná syntetická věta pro E2E 2026';
export const initializationSecret = process.env.E2E_INITIALIZATION_SECRET ?? '';

export async function ensureAuthenticated(page: Page): Promise<void> {
  await page.goto('/');
  await page.locator('h1').waitFor();
  if (
    await page
      .getByRole('heading', { name: 'Bezpečné první spuštění' })
      .isVisible()
      .catch(() => false)
  ) {
    if (!initializationSecret)
      throw new Error('E2E_INITIALIZATION_SECRET je povinné pro inicializaci.');
    await page.getByLabel('Inicializační tajemství').fill(initializationSecret);
    await page.getByLabel('Jméno pro zobrazení').fill('E2E správce');
    await page.getByLabel('První heslo').fill(password);
    await page.getByLabel('Potvrzení hesla').fill(password);
    await page.getByRole('button', { name: 'Aktivovat účet' }).click();
    await page.getByRole('heading', { name: /^(Přihlášení|Chat)$/ }).waitFor();
  }
  if (
    await page
      .getByRole('heading', { name: 'Přihlášení' })
      .isVisible()
      .catch(() => false)
  ) {
    await page.getByLabel('Heslo').fill(password);
    await page.getByRole('button', { name: 'Přihlásit se' }).click();
  }
  await page.getByRole('heading', { name: 'Chat' }).waitFor();
}

export async function navigateTo(page: Page, section: string): Promise<void> {
  const desktopLink = page.locator('.sidebar a', { hasText: section });
  if (await desktopLink.isVisible()) {
    await desktopLink.click();
  } else {
    const mobileLink = page.locator('.mobile-header a', { hasText: section });
    if (!(await mobileLink.isVisible())) {
      await page.getByText('Navigace', { exact: true }).click();
    }
    await mobileLink.click();
  }
}
