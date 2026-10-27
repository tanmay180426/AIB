import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.analytics import metrics
from app.analytics.filters import Filters, analytics_filters
from app.api.deps import get_current_user
from app.database.deps import get_db
from app.services import users as user_service

router = APIRouter()


@router.get('/business-sales.docx', response_class=Response)
def business_sales_document(f: Filters = Depends(analytics_filters), db: Session = Depends(get_db),
                            user: dict = Depends(get_current_user)):
    if not user_service.role_at_least(user, 'analyst'):
        raise HTTPException(403, 'Requires analyst role to generate business reports.')
    from app.services.business_report import generate
    content = generate(db, f)
    return Response(content, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition':'attachment; filename="business-sales-analysis.docx"',
                 'X-Dataset-ID':db.info['dataset'].id, 'Cache-Control':'no-store'})

# Business reports are shared BI functionality: admin and analyst alike.
REPORT_ACCESS = {
    "kpis": "analyst",
    "monthly_revenue": "analyst",
    "revenue_by_category": "analyst",
    "orders_by_status": "analyst",
    "dataset_rows": "analyst",
    "numeric_statistics": "analyst",
}


def _csv_value(value):
    return "'"+value if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')) else value


def _to_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.writer(buf)
    keys = list(rows[0].keys())
    # Headers are also untrusted upload strings, not just cell values.
    writer.writerow([_csv_value(k) for k in keys])
    writer.writerows([[_csv_value(row.get(k)) for k in keys] for row in rows])
    return buf.getvalue()


def _build_rows(report: str, db: Session, filters: Filters) -> list[dict]:
    ds = db.info.get("dataset")
    if report in {"dataset_rows", "numeric_statistics"}:
        if ds and ds.source_type == 'bundle':
            raise HTTPException(422,'Select an individual bundle table for raw-row or numeric-statistics export. Bundle KPI and chart exports use order-grain aggregates.')
        if not ds or ds.adapter != "tabular":
            raise HTTPException(422, "This export requires an uploaded tabular dataset.")
        from app.analytics.tabular import TabularSource
        source = TabularSource(db, filters)
        if report == "numeric_statistics":
            from app.analytics.tabular import _technical_column
            return [source.numeric_stats(c) for c in source.columns
                    if c["dtype"] == "numeric" and c["role"] != "identifier" and not _technical_column(c)]
        return source.rows(source.statement(*[source.by_name[c["name"]].label(c["name"]) for c in source.columns]).order_by(source.table.c.row_id))
    if report == "kpis":
        data = metrics.kpis(db, filters)
        return [{"metric": k, "value": v} for k, v in data.items()]
    if report == "monthly_revenue":
        return metrics.time_series(db, filters, "month")
    if report == "revenue_by_category":
        return metrics.revenue_by_category(db, filters)
    if report == "orders_by_status":
        return metrics.orders_by_status(db, filters)
    raise HTTPException(status_code=404, detail=f"unknown report '{report}'")


@router.get("/export", response_class=StreamingResponse, responses={
    200: {"description": "Filtered CSV export scoped to the authorized selected dataset.",
          "content": {"text/csv": {"schema": {"type": "string"}}}}
})
def export_report(
    report: str = Query("kpis"),
    f: Filters = Depends(analytics_filters),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    if report not in REPORT_ACCESS:
        raise HTTPException(status_code=404, detail=f"unknown report '{report}'")

    if not user_service.role_at_least(user, REPORT_ACCESS[report]):
        raise HTTPException(
            status_code=403, detail=f"Requires {REPORT_ACCESS[report]} role to export '{report}'"
        )

    if report=='dataset_rows':
        from app.services import datasets as dataset_service
        from app.analytics.tabular import TabularSource
        ds=db.info['dataset']
        if ds.source_type=='bundle' or ds.adapter!='tabular':
            raise HTTPException(422,'Select an individual uploaded table for raw-row export.')
        # FastAPI 0.115 closes dependency sessions before streaming. Own the
        # reader explicitly so large exports remain bounded and correctly scoped.
        reader=Session(db.get_bind()); result=None;closed=False
        try:
            selected=dataset_service.authorized(reader,ds.id,user,ready=True)
            reader.info['dataset']=selected;source=TabularSource(reader,f)
            columns=source.columns
            query=source.statement(*[source.by_name[c['name']] for c in columns]).order_by(source.table.c.row_id)
            result=reader.execute(query.execution_options(stream_results=True,yield_per=1000))
        except Exception:
            reader.close();raise
        def cleanup():
            nonlocal closed
            if not closed:
                closed=True;result.close();reader.close()
        def chunks():
            try:
                buf=io.StringIO();writer=csv.writer(buf)
                writer.writerow([_csv_value(c['name']) for c in columns]);yield buf.getvalue();buf.seek(0);buf.truncate(0)
                for batch in result.partitions(1000):
                    writer.writerows([[_csv_value(v) for v in row] for row in batch])
                    yield buf.getvalue();buf.seek(0);buf.truncate(0)
            finally:cleanup()
        return StreamingResponse(chunks(),media_type='text/csv',background=BackgroundTask(cleanup),
            headers={'Content-Disposition':'attachment; filename="dataset_rows.csv"','X-Dataset-ID':ds.id})

    rows = _build_rows(report, db, f)
    csv_text = _to_csv(rows)

    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{report}.csv"',
                 "X-Dataset-ID": db.info["dataset"].id},
    )
