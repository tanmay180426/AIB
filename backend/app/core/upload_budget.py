"""Bound incoming multipart bodies before framework disk spooling/parsing."""
import threading
from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse
from app.services import datasets,bundle_jobs,dataset_bundles

UPLOAD_PATHS={'/api/datasets/upload','/api/datasets/bundles/upload','/api/datasets/bundles/zip','/api/datasets/bundles/zip-preview'}
FRAMING_BYTES=1024*1024


class UploadBudgetMiddleware:
    def __init__(self,app):
        self.app=app;self.receiving=threading.Lock()

    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope.get('method')!='POST' or scope.get('path') not in UPLOAD_PATHS:
            return await self.app(scope,receive,send)
        limit=datasets.MAX_BYTES+FRAMING_BYTES
        headers=dict(scope.get('headers',[]))
        try: length=int(headers.get(b'content-length',b'0'))
        except ValueError:
            return await JSONResponse({'detail':'Invalid request Content-Length.'},status_code=400)(scope,receive,send)
        if length>limit:
            return await JSONResponse({'detail':f'Multipart request exceeds {datasets.MAX_BYTES} payload bytes plus {FRAMING_BYTES} framing bytes.'},status_code=413)(scope,receive,send)
        with bundle_jobs.GUARD:
            active=any(j['status'] in {'QUEUED','PROCESSING'} for j in bundle_jobs.JOBS.values())
        if active or dataset_bundles.IMPORT_LOCK.locked() or not self.receiving.acquire(blocking=False):
            return await JSONResponse({'detail':'Another import is receiving or processing data. Wait for completion and retry.'},status_code=429)(scope,receive,send)
        total=0;oversized=False
        async def bounded_receive():
            nonlocal total,oversized
            message=await receive()
            if message['type']=='http.request':
                total+=len(message.get('body',b''))
                if total>limit:
                    oversized=True
                    # Starlette closes its open multipart temporary files for
                    # this exception; preserve 413 rather than its default 400.
                    raise MultiPartException(f'Multipart request exceeds {datasets.MAX_BYTES} payload bytes plus {FRAMING_BYTES} framing bytes.')
            return message
        async def bounded_send(message):
            if oversized and message['type']=='http.response.start':
                message={**message,'status':413}
            await send(message)
        try:
            return await self.app(scope,bounded_receive,bounded_send)
        finally:
            self.receiving.release()
