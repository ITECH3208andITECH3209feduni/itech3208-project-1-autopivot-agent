// Two actions that mutate a listing's photographs rather than just navigate:
// redoing a complete listing with a new backdrop, and the two ways to include
// a kind-excluded original. Kept apart from ResultsView.test.tsx, whose own
// doc comment scopes it to the upload hand-over, not these.

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  api,
  type Backdrop,
  type ProcessingJob,
  type ProcessingSummary,
  type VehicleListingDetail,
} from '../api/client'
import { Landed, photograph, vehicle } from '../test/helpers'
import ResultsView from './ResultsView'

function renderVehicle(detail: VehicleListingDetail) {
  vi.spyOn(api, 'listing').mockResolvedValue(detail)
  return render(
    <MemoryRouter initialEntries={[`/app/vehicles/${detail.id}`]}>
      <Routes>
        <Route path="/app/vehicles/:listingId" element={<ResultsView />} />
        <Route path="/app/processing/:listingId" element={<Landed />} />
      </Routes>
    </MemoryRouter>,
  )
}

function backdrop(overrides: Partial<Backdrop> = {}): Backdrop {
  return {
    id: 5, name: 'Showroom floor', suits_angles: [], is_default: false,
    image_url: '/api/files/backdrops/5.jpg', created_at: '2026-09-01T00:00:00Z',
    ...overrides,
  }
}

function job(overrides: Partial<ProcessingJob> = {}): ProcessingJob {
  return {
    id: 1, status: 'pending', processing_type: 'full', input_image_id: 0,
    output_image_id: null, output_image_url: null, backdrop_id: null,
    detected_angle: null, angle_confidence: null, plates_detected: null,
    plate_treatment: null, review_state: null, model_used: null,
    error_message: null, started_at: null, completed_at: null,
    ...overrides,
  }
}

function processingSummary(overrides: Partial<ProcessingSummary> = {}): ProcessingSummary {
  return {
    listing_id: 12, processing_status: 'processing', total: 0, completed: 0,
    failed: 0, needs_review: 0, jobs: [],
    ...overrides,
  }
}

beforeEach(() => {
  // Loading forever keeps every photograph a stable placeholder — same as
  // ResultsView.test.tsx — so no test here is about image bytes.
  vi.spyOn(api, 'fetchFile').mockReturnValue(new Promise(() => {}))
})

describe('Redoing a complete listing with a new backdrop', () => {
  it('still offers the backdrop control once every original has a result, and sends force: true', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'backdrops').mockResolvedValue([backdrop()])
    vi.spyOn(api, 'processListing').mockResolvedValue(processingSummary())
    renderVehicle(vehicle({
      images: [
        photograph({ id: 101, image_kind: 'exterior' }),
        photograph({
          id: 201, image_type: 'processed', source_image_id: 101,
          original_filename: 'front-done.jpg',
        }),
      ],
    }))

    const redoButton = await screen.findByRole('button', { name: /redo with this backdrop/i })
    // Wording must not read as a no-op on a finished listing.
    expect(screen.getByText(/already has a result/i)).toBeTruthy()

    await waitFor(() => expect(screen.getByText('Showroom floor')).toBeTruthy())
    await user.selectOptions(screen.getByLabelText('Backdrop'), 'Showroom floor')
    await user.click(redoButton)

    await waitFor(() => expect(api.processListing).toHaveBeenCalledWith(12, 5, true))
  })

  it('still processes normally (force left out) while an original has no result yet', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'backdrops').mockResolvedValue([])
    vi.spyOn(api, 'processListing').mockResolvedValue(processingSummary())
    renderVehicle(vehicle({ images: [photograph({ id: 101, image_kind: 'exterior' })] }))

    await user.click(await screen.findByRole('button', { name: 'Start processing' }))

    await waitFor(() => expect(api.processListing).toHaveBeenCalledWith(12, null, false))
    expect(screen.queryByText(/already has a result/i)).toBeNull()
  })
})

describe('Including a kind-excluded original', () => {
  it('offers two distinct actions, calling includeImage with "rerun" and "keep_only"', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'backdrops').mockResolvedValue([])
    vi.spyOn(api, 'includeImage').mockResolvedValue(photograph({ id: 301, image_kind: 'exterior' }))
    renderVehicle(vehicle({
      images: [photograph({ id: 301, image_kind: 'interior', original_filename: 'cabin.jpg' })],
    }))

    await screen.findByText('Left out of the listing')

    await user.click(screen.getByRole('button', { name: /include for processing/i }))
    await waitFor(() => expect(api.includeImage).toHaveBeenCalledWith(12, 301, 'rerun'))

    const keepOnlyBtn = await screen.findByRole('button', { name: /include without processing/i })
    await user.click(keepOnlyBtn)
    await waitFor(() => expect(api.includeImage).toHaveBeenCalledWith(12, 301, 'keep_only'))

    expect(api.includeImage).toHaveBeenCalledTimes(2)
  })

  it('does not add either include action to the "Couldn\'t be processed" section', async () => {
    vi.spyOn(api, 'backdrops').mockResolvedValue([])
    vi.spyOn(api, 'listingJobs').mockResolvedValue(processingSummary({
      jobs: [job({ id: 9, input_image_id: 401, status: 'failed', error_message: 'No vehicle detected.' })],
    }))
    renderVehicle(vehicle({
      images: [
        photograph({ id: 401, image_kind: 'exterior', original_filename: 'blurry.jpg' }),
        photograph({ id: 402, image_kind: 'interior', original_filename: 'cabin.jpg' }),
      ],
    }))

    const unusableSection = (await screen.findByText("Couldn't be processed")).closest('div')
    const excludedSection = screen.getByText('Left out of the listing').closest('div')
    if (!unusableSection || !excludedSection) throw new Error('Expected both sections to render.')

    expect(within(unusableSection).queryByRole('button', { name: /include/i })).toBeNull()
    expect(within(excludedSection).getByRole('button', { name: /include for processing/i })).toBeTruthy()
    expect(within(excludedSection).getByRole('button', { name: /include without processing/i })).toBeTruthy()
  })
})

describe('An image kept without processing', () => {
  it('renders in Originals as a normal kept photograph, never in "Left out of the listing"', async () => {
    vi.spyOn(api, 'backdrops').mockResolvedValue([])
    renderVehicle(vehicle({
      images: [
        photograph({
          id: 501, image_kind: 'interior', kept_without_processing: true,
          original_filename: 'cabin-keep.jpg',
        }),
      ],
    }))

    await screen.findByRole('tabpanel')
    expect(screen.queryByText('Left out of the listing')).toBeNull()
  })
})
