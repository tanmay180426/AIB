"""Read-only authorized aggregate snapshot and bounded local report rendering."""
import io
import re
import threading
import time
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.exc import OperationalError
from app.models.dataset import DatasetBundleTable

from app.analytics import metrics, business
from app.services import ml, synthetic_forecast

REPORT_SLOTS = threading.BoundedSemaphore(2)
PLOT_LOCK = threading.Lock()


def snapshot(db, filters):
    ds = db.info['dataset']
    # All sources use the same existing metric boundary and bound filters.
    if ds.source_type == 'bundle':
        # The full interactive Dashboard also computes payment/state/review
        # distributions and duplicate product leader queries. Reports request
        # only their actual inputs through the same verified metric adapters.
        from app.analytics.bundle import BundleSource
        source = BundleSource(db, filters)
        bounds = db.execute(select(func.min(source.oc['order_purchase_timestamp']),
            func.max(source.oc['order_purchase_timestamp'])).select_from(source.ot)).one()
        products = source.specialist_charts('products')
        view = {'kpis': metrics.kpis(db, filters), 'date_range':{'min':bounds[0],'max':bounds[1]},
            'product_highlights':{key:next((chart['data'][:5] for chart in products if chart.get('kind')=='bar' and chart.get('y')==measure),[])
                for key,measure in [('by_revenue','revenue'),('by_quantity','quantity')]},
            'specialist_charts':source.specialist_charts('delivery')}
    else:
        view = metrics.overview(db, filters)
    kpis = view.get('kpis', {})
    sales = kpis.get('total_revenue') is not None
    evidence = {}
    if sales:
        for domain in ('revenue', 'customers', 'sellers'):
            try:
                evidence[domain] = business.evidence(db, filters, domain, materialize=True)
            except HTTPException as error:
                if error.status_code not in (409, 422): raise
                evidence[domain] = {'cards':[], 'series':[], 'rankings':[], 'recommendations':[], 'limitations':['Required semantic fields are unavailable.']}
    check = synthetic_forecast.compatibility(db, filters, 'orders') if sales else None
    synthetic = check is not None
    prediction = None
    forecast_reason = 'Sales/date semantics are unavailable for this selected scope.'
    if sales:
        check = check if check is not None else ml.compatibility('sales_forecast_orders', db, filters)
        if check['compatible']:
            try:
                prediction = synthetic_forecast.forecast(db, filters, 'orders', 30) if synthetic else ml.forecast(30, 'orders', db, filters)
            except (ValueError, KeyError, FileNotFoundError):
                forecast_reason = 'The selected model could not produce valid finite output for this scope.'
        else: forecast_reason = ' '.join(check['reasons'])
    categories = metrics.revenue_by_category(db, filters, limit=10) if sales else []
    statuses = metrics.orders_by_status(db, filters) if sales else []
    series = metrics.time_series(db, filters, 'month', limit=120) if sales else []
    if ds.source_type != 'bundle' and ds.adapter == 'tabular' and kpis.get('row_count') != kpis.get('total_orders'):
        # Generic row-status groups are not an order-status denominator when
        # multiple records refer to the same order. Do not relabel row counts.
        statuses = []
        series = [{k:v for k,v in point.items() if k!='orders'} for point in series]
    daily = metrics.time_series(db, filters, 'day', limit=100_000) if sales else []
    source_coverage = view.get('date_range') or metrics.filter_options(db).get('date_range',{})
    selected_coverage = {'min':daily[0]['period'],'max':daily[-1]['period']} if daily else source_coverage
    coverage_stats = {'observed_days':len(daily), 'unknown_revenue_days':sum(p.get('revenue') is None for p in daily),
        'zero_filled_days':0, 'missing_calendar_days':(date.fromisoformat(daily[-1]['period'])-date.fromisoformat(daily[0]['period'])).days+1-len(daily) if daily else None}
    recommendations = []
    for domain in evidence.values():
        for item in domain.get('recommendations', []):
            # Operational IDs from seller evidence are not public report labels.
            safe = {k: re.sub(r'Seller [A-Za-z0-9-]+', 'sample-qualified seller group', str(item.get(k,'')))
                    for k in ('title','observation','suggested_action','measurement_window','limitations')}
            recommendations.append(safe)
    quality = ds.quality or {}
    data_provenance = view.get('provenance')
    marked_synthetic = bool(data_provenance and (data_provenance.get('synthetic_rows') or 0) > 0)
    if marked_synthetic:
        synthetic = True
    provenance_text = (f"{data_provenance['synthetic_rows']:,} of {data_provenance['rows']:,} selected rows ({data_provenance['synthetic_share_pct']}%) are marked synthetic in {data_provenance.get('synthetic_field')}. Generated values are not verified transactions; origin labels are input metadata, not independent certification."
                       if marked_synthetic else
                       'Synthetic/extended dataset; row-level composition and generation rules are not independently verified.' if synthetic else
                       'Source real/synthetic provenance is unconfirmed; uploaded records are not certified real-world history.')
    return {'dataset':ds.name, 'scope':'Authorized multi-table order-grain bundle' if ds.source_type=='bundle' else 'Authorized selected dataset or table',
        'generated_at':datetime.now(timezone.utc).astimezone(ZoneInfo('Asia/Kolkata')).isoformat(), 'filters':{k:v for k,v in filters.as_dict().items() if v is not None},
        'synthetic':synthetic,'provenance':provenance_text, 'data_provenance':data_provenance,
        'currency':ds.semantics.get('currency_code'), 'money_unit':'source revenue units — currency unconfirmed' if not ds.semantics.get('currency_code') else ds.semantics['currency_code'],
        'source_rows':ds.row_count,'table_count':db.scalar(select(func.count()).select_from(DatasetBundleTable).where(DatasetBundleTable.bundle_id==ds.id)) if ds.source_type=='bundle' else 1,
        'coverage':selected_coverage,'source_coverage':source_coverage,'coverage_stats':coverage_stats,'sales_supported':sales,'kpis':kpis,'metric_cards':view.get('metric_cards',[]),
        'series':series,'categories':categories[:10],'statuses':statuses[:20],
        'products':view.get('product_highlights',{}),'specialist_charts':view.get('specialist_charts',{}),
        'evidence':evidence,'recommendations':recommendations[:12],
        'quality':{k:v for k,v in quality.items() if k in ('warnings','missing_cells','duplicate_rows','issues')},
        'numeric_statistics':view.get('numeric_statistics',[])[:12],
        'definitions':view.get('metric_definitions',{}),
        'forecast':prediction,'forecast_reason':None if prediction else forecast_reason,
        'forecast_evaluation':synthetic_forecast.selected_evidence(db,'orders') if synthetic else None}


def charts(data):
    """Aggregate-only images; private figures closed even when rendering fails."""
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    images = {}
    scope = f"Applied report filters; coverage {data['coverage'].get('min','unknown')} to {data['coverage'].get('max','unknown')}"
    with PLOT_LOCK:
        def draw(key, title, labels, values, unit, bars=False):
            pairs = [(str(label)[:52],float(value)) for label,value in zip(labels,values) if value is not None]
            if not pairs: return
            fig=Figure(figsize=(7.0,2.7),dpi=160); FigureCanvasAgg(fig); ax=fig.add_subplot(111)
            x,y=zip(*pairs)
            unit = 'Percent (%)' if unit.startswith('Percent') else unit if len(unit)<30 else 'Value in source units'
            if bars:
                ax.barh(x[::-1],y[::-1],color='#315b7d');ax.set_xlabel(unit)
            else:
                positions=list(range(len(x)));ax.plot(positions,y,color='#315b7d',linewidth=1.6)
                step=max(1,len(x)//6); ax.set_xticks(positions[::step],x[::step],rotation=18,ha='right');ax.set_ylabel(unit)
            ax.set_title(title,loc='left',fontsize=11);ax.tick_params(labelsize=8);ax.spines[['top','right']].set_visible(False)
            fig.text(.015,.01,scope,fontsize=7,color='#444444');fig.tight_layout(rect=(0,.04,1,1))
            stream=io.BytesIO();fig.savefig(stream,format='png');images[key]=stream.getvalue();fig.clear()
        series=data['series']
        draw('revenue','Observed item revenue',[p['period'] for p in series],[p.get('revenue') for p in series],data['money_unit'])
        draw('orders','Observed distinct order volume',[p['period'] for p in series],[p.get('orders') for p in series],'Orders')
        draw('categories','Leading categories by item revenue',[p.get('category') or 'Unmapped' for p in data['categories']],[p.get('revenue') for p in data['categories']],data['money_unit'],True)
        draw('statuses','Order status distribution',[p.get('status') or 'Unknown' for p in data['statuses']],[p.get('orders') for p in data['statuses']],'Orders',True)
        customers=data['evidence'].get('customers',{})
        draw('customers','Purchase frequency among observed customers',[str(p['orders'])+' orders' for p in customers.get('frequency',[])],[p['customers'] for p in customers.get('frequency',[])],'Customers',True)
        customer_series=[p for p in customers.get('series',[]) if p.get('first_time') is not None and p.get('returning') is not None]
        if customer_series:
            fig=Figure(figsize=(7,2.7),dpi=160);FigureCanvasAgg(fig);ax=fig.add_subplot(111)
            x=list(range(len(customer_series)));first=[p['first_time'] for p in customer_series];returning=[p['returning'] for p in customer_series]
            ax.bar(x,first,label='First observed purchase',color='#315b7d');ax.bar(x,returning,bottom=first,label='Returning purchase',color='#b47722')
            step=max(1,len(x)//6);ax.set_xticks(x[::step],[p['period'] for p in customer_series][::step],rotation=18,ha='right');ax.set_title('First observed and returning customer revenue',loc='left',fontsize=11);ax.set_ylabel('Revenue in source units');ax.legend(fontsize=8);ax.tick_params(labelsize=8)
            fig.text(.015,.01,scope,fontsize=7);fig.tight_layout(rect=(0,.04,1,1));stream=io.BytesIO();fig.savefig(stream,format='png');images['customer_revenue']=stream.getvalue();fig.clear()
        delivery=data['evidence'].get('sellers',{}).get('cards',[])
        delivery=[p for p in delivery if 'rate' in p['label'].lower()]
        draw('delivery','Eligible completed delivery rates',[p['label'] for p in delivery],[p['value'] for p in delivery],'Percent of eligible completed orders',True)
        for chart in data.get('specialist_charts',[]):
            if chart.get('y') in ('days','cancellation_rate'):
                draw(chart['y'],chart['title'],[p[chart['x']] for p in chart['data']],[p.get(chart['y']) for p in chart['data']], 'Days' if chart['y']=='days' else 'Percent (%)')
        forecast=data.get('forecast')
        if forecast:
            fig=Figure(figsize=(7,2.7),dpi=160);FigureCanvasAgg(fig);ax=fig.add_subplot(111)
            history=forecast['history_tail'];future=forecast['forecast']
            ax.plot(range(len(history)),[p['orders'] for p in history],label='Observed orders',color='#315b7d')
            ax.plot(range(len(history),len(history)+len(future)),[p['orders'] for p in future],label='Model estimates',linestyle='--',color='#b47722')
            ax.axvline(len(history)-.5,color='#777777',linestyle=':');ax.set_xticks([0,len(history)-1,len(history)+len(future)-1],[history[0]['date'],history[-1]['date'],future[-1]['date']])
            ax.set_ylabel('Expected orders');ax.set_title('Observed history and future model estimates',loc='left');ax.legend(fontsize=8);ax.tick_params(labelsize=8);fig.tight_layout()
            stream=io.BytesIO();fig.savefig(stream,format='png');images['forecast']=stream.getvalue();fig.clear()
        fig=Figure(figsize=(7,1.2),dpi=160);FigureCanvasAgg(fig);ax=fig.add_subplot(111);ax.axis('off')
        for x,label in zip((.04,.40,.76),('Authorized scope','SQL aggregates','Charts and DOCX')):
            ax.text(x,.5,label,transform=ax.transAxes,fontsize=9,bbox={'boxstyle':'round,pad=0.5','facecolor':'#f3f5f7','edgecolor':'#999999'})
        ax.text(.30,.5,'→',fontsize=16,transform=ax.transAxes);ax.text(.66,.5,'→',fontsize=16,transform=ax.transAxes)
        stream=io.BytesIO();fig.savefig(stream,format='png',bbox_inches='tight');images['flow']=stream.getvalue();fig.clear()
    return images


def generate(db, filters):
    if not REPORT_SLOTS.acquire(blocking=False):
        raise HTTPException(429,'Report generation is busy. Retry when the current report finishes.')
    driver = None
    deadline = time.monotonic()+120
    try:
        if db is not None and db.get_bind().dialect.name == 'sqlite':
            driver = db.connection().connection.driver_connection
            driver.set_progress_handler(lambda: int(time.monotonic()>deadline),10000)
        from app.services.word_document import build
        data=snapshot(db,filters)
        return build(data,charts(data))
    except OperationalError:
        if time.monotonic()>deadline:
            raise HTTPException(503,'Report aggregation exceeded its time budget. Select a narrower date range and retry.') from None
        raise
    finally:
        if driver is not None: driver.set_progress_handler(None,0)
        REPORT_SLOTS.release()
