// Fixtures and small pieces shared by the view tests.
//
// The fixtures carry every field the API returns, not just the ones a given
// test reads: a view that starts reading another field should meet a real
// value, not an undefined that happens to render as nothing.

import { screen } from '@testing-library/react'
import { useLocation } from 'react-router-dom'

import type { ListingImage, VehicleListingDetail } from '../api/client'

/** Vehicle #12 as GET /api/listings/12 returns it, with no photographs yet. */
export function vehicle(overrides: Partial<VehicleListingDetail> = {}): VehicleListingDetail {
  return {
    id: 12,
    stock_number: '4471',
    title: '2021 Mazda CX-5 GT',
    make: 'Mazda',
    model: 'CX-5',
    year: 2021,
    variant: 'GT',
    price: '32990.00',
    status: 'draft',
    processing_status: 'pending',
    image_count: 0,
    created_at: '2026-09-20T09:00:00Z',
    updated_at: '2026-09-20T09:00:00Z',
    description: null,
    images: [],
    ...overrides,
  }
}

/** An original exterior photograph already on vehicle #12. */
export function photograph(overrides: Partial<ListingImage> = {}): ListingImage {
  return {
    id: 101,
    image_type: 'original',
    image_kind: 'exterior',
    kind_confidence: 0.97,
    original_filename: 'front.jpg',
    image_url: '/api/files/listings/12/front.jpg',
    width: 4032,
    height: 3024,
    file_size_bytes: 2_400_000,
    created_at: '2026-09-20T09:05:00Z',
    ...overrides,
  }
}

/**
 * Stands in for whatever screen a navigation lands on, and says where that
 * was, so a test can follow a button without rendering the whole app.
 */
export function Landed() {
  const { pathname, search } = useLocation()
  return <p>Landed on {pathname + search}</p>
}

/** The file input behind the upload form's drop zone, once the form is up. */
export async function photoPicker(): Promise<HTMLInputElement> {
  await screen.findByRole('button', { name: /drop vehicle photos here/i })
  const input = document.querySelector<HTMLInputElement>('input[type="file"]')
  if (!input) throw new Error('The drop zone is on screen but its file input is not.')
  return input
}
