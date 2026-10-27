import { expect, test } from '@playwright/test'

test('core browser workflows and deterministic Insights need only loopback services', async ({ page }) => {
  test.setTimeout(180_000)
  const external: string[] = []
  await page.context().route('**/*', async route => {
    const url = new URL(route.request().url())
    if (['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)) {
      await route.continue()
    } else {
      external.push(url.origin)
      await route.abort()
    }
  })
  await page.goto('/login')
  await page.getByLabel('Username').fill('admin')
  await page.getByLabel('Password').fill('abi_test_admin_only')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/dashboard/)
  for (const path of ['/analytics/sales', '/ml/metrics', '/admin/settings', '/reports']) {
    await page.goto(path)
    await expect(page.locator('main')).toBeVisible()
  }
  await page.goto('/insights')
  await page.getByLabel('Question').fill('What is the total revenue?')
  const numerical = page.waitForResponse(r => r.url().includes('/api/insights/query'))
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  const computed = await (await numerical).json()
  expect(computed.provider).toBe('computed')
  expect(computed.status).toBe('available')
  await expect(page.locator('pre')).toContainText(computed.answer)
  await page.getByLabel('Question').fill('Tell me a joke')
  const fallback = page.waitForResponse(r => r.url().includes('/api/insights/query'))
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  const limited = await (await fallback).json()
  expect(limited.status).toBe('llm_unavailable')
  expect(limited.provider).toBe('disabled')
  await expect(page.locator('pre')).toContainText('cannot answer that question')
  await expect(page.locator('pre')).toContainText('deterministic summary')
  expect(external).toEqual([])
})
