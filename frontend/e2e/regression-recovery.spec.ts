import { expect, test } from '@playwright/test'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'

const api=`http://localhost:${process.env.SEM5_E2E_BACKEND_PORT || '8000'}`
test.afterEach(async({page},info)=>{if(info.status!==info.expectedStatus)await page.screenshot({path:info.outputPath('failure.png'),fullPage:true}).catch(()=>{})})
async function login(page: import('@playwright/test').Page, role='admin') {
  await page.goto('/login');await page.getByLabel('Username').fill(role);await page.getByLabel('Password').fill(role+'123')
  await page.getByRole('button',{name:'Sign in',exact:true}).click();await expect(page).toHaveURL(/dashboard/)
}

test('invalid restored refresh session clears private state and returns to sign-in',async({page},info)=>{
  await login(page)
  await page.goto('/datasets')
  await expect(page.getByText(/Upload 200.00 MiB/)).toBeVisible()
  const statuses: {path:string;status:number}[]=[]
  page.on('response',r=>{if(r.url().startsWith(api)&&['/api/datasets','/api/auth/refresh'].includes(new URL(r.url()).pathname))statuses.push({path:new URL(r.url()).pathname,status:r.status()})})
  await page.evaluate(()=>{localStorage.setItem('sem5_token','invalid-access');localStorage.setItem('sem5_refresh','invalid-refresh')})
  await page.reload()
  await expect(page).toHaveURL(/\/login/)
  expect(await page.evaluate(()=>['sem5_token','sem5_refresh','sem5_user'].every(key=>localStorage.getItem(key)===null))).toBe(true)
  await expect(page.getByLabel('Active Dataset')).toHaveCount(0)
  expect(statuses).toContainEqual({path:'/api/datasets',status:401})
  expect(statuses.filter(r=>r.path==='/api/auth/refresh'&&r.status===401).length).toBe(1)
  await login(page,'analyst')
  const token=await page.evaluate(()=>localStorage.getItem('sem5_token'))
  expect((await page.request.get(api+'/api/admin/system/status',{headers:{Authorization:`Bearer ${token}`}})).status()).toBe(403)
  await info.attach('sanitized-auth-statuses',{body:JSON.stringify(statuses),contentType:'application/json'})
})

test('nested duplicate folder selection is explicit, uploads with refresh once and preserves activation',async({page},info)=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'sem5-recovery-'))
  for(const child of ['current','backup/current']){
    await fs.mkdir(path.join(dir,child),{recursive:true})
    await fs.writeFile(path.join(dir,child,'orders.csv'),'date,order_id,revenue\n2025-01-01,o1,100\n2025-01-02,o2,200\n')
    await fs.writeFile(path.join(dir,child,'items.csv'),'order_id,product_id,price\no1,p1,100\no2,p2,200\n')
  }
  await login(page)
  await page.getByRole('link',{name:'Dataset Manager',exact:true}).click()
  const original=await page.getByLabel('Active Dataset',{exact:true}).inputValue()
  await page.getByLabel('Dataset folder',{exact:true}).setInputFiles(dir)
  await expect(page.getByText(/Repeated CSV filenames/)).toBeVisible()
  await page.getByLabel('CSV folder to import',{exact:true}).selectOption(path.basename(dir)+'/current')
  await expect(page.getByText(/2 files ·/)).toBeVisible()
  await expect(page.getByText(/2 files excluded by your folder choice/)).toBeVisible()
  await expect(page.getByLabel('Bundle name')).toHaveValue('current')
  await page.getByLabel('Bundle name').fill(`Recovery scoped ${Date.now()}`)
  const statuses:number[]=[];let refreshes=0
  page.on('response',r=>{if(r.url().endsWith('/api/datasets/bundles/upload'))statuses.push(r.status());if(r.url().endsWith('/api/auth/refresh'))refreshes++})
  await page.evaluate(()=>localStorage.setItem('sem5_token','expired-access'))
  const uploaded=page.waitForResponse(r=>r.url().endsWith('/api/datasets/bundles/upload')&&r.status()===201)
  await page.getByRole('button',{name:'Confirm bundle import'}).dblclick()
  const bundle=await(await uploaded).json()
  expect(bundle.tables).toHaveLength(2)
  expect(bundle.tables.every((t:{relative_path:string})=>t.relative_path.includes('/current/')&&!t.relative_path.includes('/backup/'))).toBe(true)
  await expect(page.getByText(/Imported 2 separate tables/)).toBeVisible()
  await expect(page.getByLabel('Active Dataset',{exact:true})).toHaveValue(original)
  expect(statuses).toEqual([401,201]);expect(refreshes).toBe(1)
  await expect(page.getByRole('button',{name:'Inspect table',exact:true})).toHaveCount(2)
  await page.getByRole('button',{name:'Inspect table',exact:true}).first().click()
  await expect(page.getByText('Data preview · first 20 rows')).toBeVisible()
  await page.reload();await expect(page.getByRole('heading',{name:'Dataset Manager',exact:true})).toBeVisible()
  await expect(page.getByRole('row').filter({hasText:bundle.dataset_name})).toContainText('READY')
  await info.attach('folder-result',{body:JSON.stringify({selected_files:4,imported_tables:2,excluded_files:2,statuses,refreshes,active_unchanged:true,paths:bundle.tables.map((t:{relative_path:string})=>t.relative_path)}),contentType:'application/json'})
})

test('Admin folder import drives executive BI, real ML and export before isolated Analyst login',async({page},info)=>{
  test.setTimeout(240000)
  const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text())})
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'sem5-recovery-olist-'))
  const files:Record<string,string>={orders:'order_id,customer_id,order_status,order_purchase_timestamp,order_delivered_customer_date,order_estimated_delivery_date\n',items:'order_id,order_item_id,product_id,seller_id,price,freight_value\n',payments:'order_id,payment_sequential,payment_type,payment_value\n',reviews:'order_id,review_id,review_score\n',customers:'customer_id,customer_unique_id,customer_state\nc0,u0,SP\nc1,u1,RJ\n',products:'product_id,product_category_name,product_weight_g\np1,books,100\np2,office,200\n',sellers:'seller_id,seller_state\ns1,SP\ns2,RJ\n',geolocation:'geolocation_zip_code_prefix,geolocation_lat,geolocation_lng\n01000,-1,-2\n',translation:'product_category_name,product_category_name_english\nbooks,Books\noffice,Office\n'}
  for(let i=0;i<40;i++){
    const day=(offset:number)=>new Date(Date.UTC(2025,0,1+i+offset)).toISOString().slice(0,10)
    files.orders+=`o${i},c${i%2},delivered,${day(0)},${day(i<20?9:2)},${day(5)}\n`
    files.items+=`o${i},1,p1,${i<20?'s1':'s2'},${i===0?30:90},10\n`
    files.payments+=`o${i},1,credit_card,${i===0?40:90}\n`;files.reviews+=`o${i},r${i},5\n`
  }
  files.items+='o0,2,p2,s2,70,5\n';files.payments+='o0,2,voucher,60\n'
  await fs.mkdir(path.join(dir,'current'))
  for(const [name,content] of Object.entries(files))await fs.writeFile(path.join(dir,'current',name+'.csv'),content)
  await login(page)
  await page.getByRole('link',{name:'Dataset Manager',exact:true}).click()
  const activeBefore=await page.getByLabel('Active Dataset',{exact:true}).inputValue()
  const chooser=page.waitForEvent('filechooser')
  await page.getByRole('button',{name:'Upload Folder',exact:true}).click()
  const picker=await chooser;expect(picker.isMultiple()).toBe(true);await picker.setFiles(dir)
  const name=`Recovery admin Olist ${Date.now()}`
  await page.getByLabel('Bundle name').fill(name)
  const uploaded=page.waitForResponse(r=>r.url().endsWith('/api/datasets/bundles/upload')&&r.status()===201)
  await page.getByRole('button',{name:'Confirm bundle import'}).click();const bundle=await(await uploaded).json()
  expect(bundle.tables).toHaveLength(9)
  await expect(page.getByText(/Imported 9 separate tables/)).toBeVisible()
  await expect(page.getByLabel('Active Dataset',{exact:true})).toHaveValue(activeBefore)
  for(let index=0;index<9;index++){
    await page.getByRole('button',{name:'Inspect table',exact:true}).nth(index).click()
    await expect(page.getByRole('heading',{name:'Data preview · first 20 rows',exact:true})).toHaveCount(1)
    await expect(page.getByRole('heading',{name:'Data preview · first 20 rows',exact:true})).toBeVisible()
    await page.getByRole('button',{name:'Back to bundle',exact:true}).click()
  }
  await page.getByLabel('Currency',{exact:true}).selectOption('BRL');await page.getByLabel('Dataset domain',{exact:true}).selectOption('commerce')
  await page.getByRole('button',{name:'Confirm schema',exact:true}).click();await expect(page.getByText('Schema confirmed.')).toBeVisible()
  await page.getByRole('link',{name:'Open bundle Dashboard',exact:true}).click()
  await expect(page.getByText('Item revenue',{exact:true}).locator('..')).toContainText('3,610')
  await expect(page.getByText('Distinct orders',{exact:true}).locator('..')).toContainText('40')
  await expect(page.getByRole('heading',{name:'Observed order volume',exact:true})).toBeVisible()
  await expect(page.getByRole('heading',{name:'Product performance highlights',exact:true})).toBeVisible()
  await expect(page.getByLabel('Order status shares')).toContainText('100.00%')
  await expect(page.getByLabel('customers business evidence')).toContainText('Repeat customer rate (%)')
  await expect(page.getByLabel('sellers business evidence')).toContainText('Eligible completed orders')
  await page.getByLabel('Date To',{exact:true}).fill('2025-01-01')
  await expect(page.getByText('Item revenue',{exact:true}).locator('..')).toContainText('100')
  await page.getByRole('button',{name:'Reset',exact:true}).click()
  await expect(page.getByText('Item revenue',{exact:true}).locator('..')).toContainText('3,610')
  await page.getByRole('button',{name:'Load 7-day model outlook'}).click()
  await expect(page.getByText(/last actual 2025-02-09/).first()).toBeVisible()
  await page.screenshot({path:info.outputPath('executive-dashboard.png'),fullPage:true})
  for(const route of ['customers','products','delivery','sellers']){
    await page.goto('/analytics/'+route);await expect(page.locator('.recharts-surface').first()).toBeVisible()
  }
  const forecast=page.waitForResponse(r=>r.url().includes('/api/ml/forecast?')&&r.url().includes('target=orders'))
  await page.goto('/ml/metrics');expect((await(await forecast).json()).status).toBe('available')
  await expect(page.getByTestId('forecast-chart')).toHaveAttribute('data-forecast-points','365')
  await page.getByLabel('Forecast horizon').selectOption('30')
  await expect(page.getByTestId('forecast-chart')).toHaveAttribute('data-forecast-points','30')
  await page.goto('/reports')
  const exported=page.waitForResponse(r=>r.url().includes('report=kpis'))
  await page.getByRole('button',{name:/KPIs/}).click();expect((await exported).status()).toBe(200)
  await page.reload();await expect(page.getByRole('heading',{name:'Reports',exact:true})).toBeVisible()
  await page.getByRole('button',{name:'Sign out',exact:true}).click();await expect(page).toHaveURL(/login/)
  await login(page,'analyst')
  await expect(page.getByLabel('Active Dataset',{exact:true}).locator('option').filter({hasText:name})).toHaveCount(0)
  const token=await page.evaluate(()=>localStorage.getItem('sem5_token'))
  const auth={Authorization:`Bearer ${token}`}
  expect((await page.request.get(api+`/api/datasets/${bundle.dataset_id}`,{headers:auth})).status()).toBe(403)
  expect((await page.request.get(api+'/api/admin/system/status',{headers:auth})).status()).toBe(403)
  await page.goto('/datasets');await expect(page.getByRole('heading',{name:'Dataset Manager',exact:true})).toBeVisible()
  expect(errors).toEqual([])
  await info.attach('workflow-results',{body:JSON.stringify({tables:bundle.tables.length,orders:40,item_revenue:3610,private_access:403,admin_access:403,errors}),contentType:'application/json'})
})
