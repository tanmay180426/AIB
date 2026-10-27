"""Validated Olist table adapter. Aggregate each fact before order-grain joins.

Item revenue is SUM(price), excludes freight and is never added to payments.
No value is imputed for a missing fact. Currency is owner-confirmed metadata.
"""
from __future__ import annotations
import json
from fastapi import HTTPException
from sqlalchemy import select, func, literal_column, or_, case, Index
from app.models.dataset import Dataset, DatasetBundleTable
from app.services.datasets import storage_table
from app.analytics.filters import Filters, period_expr

SIGNATURES = {
    'orders': {'order_id','customer_id','order_status','order_purchase_timestamp'},
    'items': {'order_id','order_item_id','product_id','seller_id','price'},
    'customers': {'customer_id','customer_unique_id','customer_state'},
    'products': {'product_id','product_category_name'},
    'sellers': {'seller_id','seller_state'},
    'payments': {'order_id','payment_value','payment_type'},
    'reviews': {'order_id','review_score','review_id'},
    'translation': {'product_category_name','product_category_name_english'},
    'geolocation': {'geolocation_zip_code_prefix','geolocation_lat','geolocation_lng'},
}


def members(db, parent):
    catalog = db.scalars(select(DatasetBundleTable).where(DatasetBundleTable.bundle_id == parent.id)).all()
    found, ambiguous = {}, set()
    for member in catalog:
        ds = db.get(Dataset, member.dataset_id)
        cols = {c['name']: c for c in ds.profile['columns']}
        for role, required in SIGNATURES.items():
            if required <= cols.keys():
                if role in found:
                    ambiguous.add(role)
                table = storage_table(ds, db)
                found[role] = (ds, {name: table.c[c['storage']] for name,c in cols.items()}, table)
    return {r:v for r,v in found.items() if r not in ambiguous}


def analytic_indexes(db,parent):
    """Cover fact aggregations so random UUID key order avoids disk row probes."""
    tables=members(db,parent)
    for role,names in [('items',['order_id','price','product_id','seller_id']),
                       ('payments',['order_id','payment_value']),
                       ('reviews',['order_id','review_score']),
                       ('customers',['customer_id','customer_unique_id','customer_state'])]:
        if role in tables:
            _,columns,table=tables[role]
            Index(f'ix_{table.name}_bundle_aggregate',*[columns[name] for name in names]).create(db.connection(),checkfirst=True)


def describe(db, parent):
    tables = members(db, parent)
    relationships = []
    unique = {}
    item_grain = None
    if 'items' in tables:
        _,ic,it=tables['items']
        groups=select(ic['order_id'],ic['order_item_id']).select_from(it).group_by(ic['order_id'],ic['order_item_id']).having(func.count()>1).subquery()
        duplicate_groups=db.scalar(select(func.count()).select_from(groups))
        null_keys=db.scalar(select(func.count()).select_from(it).where(or_(ic['order_id'].is_(None),ic['order_item_id'].is_(None))))
        item_grain={'unique':not duplicate_groups and not null_keys,'duplicate_keys':duplicate_groups,'null_keys':null_keys}
    for role, key in [('orders','order_id'),('customers','customer_id'),('products','product_id'),('sellers','seller_id'),('translation','product_category_name')]:
        if role in tables:
            _, cols, table = tables[role]
            n, nonnull, distinct = db.execute(select(func.count(),func.count(cols[key]),func.count(func.distinct(cols[key]))).select_from(table)).one()
            unique[role] = n == nonnull == distinct
    for child, key, parent_role, parent_key in [('items','order_id','orders','order_id'),('payments','order_id','orders','order_id'),('reviews','order_id','orders','order_id'),('orders','customer_id','customers','customer_id'),('items','product_id','products','product_id'),('items','seller_id','sellers','seller_id'),('products','product_category_name','translation','product_category_name')]:
        if child not in tables or parent_role not in tables:
            continue
        _, cc, ct = tables[child]; _, pc, pt = tables[parent_role]
        matching = select(pc[parent_key]).where(pc[parent_key] == cc[key]).exists()
        unmatched = db.scalar(select(func.count()).select_from(ct).where(cc[key].is_not(None),~matching))
        nulls = db.scalar(select(func.count()).select_from(ct).where(cc[key].is_(None)))
        types = {ds.id:{c['name']:c['dtype'] for c in ds.profile['columns']} for ds,_,_ in [tables[child],tables[parent_role]]}
        same_type = types[tables[child][0].id][key] == types[tables[parent_role][0].id][parent_key]
        enabled = bool(unique.get(parent_role) and same_type)
        measure={'items':'price','payments':'payment_value','reviews':'review_score'}.get(child)
        numeric_valid=not measure or next(c['dtype'] for c in tables[child][0].profile['columns'] if c['name']==measure)=='numeric'
        enabled = enabled and numeric_valid and (child!='items' or bool(item_grain and item_grain['unique']))
        relationships.append({'from_table':child,'from_key':key,'to_table':parent_role,'to_key':parent_key,
                              'enabled':enabled,'cardinality':'many-to-one' if enabled else 'unverified',
                              'unmatched_rows':unmatched,'null_keys':nulls,
                              'reason':None if enabled else 'Key uniqueness, compatible types or numeric fact grain could not be validated.'})
    if 'geolocation' in tables:
        geo=tables['geolocation'][0]
        prefix=next(c for c in geo.profile['columns'] if c['name']=='geolocation_zip_code_prefix')
        unique_prefix=prefix['unique']==geo.row_count and not prefix['missing']
        relationships.append({'from_table':'customers','from_key':'customer_zip_code_prefix','to_table':'geolocation',
                              'to_key':'geolocation_zip_code_prefix','enabled':False,
                              'null_keys':prefix['missing'],'unique_prefix':unique_prefix,
                              'reason':'Geolocation prefixes repeat or contain nulls; no direct join is enabled.' if not unique_prefix else
                                       'Prefix keys are unique, but geospatial joins are not implemented by this adapter.'})
    orders = tables.get('orders')
    date_valid = orders and next(c['dtype'] for c in orders[0].profile['columns'] if c['name']=='order_purchase_timestamp') == 'datetime'
    supported = bool(unique.get('orders') and date_valid)
    return {'supported':supported,'reason': 'Order-grain overview; item prices and payments are aggregated separately.' if supported else
            'Cross-table analytics are not supported for this schema; no joins are calculated. A unique non-null order_id and validated order_purchase_timestamp are required. Select a table for generic analysis.',
            'roles':{role:ds.id for role,(ds,_,_) in tables.items()},'relationships':relationships,
            'unique_dimensions':unique,'item_grain':item_grain,'revenue_definition':'Sum of item price; excludes freight, includes matching order statuses, never added to payment_value.',
            'provenance':'Uploaded records; real/synthetic composition is not verified from filenames.'}


class BundleSource:
    def __init__(self, db, f=None):
        self.db=db; self.ds=db.info['dataset']; self.f=f or Filters()
        self.meta=self.ds.profile['relational_analysis']; self.tables=members(db,self.ds)
        if not self.meta['supported']:
            raise HTTPException(422,self.meta['reason'])
        _, self.oc, self.ot=self.tables['orders']
        self.where=[]
        date=self.oc['order_purchase_timestamp']
        if self.f.date_from: self.where.append(date >= self.f.date_from)
        if self.f.date_to: self.where.append(date < self.f.date_to+'T99')
        if self.f.order_status: self.where.append(self.oc['order_status']==self.f.order_status)
        self.base=self.ot
        self.customer=self.oc['customer_id']
        if self.enabled('orders','customers'):
            _,cc,ct=self.tables['customers']; self.base=self.base.outerjoin(ct,self.oc['customer_id']==cc['customer_id'])
            self.customer=cc['customer_unique_id']
            if self.f.customer_state: self.where.append(cc['customer_state']==self.f.customer_state)
        elif self.f.customer_state:
            raise HTTPException(422,'Customer-state filter requires a validated customers relationship.')
        for parameter,role,column in [('payment_type','payments','payment_type'),('review_score','reviews','review_score')]:
            value=getattr(self.f,parameter)
            if value is not None:
                if not self.enabled(role,'orders'): raise HTTPException(422,f'{parameter} requires a validated {role} relationship.')
                _,cols,table=self.tables[role]
                self.where.append(select(cols['order_id']).select_from(table).where(cols['order_id']==self.oc['order_id'],cols[column]==value).correlate(self.ot).exists())
        for column,value in json.loads(self.f.column_filters or '{}').items():
            if column not in {'order_status'}: raise HTTPException(422,'Bundle column filters support order_status; select a table for other column filters.')
            self.where.append(self.oc[column]==value)
        self.item_base=None; self.ic={}; self.pc={}
        if self.enabled('items','orders'):
            _,self.ic,it=self.tables['items']; self.item_base=it
            if self.enabled('items','products'):
                _,self.pc,pt=self.tables['products']; self.item_base=self.item_base.outerjoin(pt,self.ic['product_id']==self.pc['product_id'])
            if self.enabled('items','sellers'):
                _,sc,st=self.tables['sellers']
                if self.f.seller_state: self.item_base=self.item_base.outerjoin(st,self.ic['seller_id']==sc['seller_id'])
                self.seller_state=sc['seller_state']
        item_where=[]
        if self.f.category:
            if not self.pc: raise HTTPException(422,'Category filter requires unique product keys and a validated items/products relationship.')
            item_where.append(self.pc['product_category_name']==self.f.category)
        if self.f.seller_state:
            if not hasattr(self,'seller_state'): raise HTTPException(422,'Seller-state filter requires a validated sellers relationship.')
            item_where.append(self.seller_state==self.f.seller_state)
        self.item_where=item_where
        if item_where:
            self.where.append(select(self.ic['order_id']).select_from(self.item_base).where(self.ic['order_id']==self.oc['order_id'],*item_where).correlate(self.ot).exists())
        self.amount=None; self.payments=None
        self.order_base=self.base
        if self.item_base is not None:
            fact_base=self.item_base if item_where else self.tables['items'][2]
            agg=select(self.ic['order_id'].label('order_id'),func.sum(self.ic['price']).label('revenue'),func.count().label('items')).select_from(fact_base).where(*item_where).group_by(self.ic['order_id']).subquery()
            self.base=self.base.outerjoin(agg,self.oc['order_id']==agg.c.order_id); self.amount=agg.c.revenue
        self.revenue_base=self.base
        if self.enabled('payments','orders'):
            _,cols,table=self.tables['payments']
            pay=select(cols['order_id'].label('order_id'),func.sum(cols['payment_value']).label('payments')).select_from(table).group_by(cols['order_id']).subquery()
            self.base=self.base.outerjoin(pay,self.oc['order_id']==pay.c.order_id); self.payments=pay.c.payments

    def enabled(self,child,parent):
        return any(r.get('enabled') and r['from_table']==child and r['to_table']==parent for r in self.meta['relationships'])

    def statement(self,*cols):
        return select(*cols).select_from(self.base).where(*self.where)

    def scalar(self,expression):
        return self.db.scalar(self.statement(expression))

    def rows(self,statement):
        return [dict(r) for r in self.db.execute(statement).mappings()]

    def item_statement(self,*cols):
        order_ids=self.order_ids()
        return select(*cols).select_from(self.item_base).where(self.ic['order_id'].in_(order_ids),*self.item_where)

    def order_ids(self):
        # Existence probes do not need the customer dimension unless filtered.
        base=self.order_base if self.f.customer_state else self.ot
        return select(self.oc['order_id']).select_from(base).where(*self.where)

    def fact_statement(self,role,*expressions):
        _,cols,table=self.tables[role]
        query=select(*expressions).select_from(table)
        relation=next(r for r in self.meta['relationships'] if r.get('enabled') and r['from_table']==role and r['to_table']=='orders')
        if not (self.f.is_empty and relation['unmatched_rows']==0 and relation['null_keys']==0):
            query=query.where(cols['order_id'].in_(self.order_ids()))
        return query

    def kpis(self):
        expressions=[func.count().label('orders')]
        if self.enabled('orders','customers'): expressions.append(func.count(func.distinct(self.customer)).label('customers'))
        delivered=self.oc.get('order_delivered_customer_date')
        if delivered is not None:
            if self.db.get_bind().dialect.name == 'postgresql':
                from sqlalchemy import cast,DateTime,extract
                days=extract('epoch',cast(delivered,DateTime)-cast(self.oc['order_purchase_timestamp'],DateTime))/86400
            else: days=func.julianday(delivered)-func.julianday(self.oc['order_purchase_timestamp'])
            expressions.append(func.avg(case(((self.oc['order_status']=='delivered') & (days>=0),days),else_=None)).label('delivery'))
            expressions.append(func.count(case(((self.oc['order_status']=='delivered') & (days>=0),1),else_=None)).label('completed_deliveries'))
        aggregate=self.rows(select(*expressions).select_from(self.order_base).where(*self.where))[0]
        n=aggregate['orders'];revenue=None;payments=None
        if self.amount is not None:
            revenue=self.db.scalar(self.item_statement(func.sum(self.ic['price']))) if self.item_where else self.db.scalar(self.fact_statement('items',func.sum(self.ic['price'])))
        if self.payments is not None:
            payments=self.db.scalar(self.fact_statement('payments',func.sum(self.tables['payments'][1]['payment_value'])))
        result={'total_orders':n,'unique_customers':aggregate.get('customers'),
                'total_revenue':revenue,'avg_order_value':revenue/n if revenue is not None and n else None,
                'total_payments':payments,
                'products_sold':None,'active_sellers':None,'items_sold':None,'avg_review_score':None,'avg_delivery_days':aggregate.get('delivery'),
                'completed_delivery_orders':aggregate.get('completed_deliveries'),
                'delivery_completion_pct':100*aggregate['completed_deliveries']/n if n and 'completed_deliveries' in aggregate else None}
        if self.item_base is not None:
            columns=[func.count(),func.count(func.distinct(self.ic['product_id'])),func.count(func.distinct(self.ic['seller_id']))]
            counts=self.db.execute(self.item_statement(*columns) if self.item_where else self.fact_statement('items',*columns)).one()
            result.update(items_sold=counts[0],products_sold=counts[1],active_sellers=counts[2])
        if self.enabled('reviews','orders'):
            _,rc,rt=self.tables['reviews']; query=self.fact_statement('reviews',func.avg(rc['review_score']))
            result['avg_review_score']=self.db.scalar(query)
        return result

    def time_series(self,grain='month',limit=400):
        date=self.oc['order_purchase_timestamp']
        expression=f'{self.ot.name}.{date.name}'
        if self.db.get_bind().dialect.name == 'postgresql': expression=f'CAST({expression} AS timestamp)'
        period=literal_column(period_expr(self.db,expression,grain)).label('period')
        base=self.order_base if self.f.customer_state else self.ot
        query=select(period,func.count().label('orders'),func.count().label('rows')).select_from(base).where(*self.where,date.is_not(None))
        points=self.rows(query.group_by(period).order_by(period.desc()).limit(limit))[::-1]
        if self.amount is not None:
            # A many-to-one items→orders join is safe at item grain. Payments
            # never enter it. Merge only the bounded period aggregates.
            item_base=self.item_base if self.item_where else self.tables['items'][2]
            fact=item_base.join(base,self.ic['order_id']==self.oc['order_id'])
            money=select(period,func.sum(self.ic['price']).label('revenue')).select_from(fact).where(*self.where,*self.item_where,date.is_not(None)).group_by(period)
            by_period={r['period']:r['revenue'] for r in self.rows(money)}
            for point in points: point['revenue']=by_period.get(point['period'])
        return points

    def category(self,limit=15):
        if not self.pc: return []
        category=self.pc['product_category_name']
        return self.rows(self.item_statement(category.label('category'),func.sum(self.ic['price']).label('revenue'),func.count().label('items')).group_by(category).order_by(func.sum(self.ic['price']).desc()).limit(limit))

    def statuses(self):
        status=self.oc['order_status']
        return self.rows(select(status.label('status'),func.count().label('orders')).select_from(self.order_base).where(*self.where).group_by(status))

    def filters(self):
        def values(role,column):
            if role not in self.tables:return []
            _,c,t=self.tables[role]
            return list(self.db.scalars(select(c[column]).select_from(t).where(c[column].is_not(None)).distinct().order_by(c[column]).limit(100)))
        bounds=self.db.execute(select(func.min(self.oc['order_purchase_timestamp']),func.max(self.oc['order_purchase_timestamp']))).one()
        return {'has_date':True,'date_range':{'min':bounds[0],'max':bounds[1]},'categories':values('products','product_category_name') if self.enabled('items','products') else [],
                'customer_states':values('customers','customer_state') if self.enabled('orders','customers') else [],'seller_states':values('sellers','seller_state') if self.enabled('items','sellers') else [],
                'order_statuses':values('orders','order_status'),'payment_types':values('payments','payment_type') if self.enabled('payments','orders') else [],'review_scores':values('reviews','review_score') if self.enabled('reviews','orders') else []}

    def specialist_charts(self, section):
        """Bounded native-grain aggregates, only for the requested specialist page."""
        charts=[]
        if section == 'products' and self.item_base is not None:
            product=self.ic['product_id']; revenue=func.sum(self.ic['price']); quantity=func.count()
            query=self.item_statement(product.label('label'),revenue.label('revenue'),quantity.label('quantity'),func.avg(self.ic['price']).label('price')).where(product.is_not(None)).group_by(product)
            highest_revenue=self.rows(query.order_by(revenue.desc(),product).limit(10))
            highest_quantity=self.rows(query.order_by(quantity.desc(),product).limit(50))
            charts.extend([
                {'title':'Highest-revenue products','kind':'bar','x':'label','y':'revenue','data':highest_revenue,'note':'Top 10 by qualifying item price, excluding freight.'},
                {'title':'Highest-selling products','kind':'bar','x':'label','y':'quantity','data':highest_quantity[:10],'note':'Top 10 by item-row count; one validated row per order item.'},
                {'title':'Product price versus observed demand','kind':'scatter','x':'price','y':'quantity','data':highest_quantity,'note':'Top 50 products by item count; mean observed item price versus item count. Association, not a causal price effect.'}])
        if section in {'delivery','overview','dashboard'}:
            delivered=self.oc.get('order_delivered_customer_date'); estimated=self.oc.get('order_estimated_delivery_date')
            if delivered is not None:
                from sqlalchemy import cast,DateTime,extract
                purchase=self.oc['order_purchase_timestamp']
                if self.db.get_bind().dialect.name == 'postgresql':
                    duration=extract('epoch',cast(delivered,DateTime)-cast(purchase,DateTime))/86400
                else: duration=func.julianday(delivered)-func.julianday(purchase)
                valid=(self.oc['order_status']=='delivered') & (duration>=0)
                expression=f'{self.ot.name}.{purchase.name}'
                if self.db.get_bind().dialect.name == 'postgresql': expression=f'CAST({expression} AS timestamp)'
                period=literal_column(period_expr(self.db,expression,'month')).label('label')
                rows=self.rows(select(period,func.avg(case((valid,duration),else_=None)).label('days'),
                    (100.0*func.sum(case((self.oc['order_status']=='canceled',1),else_=0))/func.count()).label('cancellation_rate'))
                    .select_from(self.order_base).where(*self.where,purchase.is_not(None)).group_by(period).order_by(period.desc()).limit(120))[::-1]
                charts.extend([{'title':'Average completed delivery time','kind':'line','x':'label','y':'days','data':rows,'note':'Days from purchase to delivery; valid delivered orders only, grouped by purchase month.'},
                    {'title':'Order cancellation rate','kind':'line','x':'label','y':'cancellation_rate','data':rows,'note':'Canceled orders / all matching orders × 100, grouped by purchase month. Missing delivery dates are not zero-duration deliveries.'}])
        return charts

    def view(self,section='dashboard'):
        k=self.kpis(); labels={'total_orders':'Distinct orders','unique_customers':'Unique customers','products_sold':'Products sold','active_sellers':'Active sellers','items_sold':'Items sold','total_revenue':'Item revenue','avg_order_value':'Average order value','total_payments':'Payment total','avg_review_score':'Average review score','avg_delivery_days':'Average delivery days'}
        statuses=self.statuses(); categories=self.category()
        dates=self.db.execute(select(func.min(self.oc['order_purchase_timestamp']),func.max(self.oc['order_purchase_timestamp']))).one()
        product_highlights={}
        if section in {'overview','dashboard'} and self.item_base is not None:
            product=self.ic['product_id']; revenue=func.sum(self.ic['price']); quantity=func.count()
            query=self.item_statement(product.label('product'),revenue.label('revenue'),quantity.label('quantity')).where(product.is_not(None)).group_by(product)
            product_highlights={'by_revenue':self.rows(query.order_by(revenue.desc(),product).limit(5)),
                                'by_quantity':self.rows(query.order_by(quantity.desc(),product).limit(5))}
        return {'status':'available','dataset_id':self.ds.id,'dataset_name':self.ds.name,'section':section,'filters':self.f.as_dict(),'kpis':k,
                'date_range':{'min':dates[0],'max':dates[1]},
                'metric_cards':[{'label':label,'value':k[key]} for key,label in labels.items()], 'currency_code':self.ds.semantics.get('currency_code'),
                'time_series':self.time_series(),'distributions':[{'field':'order status','series':[{'label':r['status'],'rows':r['orders']} for r in statuses]}]+
                  ([{'field':'category','measure':'amount','series':[{'label':r['category'] or 'Unmapped category','rows':r['items'],'amount':r['revenue']} for r in categories]}] if categories else []),
                'entities':[{'label':r['category'] or 'Unmapped category','rows':r['items'],'amount':r['revenue']} for r in categories],
                'quality':self.ds.quality,'relationships':self.meta,'revenue_definition':self.meta['revenue_definition'],'grain':'orders',
                'specialist_charts':self.specialist_charts(section),
                'product_highlights':product_highlights,
                'metric_definitions':{'avg_order_value':'Average order value = qualifying item prices / matching distinct orders. Category/seller filters narrow the item prices.',
                    'total_payments':'Payment totals cover all payment rows for matching orders. Payment-type filters select orders by existence.',
                    'avg_review_score':'Average review score covers all review rows for matching orders. Review-score filters select orders by existence.',
                    'avg_delivery_days':'Mean observed delivered-customer timestamp minus purchase timestamp, excluding missing and negative intervals.'},
                'unavailable':[label for key,label in labels.items() if k[key] is None]}
