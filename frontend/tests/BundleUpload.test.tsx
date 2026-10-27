import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import BundleUpload from '@/components/BundleUpload'
import { bundleManifest } from '@/services/bundleManifest'
import { getUploadLimits, getZipManifest, uploadDatasetBundle } from '@/services/api'
vi.mock('@/services/api', () => ({ getUploadLimits: vi.fn(), getZipManifest: vi.fn(), uploadDatasetBundle: vi.fn(), resumeBundleImport: vi.fn(async () => null), cancelBundleImport: vi.fn() }))
const limits = { max_bytes: 209715200, max_expanded_bytes:536870912, bundle_max_rows:5000000, bundle_max_cells:40000000, bundle_max_seconds:900, max_table_rows:1500000, max_rows: 100000, max_columns: 100, max_cells: 2000000, max_files: 32, max_seconds: 60 }
beforeEach(() => { vi.mocked(getUploadLimits).mockResolvedValue(limits); vi.mocked(getZipManifest).mockResolvedValue({files:[{path:'a.csv',bytes:3}],total_bytes:3}) })
afterEach(() => { cleanup(); vi.clearAllMocks() })
describe('bundle input and manifest', () => {
  it('keeps the 200 MiB boundary and lets the user explicitly select one nested CSV set', async () => {
    const files=['root/current/orders.csv','root/current/items.csv','root/backup/current/orders.csv','root/backup/current/items.csv'].map(path => {
      const file=new File(['a\n1'],path.split('/').pop()!);Object.defineProperty(file,'webkitRelativePath',{value:path});Object.defineProperty(file,'size',{value:60*1024*1024});return file
    })
    render(<BundleUpload saved={async()=>{}} />)
    fireEvent.change(screen.getByLabelText('Dataset folder'),{target:{files}})
    await waitFor(()=>expect(screen.getByText(/240.00 MiB exceeds 200.00 MiB/)).toBeVisible())
    expect(screen.getByRole('button',{name:'Confirm bundle import'})).toBeDisabled()
    fireEvent.change(screen.getByLabelText('CSV folder to import'),{target:{value:'root/current'}})
    expect(screen.getByText(/2 files excluded by your folder choice/)).toBeVisible()
    expect(screen.getByText(/2 files · 120.00 MiB/)).toBeVisible()
    expect(screen.getByRole('button',{name:'Confirm bundle import'})).toBeEnabled()
    expect(uploadDatasetBundle).not.toHaveBeenCalled()
  })
  it('accepts exactly the configured payload size and rejects one byte above without allocating a large file',async()=>{
    const file=new File(['a\n1'],'orders.csv');Object.defineProperty(file,'size',{value:limits.max_bytes,configurable:true})
    render(<BundleUpload saved={async()=>{}} />)
    fireEvent.change(screen.getByLabelText('Dataset folder'),{target:{files:[file]}})
    await waitFor(()=>expect(screen.getByRole('button',{name:'Confirm bundle import'})).toBeEnabled())
    Object.defineProperty(file,'size',{value:limits.max_bytes+1});fireEvent.change(screen.getByLabelText('Dataset folder'),{target:{files:[file]}})
    expect(screen.getByRole('button',{name:'Confirm bundle import'})).toBeDisabled()
  })
  it('reports persisted import separately from a registry refresh failure',async()=>{
    vi.mocked(uploadDatasetBundle).mockResolvedValue({dataset_id:'bundle',tables:[{}]} as never)
    render(<BundleUpload saved={async()=>{throw new Error('offline')}} />)
    fireEvent.change(screen.getByLabelText('Dataset folder'),{target:{files:[new File(['a\n1'],'a.csv')]}})
    await waitFor(()=>expect(screen.getByRole('button',{name:'Confirm bundle import'})).toBeEnabled())
    fireEvent.click(screen.getByRole('button',{name:'Confirm bundle import'}))
    await waitFor(()=>expect(screen.getByRole('alert')).toHaveTextContent('Import succeeded'))
    expect(screen.getByText(/Imported 1 separate tables/)).toBeVisible()
    expect(screen.queryByRole('button',{name:'Confirm bundle import'})).not.toBeInTheDocument()
  })
  it('provides a real directory input and ZIP fallback', async () => {
    render(<BundleUpload saved={async () => {}} />)
    expect(screen.getByLabelText('Dataset folder')).toHaveAttribute('webkitdirectory')
    expect(screen.getByLabelText('Dataset folder')).toHaveAttribute('multiple')
    expect(screen.getByRole('button', { name: 'Upload ZIP' })).toBeVisible()
    await waitFor(() => expect(screen.getByText(/200.00 MiB/)).toBeVisible())
  })
  it('keeps every CSV, hides OS noise and identifies unsupported/empty files', () => {
    const files = [new File(['a\n1'], 'a.csv'), new File(['b\n2'], 'b.csv'), new File(['x'], '.DS_Store'), new File(['x'], 'bad.exe'), new File([], 'empty.csv')]
    const manifest = bundleManifest(files)
    expect(manifest.map(r => r.path)).toEqual(['a.csv','b.csv','bad.exe','empty.csv'])
    expect(manifest[2].error).toBe('CSV only'); expect(manifest[3].error).toBe('Empty file')
  })
  it('renders counts and per-file manifest, handles processing and success', async () => {
    const saved = vi.fn().mockResolvedValue(undefined)
    vi.mocked(uploadDatasetBundle).mockResolvedValue({ dataset_id:'bundle', tables:[{},{}] } as never)
    render(<BundleUpload saved={saved} />)
    fireEvent.change(screen.getByLabelText('Dataset folder'), { target: { files:[new File(['a\n1'], 'a.csv'), new File(['b\n2'], 'b.csv')] } })
    expect(screen.getByText(/2 files/)).toBeVisible()
    expect(screen.getByText('a.csv')).toBeVisible(); expect(screen.getByText('b.csv')).toBeVisible()
    await waitFor(() => expect(screen.getByRole('button',{name:'Confirm bundle import'})).toBeEnabled())
    fireEvent.click(screen.getByRole('button',{name:'Confirm bundle import'}))
    await waitFor(() => expect(saved).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText(/Imported 2 separate tables/)).toBeVisible())
    expect(uploadDatasetBundle).toHaveBeenCalledWith(expect.arrayContaining([expect.any(File),expect.any(File)]),'a.csv',false,expect.any(Function))
  })
  it('preserves selection for retry after API validation failure', async () => {
    vi.mocked(uploadDatasetBundle).mockRejectedValue(new Error('Nothing was imported. bad.csv: malformed rows'))
    render(<BundleUpload saved={async () => {}} />)
    fireEvent.change(screen.getByLabelText('Dataset ZIP'), {target:{files:[new File(['zip'],'example.zip')]}})
    await waitFor(() => expect(screen.getByRole('button',{name:'Confirm bundle import'})).toBeEnabled())
    fireEvent.click(screen.getByRole('button',{name:'Confirm bundle import'}))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Nothing was imported'))
    expect(screen.getByText('example.zip')).toBeVisible()
    expect(screen.getByRole('button',{name:'Confirm bundle import'})).toBeEnabled()
  })
  it('blocks unsupported files before submission and permits cancellation', async () => {
    render(<BundleUpload saved={async () => {}} />)
    fireEvent.change(screen.getByLabelText('Dataset folder'),{target:{files:[new File(['x'],'script.exe')]}})
    expect(screen.getByRole('button',{name:'Confirm bundle import'})).toBeDisabled()
    fireEvent.click(screen.getByRole('button',{name:'Cancel selection'}))
    expect(screen.queryByText('script.exe')).not.toBeInTheDocument()
  })
})
