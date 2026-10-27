import { test, expect } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'

test.afterEach(async ({page},testInfo)=>{
  if(testInfo.status!==testInfo.expectedStatus){
    await fs.writeFile(testInfo.outputPath('failure-page.txt'),await page.locator('body').innerText().catch(()=>''))
    await page.screenshot({path:testInfo.outputPath('failure-page.png'),fullPage:true}).catch(()=>{})
  }
})

test('Synthetic nine-table folder → reconciled Dashboard → real model inference', async ({ page }, testInfo) => {
  const folder=await fs.mkdtemp(path.join(os.tmpdir(),'sem5-olist-e2e-'))
  const orders=['order_id,customer_id,order_status,order_purchase_timestamp,order_delivered_customer_date']
  const items=['order_id,order_item_id,product_id,seller_id,price,freight_value']
  const payments=['order_id,payment_sequential,payment_type,payment_value']
  const reviews=['order_id,review_id,review_score']
  for(let i=0;i<40;i++){
    const day=new Date(Date.UTC(2025,0,1+i)).toISOString().slice(0,10)
    const delivered=new Date(Date.UTC(2025,0,4+i)).toISOString().slice(0,10)
    orders.push(`o${i},c${i%2},delivered,${day},${delivered}`)
    items.push(`o${i},1,p1,s1,${i===0?30:90},10`)
    payments.push(`o${i},1,credit_card,${i===0?40:90}`)
    reviews.push(`o${i},r${i},5`)
  }
  items.push('o0,2,p2,s2,70,5');payments.push('o0,2,voucher,60')
  const files:Record<string,string>={orders:orders.join('\n'),items:items.join('\n'),payments:payments.join('\n'),reviews:reviews.join('\n'),
    customers:'customer_id,customer_unique_id,customer_state\nc0,u0,SP\nc1,u1,RJ',products:'product_id,product_category_name,product_weight_g\np1,books,100\np2,office,200',
    sellers:'seller_id,seller_state\ns1,SP\ns2,RJ',geolocation:'geolocation_zip_code_prefix,geolocation_lat,geolocation_lng\n01000,-1,-2\n01000,-2,-3',translation:'product_category_name,product_category_name_english\nbooks,Books\noffice,Office'}
  await Promise.all(Object.entries(files).map(([name,content])=>fs.writeFile(path.join(folder,name+'.csv'),content+'\n')))
  await page.goto('/login');await page.getByLabel('Username').fill('analyst');await page.getByLabel('Password').fill('abi_test_analyst_only');await page.getByRole('button',{name:'Sign in'}).click()
  await page.getByRole('link',{name:'Dataset Manager',exact:true}).click()
  await expect(page.getByText(/Upload 200.00 MiB/)).toBeVisible()
  await page.getByLabel('Dataset folder').setInputFiles(folder)
  await page.getByRole('button',{name:'Confirm bundle import'}).click()
  await expect(page.getByText(/Imported 9 separate tables/)).toBeVisible()
  await page.getByLabel('Currency',{exact:true}).selectOption('BRL');await page.getByRole('button',{name:'Confirm schema'}).click()
  await page.getByRole('link',{name:'Open bundle Dashboard',exact:true}).click()
  await expect(page.getByText('Distinct orders',{exact:true}).locator('..')).toContainText('40')
  await expect(page.getByText('Item revenue',{exact:true}).locator('..')).toContainText('3,610')
  await page.getByLabel('Category',{exact:true}).selectOption('office')
  await expect(page.getByText('Item revenue',{exact:true}).locator('..')).toContainText('70')
  await expect(page.getByText('Distinct orders',{exact:true}).locator('..')).toContainText('1')
  await page.getByRole('button',{name:'Reset',exact:true}).click()
  await expect(page.getByText('Item revenue',{exact:true}).locator('..')).toContainText('3,610')
  await page.screenshot({path:testInfo.outputPath('olist-dashboard.png'),fullPage:true})
  await page.setViewportSize({width:390,height:844})
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
  await page.screenshot({path:testInfo.outputPath('olist-dashboard-mobile.png'),fullPage:true})
  await page.setViewportSize({width:1280,height:900})
  const prediction=page.waitForResponse(r=>r.url().includes('/api/ml/forecast?')&&r.url().includes('target=revenue'))
  await page.goto('/ml/revenue-forecast');const result=await(await prediction).json()
  expect(result.status).toBe('available');expect(result.forecast).toHaveLength(365);expect(result.forecast.every((p:{revenue:number})=>Number.isFinite(p.revenue))).toBe(true)
  await expect(page.getByRole('heading',{name:'Revenue Forecast',exact:true})).toBeVisible()
  await page.goto('/ml/metrics');await expect(page.getByText('Runtime: Loaded and serving contract validated',{exact:false}).first()).toBeVisible()
  await expect(page.getByText('Inactive source candidate:',{exact:false})).toBeVisible()
  // Leave synthetic files in their task-owned temporary folder for inspection.
  await testInfo.attach('model-result',{body:JSON.stringify(result),contentType:'application/json'})
})

test('Exact user ZIP imports every measured CSV and opens a real Dashboard', async ({ page }, testInfo) => {
  const archive=process.env.SEM5_OLIST_ARCHIVE
  test.skip(!archive,'Set SEM5_OLIST_ARCHIVE only for the explicitly supplied local archive.')
  test.setTimeout(1100000)
  await page.goto('/login');await page.getByLabel('Username').fill('admin');await page.getByLabel('Password').fill('abi_test_admin_only');await page.getByRole('button',{name:'Sign in'}).click()
  await page.getByRole('link',{name:'Dataset Manager',exact:true}).click()
  await page.getByLabel('Dataset ZIP').setInputFiles(archive!)
  await expect(page.getByText(/9 CSV tables/)).toBeVisible({timeout:60000})
  await expect(page.getByRole('button',{name:'Confirm bundle import'})).toBeEnabled()
  await page.getByLabel('Bundle name').fill('Olist 2016–2021 complete verification')
  const upload=page.waitForResponse(r=>r.url().endsWith('/api/datasets/bundles/zip')&&r.request().method()==='POST',{timeout:60000})
  await page.getByRole('button',{name:'Confirm bundle import'}).click()
  const initial=await(await upload).json();expect(initial.job_id).toBeTruthy()
  await expect(page.getByText(/Imported 9 separate tables/)).toBeVisible({timeout:1000000})
  const token=await page.evaluate(()=>localStorage.getItem('sem5_token'))
  const api=`http://localhost:${process.env.SEM5_E2E_BACKEND_PORT||'8000'}`
  const state=await(await page.request.get(`${api}/api/datasets/bundles/jobs/${initial.job_id}`,{headers:{Authorization:`Bearer ${token}`}})).json()
  expect(state.status).toBe('READY');expect(state.result.row_count).toBe(3028547);expect(state.result.tables).toHaveLength(9)
  const expected:Record<string,[number,number]>={olist_customers_dataset:[385650,5],olist_geolocation_dataset:[1000163,5],olist_order_items_dataset:[437572,7],olist_order_payments_dataset:[402457,5],olist_order_reviews_dataset:[380938,7],olist_orders_dataset:[385650,8],olist_products_dataset:[32951,9],olist_sellers_dataset:[3095,4],product_category_name_translation:[71,2]}
  for(const table of state.result.tables){const key=table.original_filename.replace(/\.csv$/,'');expect([table.row_count,table.column_count]).toEqual(expected[key])}
  await page.getByRole('link',{name:'Open bundle Dashboard',exact:true}).click()
  await expect(page.getByText('Distinct orders',{exact:true}).locator('..')).toContainText('385,650',{timeout:60000})
  await page.getByLabel('Order Status',{exact:true}).selectOption('delivered')
  await expect(page.getByText('Distinct orders',{exact:true})).toBeVisible()
  await page.getByRole('button',{name:'Reset',exact:true}).click()
  await page.screenshot({path:testInfo.outputPath('exact-archive-dashboard.png'),fullPage:true})
  await page.goto('/ml/metrics');await expect(page.getByRole('heading',{name:'ML Metrics',exact:true})).toBeVisible({timeout:60000})
  await testInfo.attach('complete-import',{body:JSON.stringify(state.result),contentType:'application/json'})
})

test('Complete persisted exact-archive bundle reconciles Dashboard and executes orders ML', async ({page},testInfo)=>{
  const ident=process.env.SEM5_VERIFIED_OLIST_ID
  test.skip(!ident,'Requires the complete previously browser-imported exact archive in the identified disposable database.')
  test.setTimeout(240000)
  await page.goto('/login');await page.getByLabel('Username').fill('admin');await page.getByLabel('Password').fill('abi_test_admin_only');await page.getByRole('button',{name:'Sign in'}).click()
  await page.getByLabel('Active Dataset').selectOption(ident!)
  await expect(page.getByText('Distinct orders',{exact:true}).locator('..')).toContainText('385,650',{timeout:90000})
  await expect(page.getByText('Item revenue',{exact:true}).locator('..')).toContainText('53,088,558.01')
  await expect(page.getByText('Unique customers',{exact:true}).locator('..')).toContainText('372,795')
  await page.getByLabel('Order Status',{exact:true}).selectOption('delivered')
  await expect(page.getByText('Distinct orders',{exact:true}).locator('..')).toContainText('371,293',{timeout:90000})
  await page.getByRole('button',{name:'Reset',exact:true}).click()
  await expect(page.getByText('Distinct orders',{exact:true}).locator('..')).toContainText('385,650',{timeout:90000})
  await page.screenshot({path:testInfo.outputPath('exact-archive-dashboard.png'),fullPage:true})
  const forecast=page.waitForResponse(r=>r.url().includes('/api/ml/forecast?')&&r.url().includes('target=orders'),{timeout:60000})
  await page.goto('/ml/order-forecast?date_from=2018-01-01&date_to=2018-01-31')
  const body=await(await forecast).json();expect(body.status).toBe('available');expect(body.dataset_id).toBe(ident);expect(body.forecast).toHaveLength(365)
  expect(body.forecast.every((p:{orders:number})=>Number.isFinite(p.orders))).toBe(true)
  await expect(page.getByRole('heading',{name:'Forecast Data Table'})).toBeVisible()
  await page.goto('/ml/metrics');await expect(page.getByText('Runtime: Loaded and serving contract validated',{exact:false}).first()).toBeVisible()
  await expect(page.getByText('Inactive source candidate:',{exact:false})).toBeVisible()
  await testInfo.attach('exact-archive-real-orders-forecast',{body:JSON.stringify(body),contentType:'application/json'})
})
