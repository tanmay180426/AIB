"""Atomic bounded CSV bundles. Paths are display metadata, never destinations."""
from __future__ import annotations

import csv
import io
import re
import stat
import time
import uuid
import zipfile
import zlib
import threading
from pathlib import Path
from pathlib import PurePosixPath

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import select

from app.models.dataset import Dataset, DatasetBundleTable
from app.services import datasets as service

MAX_FILES = 32
MAX_RATIO = 100
from app.core.config import settings
MAX_EXPANDED_BYTES = settings.BUNDLE_MAX_EXPANDED_BYTES
MAX_TABLE_ROWS = settings.BUNDLE_MAX_TABLE_ROWS
MAX_TABLE_CELLS = settings.BUNDLE_MAX_TABLE_CELLS
MAX_ROWS = settings.BUNDLE_MAX_ROWS
MAX_CELLS = settings.BUNDLE_MAX_CELLS
MAX_SECONDS = settings.BUNDLE_MAX_SECONDS
IMPORT_LOCK = threading.Lock()
RELATIONSHIP_LIMITATION = "Cross-table analytics are not supported. Metrics use only the selected table; no joins or combined monetary totals are calculated."


def normalized_path(value):
    value = value.replace("\\", "/")
    path = PurePosixPath(value)
    if (not value or len(value) > 500 or value.startswith("/") or
            any(p in {"", ".", ".."} for p in value.split("/")) or
            any(ord(c) < 32 for c in value) or ":" in value):
        raise HTTPException(422, "Invalid relative file path. Use folder-relative paths without traversal or drive names.")
    return str(path)


def noise(path):
    return any(p in {"__MACOSX", ".DS_Store", "Thumbs.db"} or p.startswith("._") for p in path.split("/"))


def unzip(raw):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_FILES * 2:
                raise HTTPException(413, f"Archive exceeds the {MAX_FILES * 2} entry limit (including directories).")
            files = []
            total = 0
            for entry in entries:
                path = normalized_path(entry.filename.rstrip("/") if entry.is_dir() else entry.filename)
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))):
                    raise HTTPException(422, "ZIP contains a symlink or special file; only ordinary CSV files are supported.")
                if noise(path) or entry.is_dir():
                    continue
                if not path.lower().endswith(".csv"):
                    raise HTTPException(422, f"Unsupported entry: {path}. Bundles support CSV only; nested archives are not supported.")
                total += entry.file_size
                if total > MAX_EXPANDED_BYTES:
                    raise HTTPException(413, f"ZIP expanded size {total} bytes exceeds the {MAX_EXPANDED_BYTES} byte expansion budget.")
                if entry.file_size > max(entry.compress_size, 1) * MAX_RATIO:
                    raise HTTPException(413, f"ZIP compression ratio exceeds {MAX_RATIO}:1 for {path}.")
                if len(files) >= MAX_FILES:
                    raise HTTPException(413, f"Bundle exceeds the {MAX_FILES} CSV file limit.")
                with archive.open(entry) as stream:
                    content = stream.read(MAX_EXPANDED_BYTES + 1)
                if len(content) > MAX_EXPANDED_BYTES:
                    raise HTTPException(413, "ZIP entry exceeds the expansion budget.")
                files.append((path, content))
            return files
    except (zipfile.BadZipFile, RuntimeError, OSError, NotImplementedError, zlib.error, EOFError, UnicodeError):
        raise HTTPException(422, "ZIP could not be read. Use an unencrypted, valid ZIP containing CSV files.") from None


def public(ds, db):
    result = service.public(ds)
    if ds.source_type == "bundle":
        members = db.scalars(select(DatasetBundleTable).where(DatasetBundleTable.bundle_id == ds.id)
                             .order_by(DatasetBundleTable.relative_path)).all()
        result["tables"] = [public(service.authorized(db, m.dataset_id, {"username": ds.owner}), db) for m in members]
        result['column_count'] = sum(t['column_count'] for t in result['tables'])
        result['quality'] = {**result['quality'], 'missing_values':sum(t['quality'].get('missing_values',0) for t in result['tables']),
                             'duplicate_rows':sum(t['quality'].get('duplicate_rows',0) for t in result['tables']),
                             'warnings':[f"{t['relative_path']}: {warning}" for t in result['tables'] for warning in t['quality'].get('warnings',[])]}
        result["relational_analysis"] = ds.profile.get('relational_analysis', {"supported": False, "reason": RELATIONSHIP_LIMITATION})
    else:
        member = db.get(DatasetBundleTable, ds.id)
        if member:
            result.update(bundle_id=member.bundle_id, relative_path=member.relative_path,
                          internal_name=member.internal_name, original_filename=PurePosixPath(member.relative_path).name)
    return result


def semantic_fields(relation):
    fields={'date':'order_purchase_timestamp','order':'order_id','status':'order_status'}
    enabled={(r['from_table'],r['to_table']) for r in relation['relationships'] if r.get('enabled')}
    if ('items','orders') in enabled: fields.update(revenue='item_price_sum',quantity='validated_item_count',product='product_id',seller='seller_id')
    if ('orders','customers') in enabled: fields.update(customer='customer_unique_id',location='customer_state')
    if ('items','products') in enabled: fields['category']='product_category_name'
    return fields if relation['supported'] else {}


def ingest(db, user, name, files, *, expanded=False, progress=None, cancelled=None):
    if not IMPORT_LOCK.acquire(blocking=False):
        raise HTTPException(429, 'Another bundle is being processed. Retry when it finishes.')
    try:
        return _ingest(db, user, name, files, expanded=expanded, progress=progress, cancelled=cancelled)
    finally:
        IMPORT_LOCK.release()


def _ingest(db, user, name, files, *, expanded=False, progress=None, cancelled=None):
    service.ensure_registry(db)
    if not name.strip():
        raise HTTPException(422, "Bundle name is required.")
    if not files:
        raise HTTPException(422, "No supported CSV files were selected.")
    if len(files) > MAX_FILES:
        raise HTTPException(413, f"Bundle has {len(files)} files; limit is {MAX_FILES}.")
    total_bytes = sum(raw.stat().st_size if isinstance(raw, Path) else len(raw) for _, raw in files) if isinstance(files, list) else files.total_bytes
    byte_limit = MAX_EXPANDED_BYTES if expanded else service.MAX_BYTES
    if total_bytes > byte_limit:
        raise HTTPException(413, f"Bundle contains {total_bytes} bytes; {'expanded' if expanded else 'upload'} limit is {byte_limit} bytes.")
    started = time.monotonic()
    def deadline():
        if cancelled and cancelled():
            raise ValueError('Import cancelled. Nothing was imported.')
        if time.monotonic() - started > MAX_SECONDS:
            raise ValueError(f"Bundle processing exceeds {MAX_SECONDS} seconds. Nothing was imported.")
    seen = set()
    total_rows = total_cells = 0
    parent = Dataset(id=str(uuid.uuid4()), name=name.strip(), owner=user["username"], status="READY",
                     source_type="bundle", row_count=0, column_count=0, profile={}, semantics={'fields': {}, 'domain': 'general'},
                     capabilities={}, quality={"table_count": len(files), "total_bytes": total_bytes})
    created = []
    try:
        connection = db.connection()
        if connection.dialect.name == 'sqlite' and not connection.connection.driver_connection.in_transaction:
            # sqlite3 otherwise autocommits CREATE TABLE before the first INSERT.
            connection.exec_driver_sql('BEGIN IMMEDIATE')
        db.add(parent)
        for source_path, raw in files:
            path = normalized_path(source_path)
            if noise(path):
                continue
            if path.casefold() in seen:
                raise ValueError(f'Duplicate file path: {path}. Nothing was imported.')
            seen.add(path.casefold())
            if not path.lower().endswith('.csv'):
                raise ValueError(f'Unsupported file: {path}. Bundles support CSV only.')
            if isinstance(raw, Path):
                raw = raw.read_bytes()
            if progress:
                progress(stage='profiling', current_file=path, completed_tables=len(created), total_tables=len(files), stored_rows=total_rows)
            deadline()
            source = service.parse_source(raw, '.csv', max_rows=MAX_TABLE_ROWS, max_cells=MAX_TABLE_CELLS, max_bytes=MAX_EXPANDED_BYTES, check=deadline)
            frame, cols, quality = service.profile_frame(source, check=deadline)
            del source
            total_rows += len(frame)
            total_cells += len(frame) * len(cols)
            if total_rows > MAX_ROWS or total_cells > MAX_CELLS:
                raise ValueError(f'Bundle has {total_rows} rows / {total_cells} cells; total limits are {MAX_ROWS} rows / {MAX_CELLS} cells.')
            deadline()
            ds = Dataset(id=str(uuid.uuid4()), name=path[:120], owner=user["username"], status="READY",
                         source_type="csv", row_count=len(frame), column_count=len(cols), raw_source=raw,
                         profile={"columns": cols}, quality=quality, semantics=service.infer_semantics(cols))
            ds.capabilities = service.detect_capabilities(ds.semantics)
            table = service.storage_table(ds, columns=cols)
            table.create(db.connection()); created.append(table)
            for start in range(0, len(frame), 5000):
                rows = [{f"c{idx}": None if pd.isna(v) else float(v) if cols[idx]["dtype"] == "numeric" else str(v)
                         for idx, v in enumerate(values)} for values in frame.iloc[start:start+5000].itertuples(index=False, name=None)]
                if rows:
                    db.execute(table.insert(), rows)
                deadline()
                if progress:
                    progress(stage='storing', stored_rows=total_rows-len(frame)+min(start+5000,len(frame)))
            db.add(ds)
            internal = re.sub(r"[^a-zA-Z0-9_]", "_", PurePosixPath(path).with_suffix("").as_posix())[:150]
            db.add(DatasetBundleTable(dataset_id=ds.id, bundle_id=parent.id, relative_path=path,
                                      internal_name=internal + "_" + uuid.UUID(ds.id).hex[:12]))
            # Relationships need indexed keys; names here are server-generated.
            from sqlalchemy import Index
            for col in cols:
                if col['role'] in {'order', 'customer', 'product', 'seller', 'date'} or col['name'] in {'customer_id', 'product_category_name'}:
                    Index(f"ix_{table.name}_{col['storage']}", table.c[col['storage']]).create(db.connection())
            db.flush()
            del frame, rows, raw
        if not created:
            raise ValueError('No supported CSV files were selected.')
        parent.row_count = total_rows
        parent.quality = {**parent.quality, 'table_count': len(created), 'total_cells': total_cells, 'processing_seconds': round(time.monotonic()-started, 3)}
        from app.analytics.bundle import describe, analytic_indexes
        if progress: progress(stage='indexing',completed_tables=len(created),current_file=None)
        analytic_indexes(db,parent)
        relation = describe(db, parent)
        deadline()
        parent.profile = {'relational_analysis': relation}
        if relation['supported']:
            fields=semantic_fields(relation)
            parent.semantics = {'fields': fields, 'domain':'commerce', 'currency_code':None}
            parent.capabilities = service.detect_capabilities(parent.semantics)
        db.commit()
    except Exception as exc:
        db.rollback()
        for table in created:
            table.drop(db.connection(), checkfirst=True)
        db.commit()
        raise HTTPException(422, 'Nothing was imported. ' + str(exc) if isinstance(exc, (ValueError, HTTPException, csv.Error, UnicodeError)) else "Bundle storage failed. Nothing was imported; retry or use smaller CSVs.") from None
    return public(parent, db)
