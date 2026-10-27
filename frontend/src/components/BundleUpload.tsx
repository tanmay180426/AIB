import { useEffect, useRef, useState } from 'react'
import { getUploadLimits, getZipManifest, uploadDatasetBundle, resumeBundleImport, cancelBundleImport, type ImportJob, type Dataset, type UploadLimits } from '@/services/api'
import { bundleManifest, folderSupported } from '@/services/bundleManifest'
const bytes = (n: number) => `${(n / 1024 / 1024).toFixed(2)} MiB`

export default function BundleUpload({ saved }: { saved: (dataset: Dataset) => Promise<void> }) {
  const directory = useRef<HTMLInputElement>(null)
  const zipInput = useRef<HTMLInputElement>(null)
  const [files, setFiles] = useState<File[]>([])
  const [folderScope, setFolderScope] = useState('')
  const [csvOnly, setCsvOnly] = useState(false)
  const inFlight = useRef(false)
  const [zip, setZip] = useState(false)
  const [name, setName] = useState('')
  const [limits, setLimits] = useState<UploadLimits | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [zipManifest, setZipManifest] = useState<Awaited<ReturnType<typeof getZipManifest>> | null>(null)
  const [validating, setValidating] = useState(false)
  const [job, setJob] = useState<ImportJob | null>(null)
  const savedRef = useRef(saved)
  savedRef.current = saved
  useEffect(() => {
    let current = true
    void resumeBundleImport?.(value => { if (current) { setBusy(true); setJob(value) } }).then(async result => {
      if (current && result) { await savedRef.current(result); setSuccess(`Imported ${result.tables?.length || 0} separate tables.`) }
    }).catch(e => { if (current) setError(e.message) }).finally(() => { if (current) setBusy(false) })
    return () => { current = false }
  }, [])
  useEffect(() => { let current = true; getUploadLimits().then(l => { if (current) setLimits(l) }).catch(e => { if (current) setError(e.message) }); return () => { current = false } }, [])
  const parentPath = (file: File) => (file.webkitRelativePath || file.name).split('/').slice(0,-1).join('/')
  const folderChoices = [...new Set(files.filter(file => file.name.toLowerCase().endsWith('.csv')).map(parentPath))].sort()
  const repeatedNames = !zip && folderChoices.length > 1 && new Set(files.filter(f => f.name.toLowerCase().endsWith('.csv')).map(f => f.name.toLowerCase())).size < files.filter(f => f.name.toLowerCase().endsWith('.csv')).length
  const folderFiles = files.filter(file => !folderScope || parentPath(file) === folderScope)
  const scopedFiles = folderFiles.filter(file => !csvOnly || file.name.toLowerCase().endsWith('.csv'))
  const manifest = zip ? files.map(file => ({ file, path: file.name, error: null })) : bundleManifest(scopedFiles)
  const total = manifest.reduce((sum, row) => sum + row.file.size, 0)
  const invalid = manifest.some(r => r.error) || new Set(manifest.map(r => r.path.toLowerCase())).size !== manifest.length
  const over = !!limits && (total > limits.max_bytes || manifest.length > limits.max_files)
  useEffect(() => {
    let current = true; setZipManifest(null)
    if (zip && files[0] && limits && files[0].size <= limits.max_bytes) {
      setValidating(true)
      getZipManifest(files[0]).then(m => { if (current) setZipManifest(m) }).catch(e => { if (current) setError(e.message) }).finally(() => { if (current) setValidating(false) })
    } else setValidating(false)
    return () => { current = false }
  }, [zip, files, limits])
  const choose = (list: FileList | null, zipped: boolean) => {
    setFolderScope(''); setCsvOnly(false); setJob(null)
    const selected = Array.from(list || []); setFiles(selected); setZip(zipped); setError(''); setSuccess('')
    setName(selected[0] ? ((selected[0].webkitRelativePath || '').split('/')[0] || selected[0].name.replace(/\.zip$/i, '')) : '')
    if (!selected.length) setError('No files selected. Choose a folder containing CSV files or a ZIP.')
  }
  const upload = async () => {
    if (inFlight.current || busy || validating || invalid || over || !limits || !name.trim() || !manifest.length || (zip && !zipManifest)) return
    inFlight.current = true
    setJob(null)
    setBusy(true); setError(''); setSuccess('')
    try {
      const result = await uploadDatasetBundle(manifest.map(r => r.file), name, zip, setJob)
      setFiles([])
      setSuccess(`Imported ${result.tables?.length || 0} separate tables. Inspect the bundle below, then select a table for analysis.`)
      try { await saved(result) } catch { setError('Import succeeded, but the dataset list could not refresh. Reload Dataset Manager before retrying; do not import the same files again.') }
    } catch (e) { setError(e instanceof Error ? e.message : 'Import failed. No bundle was created; fix the files and retry.') }
    finally { inFlight.current = false; setBusy(false); if (directory.current) directory.current.value = ''; if (zipInput.current) zipInput.current.value = '' }
  }
  return <section className="abi-panel border border-neutral-800 rounded-xl p-5 space-y-4" aria-label="Folder and ZIP upload">
    <div><h2 className="font-semibold">Import a dataset folder</h2><p className="text-sm text-neutral-400 mt-1">One private bundle, separate CSV tables. Nested folders are supported; tables are never concatenated.</p></div>
    <div className="flex flex-wrap gap-3">
      <button disabled={busy || !folderSupported()} onClick={() => directory.current?.click()} className="px-4 py-2 bg-blue-600 rounded-lg disabled:opacity-50">Upload Folder</button>
      <button disabled={busy} onClick={() => zipInput.current?.click()} className="px-4 py-2 border border-neutral-600 rounded-lg">Upload ZIP</button>
    </div>
    {!folderSupported() && <p role="status">Directory selection is unavailable in this browser. Use Upload ZIP.</p>}
    <input ref={directory} aria-label="Dataset folder" type="file" multiple {...{ webkitdirectory: '' }} className="sr-only" onClick={e => { e.currentTarget.value = '' }} onChange={e => choose(e.target.files, false)} />
    <input ref={zipInput} aria-label="Dataset ZIP" type="file" accept=".zip" className="sr-only" onClick={e => { e.currentTarget.value = '' }} onChange={e => choose(e.target.files, true)} />
    {limits && <p className="text-xs text-neutral-400">Upload {bytes(limits.max_bytes)} · ZIP expanded {bytes(limits.max_expanded_bytes || limits.max_bytes)} · {limits.max_files} CSVs · bundle {(limits.bundle_max_rows || limits.max_rows).toLocaleString()} rows / {(limits.bundle_max_cells || limits.max_cells).toLocaleString()} cells · per table {(limits.max_table_rows || limits.max_rows).toLocaleString()} rows · {limits.max_columns} columns · {(limits.bundle_max_seconds || limits.max_seconds)}s processing budget. Large imports run as a status-tracked job.</p>}
    {!!files.length && <div className="space-y-3">
      {repeatedNames && <div className="border border-amber-800 rounded p-3 space-y-2"><p role="status">Repeated CSV filenames occur in different folders. This may include backup copies. No CSV is removed automatically; choose one folder or keep all tables within the configured limits.</p><label className="block text-sm">CSV folder to import<select aria-label="CSV folder to import" disabled={busy} value={folderScope} onChange={e => { setFolderScope(e.target.value); setError(''); if (e.target.value) setName(e.target.value.split('/').pop() || name) }} className="block mt-1 w-full bg-neutral-950 border border-neutral-700 rounded p-2"><option value="">All selected folders</option>{folderChoices.map(folder => <option key={folder} value={folder}>{folder || 'Selected folder root'} · {files.filter(f => parentPath(f) === folder && f.name.toLowerCase().endsWith('.csv')).length} CSVs · {bytes(files.filter(f => parentPath(f) === folder).reduce((sum,f) => sum+f.size,0))}</option>)}</select></label></div>}
      {folderScope && <p className="text-sm text-neutral-400">{files.length-folderFiles.length} files excluded by your folder choice. Only files directly in {folderScope} will be uploaded; original relative paths are preserved.</p>}
      {!zip && scopedFiles.some(f => !f.name.toLowerCase().endsWith('.csv') && !['.DS_Store','Thumbs.db'].includes(f.name)) && <button disabled={busy} className="text-sm text-amber-300" onClick={() => setCsvOnly(true)}>Exclude unsupported non-CSV files</button>}
      {csvOnly && <p className="text-sm text-neutral-400">Non-CSV files excluded by your choice. Every CSV in the chosen scope is retained.</p>}
      <label className="block text-sm">Bundle name<input aria-label="Bundle name" maxLength={120} value={name} onChange={e => setName(e.target.value)} className="block mt-1 w-full bg-neutral-950 border border-neutral-700 rounded px-3 py-2" /></label>
      <p>{manifest.length} {zip ? 'archive' : 'files'} · {bytes(total)}</p>
      {zip && <p className="text-sm text-neutral-400">Archive contents are validated on the server before storage. Successful import returns every table; invalid archives create nothing.</p>}
      {validating && <p role="status">Validating ZIP manifest; no data is being stored…</p>}
      {zipManifest && <div><p>{zipManifest.files.length} CSV tables · {bytes(zipManifest.total_bytes)} uncompressed</p><ul className="max-h-48 overflow-auto text-sm">{zipManifest.files.map(f => <li key={f.path} className="break-all py-1">{f.path} · {bytes(f.bytes)}</li>)}</ul></div>}
      {!!zipManifest?.ignored?.length && <details><summary>Ignored archive metadata</summary>{zipManifest.ignored.map(f => <p className="text-sm break-all" key={f.path}>{f.path}: {f.reason}</p>)}</details>}
      {!zip && scopedFiles.length > manifest.length && <details><summary>Ignored folder metadata</summary>{scopedFiles.filter(f => !manifest.some(r => r.file === f)).map(f => <p className="text-sm break-all" key={f.webkitRelativePath || f.name}>{f.webkitRelativePath || f.name}: operating-system metadata</p>)}</details>}
      {!manifest.length && <p role="alert">No supported CSV files found.</p>}
      <ul className="max-h-48 overflow-auto text-sm divide-y divide-neutral-800">{manifest.map((r, index) => <li className="py-2 break-all flex flex-wrap justify-between gap-2" key={`${r.path}-${index}`}><span>{r.path}</span><span>{bytes(r.file.size)} · {r.error || (zip ? 'Awaiting archive validation' : 'CSV selected; schema validation on import')}</span></li>)}</ul>
      {invalid && <p role="alert">Resolve unsupported, empty or duplicate file paths before importing. Nothing has been uploaded.</p>}
      {over && <p role="alert">{total > (limits?.max_bytes || 0) ? `Upload payload ${bytes(total)} exceeds ${bytes(limits?.max_bytes || 0)}.` : `${manifest.length} CSV files exceeds the ${limits?.max_files} file limit.`}</p>}
      <div className="flex gap-3"><button disabled={busy || validating || (zip && !zipManifest) || !limits || !name.trim() || !manifest.length || invalid || over} onClick={() => void upload()} className="bg-blue-600 px-4 py-2 rounded disabled:opacity-50">{busy ? 'Uploading / validating all tables…' : 'Confirm bundle import'}</button><button disabled={busy} onClick={() => { setFiles([]); setError('') }} className="px-3 py-2">Cancel selection</button></div>
    </div>}
    {busy && <div role="status" aria-live="polite"><p>{job ? `${job.stage} · ${job.completed_tables}/${job.total_tables} tables completed · ${job.stored_rows.toLocaleString()} rows stored in the uncommitted transaction · ${job.current_file || ''}` : 'Receiving and validating all tables atomically. Please wait.'}</p>{job && <button onClick={() => void cancelBundleImport().catch(e => setError(e.message))} className="text-amber-400 mt-2">Cancel import</button>}</div>}
    {error && <p role="alert" className="text-red-400 break-words">{error}</p>}
    {error && job && !['READY','FAILED','CANCELLED'].includes(job.status) && <p className="text-sm text-amber-300">Import job {job.job_id} may still be running. Reload this page to resume its authoritative status; check the bundle list before starting another import.</p>}
    {success && <p role="status" className="text-emerald-400">{success}</p>}
  </section>
}
