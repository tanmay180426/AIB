import { expect, test } from '@playwright/test'

test('landing page renders hero', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toContainText(
    'AI-Powered Business Intelligence',
  )
})

test('login page renders the sign-in form', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByLabel('Username')).toBeVisible()
  await expect(page.getByLabel('Password')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
})

test('admin can sign in with real credentials and reach the dashboard', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Username').fill('admin')
  await page.getByLabel('Password').fill('abi_test_admin_only')
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect(page).toHaveURL(/\/dashboard/)
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
})

test('admin sees the administration section and can open user management', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Username').fill('admin')
  await page.getByLabel('Password').fill('abi_test_admin_only')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/dashboard/)

  await expect(page.getByRole('link', { name: 'System Health' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Settings' })).toBeVisible()

  await page.getByRole('link', { name: 'Users', exact: true }).click()
  await expect(page).toHaveURL(/\/admin\/users/)
  await expect(page.getByRole('heading', { name: 'Platform Administration' })).toBeVisible()
  await expect(page.getByText('admin', { exact: true }).first()).toBeVisible()
})

test('analyst gets full BI access but no administration', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Username').fill('analyst')
  await page.getByLabel('Password').fill('abi_test_analyst_only')
  await page.getByRole('button', { name: 'Sign in' }).click()

  // business intelligence works
  await expect(page).toHaveURL(/\/dashboard/)
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()

  // administration navigation is not offered
  await expect(page.getByRole('link', { name: 'System Health' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Settings' })).toHaveCount(0)

  // other BI pages work too (first navigation loads the lazy chart chunk)
  await page.getByRole('link', { name: 'Machine Learning' }).click()
  await expect(page).toHaveURL(/\/ml/)
  await expect(page.getByRole('heading', { name: 'ML Metrics' })).toBeVisible({ timeout: 30_000 })

  // direct admin URL is blocked in the UI
  await page.goto('/admin/users')
  await expect(page.getByText('Access Restricted')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Platform Administration' })).toHaveCount(0)
})
