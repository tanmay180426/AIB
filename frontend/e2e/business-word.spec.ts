import { expect, test } from '@playwright/test'
import fs from 'node:fs/promises'
import { execFileSync } from 'node:child_process'

const api=`http://127.0.0.1:${process.env.SEM5_E2E_BACKEND_PORT || '8000'}`

test('real filtered business Word download contains scoped figures and embedded charts while CSV survives',async({page},info)=>{
  test.setTimeout(120000)
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
  await page.goto('/login');await page.getByLabel('Username').fill('analyst');await page.getByLabel('Password').fill('abi_test_analyst_only')
  await page.getByRole('button',{name:'Sign in',exact:true}).click();await expect(page).toHaveURL(/dashboard/)
  const token=await page.evaluate(()=>localStorage.getItem('sem5_token'))
  const uploaded=await page.request.post(api+'/api/datasets/upload',{headers:{Authorization:'Bearer '+token},multipart:{
    name:'Synthetic Word scope fixture',file:{name:'sales.csv',mimeType:'text/csv',buffer:Buffer.from('date,order_id,region,revenue,status\n2025-01-01,a,Pune,200,delivered\n2025-01-02,b,Delhi,800,canceled\n')}}})
  expect(uploaded.status()).toBe(201);const dataset=await uploaded.json()
  await page.reload();await page.getByLabel('Active Dataset',{exact:true}).selectOption(dataset.dataset_id)
  await page.goto('/reports?date_from=2025-01-01&date_to=2025-01-01')
  await expect(page.getByRole('button',{name:'Monthly Revenue',exact:false})).toBeVisible()
  const downloaded=page.waitForEvent('download'),response=page.waitForResponse(r=>r.url().includes('/api/reports/business-sales.docx'))
  await page.getByRole('button',{name:'Generate Business Sales Report (.docx)',exact:true}).click()
  const http=await response;expect(http.status()).toBe(200);expect(http.headers()['content-type']).toContain('wordprocessingml.document')
  const file=await downloaded;expect(file.suggestedFilename()).toBe('business-sales-analysis.docx')
  const saved=info.outputPath('sales-analysis.docx');await file.saveAs(saved)
  const content=await fs.readFile(saved);expect(content.subarray(0,4).equals(Buffer.from([80,75,3,4]))).toBe(true)
  const inspect='import sys,json,zipfile,xml.etree.ElementTree as E;z=zipfile.ZipFile(sys.argv[1]);assert z.testzip() is None;r=E.fromstring(z.read("word/document.xml"));t=" ".join(r.itertext());print(json.dumps({"text":t,"images":len([n for n in z.namelist() if n.startswith("word/media/")])}))'
  const parsed=JSON.parse(execFileSync(process.env.SEM5_PYTHON || 'python',['-c',inspect,saved],{encoding:'utf8'}))
  expect(parsed.text).toContain('Business Sales Analysis Report');expect(parsed.text).toContain('Synthetic Word scope fixture')
  expect(parsed.text).toContain('200');expect(parsed.text).not.toContain('1,000');expect(parsed.text).toContain('Forecast unavailable')
  expect(parsed.images).toBeGreaterThanOrEqual(4)
  expect(parsed.text).not.toContain(dataset.dataset_id)
  await expect(page.getByText(/Downloaded business-sales-analysis.docx/)).toBeVisible()
  const csvDownload=page.waitForEvent('download');await page.getByRole('button',{name:'Monthly Revenue',exact:false}).click()
  const csv=await csvDownload;const csvPath=info.outputPath('monthly-revenue.csv');await csv.saveAs(csvPath)
  const csvText=await fs.readFile(csvPath,'utf8');expect(csvText).toContain('200');expect(csvText).not.toContain('800')
  await page.goto('/dashboard');await expect(page.getByText('Total revenue',{exact:true}).locator('..')).toContainText('1,000')
  expect(errors).toEqual([])
})
