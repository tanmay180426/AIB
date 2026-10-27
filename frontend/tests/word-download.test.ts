import { afterEach, expect, it, vi } from 'vitest'
import { downloadBusinessReport, setDatasetScope } from '@/services/api'
import { logout } from '@/services/auth'
afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks();setDatasetScope(null);localStorage.clear()})
function setup(){localStorage.setItem('sem5_user',JSON.stringify({username:'analyst',role:'analyst'}));localStorage.setItem('sem5_token','fixture');setDatasetScope('fixture')}
it('rejects a CSV or invalid package instead of downloading a renamed Word document',async()=>{
  setup();vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(new Response('csv',{headers:{'Content-Type':'text/csv'}})))
  await expect(downloadBusinessReport()).rejects.toThrow('did not return a Word document')
  vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(new Response('not an Office package',{headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}})))
  await expect(downloadBusinessReport()).rejects.toThrow('package is invalid')
})
it('discards document data decoded after logout',async()=>{
  setup();let finish!:(blob:Blob)=>void
  const response=new Response('',{headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}})
  vi.spyOn(response,'blob').mockImplementation(()=>new Promise(done=>{finish=done}))
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response))
  const pending=downloadBusinessReport({date_to:'2021-12-31'})
  await vi.waitFor(()=>expect(finish).toBeDefined());logout();finish(new Blob(['private']))
  await expect(pending).rejects.toThrow('report discarded')
})
