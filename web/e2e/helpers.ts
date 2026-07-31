import type { Page } from '@playwright/test';

export const password = process.env.E2E_PASSWORD ?? 'Bezpečná syntetická věta pro E2E 2026';
export const initializationSecret = process.env.E2E_INITIALIZATION_SECRET ?? '';
export const username = process.env.E2E_USERNAME ?? 'Karmar78';

export async function ensureAuthenticated(page: Page): Promise<void> {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  const heading = page.locator('h1');
  try {
    await heading.waitFor({ timeout: 10_000 });
  } catch {
    // Caddy can report healthy while the first proxied document is still warming up.
    // Retry the same isolated endpoint rather than masking a real application error.
    await page.reload({ waitUntil: 'domcontentloaded' });
    await heading.waitFor();
  }
  if (
    await page
      .getByRole('heading', { name: 'Bezpečné první spuštění' })
      .isVisible()
      .catch(() => false)
  ) {
    if (!initializationSecret)
      throw new Error('E2E_INITIALIZATION_SECRET je povinné pro inicializaci.');
    await page.getByLabel('Inicializační tajemství').fill(initializationSecret);
    await page.getByLabel('Uživatelské jméno').fill(username);
    await page.getByLabel('Jméno pro zobrazení').fill('E2E správce');
    await page.getByLabel('První heslo').fill(password);
    await page.getByLabel('Potvrzení hesla').fill(password);
    const initializeResponse = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' && response.url().includes('/api/v1/auth/initialize'),
    );
    await page.getByRole('button', { name: 'Aktivovat účet' }).click();
    if ((await initializeResponse).status() !== 201) {
      throw new Error('E2E initialization did not return HTTP 201.');
    }
    await page.getByRole('heading', { name: /^(Přihlášení|Chat)$/ }).waitFor();
  }
  if (
    await page
      .getByRole('heading', { name: 'Přihlášení' })
      .isVisible()
      .catch(() => false)
  ) {
    await page.getByLabel('Heslo').fill(password);
    const loginResponse = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' && response.url().includes('/api/v1/auth/login'),
    );
    await page.getByRole('button', { name: 'Přihlásit se' }).click();
    if ((await loginResponse).status() !== 200) {
      throw new Error('E2E login did not return HTTP 200.');
    }
  }
  try {
    await page.getByRole('heading', { name: 'Chat' }).waitFor({ timeout: 10_000 });
  } catch {
    // A freshly rotated session can finish after the first client render. A
    // full reload re-reads the authenticated cookie and exposes a real 401
    // rather than leaving the browser on a stale login route.
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.getByRole('heading', { name: 'Chat' }).waitFor();
  }
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
