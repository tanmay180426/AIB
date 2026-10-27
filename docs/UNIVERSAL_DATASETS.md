# Dataset-driven platform

## User workflow

Sign in as an Admin or Analyst, open **Dataset Manager**, enter a name, and upload
one CSV, XLSX/XLS worksheet, or JSON array of flat records. The manager displays
upload/processing progress and the registered READY or FAILED result. Inspect a
dataset to see its fields, types, confidence, missing values, duplicates and
capabilities. Select a READY dataset in the header or manager. The active dataset
name remains visible on every application page.

### Folder and ZIP bundles

Use **Upload Folder** in Chromium/Edge to select an actual directory (including
nested folders), or **Upload ZIP** if directory selection is unavailable. Folder
and ZIP bundles support CSV only; the separate Upload File workflow retains
CSV/XLSX/XLS/flat JSON support. Review the bundle name, file manifest, counts and
sizes, then choose **Confirm bundle import**. ZIP contents receive a server-side
manifest preflight before import. OS noise is ignored; other unsupported files
are rejected, not silently dropped.

One bundle groups independently stored tables. Inspect the bundle, choose
**Inspect table** for the first 20 rows, columns, quality and semantic mappings,
then confirm each table's schema as needed. Select the bundle and use
**Active Table** to choose the source for Dashboard, Analytics, numerical Insights
and CSV reports. Table IDs are distinct from the parent bundle ID. Switching
tables clears active filters and stale responses. Delete requires confirmation
and removes the whole bundle and its tables under the existing owner policy;
Admin privileges do not grant access to another user's uploads.

Imports are atomic: every file must validate and storage must succeed before
any READY bundle is committed. A failure leaves no partially imported bundle;
correct the reported files and retry. The UI reports validation/processing
stages, not an invented upload percentage. Duplicate relative paths are rejected;
duplicate basenames in different subfolders retain separate UUID tables.

Incoming payload is limited to **200 MiB (209,715,200 bytes)** for single-file,
folder aggregate and compressed ZIP uploads. ZIP expansion has a separate
**512 MiB** budget. Bundles allow 5,000,000 rows / 40,000,000 cells in total,
1,500,000 rows / 12,000,000 cells per table, 100 columns per table and 900 seconds.
Single-file row/cell/time limits stay 100,000 / 2,000,000 / 60 seconds.
The separate XLSX expansion limit remains 200 MiB; raising the payload cap does
not multiply spreadsheet decompression budgets. Multipart reception is bounded
before framework spooling to the payload cap plus 1 MiB for framing, with one
receiver at a time and 429 while another import is processing.
There are 32 CSVs, 64 ZIP entries and a maximum per-member compression ratio of
100:1. Each safety budget has a distinct error. The authenticated
`GET /api/datasets/upload-limits` reports the current configured values.
UTF-8/BOM and existing CSV delimiter handling are retained. Empty/malformed CSVs,
duplicate headers, invalid paths, symlinks, nested archives, special files,
encrypted/corrupt ZIPs and oversized collections are rejected. ZIPs are read in
bounded memory without filesystem extraction.

Recognized Olist schemas support a bundle overview when order IDs are unique,
non-null and purchase timestamps validated. Dimension keys are checked over the
complete table for uniqueness, compatible types, nulls and unmatched records.
Items and payments are aggregated independently; they are never joined to each
other before aggregation. Totals use their native fact grain and RFM uses item
prices aggregated to order grain.
Item revenue is sum(price), excluding freight, and is never added to payments.
Category/seller filters restrict eligible items and orders; average order value
is qualifying item revenue / matching distinct orders. Date/status/customer
filters restrict orders. Payment/review filters use existence tests to select
orders; payment and review summaries then cover all facts for those orders. Duplicate
dimension keys disable their joins/filters. Repeated geolocation prefixes are
disclosed and never directly joined. Generic schemas retain table-specific BI.

After import choose **Open bundle Dashboard**; **Active Table** switches between
overview and individual tables. KPIs, trends, category/status summaries, review
scores, delivery days, numerical Insights and aggregate exports share filters.
Select a table for raw-row export. Confirm currency/domain before monetary ML.
Unknown currency and real/synthetic provenance are never inferred from filenames.

The local enriched Olist ZIP is not included in this repository. Review the
README's data provenance and limitations before obtaining or using any source
dataset. Bundle limits are configurable in the local environment.

Uploads at least 2 MiB return an owner-scoped 202 job. One bundle import runs at
a time; concurrent requests receive 429. The UI polls actual stages, current
table, completed-table and stored-row counts, and remembers the job ID to resume
after navigation/reload. Cancellation/deadline failure rolls back all tables.
Status expires one hour after completion. API restart loses in-memory job status;
check the persisted bundle list before retrying. Run one API worker locally.
Sources are spooled to a server-created temporary directory. Only one CSV's
bounded source/profile frame is materialized at a time; inserts use 5,000-row
batches. Temporary sources are cleaned on completion/failure. SQLite WAL allows
auth/status readers during imports; explicit transactions also cover table DDL.

The Dashboard shows dataset/bundle/table context, shared filter summary/reset,
observed capability-aware metrics, current-filter trends/distributions and
whole-table profile quality labelled separately. Unknown currency stays unknown;
no conversion or fabricated growth is applied. No matching rows, missing
capabilities, loading and retryable errors have explicit states. Uploads,
analytics, Insights and exports remain local and require no paid API or LLM.

Bundle APIs: `POST /api/datasets/bundles/upload` (multipart files + paths + name),
`POST /api/datasets/bundles/zip-preview`, `POST /api/datasets/bundles/zip`, existing
detail/select/schema/delete routes and `GET /api/datasets/{table_id}/preview`.
The additive `app_dataset_bundle_table` catalog is created check-first; no
existing dataset columns or database rebuild are required.

Uploads do not automatically merge with other datasets or replace the selected
dataset. Every upload receives a UUID. A failed dataset can be inspected/deleted
but cannot be selected. Owners may delete their own uploads. The registered
shared Olist reference is read-only. Deleting the current dataset requires an
explicit new selection; it never causes an Olist fallback.

## Existing architecture

React routing, layouts, six analytics pages, dashboard, reports, ML pages,
assistant, authentication and Admin/Analyst permissions remain in use. There is
no Viewer role, alternate dashboard route, second chatbot or training system.

FastAPI's shared BI dependency authenticates the caller, resolves the explicit
`X-Dataset-ID`/`dataset_id` or saved per-user selection, checks ownership and
readiness, and attaches that context to the existing SQLAlchemy request session.
All BI routers use this dependency. Contradictory IDs are rejected. Unknown
filters are rejected rather than silently ignored.

The registry and selections are new tables in the existing application database.
Each upload has a private, typed table with server-generated UUID/c0..c99
identifiers. Original names remain metadata and SQLAlchemy expressions bind
values. No uploaded name becomes a filesystem path or executable SQL identifier.
The existing `analytics.metrics` layer selects its storage adapter centrally.
Reference star-schema queries retain their existing grain and conditional joins;
uploaded tables aggregate through SQL in the same metric layer. Existing KPI
wrappers, routes, reports and AI tools call that shared layer.

## Ingestion and lifecycle

The authenticated upload handler bounds source bytes before parsing. Defaults:
200 MiB payload, 100,000 rows, 100 columns, 2,000,000 cells and 60 seconds for
single-file processing. Folder/ZIP processing uses the separate bundle budgets.
These limits are configurable with the DATASET_* settings in `.env.example`.
Inserts use batches of 1,000 rows. Appropriate date/entity/category columns receive
indexes. Expanded XLSX data is bounded; macros and external spreadsheet links
are rejected. Headers, duplicate names, consistent CSV row width, UTF-8 encoding,
empty data, flat JSON structure and finite numeric values are checked.

XLSX requires openpyxl; XLS requires xlrd. A missing reader produces a clear
failure and recommends exporting to a supported format. Multi-sheet workbooks
and nested JSON are rejected explicitly. Raw source bytes are preserved privately
in the registry, normalized values in the dataset's table, and metadata in JSON
columns. Raw source bytes never appear in public responses or the LLM context.
Parsing failures retain a FAILED record and remove partial storage. Errors from
database/reader internals are replaced with safe messages.

Single-file and small-bundle uploads remain synchronous. Large folder/ZIP
imports use the status job above. Failed bundles never become READY; uploads
never train models. Distributed processing and automatic retries are not used.

## Schema intelligence

Profiling detects numeric, datetime, boolean, text and identifier-like fields;
missing count/percentage, unique count, constants and duplicate rows; numeric
min/max/mean/median/standard deviation; ambiguous and invalid dates. Semantic
aliases normalize camelCase, underscores and spacing. Types and observed values
must support the proposed role: monetary, quantity and rating inputs must be
numeric, and date roles must parse successfully.

Customer/client, product/item, seller/vendor, order/transaction, monetary amount,
revenue, quantity, location, category, status, rating, delivery and estimated date
roles are distinguished. User/account identities can support entity analytics
with user/account terminology. Student IDs and phone-like identifiers remain
identifiers; age and coordinates never automatically become revenue. `amount` is
a monetary amount, not automatically revenue. Currency is detected only from
explicit currency codes or measure suffixes such as `revenue_brl`, otherwise
remains unknown. Confidence is a heuristic evidence score, not calibrated model
probability.

Several candidates for a material role disable automatic selection and record
the ambiguity. Dataset inspection offers optional mapping correction, units and
domain confirmation. Ambiguous slash dates require day/month-order confirmation.
Known incompatible numeric/date mapping choices return 422. Corrections update
capabilities and the dataset revision so active content reloads.

## Analytics and filters

The existing dashboard/sales content displays observed measures, row/entity
counts, numeric summaries, categorical distributions and time trends. Numeric
identifiers are excluded from measure selection. Missing measures remain null;
an empty filtered population shows zero matching rows and no observed values.
There is no invented revenue or percentage and no implied Brazilian currency for
unknown monetary units. Trends support day, week, month, quarter and year.

Orders/transactions, customer/account, product/item and seller/vendor sections
require their corresponding semantic identities. Delivery duration requires
confirmed analytical/delivered dates; on-time percentage additionally requires
estimated dates. Unavailable sections remain accessible and explain the missing
requirements. Entity tables are bounded rankings, not entire browser datasets.

The existing `useFilters` URL state and `FilterBar` remain the only filter system.
Uploaded categorical controls come from that dataset's distinct values; date
controls appear only with a confirmed analytical date. Selected values are sent
as validated `column_filters` JSON or existing semantic filters. Filter values
are bound in SQL and apply before aggregation, reporting, AI context and inference.
Navigation preserves the filter URL. Switching datasets clears those filters,
remounts dependent page state, and discards responses from an older generation.
Concurrent identical GETs are coalesced only while pending; the key includes user,
dataset generation and full parameters. Completed results are not cached.

Reference revenue/freight use filtered item totals. Order-grain filters use a
set-based matching-item scope without multiplying orders. This corrects a
pre-existing category-filter KPI/report mismatch while preserving unfiltered
Olist totals.

## Existing trained models

No model is trained or replaced on upload. Reviewed contracts extend existing
metadata JSON. Existing artifact loaders, saved scalers, pipelines and algorithms
are reused. Compatibility and artifact availability are separate facts. Responses
include dataset identity, compatibility, reasons and training domain. Missing
artifacts produce 503; incompatible inputs produce `status: not_applicable` with
no predictions. Output numbers are checked for finiteness.

| Model | Required semantics | Existing inference | Additional requirements |
|---|---|---|---|
| Revenue forecast | Date, revenue | Linear regression on saved lag/rolling features | Confirmed commerce/transaction domain, BRL, at least 30 daily observations |
| Order forecast | Date, order ID | Same existing forecast pipeline, order target | Commerce/transaction domain and at least 30 daily observations |
| Product segmentation | Product, quantity, revenue, price, weight in grams | Saved StandardScaler + KMeans; log1p quantity/revenue | Confirmed commerce domain and BRL; complete, nonnegative features |
| Customer segmentation | Customer/account, order, date, revenue | Saved RFM scaler + KMeans | Commerce/transaction domain, BRL, complete required inputs |
| Anomaly detection | Date, order, revenue | Saved IsolationForest on daily aggregates | Commerce/transaction domain, BRL, at least 30 daily observations |
| Sales prediction | Date, order, quantity, location, category, revenue | Saved checkout feature pipeline on the existing request inputs | Commerce/transaction domain, BRL, complete required fields |

Uploaded forecasts/anomaly inputs require the latest 30 observations to represent
consecutive days. Missing days are not silently converted to zero. Legacy
reference forecasting preserves the existing observed-day lag convention.
Historical forecast actuals now come from the selected warehouse and filters,
not the fixed training CSV. Customer recency uses the selected population's most
recent purchase plus one day, consistent with the training transformation.
Reference rows without purchase dates are excluded as during training.

ML Metrics explicitly label offline Olist evaluation metrics. They do not measure
accuracy on an upload. Schema/units compatibility is necessary, not proof of
statistical generalization, drift tolerance or forecasting accuracy. Models can
return Not Applicable for otherwise valid datasets. Additional domains/units
require a reviewed contract/model deployment, not fabricated predictions.

## AI grounding

The existing assistant builds authorized, filter-scoped context containing the
dataset ID/name, schema roles, capabilities and calculated aggregates. It receives
no arbitrary SQL tool, cross-dataset access, raw sources or administration data.
There is no embeddings/vector store in this repository.

Numerical questions use deterministic calculated facts: total/count, average,
median, minimum and maximum for named observed fields and bounded grouped
sum/mean/count by named dimensions. Unavailable intents explain missing fields.
Sources include the dataset identity. Qualitative questions may use the existing
Ollama provider with bounded aggregate context; if it is unavailable, the existing
data-grounded summary remains available. Uploaded text is treated as untrusted
data in the prompt. Switching remounts the assistant and removes previous results.

## Reports, exports and security

All existing report endpoints now consume the same complete filter object as
analytics. KPIs, monthly series, category/status aggregates and additional uploaded
numeric-statistics/raw-row CSV exports are authorized and dataset-scoped. Responses
identify the dataset in an HTTP header. The UI verifies the current generation
before starting a download. Export strings starting with spreadsheet formula
characters are escaped; numeric cells remain numeric.

Both roles can manage their own uploads; neither can access another user's
private upload by manipulating an ID, including administrators. The only shared
dataset is the registered reference. Authentication also rejects disabled users
and refresh tokens presented as access tokens. Last-admin protection and the
two-role policy remain in use. Uploaded filenames are never written as paths or
executed. SQL identifiers are generated/validated, query values parameterized,
and semantics checked against the dataset's own schema.

## Boundaries and operations

This implementation supports one flat logical table per upload. Existing related
Olist files remain supported through the existing intentional ETL/star-schema
adapter. Automatic joins of arbitrary multi-file uploads are not supported:
inferring shared ID spelling does not establish join cardinality or additive
measure grain, and could duplicate financial results. Upload each unrelated file
as its own dataset; multi-sheet/nested structures receive explicit errors.

UTF-8 CSV, ISO/common unambiguous dates and ordinary finite numeric cells are
supported. Localized monetary strings/encodings may require re-export. Processing
time is checked between parsing/profiling/storage phases and insert batches;
there is no hard worker-process timeout around third-party parsers. Byte, expanded
size, row, column and cell budgets bound their inputs. Large-scale deployments
should supply a dedicated job worker and database-specific resource quotas.

SQLite is the verified local runtime. PostgreSQL remains the existing documented
deployment target; SQLAlchemy storage and date expressions include PostgreSQL
support, but an actual PostgreSQL instance was not available for this verification.
Dataset changes are persisted per user; requests carry an explicit ID so concurrent
browser tabs retain their own displayed context. No automatic cross-user sharing
or private-data promotion is introduced.

Tests use small synthetic Sales, Student, Transaction, Minimal and Ambiguous data,
real saved-model inference on a compatible 40-day commerce fixture, and the loaded
Olist reference. Playwright starts the real API on a disposable SQLite backup so
browser uploads do not alter the developer database. See
`UNIVERSAL_DATASET_REPORT.md` for executed results and the audit.
