import { act, cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { getToken, logout, refreshAccessToken } from '@/services/auth'
import { getAnalyticsOverview, setDatasetScope } from '@/services/api'
import RequireAuth from '@/components/RequireAuth'
beforeEach(()=>{localStorage.setItem('sem5_token','old');localStorage.setItem('sem5_refresh','refresh');localStorage.setItem('sem5_user',JSON.stringify({username:'admin',role:'admin'}))})
afterEach(()=>{cleanup();logout();setDatasetScope(null);vi.unstubAllGlobals()})
it('clears a terminally rejected restored session and removes protected content immediately',async()=>{
  render(<MemoryRouter initialEntries={['/private']}><Routes><Route element={<RequireAuth/>}><Route path="/private" element={<div>Private data</div>} /></Route><Route path="/login" element={<div>Sign in again</div>} /></Routes></MemoryRouter>)
  expect(screen.getByText('Private data')).toBeVisible()
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('{}',{status:401})))
  await act(async()=>{expect(await refreshAccessToken()).toBeNull()})
  expect(getToken()).toBeNull();expect(localStorage.getItem('sem5_refresh')).toBeNull();expect(localStorage.getItem('sem5_user')).toBeNull()
  expect(screen.getByText('Sign in again')).toBeVisible();expect(screen.queryByText('Private data')).not.toBeInTheDocument()
})
it('shares one refresh across simultaneous protected requests and retries each only once',async()=>{
  let finish!: (response:Response)=>void
  const fetch=vi.fn().mockImplementation((url:string,init:RequestInit)=>url.includes('/auth/refresh')?new Promise(resolve=>{finish=resolve}):Promise.resolve(new Response('{}',{status:(init.headers as Record<string,string>).Authorization==='Bearer fresh'?200:401})))
  vi.stubGlobal('fetch',fetch)
  const a=getAnalyticsOverview({date_from:'2025-01-01'}),b=getAnalyticsOverview({date_from:'2025-01-02'})
  await vi.waitFor(()=>expect(finish).toBeDefined())
  finish(new Response('{"access_token":"fresh"}',{status:200}));await Promise.all([a,b])
  expect(fetch.mock.calls.filter(([url])=>url.includes('/auth/refresh'))).toHaveLength(1)
  expect(fetch).toHaveBeenCalledTimes(5)
})
it('preserves the session and never refreshes a forbidden request',async()=>{
  const fetch=vi.fn().mockResolvedValue(new Response('{"detail":"Forbidden"}',{status:403}));vi.stubGlobal('fetch',fetch)
  await expect(getAnalyticsOverview()).rejects.toThrow('Forbidden')
  expect(fetch).toHaveBeenCalledTimes(1);expect(getToken()).toBe('old')
})
it('expires access if the one successful refresh is still rejected, without looping',async()=>{
  const fetch=vi.fn().mockResolvedValueOnce(new Response('{}',{status:401})).mockResolvedValueOnce(new Response('{"access_token":"fresh"}',{status:200})).mockResolvedValueOnce(new Response('{}',{status:401}));vi.stubGlobal('fetch',fetch)
  await expect(getAnalyticsOverview()).rejects.toThrow(/Session expired/)
  expect(fetch).toHaveBeenCalledTimes(3);expect(getToken()).toBeNull()
})
it('reacts to another browser tab signing out',()=>{
  render(<MemoryRouter initialEntries={['/private']}><Routes><Route element={<RequireAuth/>}><Route path="/private" element={<div>Private data</div>} /></Route><Route path="/login" element={<div>Login</div>} /></Routes></MemoryRouter>)
  act(()=>{localStorage.removeItem('sem5_token');window.dispatchEvent(new StorageEvent('storage',{key:'sem5_token'}))})
  expect(screen.getByText('Login')).toBeVisible();expect(screen.queryByText('Private data')).not.toBeInTheDocument()
})
