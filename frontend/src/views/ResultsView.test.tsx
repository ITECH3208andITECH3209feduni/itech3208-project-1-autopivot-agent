// The ways back from a vehicle page to adding photographs to that vehicle.
//
// Each test follows the whole journey — vehicle page, upload form, upload —
// because the break being guarded against was a hand-over: the button went to
// the upload form, but the form had no idea which vehicle it was for.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api, type VehicleListingDetail } from '../api/client'
import { Landed, photoPicker, photograph, vehicle } from '../test/helpers'
import ResultsView from './ResultsView'
import UploadView from './UploadView'

function renderVehicle(detail: VehicleListingDetail) {
  vi.spyOn(api, 'listing').mockResolvedValue(detail)
  return render(
    <MemoryRouter initialEntries={[`/app/vehicles/${detail.id}`]}>
      <Routes>
        <Route path="/app/vehicles/:listingId" element={<ResultsView />} />
        <Route path="/app/upload" element={<UploadView />} />
        <Route path="/app/processing/:listingId" element={<Landed />} />
      </Routes>
    </MemoryRouter>,
  )
}

/** Picks a file on the upload form and presses its one primary button. */
async function uploadOnePhotograph(user: ReturnType<typeof userEvent.setup>): Promise<File> {
  const file = new File(['jpeg bytes'], 'rear.jpg', { type: 'image/jpeg' })
  await user.upload(await photoPicker(), file)
  await user.click(screen.getByRole('button', { name: /start processing/i }))
  return file
}

describe('A vehicle page', () => {
  beforeEach(() => {
    vi.spyOn(api, 'backdrops').mockResolvedValue([])
    vi.spyOn(api, 'fetchFile').mockReturnValue(new Promise(() => {}))
    vi.spyOn(api, 'createListing').mockResolvedValue(vehicle({ id: 99, title: 'A duplicate' }))
    vi.spyOn(api, 'uploadImages').mockResolvedValue([photograph({ id: 201, original_filename: 'rear.jpg' })])
    vi.spyOn(api, 'processListing').mockResolvedValue({
      listing_id: 12, processing_status: 'processing',
      total: 1, completed: 0, failed: 0, needs_review: 0, jobs: [],
    })
  })

  it('with no photographs yet sends "Add photographs" to that vehicle', async () => {
    const user = userEvent.setup()
    renderVehicle(vehicle())

    await user.click(await screen.findByRole('button', { name: 'Add photographs' }))
    const file = await uploadOnePhotograph(user)

    await waitFor(() => expect(api.uploadImages).toHaveBeenCalledWith(12, [file]))
    expect(api.createListing).not.toHaveBeenCalled()
  })

  it('that already has photographs offers to add more to it', async () => {
    const user = userEvent.setup()
    renderVehicle(vehicle({ image_count: 1, images: [photograph()] }))

    await user.click(await screen.findByRole('button', { name: 'Add photographs' }))
    const file = await uploadOnePhotograph(user)

    await waitFor(() => expect(api.uploadImages).toHaveBeenCalledWith(12, [file]))
    expect(api.createListing).not.toHaveBeenCalled()
  })

  it('leads back from its first step to adding photographs to it, not to a blank vehicle', async () => {
    const user = userEvent.setup()
    renderVehicle(vehicle({ image_count: 1, images: [photograph()] }))

    // The Stepper's first step, done and so clickable from Review.
    await user.click(await screen.findByRole('button', { name: 'Add vehicle' }))
    const file = await uploadOnePhotograph(user)

    await waitFor(() => expect(api.uploadImages).toHaveBeenCalledWith(12, [file]))
    expect(api.createListing).not.toHaveBeenCalled()
  })
})
