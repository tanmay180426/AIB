import { expect, test } from '@playwright/test'

const sales = 'date,product,category,region,quantity,price,revenue\n2025-01-01,Book,Books,Pune,2,100,200\n2025-01-02,Pen,Office,Delhi,4,200,800\n'
const students = 'student_id,name,department,marks,attendance,semester\n1,Ada,CS,80,90,5\n2,Ben,EE,60,70,5\n'
const apiBase = `http://localhost:${process.env.SEM5_E2E_BACKEND_PORT || '8000'}`

test('real upload, filters, chatbot, ML applicability, switching and filtered exports', async ({ page }) => {
  test.setTimeout(180_000)
  const ids: string[] = []
  const names = [`Sales A ${Date.now()}`, `Sales B ${Date.now()}`, `Students ${Date.now()}`]
  let token = ''
  let originalDatasetId: string | null = null
  try {
    await page.goto('/login')
    await page.getByLabel('Username').fill('analyst')
    await page.getByLabel('Password').fill('abi_test_analyst_only')
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page).toHaveURL(/\/dashboard/)
    token = await page.evaluate(() => localStorage.getItem('sem5_token') || '')
    originalDatasetId = (await (await page.request.get(`${apiBase}/api/datasets`, {
      headers: { Authorization: 'Bearer ' + token },
    })).json()).active_dataset_id
    await page.getByRole('link', { name: 'Dataset Manager' }).click()
    for (const [i, content] of [sales, sales.replace(',200\n', ',1000\n').replace(',800\n', ',4000\n'), students].entries()) {
      await page.getByLabel('Dataset name').fill(names[i])
      await page.getByLabel('Dataset file').setInputFiles({ name: `dataset${i}.csv`, mimeType: 'text/csv', buffer: Buffer.from(content) })
      const response = page.waitForResponse(r => r.url().endsWith('/api/datasets/upload') && r.request().method() === 'POST')
      await page.getByRole('button', { name: 'Upload dataset', exact: true }).click()
      const dataset = await (await response).json()
      expect(dataset.status).toBe('READY')
      ids.push(dataset.dataset_id)
      await expect(page.getByRole('row').filter({ hasText: names[i] })).toContainText('READY')
    }
    await page.getByLabel('Active Dataset').selectOption(ids[0])
    await page.getByRole('link', { name: 'Dashboard', exact: true }).click()
    await expect(page.getByText('Total revenue', { exact: true })).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText('1,000', { exact: true }).first()).toBeVisible()
    await page.getByLabel('Filter region').selectOption('Pune')
    await expect(page.getByText('Calculated from ' + names[0] + ' with the current filters.')).toBeVisible()
    await expect(page.locator('div').filter({ has: page.getByText('Total revenue', { exact: true }) }).filter({ hasText: '200' }).last()).toBeVisible()

    await page.getByRole('link', { name: 'Analytics', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Analytics', exact: true })).toBeVisible()
    await page.getByLabel('Filter region').selectOption('Pune')
    await page.getByRole('link', { name: 'Delivery', exact: true }).click()
    await expect(page.getByText('Not available for this dataset.', { exact: true })).toBeVisible()

    await page.getByRole('link', { name: 'Machine Learning', exact: true }).click()
    await expect(page.getByText('Not Applicable to active dataset').first()).toBeVisible()
    await page.getByRole('link', { name: 'Revenue Forecast', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Not Applicable', exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Reset', exact: true }).click()

    await page.getByRole('link', { name: 'AI Insights', exact: true }).click()
    await page.getByLabel('Question').fill('What is the total revenue?')
    await page.getByRole('button', { name: 'Ask', exact: true }).click()
    await expect(page.locator('pre')).toContainText('1,000.00')

    // Switch in place: old answer and filter values are discarded.
    await page.getByLabel('Active Dataset').selectOption(ids[1])
    await expect(page.locator('pre')).toHaveCount(0)
    await page.getByRole('button', { name: 'Ask', exact: true }).click()
    await expect(page.locator('pre')).toContainText('5,000.00')
    await expect(page.locator('pre')).not.toContainText('1,000.00')
    await page.getByLabel('Active Dataset').selectOption(ids[2])
    await expect(page.getByLabel('Filter department')).toBeVisible()
    await expect(page.getByLabel('Filter region')).toHaveCount(0)
    await page.getByLabel('Question').fill('What is the average marks?')
    await page.getByRole('button', { name: 'Ask', exact: true }).click()
    await expect(page.locator('pre')).toContainText('70.00')
    await page.getByLabel('Active Dataset').selectOption(ids[0])
    await page.getByLabel('Question').fill('What is the total revenue?')
    await page.getByRole('button', { name: 'Ask', exact: true }).click()
    await expect(page.locator('pre')).toContainText('1,000.00')

    await page.getByRole('link', { name: 'Reports', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Reports', exact: true })).toBeVisible()
    await page.getByLabel('Filter region').selectOption('Pune')
    const download = page.waitForEvent('download', { timeout: 15_000 }).catch(error => ({ error }))
    const exportResponse = page.waitForResponse(r => r.request().method() === 'GET' && r.url().includes('report=dataset_rows'))
    await page.getByRole('button', { name: /Dataset Rows/ }).click()
    expect((await exportResponse).status()).toBe(200)
    const file = await download
    if ('error' in file) throw file.error
    const stream = await file.createReadStream()
    expect(stream).not.toBeNull()
    const chunks: Buffer[] = []
    for await (const chunk of stream!) chunks.push(Buffer.from(chunk))
    const csv = Buffer.concat(chunks).toString('utf8')
    expect(csv).toContain('Pune')
    expect(csv).not.toContain('Delhi')
    expect(csv).not.toContain('4000')
    expect(csv).not.toContain('Ada')
  } catch (error) {
    console.log('Dataset workflow page:', await page.locator('main').innerText())
    throw error
  } finally {
    // Remove synthetic uploads and restore the registered reference selection.
    if (token) {
      const headers = { Authorization: `Bearer ${token}` }
      for (const id of ids) await page.request.delete(`${apiBase}/api/datasets/${id}`, { headers })
      const list = await (await page.request.get(`${apiBase}/api/datasets`, { headers })).json()
      const reference = list.datasets.find((d: { read_only: boolean }) => d.read_only)
      const restoreId = list.datasets.flatMap((ds: { dataset_id: string; tables?: { dataset_id: string }[] }) => ds.tables || [ds])
        .some((ds: { dataset_id: string }) => ds.dataset_id === originalDatasetId)
        ? originalDatasetId : reference?.dataset_id
      if (restoreId) await page.request.post(`${apiBase}/api/datasets/${restoreId}/select`, { headers })
    }
  }
})
