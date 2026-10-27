import { expect, test } from '@playwright/test'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

test('mobile workspace navigation supports Escape, focus return and dataset controls without overflow', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/login')
  await page.getByLabel('Username').fill('analyst')
  await page.getByLabel('Password').fill('abi_test_analyst_only')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(/\/dashboard/)
  await page.getByRole('button', { name: 'Open navigation', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Dataset Manager', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Open navigation', exact: true })).toBeFocused()
  await expect(page.getByRole('button', { name: 'Open navigation', exact: true })).toHaveAttribute('aria-expanded', 'false')
  await page.getByRole('button', { name: 'Open navigation', exact: true }).click()
  await page.getByRole('link', { name: 'Dataset Manager', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Dataset Manager', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Upload Folder', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Upload ZIP', exact: true })).toBeVisible()
  await expect(page.getByLabel('Dataset folder', { exact: true })).toHaveAttribute('webkitdirectory')
  await expect(page.getByLabel('Dataset folder', { exact: true })).toHaveAttribute('multiple')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('mobile-datasets.png'), fullPage: true })
})

test('desktop and laptop presentation keeps real routes readable with no browser errors', async ({ page }, testInfo) => {
  test.setTimeout(180000)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/login')
  await page.screenshot({ path: testInfo.outputPath('login.png'), fullPage: true })
  await page.getByLabel('Username').fill('admin')
  await page.getByLabel('Password').fill('abi_test_admin_only')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(/\/dashboard/)
  for (const route of ['/dashboard', '/datasets', '/ml/metrics', '/analytics/sales', '/admin/settings', '/reports', '/insights']) {
    await page.goto(route)
    await expect(page.locator('main')).toBeVisible()
    await expect(page.getByLabel('Active Dataset', { exact: true })).toBeEnabled()
    await expect(page.locator('main h1').first()).toBeVisible()
    if (route === '/dashboard' || route === '/analytics/sales') await expect(page.locator('.recharts-surface').first()).toBeVisible()
    if (route === '/ml/metrics') {
      await page.getByText('Historical evaluation metrics', { exact: true }).first().click()
      await expect(page.locator('details[open]').first()).toBeVisible()
      await expect(page.getByRole('link', { name: 'Review dataset mapping →', exact: true }).first()).toHaveAttribute('href', '/datasets')
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(route.replaceAll('/', '-') + '.png'), fullPage: true })
  }
  await page.setViewportSize({ width: 1024, height: 768 })
  await page.goto('/dashboard')
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('laptop-dashboard.png'), fullPage: true })
  expect(errors).toEqual([])
})

test('large real folder import shows its job and resumes after reload with delayed status transport', async ({ page }, testInfo) => {
  test.setTimeout(180000)
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'sem5-ui-job-'))
  const file = path.join(directory, 'observations.csv')
  fs.writeFileSync(file, 'date,revenue,note\n' + Array.from({ length: 500 }, (_, index) => `2025-01-01,${index + 1},${'x'.repeat(4500)}`).join('\n'))
  let releaseStatus!: () => void
  const delayed = new Promise<void>(resolve => { releaseStatus = resolve })
  let held = false
  await page.route('**/api/datasets/bundles/jobs/*', async route => {
    if (!held && route.request().method() === 'GET') { held = true; await delayed }
    await route.continue().catch(() => {})
  })
  try {
    await page.goto('/login')
    await page.getByLabel('Username').fill('analyst')
    await page.getByLabel('Password').fill('abi_test_analyst_only')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page).toHaveURL(/\/dashboard/)
    await page.getByRole('link', { name: 'Dataset Manager', exact: true }).click()
    await page.getByLabel('Dataset folder', { exact: true }).setInputFiles(directory)
    const uploaded = page.waitForResponse(response => response.url().endsWith('/api/datasets/bundles/upload') && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'Confirm bundle import', exact: true }).click()
    const response = await uploaded
    expect(response.status()).toBe(202)
    const job = await response.json()
    expect(job.job_id).toBeTruthy()
    await expect(page.getByRole('button', { name: 'Cancel import', exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('real-job-status.png'), fullPage: true })
    await page.reload()
    releaseStatus()
    await expect(page.getByText('Imported 1 separate tables.', { exact: true })).toBeVisible({ timeout: 120000 })
    expect(await page.evaluate(() => Object.keys(localStorage).filter(key => key.startsWith('sem5_pending_bundle:')).length)).toBe(0)
    await testInfo.attach('real-async-import', { body: JSON.stringify({ status: response.status(), job_id: job.job_id, rows: 500, source_bytes: fs.statSync(file).size }), contentType: 'application/json' })
  } finally {
    releaseStatus()
    fs.unlinkSync(file)
    fs.rmdirSync(directory)
  }
})
