from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.analytics import metrics
from app.analytics.filters import Filters
from app.database.session import Base
from app.models.warehouse import DimCustomer, DimSeller, FactOrders, FactOrderItems
from app.services import ml


ORDERS = [
    ('o1', 'c1', '2025-01-01', 'delivered', 'credit_card', 5, 'SP'),
    ('o2', 'c1', '2025-02-01', 'canceled', 'credit_card', 4, 'SP'),
    ('o3', 'c2', '2025-02-01', 'delivered', 'boleto', 3, 'RJ'),
    ('o4', 'c3', '2025-02-02', 'delivered', 'credit_card', 5, 'SP'),
]
ITEMS = [('o1', 'Books', 'SP', 20), ('o1', 'Tools', 'RJ', 80),
         ('o2', 'Books', 'SP', 30), ('o3', 'Tools', 'RJ', 50), ('o4', 'Books', 'SP', 40)]


@pytest.fixture
def reference():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([DimCustomer(customer_unique_id=c, customer_state=s) for c, s in [('c1','SP'),('c2','RJ'),('c3','SP')]])
        db.add_all([DimSeller(seller_id=s, seller_state=s) for s in ['SP','RJ']])
        for oid, cid, day, status, payment, review, _ in ORDERS:
            db.add(FactOrders(order_id=oid, customer_unique_id=cid, purchase_date=date.fromisoformat(day),
                order_status=status, payment_type=payment, review_score=review, payment_installments=2,
                item_revenue=sum(v for o, _, _, v in ITEMS if o == oid)))
        for idx, (oid, category, state, amount) in enumerate(ITEMS, 1):
            order = next(o for o in ORDERS if o[0] == oid)
            db.add(FactOrderItems(order_id=oid, order_item_id=idx, product_id=str(idx), seller_id=state,
                customer_unique_id=order[1], purchase_date=date.fromisoformat(order[2]), price=amount,
                freight_value=0, product_category_name_en=category))
        db.commit()
        db.info['dataset'] = SimpleNamespace(adapter='star_schema')
        yield db
    engine.dispose()


def matches(order, f):
    oid, _, day, status, payment, review, state = order
    return (not f.date_from or day >= f.date_from) and (not f.date_to or day <= f.date_to) and (
        not f.order_status or status == f.order_status) and (not f.payment_type or payment == f.payment_type) and (
        f.review_score is None or f.review_score - .5 <= review < f.review_score + .5) and (
        not f.customer_state or state == f.customer_state) and any(
        o == oid and (not f.category or cat == f.category) and (not f.seller_state or seller == f.seller_state)
        for o, cat, seller, _ in ITEMS)


@pytest.mark.parametrize('f', [Filters(), Filters(order_status='absent'), Filters(category='Books'),
    Filters(seller_state='RJ'), Filters(order_status='canceled'), Filters(payment_type='boleto'),
    Filters(review_score=5), Filters(date_from='2025-02-01'), Filters(date_to='2025-01-31'),
    Filters(date_from='2025-02-01', date_to='2025-02-02', category='Books', seller_state='SP',
            order_status='delivered', payment_type='credit_card', review_score=5)])
def test_new_customers_first_ever_intersect_filtered_population(reference, f):
    population = {o[1] for o in ORDERS if matches(o, f)}
    first = {c: min(o[2] for o in ORDERS if o[1] == c) for c in population}
    expected = sum((not f.date_from or d >= f.date_from) and (not f.date_to or d <= f.date_to) for d in first.values())
    assert metrics.kpis(reference, f)['new_customers'] == expected


@pytest.mark.parametrize('f', [Filters(), Filters(category='Books'), Filters(seller_state='SP'),
    Filters(customer_state='SP'), Filters(order_status='delivered'), Filters(payment_type='credit_card'),
    Filters(category='Books', seller_state='SP', customer_state='SP', order_status='delivered',
            payment_type='credit_card', review_score=5)])
def test_all_monetary_breakdowns_reconcile_without_multiplying_orders(reference, f):
    matching = [o for o in ORDERS if matches(o, f)]
    expected = sum(v for oid, cat, state, v in ITEMS if any(o[0] == oid for o in matching)
                   and (not f.category or cat == f.category) and (not f.seller_state or state == f.seller_state))
    k = metrics.kpis(reference, f)
    assert k['total_revenue'] == expected
    assert k['total_orders'] == len(matching)
    assert k['unique_customers'] == len({o[1] for o in matching})
    for function in [metrics.payment_types, metrics.payment_installments, metrics.customer_spend_distribution,
                     metrics.customers_by_state, metrics.top_customer_states,
                     lambda db, filters: metrics.top_customers(db, filters, limit=100)]:
        assert sum(r['revenue'] for r in function(reference, f)) == pytest.approx(expected)
    assert sum(r['monetary'] for r in ml.customer_segments(reference, f)['segments']) == pytest.approx(expected)
