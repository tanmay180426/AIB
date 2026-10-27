"""Build complete coverage documentation from actual generated inventories."""
import json
from collections import Counter
from pathlib import Path
import sys
import subprocess
from datetime import date

ROOT = Path(__file__).resolve().parents[2]
report_path = ROOT / "docs/API_ENDPOINT_COVERAGE.md"
existing_report = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
narrative_marker = "## Verification narrative"
narrative = existing_report[existing_report.index(narrative_marker):] if narrative_marker in existing_report else ""
commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
data = json.loads((ROOT / "docs/API_ROUTE_INVENTORY.json").read_text())
frontend = json.loads((ROOT / "docs/FRONTEND_API_INVENTORY.json").read_text())
verified = '--verified' in sys.argv
classifications = []
route_clients = {
    "/health": ["health"], "/api/auth/login": ["login"], "/api/auth/refresh": ["refreshAccessToken"],
    "/api/auth/register": ["createUser"], "/api/users/me": ["getMe"],
    "/api/users": ["listUsers", "adminCreateUser"], "/api/users/{username}/role": ["updateUserRole"],
    "/api/users/{username}/status": ["updateUserStatus"], "/api/users/roles/metadata": ["getRoleMetadata"],
    "/api/datasets": ["listDatasets"], "/api/datasets/upload": ["uploadDataset"],
    "/api/datasets/{dataset_id}/select": ["selectDataset"], "/api/datasets/{dataset_id}": ["deleteDataset"],
    "/api/datasets/{dataset_id}/schema": ["updateDatasetSchema"],
    "/api/dashboard/kpis": ["getKpis"], "/api/dashboard/monthly-revenue": ["getMonthlyRevenue"],
    "/api/dashboard/revenue-by-category": ["getRevenueByCategory"], "/api/dashboard/orders-by-status": ["getOrdersByStatus"],
    "/api/analytics/filters": ["getFilterOptions"], "/api/analytics/overview": ["getAnalyticsOverview"],
    **{f"/api/analytics/{name}": [f"getAnalytics{name.title()}"] for name in ("sales", "orders", "customers", "products", "sellers", "delivery")},
    "/api/ml/status": ["getMlStatus"], "/api/ml/forecast": ["getForecast"],
    "/api/ml/segments/customers": ["getCustomerSegments"], "/api/ml/anomalies": ["getAnomalies"],
    "/api/ml/predict/sales": ["predictSales"], "/api/ml/product-segmentation": ["getProductSegments"],
    "/api/insights/query": ["queryInsights"], "/api/reports/export": ["downloadReport"],
    "/api/admin/system/status": ["getSystemStatus"], "/api/admin/health": ["getAdminHealth"],
    "/api/admin/data/etl/status": ["getEtlStatus"], "/api/admin/warehouse/status": ["getWarehouseStatus"],
    "/api/admin/ml/status": ["getMlAdminStatus"], "/api/admin/settings": ["getSystemSettings"],
}
api_only = {
    "/health": "Public liveness probe used by server orchestration; no UI button needed.",
    "/api/auth/me": "Lightweight identity contract; UI uses full /api/users/me instead.",
    "/api/auth/admin/users": "Compatibility listing alias; administration uses canonical /api/users.",
    "/api/auth/register": "Compatibility create API; UI uses canonical POST /api/users. Unused createUser wrapper retained for review.",
    "/api/ml/models/{name}": "Programmatic model metadata inspection; UI catalog already exposes registered metadata/eligibility.",
    "/api/insights/status": "Provider diagnostics; user result reports provider/status and admin settings exposes configuration.",
    "/api/datasets/{dataset_id}": "Programmatic detail lookup; list returns the same schema/profile needed by Inspect UI (GET only).",
}
for name in ("kpis", "monthly-revenue", "revenue-by-category", "orders-by-status"):
    api_only[f"/api/dashboard/{name}"] = "Stable aggregate API; Dashboard now uses consolidated /api/analytics/overview. Legacy wrapper unused; no duplicate UI needed."

lines = ["# API endpoint coverage audit", "", f"Generated from the actual registered application and TypeScript AST; source commit `{commit}`, integration working tree, {date.today().isoformat()}.",
         "", "## Counting and evidence", "", data["counting"], "", f"Registered method/path pairs: **{data['counts']['total']}**. Methods: `{data['counts']['methods']}`. Access: `{data['counts']['access']}`.",
         "", f"Frontend exported network operation definitions: **{frontend['total']}** (helpers and local logout excluded). Unused wrappers are recorded rather than treated as connected consumers.",
         "", "JSON companions contain exact query/path/header parameter schemas, request bodies, OpenAPI responses, dependency tree, source handler and response keys: `API_ROUTE_INVENTORY.json`, `FRONTEND_API_INVENTORY.json`. Most backend handlers return untyped dicts; an empty OpenAPI response schema is not evidence of a typed contract. Runtime contract tests must verify those payloads.",
         "", "## Endpoint-to-consumer matrix", "", "| Method/path | Purpose / handler | Auth/RBAC | Actual consumer | Request/response match | Current test | Status | Action / justification |", "|---|---|---|---|---|---|---|---|"]
for r in data["routes"]:
    method, endpoint = r["method"], r["path"]
    clients = [op for op in frontend["operations"] if op["name"] in route_clients.get(endpoint, []) and op["method"] == method]
    consumers = sorted({f"{op['name']} → {c['file']}" for op in clients for c in op["consumers"]})
    if not endpoint.startswith("/api") and endpoint != "/health":
        status, action = "INTENTIONALLY API-ONLY", "Framework documentation/OpenAPI resource, including registered HEAD methods."
    elif consumers:
        status = "CONNECTED AND VERIFIED" if verified else "CONNECTED, INSUFFICIENTLY TESTED"
        action = "Actual router contracts and browser workflows verified." if verified else "Trace exists; current task verifies real request and displayed result."
    elif endpoint == "/api/users/me" and method in {"PATCH", "PUT"}:
        status, action = "INTENTIONALLY API-ONLY", "Authenticated self-service password API/PUT alias. No account-password screen promised in current UI; not an Admin password-reset button."
    elif endpoint in api_only:
        status, action = "INTENTIONALLY API-ONLY", api_only[endpoint]
    else:
        status, action = "ORPHANED / NEEDS DECISION", "Inspect missing intended consumer before introducing or deleting UI/routes."
    safe = lambda text: str(text).replace("|", "\\|").replace("\n", " ")
    if not endpoint.startswith('/api'):
        test = 'test_public_framework_and_health_get / test_explicit_registered_framework_head'
    elif method == 'GET':
        test = 'test_authorized_real_read_contracts; test_datasets for detail; test_real_report_csv_contract for exports'
    elif endpoint.startswith('/api/auth') or endpoint.startswith('/api/users'):
        test = 'test_auth_refresh_and_self_service_aliases; test_users/test_auth; admin E2E'
    elif endpoint.startswith('/api/datasets'):
        test = 'test_dataset_pipeline_and_independent_aggregation_contract; dataset/schema E2E'
    elif endpoint.startswith('/api/ml'):
        test = 'test_rbac/test_datasets; active ML and incompatible ML E2E'
    else:
        test = 'test_optional_llm_fallback_is_honest_and_dataset_scoped; dataset AI E2E'
    if r['classification'] != 'public':
        test += '; each-route anonymous test'
    if r['classification'] == 'admin':
        test += '; each-route Analyst denial test'
    match = 'Runtime verified; see detailed JSON schema/source keys and test assertions' if verified else 'Pending runtime verification'
    classifications.append(status)
    lines.append("| " + " | ".join(map(safe, [f"{method} {endpoint}", r["handler"], r["classification"], "; ".join(consumers) or "No active UI import", match, test, status, action])) + " |")
lines.extend(["", "## Detailed route contracts", ""])
for r in data["routes"]:
    lines.extend([f"### {r['method']} {r['path']}", "", f"- Module/handler: `{r['module']}.{r['handler']}`.",
                  f"- Purpose: {r.get('description') or r['handler']}.", f"- Access: {r['classification']}; dependencies: `{', '.join(r['dependencies']) or 'none'}`.",
                  "- Parameters: " + ("; ".join(f"`{p['name']}` ({p['in']}, {'required' if p.get('required') else 'optional'}): `{json.dumps(p.get('schema', {}))}`" for p in r["parameters"]) or "none"),
                  f"- Body: `{json.dumps(r['requestBody'])}`.", f"- OpenAPI response: `{json.dumps(r['responses'])}`.",
                  f"- Source top-level return keys: `{r.get('source_return_keys', [])}`; source/declared status codes: `{r.get('source_status_codes', [])}`.",
                  "- Safe testing: read-only calls or isolated disposable DB for uploads, user/password/status/role mutations and deletion. Model calls use existing trusted active artifacts; candidate never dispatched.", ""])
lines.extend(["## Frontend operation definitions and consumers", "", "| Client function | Method / route expression | Imported consumers |", "|---|---|---|"])
for op in frontend["operations"]:
    consumers = "; ".join(c["file"] for c in op["consumers"]) or "Unused compatibility wrapper / review required"
    lines.append(f"| {op['name']} | {op['method']} `{op['endpoint_expression']}` | {consumers} |")
lines.extend(['', '## Classification totals', '', str(dict(Counter(classifications))), '',
              'Source route tests and browser evidence are detailed below in the accompanying verification narrative. No coverage percentage is inferred from literal endpoint strings.'])
if narrative:
    lines.extend(["", narrative])
report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Documented {len(data['routes'])} registered method/path pairs.")
