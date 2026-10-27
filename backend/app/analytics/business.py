"""Bounded, deterministic business evidence. No models, causal claims or raw PII.

Reuse the authorized metric adapters. Orders and item/seller membership remain
separate grains; neither payments nor reviews enter the customer/seller joins.
"""
from datetime import date, timedelta
from sqlalchemy import String, Float, case, cast, func, literal, select, text
from sqlalchemy.sql.elements import quoted_name
from app.analytics import metrics
from app.analytics.filters import Filters, order_from, order_monetary_scope, order_where, item_from, item_where


def _rows(db, query):
    return [dict(row) for row in db.execute(query).mappings()]


def _orders(db, f, with_revenue=True):
    ds = db.info['dataset']
    if ds.source_type == 'bundle':
        from app.analytics.bundle import BundleSource
        s = BundleSource(db, f)
        c = s.oc
        customer = s.customer if s.enabled('orders', 'customers') else literal(None)
        # The order base includes only validated many-to-one customer joins.
        # Revenue is already aggregated once per order in revenue_base.
        return select(c['order_id'].label('oid'), customer.label('customer'),
                      c['order_purchase_timestamp'].label('purchased'),
                      (s.amount if with_revenue and s.amount is not None else literal(None)).label('revenue'),
                      c['order_status'].label('status'),
                      c.get('order_delivered_customer_date', literal(None)).label('delivered'),
                      c.get('order_estimated_delivery_date', literal(None)).label('estimated')
                      ).select_from(s.revenue_base if with_revenue else s.order_base).where(*s.where).subquery(), s
    if ds.adapter != 'star_schema':
        return None, None
    source, amount = order_monetary_scope(f)
    if not with_revenue:
        source, amount = order_from(f), 'NULL'
    where, params = order_where(f)
    query = text(f'SELECT o.order_id AS oid, o.customer_unique_id AS customer, o.purchase_date AS purchased, '
                 f'{amount} AS revenue, o.order_status AS status, o.delivered_customer_date AS delivered, '
                 f'o.estimated_delivery_date AS estimated FROM {source} WHERE {where}').bindparams(**params)
    return query.columns(oid=String, customer=String, purchased=String, revenue=Float,
                         status=String, delivered=String, estimated=String).subquery(), None


def _recommend(domain, ident, title, observation, action, window, evidence, limitation, priority='medium'):
    return dict(id=ident, domain=domain, title=title, priority=priority, observation=observation,
                suggested_action=action, measurement_window=window, evidence=evidence,
                limitations=limitation, metric_source='Authorized selected data; SQL aggregates')


def evidence(db, f, domain, *, materialize=False):
    ds = db.info['dataset']
    result = dict(dataset_id=ds.id, domain=domain, status='available', cards=[], series=[], rankings=[],
                  recommendations=[], limitations=[], currency_code=ds.semantics.get('currency_code'),
                  source='Observed selected data and applicable filters; no causal inference',
                  forecast_supported=False)
    if domain == 'revenue':
        points = metrics.time_series(db, f, 'day', limit=28)
        valid = [p for p in points if p.get('revenue') is not None]
        result['series'] = [dict(period=p['period'], revenue=p['revenue']) for p in valid]
        result['limitations'] = ['Item revenue excludes freight and is never added to payments for Olist. '
                                'Comparable-period change requires 28 consecutive observed days. '
                                'These observations do not establish causes or forecast a guaranteed gain.']
        if len(valid) == 28:
            dates = [date.fromisoformat(p['period']) for p in valid]
            if all(b-a == timedelta(days=1) for a, b in zip(dates, dates[1:])):
                previous = sum(p['revenue'] for p in valid[:14]); recent = sum(p['revenue'] for p in valid[14:])
                window = f'{dates[0]}–{dates[13]} versus {dates[14]}–{dates[-1]} (14 observed days each)'
                result['measurement_window'] = window
                result['cards'] = [dict(label='Previous 14-day revenue', value=previous), dict(label='Recent 14-day revenue', value=recent)]
                if previous > 0 and recent <= previous*.9:
                    change = (recent/previous-1)*100
                    result['recommendations'].append(_recommend('revenue', 'revenue-decline', 'Investigate the recent revenue decline',
                        f'Item revenue decreased {abs(change):.2f}% across equal 14-day windows.',
                        'Compare category mix and order volume in these windows before choosing an intervention.', window,
                        dict(previous=previous, recent=recent, change_pct=change),
                        'Rule: at least a 10% decline across complete equal windows. No promotion, cost, stock or marketing exposure evidence establishes the cause.',
                        priority='high' if change <= -20 else 'medium'))
        categories = metrics.revenue_by_category(db, f, limit=10)
        result['rankings'] = [dict(label=r['category'] or 'Unmapped category', value=r['revenue']) for r in categories if r.get('revenue') is not None]
        # Total is taken at the same selected item scope, not from a truncated top-N list.
        o, _ = _orders(db, f)
        total = db.scalar(select(func.sum(o.c.revenue))) if o is not None else None
        if total and total > 0 and result['rankings']:
            top = result['rankings'][0]; share = top['value']/total*100
            if share >= 30:
                result['recommendations'].append(_recommend('revenue', 'category-concentration', 'Review revenue concentration',
                    f"{top['label']} contributes {share:.2f}% of selected item revenue.",
                    'Review dependence on this category and compare margins and availability before allocating budget.',
                    'All matching selected dates', dict(category=top['label'], revenue=top['value'], total=total, share_pct=share),
                    'Concentration is exposure, not proof of risk or an estimate of achievable revenue.'))
        result['recommendations'].sort(key=lambda r: (r['priority'] != 'high', r['id']))
        return result
    o, source = _orders(db, f, with_revenue=domain != 'sellers')
    if o is None:
        return {**result, 'status':'not_applicable', 'limitations':['This analysis requires a validated Olist bundle or order-grain reference warehouse. Select the bundle overview.']}
    if materialize:
        # Report-only execution hint: reuse the same order-grain result within
        # each SQL statement. This avoids correlated re-expansion on the large
        # extended bundle, without changing formulas, filters or populations.
        o = select(o).cte('report_scoped_orders')
        if db.get_bind().dialect.name == 'sqlite': o = o.prefix_with('MATERIALIZED')
    counting_orders = o
    if materialize and domain == 'customers':
        counting_orders, _ = _orders(db, f, with_revenue=False)
        counting_orders = select(counting_orders).cte('report_customer_counts')
        if db.get_bind().dialect.name == 'sqlite': counting_orders = counting_orders.prefix_with('MATERIALIZED')
    bounds = db.execute(select(func.min(counting_orders.c.purchased), func.max(counting_orders.c.purchased))).one()
    window = f'{bounds[0]} to {bounds[1]} (matching purchase dates)'
    result['measurement_window'] = window
    if domain == 'customers':
        if source is not None and not source.enabled('orders', 'customers'):
            return {**result, 'status':'not_applicable', 'limitations':['A validated stable customer_unique_id relationship is required. Transaction customer_id is not treated as a person.']}
        customers = select(counting_orders.c.customer, func.count(func.distinct(counting_orders.c.oid)).label('n')).where(
            counting_orders.c.customer.is_not(None), counting_orders.c.purchased.is_not(None)).group_by(counting_orders.c.customer).subquery()
        counts = db.execute(select(func.count(), func.sum(case((customers.c.n >= 2, 1), else_=0)))).one()
        n, repeat = counts[0], counts[1] or 0
        result['cards'] = [dict(label='Observed customers', value=n), dict(label='Repeat customers', value=repeat),
                           dict(label='Repeat customer rate (%)', value=100*repeat/n if n else None)]
        result['frequency'] = _rows(db, select(customers.c.n.label('orders'), func.count().label('customers')).group_by(customers.c.n).order_by(customers.c.n).limit(100))
        # First purchase is established on the complete dataset, before date/dimension filters.
        all_orders, _ = _orders(db, Filters(), with_revenue=False)
        if materialize:
            all_orders = select(all_orders).cte('report_order_history')
            if db.get_bind().dialect.name == 'sqlite': all_orders = all_orders.prefix_with('MATERIALIZED')
        first = select(all_orders.c.customer, func.min(all_orders.c.purchased).label('first')).where(
            all_orders.c.customer.is_not(None), all_orders.c.purchased.is_not(None)).group_by(all_orders.c.customer).subquery()
        joined = o.join(first, o.c.customer == first.c.customer)
        period = func.substr(cast(o.c.purchased, String), 1, 7)
        result['series'] = _rows(db, select(period.label('period'),
            func.sum(case((o.c.purchased == first.c.first, o.c.revenue), else_=0)).label('first_time'),
            func.sum(case((o.c.purchased > first.c.first, o.c.revenue), else_=0)).label(quoted_name('returning', True)))
            .select_from(joined).group_by(period).order_by(period.desc()).limit(120))[::-1]
        if n >= 20 and (n-repeat)/n >= .7:
            result['recommendations'].append(_recommend('customers', 'single-purchase', 'Investigate re-engagement opportunities',
                f'{n-repeat} of {n} observed customers placed one matching order ({100*(n-repeat)/n:.2f}%).',
                'Compare sufficiently mature acquisition cohorts and purchase categories before testing a re-engagement programme.',
                window, dict(customers=n, repeat_customers=repeat, single_purchase=n-repeat),
                'Possible signal to investigate. Window censoring and filters affect repeat rate; transactions do not explain non-return.'))
        result['limitations'] = ['Historical analysis, not a customer-count forecast: no approved customer-volume model exists. '
            'Identity: customer_unique_id. Repeat means ≥2 matching orders; first observed purchase uses all available dataset history, '
            'not lifetime acquisition. Simultaneous earliest orders are first-time. No raw customer identifiers are returned.']
    elif domain == 'sellers':
        if source is not None:
            if source.item_base is None:
                return {**result, 'status':'not_applicable', 'limitations':['Validated item→order membership is required.']}
            membership = source.item_statement(source.ic['order_id'].label('oid'), source.ic['seller_id'].label('seller')).distinct().subquery()
        else:
            where, params = item_where(f)
            membership = text(f'SELECT DISTINCT i.order_id AS oid, i.seller_id AS seller FROM {item_from(f)} WHERE {where}').bindparams(**params).columns(oid=String, seller=String).subquery()
        from sqlalchemy import DateTime, extract
        if db.get_bind().dialect.name == 'postgresql':
            duration = extract('epoch', cast(o.c.delivered, DateTime)-cast(o.c.purchased, DateTime))/86400
            delay = extract('epoch', cast(o.c.delivered, DateTime)-cast(o.c.estimated, DateTime))/86400
            estimate_days = extract('epoch', cast(o.c.estimated, DateTime)-cast(o.c.purchased, DateTime))/86400
        else:
            duration = func.julianday(o.c.delivered)-func.julianday(o.c.purchased)
            delay = func.julianday(o.c.delivered)-func.julianday(o.c.estimated)
            estimate_days = func.julianday(o.c.estimated)-func.julianday(o.c.purchased)
        eligible = select(o.c.oid, duration.label('duration'), delay.label('delay'),
                          case((delay > 0, 1), else_=0).label('late')).where(
            o.c.status == 'delivered', duration >= 0, estimate_days >= 0, delay.is_not(None)).subquery()
        n, late = db.execute(select(func.count(), func.sum(eligible.c.late))).one(); late = late or 0
        baseline = 100*late/n if n else None
        result['cards'] = [dict(label='Eligible completed orders', value=n), dict(label='Late delivery rate (%)', value=baseline),
                           dict(label='On-time delivery rate (%)', value=100-baseline if baseline is not None else None)]
        grouped = select(membership.c.seller, func.count().label('orders'), func.sum(eligible.c.late).label('late'),
                         func.avg(case((eligible.c.delay > 0, eligible.c.delay), else_=None)).label('mean_late_days'))
        groups = grouped.select_from(eligible.join(membership, eligible.c.oid == membership.c.oid)).where(
            membership.c.seller.is_not(None)).group_by(membership.c.seller).having(func.count() >= 20).subquery()
        rate = 100.0*groups.c.late/groups.c.orders
        result['rankings'] = [dict(label=f"Seller {r['seller']}", value=r['rate'], orders=r['orders'], late=r['late'], mean_late_days=r['mean_late_days'])
            for r in _rows(db, select(groups, rate.label('rate')).order_by(rate.desc(), groups.c.seller).limit(10))]
        # Seller keys allow an operational follow-up; customer IDs and addresses are excluded.
        if baseline is not None and result['rankings']:
            top = result['rankings'][0]
            if top['value'] >= baseline+10:
                result['recommendations'].append(_recommend('sellers', 'seller-lateness', 'Review the highest observed delay group',
                    f"{top['label']}: {top['value']:.2f}% late across {top['orders']} eligible orders; dataset baseline {baseline:.2f}%.",
                    'Compare dispatch and carrier milestones with delivery promises for this group in an authorized operational review.',
                    window, dict(**top, baseline_pct=baseline, minimum_orders=20),
                    'Association does not assign seller responsibility. Multi-seller orders appear once per seller; baseline counts each order once.'))
        result['limitations'] = ['Historical seller delivery performance, not an ML delay prediction. '
            'Late means delivered timestamp after estimated timestamp. Only delivered orders with valid purchase, delivery and estimate dates '
            'and nonnegative durations qualify. Seller ranking requires ≥20 eligible distinct orders. '
            'Operational dispatch/carrier/inventory evidence is needed to establish a cause. Seller keys identify aggregate groups only.']
    return result
