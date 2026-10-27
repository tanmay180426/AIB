import { expect, test } from '@playwright/test'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'

const api = `http://localhost:${process.env.SEM5_E2E_BACKEND_PORT || '8000'}`
const sales = 'date,order_id,region,revenue\n2025-01-01,a,Pune,200\n2025-01-02,b,Delhi,800\n'
const items = 'order_id,product_id,price\na,x,30\na,y,70\nb,z,90\n'
const customers = 'customer_id,city\nc1,Pune\nc2,Delhi\n'

// Small stored ZIP fixture: no archive dependency and no private files.
function zipFixture(files: Record<string, string>) {
  const locals: Buffer[] = [], central: Buffer[] = []; let offset = 0
  for (const [filename, text] of Object.entries(files)) {
    const name = Buffer.from(filename), data = Buffer.from(text)
    let crc = 0xffffffff
    for (const byte of data) { crc ^= byte; for (let i = 0; i < 8; i++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0) }
    crc = (crc ^ 0xffffffff) >>> 0
    const local = Buffer.alloc(30); local.writeUInt32LE(0x04034b50); local.writeUInt16LE(20,4); local.writeUInt32LE(crc,14); local.writeUInt32LE(data.length,18); local.writeUInt32LE(data.length,22); local.writeUInt16LE(name.length,26)
    locals.push(local,name,data)
    const entry = Buffer.alloc(46); entry.writeUInt32LE(0x02014b50); entry.writeUInt16LE(20,4); entry.writeUInt16LE(20,6); entry.writeUInt32LE(crc,16); entry.writeUInt32LE(data.length,20); entry.writeUInt32LE(data.length,24); entry.writeUInt16LE(name.length,28); entry.writeUInt32LE(offset,42)
    central.push(entry,name); offset += local.length + name.length + data.length
  }
  const directory = Buffer.concat(central), end = Buffer.alloc(22)
  end.writeUInt32LE(0x06054b50); end.writeUInt16LE(Object.keys(files).length,8); end.writeUInt16LE(Object.keys(files).length,10); end.writeUInt32LE(directory.length,12); end.writeUInt32LE(offset,16)
  return Buffer.concat([...locals,directory,end])
}

test('real folder picker, tables, dashboard, filters, switching, exports and ZIP recovery', async ({ page }, testInfo) => {
  test.setTimeout(180000)
  const folder = await fs.mkdtemp(path.join(os.tmpdir(),'sem5-bundle-e2e-'))
  const singleName = `Single-file browser regression ${Date.now()}`
  await fs.mkdir(path.join(folder,'nested'))
  await fs.writeFile(path.join(folder,'orders.csv'), sales)
  await fs.writeFile(path.join(folder,'nested','items.csv'), items)
  await fs.writeFile(path.join(folder,'customers.csv'), customers)
  await page.goto('/login')
  await page.getByLabel('Username').fill('analyst'); await page.getByLabel('Password').fill('abi_test_analyst_only')
  await page.getByRole('button',{name:'Sign in'}).click()
  await expect(page).toHaveURL(/dashboard/)
  await page.getByRole('link',{name:'Dataset Manager',exact:true}).click()
  await expect(page.getByRole('button',{name:'Upload Folder'})).toBeEnabled()
  await page.getByLabel('Dataset folder').setInputFiles(folder)
  await expect(page.getByText(/3 files/)).toBeVisible()
  await page.getByLabel('Bundle name').fill('Synthetic folder browser verification')
  const response = page.waitForResponse(r => r.url().endsWith('/api/datasets/bundles/upload') && r.request().method()==='POST')
  await page.getByRole('button',{name:'Confirm bundle import'}).click()
  const result = await (await response).json(); expect(result.status).toBe('READY'); expect(result.tables).toHaveLength(3)
  await expect(page.getByText('Imported 3 separate tables.',{exact:false})).toBeVisible()
  await expect(page.getByText(/Cross-table analytics are not supported/)).toBeVisible()
  const orders = result.tables.find((t: { relative_path:string }) => t.relative_path.endsWith('/orders.csv'))
  const customerTable = result.tables.find((t: { relative_path:string }) => t.relative_path.endsWith('/customers.csv'))
  await page.getByRole('button',{name:'Inspect table'}).nth(2).click()
  await expect(page.getByText('Data preview · first 20 rows')).toBeVisible()
  await expect(page.getByRole('button',{name:'Confirm schema'})).toBeVisible()
  await page.getByLabel('Active Dataset').selectOption(result.dataset_id)
  await expect(page.getByLabel('Active Table')).toBeVisible()
  await page.getByLabel('Active Table').selectOption(orders.dataset_id)
  await page.getByRole('link',{name:'Dashboard',exact:true}).click()
  await expect(page.getByText('Total revenue',{exact:true})).toBeVisible()
  await expect(page.getByText('1,000',{exact:true}).first()).toBeVisible()
  const filteredResponse = page.waitForResponse(r => r.url().includes('/api/analytics/overview?') && r.url().includes('column_filters='))
  await page.getByLabel('Filter region').selectOption('Pune')
  const filteredData = await (await filteredResponse).json()
  expect(filteredData.time_series.reduce((sum: number, point: { revenue: number }) => sum + point.revenue, 0)).toBe(200)
  expect(filteredData.distributions.find((d: { field: string }) => d.field === 'region').series).toEqual([{ label: 'Pune', rows: 1, amount: 200 }])
  await expect(page.getByText('Total revenue',{exact:true}).locator('..')).toContainText('200')
  await page.getByRole('button',{name:'Reset',exact:true}).click()
  await expect(page.getByText('1,000',{exact:true}).first()).toBeVisible()
  await page.screenshot({path:testInfo.outputPath('dashboard-desktop.png'),fullPage:true})
  await page.setViewportSize({width:390,height:844})
  await expect(page.getByRole('heading',{name:'Dashboard',exact:true})).toBeVisible()
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({path:testInfo.outputPath('dashboard-mobile.png'),fullPage:true})
  await page.setViewportSize({width:1280,height:900})
  const token = await page.evaluate(() => localStorage.getItem('sem5_token') || '')
  const csv = await page.request.get(`${api}/api/reports/export?report=dataset_rows&column_filters=${encodeURIComponent('{"region":"Pune"}')}`,{headers:{Authorization:`Bearer ${token}`,'X-Dataset-ID':orders.dataset_id}})
  expect(csv.status()).toBe(200); expect(await csv.text()).not.toContain('Delhi')
  await page.getByLabel('Active Table').selectOption(customerTable.dataset_id)
  await expect(page.getByText(/Revenue unavailable/)).toBeVisible()
  await expect(page.getByText('Total revenue',{exact:true})).toHaveCount(0)
  await expect(page.getByLabel('Filter region')).toHaveCount(0)
  await page.getByRole('link',{name:'Dataset Manager',exact:true}).click()
  await page.getByLabel('Dataset ZIP').setInputFiles({name:'invalid.zip',mimeType:'application/zip',buffer:zipFixture({'bad.csv':'a,b\n1,2,3'})})
  await expect(page.getByText(/1 CSV tables/)).toBeVisible()
  await page.getByRole('button',{name:'Confirm bundle import'}).click()
  await expect(page.getByRole('alert')).toContainText('Nothing was imported')
  await page.getByLabel('Dataset ZIP').setInputFiles({name:'valid.zip',mimeType:'application/zip',buffer:zipFixture({'one.csv':sales,'nested/two.csv':items})})
  await expect(page.getByText(/2 CSV tables/)).toBeVisible()
  await page.getByRole('button',{name:'Confirm bundle import'}).click()
  await expect(page.getByText(/Imported 2 separate tables/)).toBeVisible()
  const adminLogin = await page.request.post(`${api}/api/auth/login`,{form:{username:'admin',password:'abi_test_admin_only'}})
  const adminToken=(await adminLogin.json()).access_token
  expect((await page.request.get(`${api}/api/datasets/${orders.dataset_id}`,{headers:{Authorization:`Bearer ${adminToken}`}})).status()).toBe(403)
  await page.getByLabel('Dataset name').fill(singleName)
  await page.getByLabel('Dataset file').setInputFiles({name:'single.csv',mimeType:'text/csv',buffer:Buffer.from(sales)})
  await page.getByRole('button',{name:'Upload dataset',exact:true}).click()
  await expect(page.getByRole('row').filter({hasText:singleName})).toContainText('READY')
  await testInfo.attach('synthetic-folder-location',{body:folder,contentType:'text/plain'})
})

test('Admin ZIP bundle ownership and confirmed cascading deletion, with local manual fixture', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Username').fill('admin'); await page.getByLabel('Password').fill('abi_test_admin_only')
  await page.getByRole('button',{name:'Sign in'}).click()
  await page.getByRole('link',{name:'Dataset Manager',exact:true}).click()
  await page.getByLabel('Dataset ZIP').setInputFiles({name:'admin.zip',mimeType:'application/zip',buffer:zipFixture({'orders.csv':sales,'customers.csv':customers})})
  await expect(page.getByText(/2 CSV tables/)).toBeVisible()
  await page.getByLabel('Bundle name').fill('Admin bundle deletion verification')
  const response=page.waitForResponse(r=>r.url().endsWith('/api/datasets/bundles/zip') && r.request().method()==='POST')
  await page.getByRole('button',{name:'Confirm bundle import'}).click()
  const bundle=await(await response).json()
  await expect(page.getByText(/Imported 2 separate tables/)).toBeVisible()
  const row=page.getByRole('row').filter({hasText:'Admin bundle deletion verification'})
  page.once('dialog',async dialog=>{expect(dialog.message()).toContain('all 2 tables');await dialog.dismiss()})
  await row.getByRole('button',{name:'Delete',exact:true}).click()
  await expect(row).toBeVisible()
  page.once('dialog',async dialog=>{expect(dialog.message()).toContain('all 2 tables');await dialog.accept()})
  await row.getByRole('button',{name:'Delete',exact:true}).click()
  await expect(row).toHaveCount(0)
  const token=await page.evaluate(()=>localStorage.getItem('sem5_token')||'')
  for(const child of bundle.tables) expect((await page.request.get(`${api}/api/datasets/${child.dataset_id}`,{headers:{Authorization:`Bearer ${token}`}})).status()).toBe(404)
  await page.getByLabel('Dataset name').fill('Admin synthetic manual verification')
  await page.getByLabel('Dataset file').setInputFiles({name:'manual.csv',mimeType:'text/csv',buffer:Buffer.from(sales)})
  const uploaded=page.waitForResponse(r=>r.url().endsWith('/api/datasets/upload') && r.request().method()==='POST')
  await page.getByRole('button',{name:'Upload dataset',exact:true}).click()
  const ds=await(await uploaded).json()
  await page.getByLabel('Active Dataset').selectOption(ds.dataset_id)
  await page.getByRole('link',{name:'Dashboard',exact:true}).click()
  await expect(page.getByText('1,000',{exact:true}).first()).toBeVisible()
})
