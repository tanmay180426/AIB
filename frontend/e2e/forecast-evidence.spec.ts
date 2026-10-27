import { expect, test } from '@playwright/test'

const api = `http://localhost:${process.env.SEM5_E2E_BACKEND_PORT || '8000'}`

test('real models render dated actual/future lines, evidence and scoped horizon changes', async ({ page }, info) => {
  test.setTimeout(240000)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/login')
  await page.getByLabel('Username').fill('analyst')
  await page.getByLabel('Password').fill('abi_test_analyst_only')
  await page.getByRole('button', { name:'Sign in', exact:true }).click()
  await expect(page).toHaveURL(/dashboard/)
  const files: Record<string,string> = {
    orders:'order_id,customer_id,order_status,order_purchase_timestamp,order_delivered_customer_date,order_estimated_delivery_date\n',
    items:'order_id,order_item_id,product_id,seller_id,price\n',
    customers:'customer_id,customer_unique_id,customer_state\n',
    products:'product_id,product_category_name,product_weight_g\np1,books,100\np2,office,200\n',
    sellers:'seller_id,seller_state\ns1,SP\ns2,RJ\n',
  }
  for(let i=0;i<45;i++) {
    const day=(offset:number)=>new Date(Date.UTC(2025,0,1+i+offset)).toISOString().slice(0,10)
    files.orders+=`o${i},c${i%40},delivered,${day(0)},${day(i<20?9:2)},${day(5)}\n`
    files.items+=`o${i},1,p1,${i<20?'s1':'s2'},${i<31?100:50}\n`
    if(i<40) files.customers+=`c${i},person${i},SP\n`
  }
  files.items+='o0,2,p2,s1,70\n'
  const dataset = await page.evaluate(async ({ files,api }) => {
    const form=new FormData(); form.append('name','Synthetic forecast evidence verification')
    for(const [name,value] of Object.entries(files)) { form.append('files',new Blob([value],{type:'text/csv'}),name+'.csv'); form.append('paths',name+'.csv') }
    const response=await fetch(api+'/api/datasets/bundles/upload',{method:'POST',headers:{Authorization:'Bearer '+localStorage.getItem('sem5_token')},body:form})
    if(response.status!==201)throw new Error(`Test bundle upload failed: ${response.status}`)
    return response.json()
  },{files,api})
  const token=await page.evaluate(()=>localStorage.getItem('sem5_token'))
  const headers={Authorization:`Bearer ${token}`,'X-Dataset-ID':dataset.dataset_id}
  expect((await page.request.patch(`${api}/api/datasets/${dataset.dataset_id}/schema`,{headers,data:{fields:{},currency_code:'BRL',domain:'commerce'}})).status()).toBe(200)
  await page.reload()
  await page.getByLabel('Active Dataset',{exact:true}).selectOption(dataset.dataset_id)
  await expect(page.getByText('Distinct orders',{exact:true}).locator('..')).toContainText('45')
  await expect(page.getByText('Item revenue',{exact:true}).locator('..')).toContainText('3,870')
  await expect(page.getByRole('heading',{name:'Investigate the recent revenue decline'})).toBeVisible()
  await page.screenshot({path:info.outputPath('dashboard-evidence.png'),fullPage:true})

  for(const target of ['orders','revenue']) {
    const response=page.waitForResponse(r=>r.url().includes('/api/ml/forecast?')&&r.url().includes(`target=${target}`))
    await page.goto(`/ml/${target==='orders'?'order':'revenue'}-forecast`)
    const annual=await(await response).json()
    expect(annual.forecast).toHaveLength(365)
    const short=page.waitForResponse(r=>r.url().includes('/api/ml/forecast?')&&r.url().includes('periods=30'))
    await page.getByLabel('Forecast horizon').selectOption('30')
    const actual=await(await short).json()
    expect(actual.status).toBe('available')
    const chart=page.getByTestId('forecast-chart')
    await expect(chart).toHaveAttribute('data-forecast-points','30')
    await expect(chart).toHaveAttribute('data-history-points',String(actual.historical_series.length))
    expect(actual.historical_series.length).toBeGreaterThan(30)
    await expect(chart).toHaveAttribute('data-history-end',actual.history_tail[29].date)
    await expect(chart).toHaveAttribute('data-forecast-start',actual.forecast[0].date)
    await expect(chart.locator('.recharts-line-curve')).toHaveCount(2)
    expect(await chart.locator('.recharts-line-curve').last().getAttribute('stroke-dasharray')).toBe('6 4')
    await expect(page.getByRole('table', {name:'Forecast data', exact:true}).locator('tbody tr').first()).toContainText(actual.forecast[0].date)
    await expect(page.getByRole('table', {name:'Forecast data', exact:true}).locator('tbody tr').first()).toContainText(actual.forecast[0][target].toLocaleString('en-US',{maximumFractionDigits:2}))
    await chart.locator('.recharts-line').first().locator('.recharts-dot').first().hover({force:true})
    await expect(chart.locator('.recharts-tooltip-wrapper')).toContainText(actual.historical_series[0].date)
    await expect(chart.locator('.recharts-tooltip-wrapper')).toContainText('Historical actual')
    const lastDot=chart.locator('.recharts-line').last().locator('.recharts-dot').last()
    await lastDot.hover({force:true})
    await expect(chart.locator('.recharts-tooltip-wrapper')).toContainText(actual.forecast[29].date)
    await expect(chart.locator('.recharts-tooltip-wrapper')).toContainText('Future forecast')
    const changed=page.waitForResponse(r=>r.url().includes('/api/ml/forecast?')&&r.url().includes('periods=7'))
    await page.getByLabel('Forecast horizon').selectOption('7')
    const seven=await(await changed).json()
    expect(seven.forecast).toHaveLength(7)
    await expect(chart).toHaveAttribute('data-forecast-points','7')
    await expect(page.getByRole('table', {name:'Forecast data', exact:true}).locator('tbody tr')).toHaveCount(7)
    await page.screenshot({path:info.outputPath(`${target}-forecast.png`),fullPage:true})
    await page.getByLabel('Forecast origin mode').selectOption('selected')
    await page.getByLabel('Date To',{exact:true}).fill('2025-02-05')
    await expect(chart).toHaveAttribute('data-history-end','2025-02-05')
  }
  await page.goto('/ml/order-forecast?date_from=2025-01-01&date_to=2025-01-31')
  await page.getByLabel('Forecast horizon').selectOption('30')
  await page.getByLabel('Forecast origin mode').selectOption('selected')
  const chart = page.getByTestId('forecast-chart')
  await expect(chart).toHaveAttribute('data-history-end','2025-01-31')
  await expect(page.getByLabel('Forecast quality')).toContainText('Candidate did not qualify for production.')
  await expect(page.getByLabel('Forecast quality')).toContainText('holdout / 14d')
  await expect(page.getByText(/Old data warning/)).toBeVisible()
  const laterResponse = page.waitForResponse(r => r.url().includes('/api/analytics/overview?') && r.url().includes('date_from=2025-02-01'))
  await page.getByLabel('Forecast origin mode').selectOption('historical')
  const later = await (await laterResponse).json()
  const laterSeries = later.time_series ?? later.revenue_series
  const comparison = page.getByRole('heading',{name:'Historical comparison · not independent validation'}).locator('..')
  await expect(comparison).toContainText('not certified out-of-sample')
  await expect(comparison.locator('tbody tr').first()).toContainText(laterSeries[0].period)
  await expect(comparison.locator('tbody tr').first().locator('td').nth(1)).toHaveText(String(laterSeries[0].orders))
  const latestResponse = page.waitForResponse(r => r.url().includes('/api/ml/forecast?') && !r.url().includes('date_to='))
  await page.getByLabel('Forecast origin mode').selectOption('latest')
  const latest = await (await latestResponse).json()
  expect(latest.forecast_origin).toBe('2025-02-14')
  expect(latest.horizon).toBe(30)
  expect(latest.frequency).toBe('daily')
  expect(latest.evaluation_status).toContain('unqualified')
  await expect(chart).toHaveAttribute('data-history-end', latest.forecast_origin)
  await expect(chart).toHaveAttribute('data-forecast-start', latest.forecast[0].date)
  await expect(page.getByText(/Latest-data mode removes date filters/)).toBeVisible()
  for(const [route,heading] of [['sales','Seasonal patterns in observed monthly revenue'],['customers','Customer retention signals'],['sellers','Seller Delivery Performance'],['delivery','Seller Delivery Performance'],['products','Highest-revenue products']]) {
    await page.goto('/analytics/'+route)
    await expect(page.getByRole('heading',{name:heading,exact:true})).toBeVisible()
    if(route==='customers') await expect(page.getByRole('heading',{name:'Investigate re-engagement opportunities'})).toBeVisible()
    if(route==='sellers') await expect(page.getByRole('heading',{name:'Review the highest observed delay group'})).toBeVisible()
    if(route==='products') await expect(page.locator('.recharts-scatter-symbol')).toHaveCount(2)
    await expect(page.getByText('Calculating selected-data evidence…')).toHaveCount(0)
    await page.screenshot({path:info.outputPath(`${route}-evidence.png`),fullPage:true})
  }
  await page.goto('/ml/customer-segments')
  await expect(page.getByRole('heading',{name:'Observed customers by trained segment'})).toBeVisible()
  await expect(page.locator('.recharts-bar')).toHaveCount(1)
  const anomalyResponse=page.waitForResponse(r=>r.url().includes('/api/ml/anomalies?'))
  await page.goto('/ml/anomalies')
  const anomalies=await(await anomalyResponse).json()
  expect(anomalies.status).toBe('available')
  if(anomalies.anomalies.length) {
    await expect(page.getByRole('heading',{name:'Observed anomaly timeline'})).toBeVisible()
    await expect(page.locator('.recharts-scatter-symbol')).toHaveCount(anomalies.anomalies.length)
  } else await expect(page.getByText('No anomalous days were returned for the selected filters.')).toBeVisible()
  await page.goto('/ml/metrics')
  await expect(page.getByTestId('forecast-chart')).toBeVisible()
  await page.getByLabel('Forecast target').selectOption('revenue')
  await expect(page.getByRole('heading',{name:'Revenue Forecast',exact:true})).toBeVisible()
  await expect(page.getByTestId('forecast-chart')).toHaveAttribute('data-forecast-points','365')
  await page.setViewportSize({width:390,height:844})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
  await page.screenshot({path:info.outputPath('metrics-mobile.png'),fullPage:true})
  const reference=await(await page.request.get(api+'/api/datasets',{headers})).json()
  const id=reference.datasets.find((d:{read_only:boolean})=>d.read_only).dataset_id
  await page.getByLabel('Active Dataset',{exact:true}).selectOption(id)
  await expect(page.locator('main p').filter({hasText:'Synthetic forecast evidence verification'})).toHaveCount(0)
  expect(errors).toEqual([])
  await info.attach('real-forecast-summary',{body:JSON.stringify({models:['sales_forecast_orders','sales_forecast_revenue'],dataset_id:dataset.dataset_id,orders:45,item_revenue:3870,pageerrors:errors}),contentType:'application/json'})
})
