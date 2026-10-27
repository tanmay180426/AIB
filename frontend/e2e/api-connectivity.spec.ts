import { expect, test, type Page } from '@playwright/test'

const january = '?date_from=2018-01-01&date_to=2018-01-31'
async function signIn(page: Page, role: 'admin' | 'analyst') {
  await page.goto('/login')
  await page.getByLabel('Username').fill(role)
  await page.getByLabel('Password').fill(role + '123')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/dashboard/)
}

test('analytics chart grain cannot break daily ML requests or discard date filters', async ({ page }) => {
  await signIn(page, 'analyst')
  await page.goto('/analytics/sales' + january + '&grain=month')
  await expect(page.getByRole('heading', { name: 'Revenue Over Time', exact: true })).toBeVisible()
  const status = page.waitForResponse(r => r.url().includes('/api/ml/status?'))
  await page.getByRole('link', { name: 'Machine Learning', exact: true }).click()
  const catalog = await status
  expect(catalog.status()).toBe(200)
  expect(catalog.url()).not.toContain('grain=')
  expect(catalog.url()).toContain('date_from=2018-01-01')
  const response = page.waitForResponse(r => r.url().includes('/api/ml/forecast?') && r.url().includes('target=orders'))
  await page.getByRole('link', { name: 'Order Forecast', exact: true }).click()
  const latest = await response
  expect(latest.status()).toBe(200)
  expect(latest.url()).not.toContain('date_to=')
  const scoped = page.waitForResponse(r => r.url().includes('/api/ml/forecast?') && r.url().includes('date_to=2018-01-31'))
  await page.getByLabel('Forecast origin mode').selectOption('selected')
  const forecast = await scoped
  expect(forecast.status()).toBe(200)
  expect(forecast.url()).not.toContain('grain=')
  expect((await forecast.json()).forecast[0].date).toBe('2018-02-01')
})

test('CSV export refreshes an invalid access token through the real authentication API', async ({ page }) => {
  await signIn(page, 'analyst')
  await page.goto('/reports' + january)
  await expect(page.getByRole('heading', { name: 'Reports', exact: true })).toBeVisible()
  await page.evaluate(() => localStorage.setItem('sem5_token', 'invalid-audit-token'))
  const refresh = page.waitForResponse(r => r.url().endsWith('/api/auth/refresh'))
  const exported = page.waitForResponse(r => r.url().includes('/api/reports/export?') && r.status() === 200)
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: /^KPIs/ }).click()
  expect((await refresh).status()).toBe(200)
  const actual = await exported
  expect(actual.headers()['content-type']).toContain('text/csv')
  expect(actual.url()).toContain('date_from=2018-01-01')
  const stream = await (await download).createReadStream()
  expect(stream).not.toBeNull()
  const chunks: Buffer[] = []
  for await (const chunk of stream!) chunks.push(Buffer.from(chunk))
  expect(Buffer.concat(chunks).toString()).toContain('total_revenue')
})

test('every analytics screen consumes its scoped endpoint and date grain', async ({ page }) => {
  test.setTimeout(180_000)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await signIn(page, 'analyst')
  for (const [section, heading] of [['sales', 'Revenue Over Time'], ['orders', 'Orders Over Time'],
    ['customers', 'Customer Spend Distribution'], ['products', 'Category Details'],
    ['sellers', 'Top Sellers Revenue Over Time'], ['delivery', 'Delivery Performance Over Time']]) {
    const response = page.waitForResponse(r => r.url().includes(`/api/analytics/${section}?`))
    await page.goto(`/analytics/${section}${january}&grain=day`)
    const actual = await response
    expect(actual.status()).toBe(200)
    expect(actual.url()).toContain('date_from=2018-01-01')
    expect(actual.url()).toContain('date_to=2018-01-31')
    if (['sales', 'orders'].includes(section)) expect(actual.url()).toContain('grain=day')
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
  }
  expect(errors).toEqual([])
})

test('newly connected active ML screens render real backend responses', async ({ page }) => {
  test.setTimeout(180_000)
  const errors: string[] = []
  page.on('pageerror', e => errors.push(e.message))
  await signIn(page, 'analyst')
  const orders = page.waitForResponse(r => r.url().includes('/api/ml/forecast?') && r.url().includes('target=orders'))
  await page.goto('/ml/order-forecast' + january)
  expect((await orders).status()).toBe(200)
  await expect(page.getByRole('heading', { name: 'Order Forecast', exact: true })).toBeVisible()
  await expect(page.getByText('Latest Actual Orders', { exact: true })).toBeVisible()
  await expect(page.getByRole('table', {name:'Forecast data', exact:true}).locator('tbody tr')).toHaveCount(365)
  await page.getByLabel('Forecast horizon').selectOption('30')
  await expect(page.getByRole('table', {name:'Forecast data', exact:true}).locator('tbody tr')).toHaveCount(30)
  const customerResponse = page.waitForResponse(r => r.url().includes('/api/ml/segments/customers'))
  await page.getByRole('link', { name: 'Customer Segments', exact: true }).click()
  const customer = await customerResponse
  const customerBody = await customer.json()
  expect(customer.status(), JSON.stringify(customerBody)).toBe(200)
  expect(customerBody.status, JSON.stringify(customerBody)).toBe('available')
  await expect(page.getByRole('columnheader', { name: 'Monetary total (BRL)' })).toBeVisible()
  expect(await page.locator('main tbody tr').count()).toBeGreaterThan(0)
  await page.getByRole('link', { name: 'Anomaly Detection', exact: true }).click()
  await expect(page.getByRole('status', { name: 'Anomaly summary' })).toContainText('anomalous days out of')
  await page.getByRole('link', { name: 'Sales Prediction', exact: true }).click()
  await page.getByLabel('Purchase month', { exact: true }).fill('1')
  await page.getByLabel('Purchase weekday (Monday = 0)', { exact: true }).fill('2')
  await page.getByLabel('Purchase hour', { exact: true }).fill('10')
  await page.getByLabel('Basket item count', { exact: true }).fill('2')
  await page.getByLabel('Customer state', { exact: true }).fill('SP')
  await page.getByLabel('Product category', { exact: true }).fill('books')
  const prediction = page.waitForResponse(r => r.url().includes('/api/ml/predict/sales?'))
  await page.getByRole('button', { name: 'Predict item revenue' }).click()
  const result = await prediction
  expect(result.status()).toBe(200)
  expect((await result.json()).status).toBe('available')
  await expect(page.getByRole('status', { name: 'Sales prediction result' })).toContainText('Predicted item revenue:')
  expect(errors).toEqual([])
})

test('all admin screens and user role/status actions use real backend contracts', async ({ page }) => {
  test.setTimeout(180_000)
  await signIn(page, 'admin')
  for (const [route, endpoint, heading] of [
    ['roles', '/api/users/roles/metadata', 'admin'],
    ['health', '/api/admin/health', 'Service Health'],
    ['data', '/api/admin/data/etl/status', 'Data pipeline / ETL'],
    ['warehouse', '/api/admin/warehouse/status', 'Warehouse'],
    ['ml', '/api/admin/ml/status', 'Model artifacts'],
    ['settings', '/api/admin/settings', 'Application']]) {
    const response = page.waitForResponse(r => r.url().includes(endpoint))
    await page.goto('/admin/' + route)
    expect((await response).status()).toBe(200)
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
    if (route === 'health') {
      const refreshed = page.waitForResponse(r => r.url().includes('/api/admin/health'))
      await page.getByRole('button', { name: 'Refresh', exact: true }).click()
      expect((await refreshed).status()).toBe(200)
    }
  }
  await page.goto('/admin/users')
  await expect(page.getByRole('heading', { name: 'Create user', exact: true })).toBeVisible()
  const username = 'api-ui-' + Date.now()
  await page.getByLabel('Username', { exact: true }).fill(username)
  await page.getByLabel('Password', { exact: true }).fill('audit-password-123')
  await page.getByLabel('New user role', { exact: true }).selectOption('analyst')
  const creation = page.waitForResponse(r => r.url().endsWith('/api/users') && r.request().method() === 'POST')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  expect((await creation).status()).toBe(200)
  const row = page.getByRole('row').filter({ hasText: username })
  await expect(row).toBeVisible()
  const role = page.waitForResponse(r => r.url().endsWith(`/api/users/${username}/role`))
  await page.getByLabel(`role for ${username}`, { exact: true }).selectOption('admin')
  expect((await role).status()).toBe(200)
  await expect(page.getByLabel(`role for ${username}`, { exact: true })).toHaveValue('admin')
  page.once('dialog', dialog => void dialog.accept())
  const deactivate = page.waitForResponse(r => r.url().endsWith(`/api/users/${username}/status`))
  await row.getByRole('button', { name: 'Deactivate', exact: true }).click()
  expect((await deactivate).status()).toBe(200)
  await expect(row.getByRole('button', { name: 'Activate', exact: true })).toBeVisible()
  const activate = page.waitForResponse(r => r.url().endsWith(`/api/users/${username}/status`))
  await row.getByRole('button', { name: 'Activate', exact: true }).click()
  expect((await activate).status()).toBe(200)
  await expect(row.getByRole('button', { name: 'Deactivate', exact: true })).toBeVisible()
  // The created account exists only in the disposable E2E database, which is removed.
})

test('incompatible dataset stays scoped on every newly connected ML screen', async ({ page }) => {
  test.setTimeout(120_000)
  await signIn(page, 'analyst')
  const token = await page.evaluate(() => localStorage.getItem('sem5_token') || '')
  const headers = { Authorization: 'Bearer ' + token }
  let id: string | undefined
  try {
    await page.goto('/datasets')
    await page.getByLabel('Dataset name').fill('ML incompatible student fixture')
    await page.getByLabel('Dataset file').setInputFiles({ name: 'students.csv', mimeType: 'text/csv',
      buffer: Buffer.from('student_id,marks\n1,80\n2,60\n') })
    const upload = page.waitForResponse(r => r.url().endsWith('/api/datasets/upload'))
    await page.getByRole('button', { name: 'Upload dataset', exact: true }).click()
    id = (await (await upload).json()).dataset_id
    await page.getByLabel('Active Dataset').selectOption(id!)
    for (const route of ['order-forecast', 'customer-segments', 'anomalies']) {
      await page.goto('/ml/' + route)
      await expect(page.getByRole('heading', { name: 'Not Applicable', exact: true })).toBeVisible()
    }
    await page.goto('/ml/sales-prediction')
    await page.getByLabel('Purchase month', { exact: true }).fill('1')
    await page.getByLabel('Purchase weekday (Monday = 0)', { exact: true }).fill('0')
    await page.getByLabel('Purchase hour', { exact: true }).fill('12')
    await page.getByLabel('Basket item count', { exact: true }).fill('1')
    await page.getByLabel('Customer state', { exact: true }).fill('SP')
    await page.getByLabel('Product category', { exact: true }).fill('books')
    const response = page.waitForResponse(r => r.url().includes('/api/ml/predict/sales?'))
    await page.getByRole('button', { name: 'Predict item revenue' }).click()
    const result = await (await response).json()
    expect(result.status).toBe('not_applicable')
    expect(result.dataset_id).toBe(id)
    await expect(page.getByRole('heading', { name: 'Not Applicable', exact: true })).toBeVisible()
    await expect(page.getByRole('status', { name: 'Sales prediction result' })).toHaveCount(0)
  } finally {
    const api = `http://localhost:${process.env.SEM5_E2E_BACKEND_PORT || '8000'}`
    if (id) await page.request.delete(`${api}/api/datasets/${id}`, { headers })
    const list = await (await page.request.get(`${api}/api/datasets`, { headers })).json()
    const reference = list.datasets.find((ds: { read_only: boolean }) => ds.read_only)
    if (reference) await page.request.post(`${api}/api/datasets/${reference.dataset_id}/select`, { headers })
  }
})

test('schema confirmation, invalid uploads and deletion use authoritative dataset state', async ({ page }) => {
  await signIn(page, 'analyst')
  await page.getByRole('link', { name: 'Dataset Manager' }).click()
  await page.getByLabel('Dataset name').fill('Connectivity schema fixture')
  await page.getByLabel('Dataset file').setInputFiles({ name: 'schema.csv', mimeType: 'text/csv',
    buffer: Buffer.from('date,order_id,revenue\n2025-01-01,o1,100\n2025-01-02,o2,200\n') })
  const upload = page.waitForResponse(r => r.url().endsWith('/api/datasets/upload'))
  await page.getByRole('button', { name: 'Upload dataset', exact: true }).click()
  const dataset = await (await upload).json()
  expect(dataset.status).toBe('READY')
  await page.getByLabel('Currency', { exact: true }).selectOption('BRL')
  await page.getByLabel('Dataset domain', { exact: true }).selectOption('commerce')
  const schema = page.waitForResponse(r => r.url().endsWith(`/api/datasets/${dataset.dataset_id}/schema`))
  await page.getByRole('button', { name: 'Confirm schema', exact: true }).click()
  expect((await schema).status()).toBe(200)
  await expect(page.getByText('Schema confirmed.', { exact: true })).toBeVisible()
  const deletion = page.waitForResponse(r => r.url().endsWith(`/api/datasets/${dataset.dataset_id}`) && r.request().method() === 'DELETE')
  await page.getByRole('row').filter({ hasText: 'Connectivity schema fixture' }).getByRole('button', { name: 'Delete', exact: true }).click()
  expect((await deletion).status()).toBe(204)
  await expect(page.getByRole('row').filter({ hasText: 'Connectivity schema fixture' })).toHaveCount(0)
  await page.getByLabel('Dataset name').fill('Invalid connectivity fixture')
  await page.getByLabel('Dataset file').setInputFiles({ name: 'invalid.csv', mimeType: 'text/csv', buffer: Buffer.from('x,x\n1,2\n') })
  const invalid = page.waitForResponse(r => r.url().endsWith('/api/datasets/upload'))
  await page.getByRole('button', { name: 'Upload dataset', exact: true }).click()
  expect((await invalid).status()).toBe(201)
  await expect(page.getByRole('alert')).toContainText('Duplicate column')
  await expect(page.getByRole('row').filter({ hasText: 'Invalid connectivity fixture' })).toContainText('FAILED')
})
