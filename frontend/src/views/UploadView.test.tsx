// Adding photographs to a vehicle that already exists.
//
// The upload form only ever built a new vehicle, so the vehicle page's "Add
// photographs" opened a blank one: re-typing the details made a duplicate
// listing, or a 409 when the stock number was reused. /app/upload?listing=12
// is the same form aimed at vehicle #12.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError } from '../api/client'
import { Landed, photoPicker, photograph, vehicle } from '../test/helpers'
import UploadView from './UploadView'

function renderUpload(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      {/* Where the sidebar's "+ New vehicle" goes, from wherever you are. */}
      <Link to="/app/upload">New vehicle</Link>
      <Routes>
        <Route path="/app/upload" element={<UploadView />} />
        <Route path="/app/processing/:listingId" element={<Landed />} />
        <Route path="/app/vehicles/:listingId" element={<Landed />} />
        <Route path="/app/vehicles" element={<Landed />} />
      </Routes>
    </MemoryRouter>,
  )
}

const rear = () => new File(['jpeg bytes'], 'rear.jpg', { type: 'image/jpeg' })

describe('UploadView for an existing vehicle', () => {
  beforeEach(() => {
    vi.spyOn(api, 'listing').mockResolvedValue(vehicle())
    vi.spyOn(api, 'backdrops').mockResolvedValue([])
    vi.spyOn(api, 'createListing').mockResolvedValue(vehicle({ id: 99, title: 'A duplicate' }))
    vi.spyOn(api, 'uploadImages').mockResolvedValue([photograph({ id: 201, original_filename: 'rear.jpg' })])
    vi.spyOn(api, 'importImagesFromUrl').mockResolvedValue({ images: [photograph({ id: 202 })], note: null })
    vi.spyOn(api, 'processListing').mockResolvedValue({
      listing_id: 12, processing_status: 'processing',
      total: 1, completed: 0, failed: 0, needs_review: 0, jobs: [],
    })
  })

  it('uploads photographs into the vehicle it was opened for, without creating another', async () => {
    const user = userEvent.setup()
    renderUpload('/app/upload?listing=12')
    const file = rear()

    await user.upload(await photoPicker(), file)
    await user.click(screen.getByRole('button', { name: /start processing/i }))

    await waitFor(() => expect(api.uploadImages).toHaveBeenCalledWith(12, [file]))
    expect(api.createListing).not.toHaveBeenCalled()
    // And the run starts on that vehicle, as it does for a new one.
    expect(await screen.findByText('Landed on /app/processing/12')).toBeTruthy()
    expect(api.processListing).toHaveBeenCalledWith(12, null)
  })

  it('imports a listing URL into the vehicle it was opened for, without creating another', async () => {
    const user = userEvent.setup()
    renderUpload('/app/upload?listing=12')

    await user.type(await screen.findByPlaceholderText(/^https:\/\//), 'https://dealer.example/cx-5')
    await user.click(screen.getByRole('button', { name: /start processing/i }))

    await waitFor(() =>
      expect(api.importImagesFromUrl).toHaveBeenCalledWith(12, 'https://dealer.example/cx-5'))
    expect(api.createListing).not.toHaveBeenCalled()
    expect(await screen.findByText('Landed on /app/processing/12')).toBeTruthy()
  })

  it('shows the vehicle being added to, with nothing to type a second copy of it into', async () => {
    renderUpload('/app/upload?listing=12')

    expect(await screen.findByText(/2021 Mazda CX-5 GT/)).toBeTruthy()
    expect(api.listing).toHaveBeenCalledWith(12)
    expect(screen.queryByPlaceholderText('Mazda')).toBeNull()
    expect(screen.queryByPlaceholderText('CX-5')).toBeNull()
    expect(screen.queryByPlaceholderText('2021')).toBeNull()
  })

  it('offers nothing to press while the vehicle is still loading', async () => {
    // Until it arrives the form has no vehicle to aim at, and a button pressed
    // then would build a new one.
    vi.spyOn(api, 'listing').mockReturnValue(new Promise(() => {}))
    renderUpload('/app/upload?listing=12')

    expect(await screen.findByText(/loading the vehicle/i)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /save|start processing/i })).toBeNull()
    expect(screen.queryByPlaceholderText('Mazda')).toBeNull()
  })

  it('says so when the vehicle cannot be found, and offers nothing to upload into', async () => {
    vi.spyOn(api, 'listing').mockRejectedValue(new ApiError(404, 'Listing not found.'))
    renderUpload('/app/upload?listing=12')

    expect((await screen.findByRole('alert')).textContent).toMatch(/could not be found/i)
    expect(screen.queryByRole('button', { name: /drop vehicle photos here/i })).toBeNull()
    expect(screen.queryByPlaceholderText('Mazda')).toBeNull()
  })

  it('says so when the vehicle cannot be loaded for any other reason', async () => {
    vi.spyOn(api, 'listing').mockRejectedValue(
      new ApiError(0, 'Could not reach the server. Is the API running?'))
    renderUpload('/app/upload?listing=12')

    const alert = await screen.findByRole('alert')
    // The server's own words, so the dealer can tell an outage from a typo.
    expect(alert.textContent).toContain('Could not reach the server. Is the API running?')
    expect(screen.queryByRole('button', { name: /drop vehicle photos here/i })).toBeNull()
    expect(screen.queryByPlaceholderText('Mazda')).toBeNull()
  })

  it('starts a genuinely new vehicle when "+ New vehicle" is chosen from this form', async () => {
    const user = userEvent.setup()
    renderUpload('/app/upload?listing=12')
    await screen.findByText(/2021 Mazda CX-5 GT/)

    // The same route with the query dropped, so the form is not remounted by
    // the router on its own.
    await user.click(screen.getByRole('link', { name: 'New vehicle' }))
    await user.type(await screen.findByPlaceholderText('Mazda'), 'Toyota')
    await user.type(screen.getByPlaceholderText('CX-5'), 'Corolla')
    await user.type(screen.getByPlaceholderText('2021'), '2019')
    const file = rear()
    await user.upload(await photoPicker(), file)
    await user.click(screen.getByRole('button', { name: /start processing/i }))

    await waitFor(() => expect(api.createListing).toHaveBeenCalledWith({
      make: 'Toyota', model: 'Corolla', year: 2019, variant: null, stock_number: null,
    }))
    expect(api.uploadImages).toHaveBeenCalledWith(99, [file])
    expect(api.uploadImages).not.toHaveBeenCalledWith(12, expect.anything())
  })

  it('refuses a reference that is not a vehicle id without asking the server', async () => {
    renderUpload('/app/upload?listing=abc')

    expect((await screen.findByRole('alert')).textContent).toMatch(/not a vehicle reference/i)
    expect(api.listing).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: /drop vehicle photos here/i })).toBeNull()
  })
})
