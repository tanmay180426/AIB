import { expect, test } from '@playwright/test'

test('fresh workspace reports missing artifacts and keeps uploaded analytics authoritative', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Username').fill('admin')
  await page.getByLabel('Password').fill('abi_test_admin_only')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/dashboard/)
  await page.goto('/ml/metrics')
  await expect(page.getByRole('heading', { name: 'ML Metrics', exact: true })).toBeVisible()
  await page.goto('/ml/revenue-forecast')
  await expect(page.getByRole('heading', { name: 'Not Applicable', exact: true })).toBeVisible()
  await page.goto('/insights')
  await page.getByLabel('Question').fill('What is the total revenue?')
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await expect(page.locator('pre')).toContainText('1,000.00')
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page).toHaveURL(/\/login/)
})
