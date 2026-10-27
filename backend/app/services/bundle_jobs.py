"""Single-worker, owner-scoped large imports with truthful progress and cleanup."""
from __future__ import annotations
import io
import stat
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.services import dataset_bundles as bundles, datasets

POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='bundle-import')
GUARD = threading.Lock()
JOBS = {}
ASYNC_BYTES = 2 * 1024 * 1024


def zip_manifest(source):
    """Validate metadata without materializing decompressed CSVs in memory."""
    try:
        with zipfile.ZipFile(source) as archive:
            entries=archive.infolist()
            if len(entries)>bundles.MAX_FILES*2: raise HTTPException(413,'ZIP exceeds the archive entry budget.')
            result=[]; ignored=[]; total=0; seen=set()
            for entry in entries:
                path=bundles.normalized_path(entry.filename.rstrip('/') if entry.is_dir() else entry.filename)
                mode=entry.external_attr>>16
                if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))):
                    raise HTTPException(422,'ZIP contains a symlink or special file.')
                if entry.is_dir() or bundles.noise(path):
                    ignored.append({'path':path,'reason':'Directory or operating-system metadata'}); continue
                if not path.lower().endswith('.csv'): raise HTTPException(422,f'Unsupported entry: {path}. CSV only; nested archives are forbidden.')
                if path.casefold() in seen: raise HTTPException(422,f'Duplicate relative path: {path}.')
                seen.add(path.casefold()); total+=entry.file_size
                if entry.flag_bits & 1: raise HTTPException(422,'Encrypted ZIP files are unsupported.')
                if not entry.file_size: raise HTTPException(422,f'Empty CSV: {path}.')
                if entry.file_size>max(entry.compress_size,1)*bundles.MAX_RATIO: raise HTTPException(413,f'Compression ratio exceeds {bundles.MAX_RATIO}:1 for {path}.')
                if total>bundles.MAX_EXPANDED_BYTES: raise HTTPException(413,f'Expanded CSV size {total} bytes exceeds {bundles.MAX_EXPANDED_BYTES} bytes.')
                if len(result)>=bundles.MAX_FILES: raise HTTPException(413,f'ZIP exceeds {bundles.MAX_FILES} CSV members.')
                result.append({'path':path,'member_name':entry.filename,'bytes':entry.file_size,'compressed_bytes':entry.compress_size})
            if not result: raise HTTPException(422,'ZIP contains no supported CSV files.')
            return {'files':result,'total_bytes':total,'ignored':ignored}
    except (zipfile.BadZipFile,RuntimeError,OSError,NotImplementedError,UnicodeError,EOFError):
        raise HTTPException(422,'ZIP could not be read. Use a valid, unencrypted CSV archive.') from None


class ArchiveFiles:
    def __init__(self,path,manifest):
        self.path=path; self.manifest=manifest; self.total_bytes=manifest['total_bytes']
    def __len__(self): return len(self.manifest['files'])
    def __iter__(self):
        try:
            with zipfile.ZipFile(self.path) as archive:
                for member in self.manifest['files']:
                    with archive.open(member.get('member_name',member['path'])) as stream:
                        raw=stream.read(member['bytes']+1)
                    if len(raw)!=member['bytes']: raise ValueError('ZIP member size is inconsistent.')
                    yield member['path'],raw
        except (zipfile.BadZipFile,RuntimeError,OSError,EOFError):
            raise ValueError('ZIP integrity validation failed. Nothing was imported.') from None


def status(job_id,user):
    with GUARD:
        job=JOBS.get(job_id)
        if not job: raise HTTPException(404,'Import job not found or expired after server restart. Check Dataset Manager before retrying.')
        if job['owner']!=user['username']: raise HTTPException(403,'You do not have access to this import.')
        return {k:v for k,v in job.items() if k not in {'owner','cancel'}}


def cancel(job_id,user):
    status(job_id,user)
    with GUARD:
        if JOBS[job_id]['status'] in {'QUEUED','PROCESSING'}:
            JOBS[job_id]['cancel'].set()
    return status(job_id,user)


def submit(db,user,name,uploads,paths=None,zipped=False):
    datasets.ensure_registry(db)
    with GUARD:
        for key,job in list(JOBS.items()):
            if job['status'] not in {'QUEUED','PROCESSING'} and time.time()-job['updated_at']>3600: del JOBS[key]
        if any(j['status'] in {'QUEUED','PROCESSING'} for j in JOBS.values()) or bundles.IMPORT_LOCK.locked():
            raise HTTPException(429,'Another bundle import is running. Wait for completion before retrying.')
        if len(JOBS)>=32: raise HTTPException(429,'Import status capacity reached. Retry after completed jobs expire.')
        ident=str(uuid.uuid4()); event=threading.Event()
        JOBS[ident]={'job_id':ident,'owner':user['username'],'status':'QUEUED','stage':'receiving', 'completed_tables':0,'total_tables':0,'stored_rows':0,'current_file':None,'updated_at':time.time(),'cancel':event}
    temp=tempfile.TemporaryDirectory(prefix='sem5-bundle-')
    try:
        payload=0; files=[]; seen=set()
        if not zipped and (not paths or len(paths)!=len(uploads)): raise HTTPException(422,'Each CSV needs one relative path.')
        if not zipped and len(uploads)>bundles.MAX_FILES: raise HTTPException(413,f'Bundle exceeds {bundles.MAX_FILES} CSV files.')
        for index,upload in enumerate(uploads):
            path='archive.zip' if zipped else bundles.normalized_path(paths[index])
            if not zipped and (not path.lower().endswith('.csv') or path.casefold() in seen): raise HTTPException(422,'Unsupported or duplicate CSV relative path.')
            seen.add(path.casefold()); target=Path(temp.name)/str(index)
            with target.open('wb') as stream:
                while chunk:=upload.file.read(1024*1024):
                    payload+=len(chunk)
                    if payload>datasets.MAX_BYTES: raise HTTPException(413,f'Uploaded payload exceeds {datasets.MAX_BYTES} bytes ({datasets.MAX_BYTES/1024/1024:.2f} MiB allowed). Received at least {payload} bytes.')
                    stream.write(chunk)
            files.append((path,target))
        manifest=zip_manifest(files[0][1]) if zipped else None
        inputs=ArchiveFiles(files[0][1],manifest) if zipped else files
        def update(**changes):
            with GUARD: JOBS[ident].update(changes,updated_at=time.time())
        update(total_tables=len(inputs))
        # Existing small-bundle API contract stays synchronous; large uploads return 202.
        if payload<ASYNC_BYTES:
            try:
                result=bundles.ingest(db,user,name,inputs,expanded=zipped)
                update(status='READY',result=result,completed_tables=len(result['tables']),stored_rows=result['row_count'])
                return result,201
            finally:
                temp.cleanup()
                with GUARD: JOBS.pop(ident,None)
        engine=db.get_bind()
        def run():
            update(status='PROCESSING',stage='validating')
            try:
                with Session(engine) as session:
                    result=bundles.ingest(session,user,name,inputs,expanded=zipped,progress=update,cancelled=event.is_set)
                update(status='READY',stage='complete',result=result,completed_tables=len(result['tables']),stored_rows=result['row_count'])
            except HTTPException as exc:
                update(status='CANCELLED' if event.is_set() else 'FAILED',stage='rolled_back',error=exc.detail)
            except Exception:
                update(status='FAILED',stage='rolled_back',error='Import failed and was rolled back. Check archive encoding and structure.')
            finally: temp.cleanup()
        POOL.submit(run)
        return status(ident,user),202
    except Exception:
        temp.cleanup()
        with GUARD: JOBS.pop(ident,None)
        raise
