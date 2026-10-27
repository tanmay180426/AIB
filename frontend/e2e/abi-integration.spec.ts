import { expect, test } from '@playwright/test'

const apiBase = `http://localhost:${process.env.SEM5_E2E_BACKEND_PORT || '8000'}`
const windowQuery = '?date_from=2018-01-01&date_to=2018-01-31'

test('active Olist ML, real forecast UI, network health and logout remain authoritative', async ({ page }) => {
  test.setTimeout(180_000)
  const errors: string[] = []
  const failures: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('requestfailed', request => {
    // Navigation cancels obsolete fetches intentionally; connection failures do not.
    if (!request.failure()?.errorText.includes('ERR_ABORTED')) failures.push(request.url())
  })
  page.on('response', response => {
    if (response.url().startsWith(apiBase) && response.status() >= 500) {
      failures.push(`${response.status()} ${response.url()}`)
    }
  })
  await page.goto('/login')
  await page.getByLabel('Username').fill('analyst')
  await page.getByLabel('Password').fill('abi_test_analyst_only')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/dashboard/)
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible()

  // Reuse the real login token without logging credentials or token values.
  const token = await page.evaluate(() => localStorage.getItem('sem5_token') || '')
  const headers = { Authorization: `Bearer ${token}` }
  const list = await (await page.request.get(`${apiBase}/api/datasets`, { headers })).json()
  const reference = list.datasets.find((ds: { read_only: boolean }) => ds.read_only)
  expect(reference).toBeTruthy()
  await page.getByLabel('Active Dataset').selectOption(reference.dataset_id)
  const scoped = { ...headers, 'X-Dataset-ID': reference.dataset_id }
  const response = page.waitForResponse(r => r.url().includes('/api/ml/forecast?'))
  await page.goto('/ml/revenue-forecast' + windowQuery)
  const latestResponse = await response
  expect(latestResponse.status()).toBe(200)
  expect(latestResponse.url()).not.toContain('date_to=')
  expect((await latestResponse.json()).forecast).toHaveLength(365)
  await page.getByLabel('Forecast horizon').selectOption('30')
  await expect(page.getByTestId('forecast-chart')).toHaveAttribute('data-forecast-points','30')
  const scopedResponse = page.waitForResponse(r => r.url().includes('/api/ml/forecast?') && r.url().includes('date_to=2018-01-31'))
  await page.getByLabel('Forecast origin mode').selectOption('selected')
  const forecastResponse = await scopedResponse
  expect(forecastResponse.status()).toBe(200)
  const forecast = await forecastResponse.json()
  expect(forecast.status).toBe('available')
  expect(forecast.dataset_id).toBe(reference.dataset_id)
  expect(forecast.forecast).toHaveLength(30)
  expect(forecast.forecast[0].date).toBe('2018-02-01')
  expect(forecast.history_tail.every((p: { date: string }) =>
    p.date >= '2018-01-01' && p.date <= '2018-01-31')).toBe(true)
  expect(forecast.forecast.every((p: { revenue: number }) => Number.isFinite(p.revenue))).toBe(true)
  await expect(page.getByText('Model: Linear Regression (Daily)', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Forecast Data Table' })).toBeVisible()
  await expect(page.getByRole('table', {name:'Forecast data', exact:true}).locator('tbody tr')).toHaveCount(30)
  await expect(page.getByText('GradientBoostingRegressor')).toHaveCount(0)

  // Exercise all existing model families through the same real scoped API.
  for (const path of ['/api/ml/forecast?target=orders&periods=7&date_from=2018-01-01&date_to=2018-01-31',
    '/api/ml/segments/customers', '/api/ml/product-segmentation',
    '/api/ml/anomalies?date_from=2018-01-01&date_to=2018-01-31']) {
    const result = await page.request.get(apiBase + path, { headers: scoped })
    expect(result.status(), path).toBe(200)
    expect((await result.json()).status, path).toBe('available')
  }
  const prediction = await page.request.post(`${apiBase}/api/ml/predict/sales`, {
    headers: scoped, data: { purchase_month: 1, purchase_weekday: 2, purchase_hour: 10,
      n_items: 2, customer_state: 'SP', product_category_name: 'books' },
  })
  expect(prediction.status()).toBe(200)
  expect(Number.isFinite((await prediction.json()).predicted_item_revenue)).toBe(true)
  expect((await page.request.get(`${apiBase}/api/admin/system/status`, { headers })).status()).toBe(403)
  // Capture after the real model checks, once chart entrance animations settle.
  await page.screenshot({ path: test.info().outputPath('active-revenue-forecast.png'), fullPage: true })

  await page.goto('/ml/product-segmentation' + windowQuery)
  await expect(page.getByText('Products Analyzed', { exact: true })).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page).toHaveURL(/\/login/)
  expect(await page.evaluate(() => ['sem5_token', 'sem5_refresh', 'sem5_user']
    .every(key => localStorage.getItem(key) === null))).toBe(true)
  await page.goto('/dashboard')
  await expect(page).toHaveURL(/\/login/)
  expect(errors).toEqual([])
  expect(failures).toEqual([])
})

test('ML administration lists only deployed target artifacts and never activates the candidate', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Username').fill('admin')
  await page.getByLabel('Password').fill('abi_test_admin_only')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/dashboard/)
  await page.getByRole('link', { name: 'ML Admin', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Model artifacts', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'sales_forecast_revenue.joblib', exact: true })).toBeVisible()
  await expect(page.getByText('gradient_boosting_sales_model.joblib')).toHaveCount(0)
  await expect(page.getByText('GradientBoostingRegressor')).toHaveCount(0)
  await expect(page.getByText('6 deployed', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page).toHaveURL(/\/login/)
})

test('forecast page honestly reflects real artifact availability', async ({ page }) => {
  const expectMissing = process.env.SEM5_E2E_EXPECT_MISSING_ARTIFACT === 'true'
  await page.goto('/login')
  await page.getByLabel('Username').fill('analyst')
  await page.getByLabel('Password').fill('abi_test_analyst_only')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/dashboard/)
  const response = page.waitForResponse(r => r.url().includes('/api/ml/forecast?'))
  await page.goto('/ml/revenue-forecast' + windowQuery)
  const result = await response
  if (expectMissing) {
    expect(result.status()).toBe(503)
    await expect(page.getByText('The trained model artifact is unavailable. Contact the administrator.',
      { exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Forecast Data Table' })).toHaveCount(0)
    await expect(page.getByText('Forecast Total (30d)', { exact: true })).toHaveCount(0)
  } else {
    expect(result.status()).toBe(200)
    expect((await result.json()).status).toBe('available')
    await expect(page.getByRole('heading', { name: 'Forecast Data Table' })).toBeVisible()
  }
})
