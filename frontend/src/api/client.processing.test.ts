// The two request shapes the backend contract for this round fixes exactly:
// force on POST .../process, and mode on POST .../include. A ResultsView test
// also exercises these through the UI, but pinning the actual URL/method/body
// here means a drift in either client method is caught at the lowest level.

import { describe, expect, it, vi } from 'vitest'

import { api } from './client'

function reply(status: number, body: unknown = null): Response {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('api.processListing', () => {
  it('defaults force to false when the caller omits it', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(reply(200, {
      listing_id: 12, processing_status: 'processing',
      total: 1, completed: 0, failed: 0, needs_review: 0, jobs: [],
    }))

    await api.processListing(12, 3)

    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('/api/listings/12/process')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init?.body as string)).toEqual({ backdrop_id: 3, force: false })
  })

  it('sends force: true when told to redo an already-complete listing', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(reply(200, {
      listing_id: 12, processing_status: 'processing',
      total: 1, completed: 0, failed: 0, needs_review: 0, jobs: [],
    }))

    await api.processListing(12, null, true)

    const [, init] = fetch.mock.calls[0]
    expect(JSON.parse(init?.body as string)).toEqual({ backdrop_id: null, force: true })
  })
})

describe('api.includeImage', () => {
  it('posts the mode to the include endpoint', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(reply(200, {
      id: 55, image_type: 'original', image_kind: 'exterior', kind_confidence: null,
      original_filename: 'side.jpg', image_url: '/api/files/x', width: 10, height: 10,
      file_size_bytes: 1, created_at: '2026-10-01T00:00:00Z',
    }))

    await api.includeImage(12, 55, 'rerun')

    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('/api/listings/12/images/55/include')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init?.body as string)).toEqual({ mode: 'rerun' })
  })

  it('posts "keep_only" distinctly from "rerun"', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(reply(200, {
      id: 56, image_type: 'original', image_kind: 'interior', kind_confidence: null,
      original_filename: 'inside.jpg', image_url: '/api/files/y', width: 10, height: 10,
      file_size_bytes: 1, created_at: '2026-10-01T00:00:00Z', kept_without_processing: true,
    }))

    await api.includeImage(12, 56, 'keep_only')

    const [, init] = fetch.mock.calls[0]
    expect(JSON.parse(init?.body as string)).toEqual({ mode: 'keep_only' })
  })
})
