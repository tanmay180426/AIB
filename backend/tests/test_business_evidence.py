"""Independent hand-calculated transactional evidence and genuine forecasts."""
from datetime import date, timedelta
import pytest
from tests.test_datasets import isolated  # noqa: F401
from tests.test_olist_bundle import fixture, upload


def test_reference_warehouse_evidence_uses_existing_order_scope(client, analyst_auth):
    headers={**analyst_auth,'X-Dataset-ID':'00000000-0000-0000-0000-000000000001'}
    customers=client.get('/api/analytics/business?domain=customers',headers=headers)
    assert customers.status_code==200,customers.text
    assert [r['value'] for r in customers.json()['cards']]==[1,1,100]
    assert sum(r['first_time'] for r in customers.json()['series'])==10
    assert sum(r['returning'] for r in customers.json()['series'])==1430
    sellers=client.get('/api/analytics/business?domain=sellers',headers=headers)
    assert sellers.status_code==200,sellers.text
    assert [r['value'] for r in sellers.json()['cards']]==[45,0,100]
    assert sellers.json()['recommendations']==[]


def scoped(client, auth, data):
    response = upload(client, auth, data)
    assert response.status_code == 201, response.text
    return {**auth, 'X-Dataset-ID': response.json()['dataset_id']}


def test_customer_repeat_identity_first_purchase_revenue_and_privacy(isolated, analyst_auth):
    client, _ = isolated
    data = fixture(40)
    # Two transaction IDs represent the same person, not two people.
    data['customers.csv'] = b'customer_id,customer_unique_id,customer_state\nc0,same-person,SP\nc1,same-person,RJ\n'
    headers = scoped(client, analyst_auth, data)
    response = client.get('/api/analytics/business?domain=customers', headers=headers)
    assert response.status_code == 200, response.text
    body = response.json(); cards = {r['label']:r['value'] for r in body['cards']}
    assert cards == {'Observed customers':1, 'Repeat customers':1, 'Repeat customer rate (%)':100}
    assert body['frequency'] == [{'orders':40, 'customers':1}]
    assert sum(r['first_time'] for r in body['series']) == 100
    assert sum(r['returning'] for r in body['series']) == 39*90
    assert 'same-person' not in response.text and 'customer_id' not in response.text
    filtered = client.get('/api/analytics/business?domain=customers&date_from=2025-02-01', headers=headers).json()
    assert sum(r['first_time'] for r in filtered['series']) == 0
    assert sum(r['returning'] for r in filtered['series']) == 9*90
    assert filtered['forecast_supported'] is False


def test_revenue_equal_period_decline_and_no_payment_fanout(isolated, analyst_auth):
    client, _ = isolated; data = fixture(28)
    lines = ['order_id,order_item_id,product_id,seller_id,price,freight_value']
    lines += [f'o{i},1,p1,s1,{100 if i < 14 else 50},999' for i in range(28)]
    data['items.csv'] = ('\n'.join(lines)+'\n').encode()
    headers = scoped(client, analyst_auth, data)
    body = client.get('/api/analytics/business?domain=revenue', headers=headers).json()
    assert [c['value'] for c in body['cards']] == [1400,700]
    decline = body['recommendations'][0]
    assert decline['id'] == 'revenue-decline' and decline['evidence']['change_pct'] == -50
    assert body['recommendations'][1]['evidence']['total'] == 2100
    assert all('estimated_opportunity' not in r for r in body['recommendations'])
    assert all('caused' not in r['observation'].lower() for r in body['recommendations'])
    small = client.get('/api/analytics/business?domain=revenue&date_from=2025-01-20', headers=headers).json()
    assert not small['cards'] and not any(r['id']=='revenue-decline' for r in small['recommendations'])


def test_seller_eligibility_minimum_samples_and_no_item_multiplication(isolated, analyst_auth):
    client, _ = isolated; data = fixture(45)
    orders = ['order_id,customer_id,order_status,order_purchase_timestamp,order_delivered_customer_date,order_estimated_delivery_date']
    items = ['order_id,order_item_id,product_id,seller_id,price']
    for i in range(45):
        d=date(2025,1,1)+timedelta(days=i)
        # Seller A 20 late, seller B 20 on-time. Five ineligible rows.
        delivered = str(d+timedelta(days=9 if i<20 else 2))
        estimated = str(d+timedelta(days=5))
        status = 'delivered'
        if i==40: delivered=''
        if i==41: estimated=''
        if i==42: status='shipped'
        if i==43: delivered=str(d-timedelta(days=1))
        if i==44: estimated=str(d-timedelta(days=1))
        orders.append(f'o{i},c0,{status},{d},{delivered},{estimated}')
        seller='s1' if i<20 else 's2'
        items += [f'o{i},1,p1,{seller},10',f'o{i},2,p2,{seller},20']
    data['orders.csv']=('\n'.join(orders)+'\n').encode(); data['items.csv']=('\n'.join(items)+'\n').encode()
    headers=scoped(client, analyst_auth, data)
    response=client.get('/api/analytics/business?domain=sellers',headers=headers)
    assert response.status_code==200,response.text
    body=response.json()
    assert [c['value'] for c in body['cards']]==[40,50,50]
    assert [(r['orders'],r['late'],r['value']) for r in body['rankings']]==[(20,20,100),(20,0,0)]
    assert body['rankings'][0]['mean_late_days']==4
    assert body['rankings'][1]['mean_late_days'] is None
    assert body['recommendations'][0]['evidence']['baseline_pct']==50
    small=client.get('/api/analytics/business?domain=sellers&date_to=2025-01-10',headers=headers).json()
    assert small['rankings']==[] and small['recommendations']==[]


def test_authorization_missing_identity_and_specialist_charts(isolated, analyst_auth, auth):
    client,_=isolated;data=fixture(2)
    headers=scoped(client,analyst_auth,data)
    assert client.get('/api/analytics/business').status_code==401
    assert client.get('/api/analytics/business',headers={**auth,'X-Dataset-ID':headers['X-Dataset-ID']}).status_code==403
    assert client.get('/api/analytics/business?domain=invalid',headers=headers).status_code==422
    products=client.get('/api/analytics/products',headers=headers).json()['specialist_charts']
    assert products[0]['data'][0]['revenue']==120
    assert products[1]['data'][0]['quantity']==2
    assert products[2]['data'][0]['price']==60
    overview=client.get('/api/analytics/overview',headers=headers).json()
    assert overview['product_highlights']['by_revenue'][0]['revenue']==120
    assert overview['product_highlights']['by_quantity'][0]['quantity']==2
    assert overview['kpis']['completed_delivery_orders']==2
    assert overview['kpis']['delivery_completion_pct']==100
    assert {chart['title'] for chart in overview['specialist_charts']}=={'Average completed delivery time','Order cancellation rate'}
    delivery=client.get('/api/analytics/delivery',headers=headers).json()['specialist_charts']
    assert delivery[0]['data'][0]['days']==4
    assert delivery[1]['data'][0]['cancellation_rate']==0
    data['customers.csv']+=b'c0,duplicate,SP,01000\n'
    bad=scoped(client,analyst_auth,data)
    missing=client.get('/api/analytics/business?domain=customers',headers=bad).json()
    assert missing['status']=='not_applicable' and missing['series']==[]


@pytest.mark.parametrize('target',['orders','revenue'])
def test_real_forecast_horizons_dates_and_filter_scopes(isolated,analyst_auth,target):
    client,_=isolated;headers=scoped(client,analyst_auth,fixture(40))
    ident=headers['X-Dataset-ID']
    assert client.patch(f'/api/datasets/{ident}/schema',headers=analyst_auth,json={'fields':{},'currency_code':'BRL','domain':'commerce'}).status_code==200
    first=client.get(f'/api/ml/forecast?target={target}&periods=7',headers=headers).json()
    second=client.get(f'/api/ml/forecast?target={target}&periods=14&date_to=2025-02-05',headers=headers).json()
    assert first['status']==second['status']=='available'
    assert len(first['history_tail'])==30 and len(first['forecast'])==7 and len(second['forecast'])==14
    assert first['history_tail'][-1]['date']=='2025-02-09'
    assert first['forecast'][0]['date']=='2025-02-10'
    assert second['history_tail'][-1]['date']=='2025-02-05'
    assert second['forecast'][0]['date']=='2025-02-06'
    assert 'interval' not in first and 'backtest' not in first
