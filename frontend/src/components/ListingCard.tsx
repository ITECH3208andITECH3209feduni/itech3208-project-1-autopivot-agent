
import { useState } from 'react'

import type { ListingImage, VehicleListing } from '../api/client'
import { C, CARD_SHADOW, MONO, SANS } from '../design'
import AuthedImage from './AuthedImage'
import { Card, StatusPill } from './primitives'

const HOVER_SHADOW = '0 2px 6px rgba(26,26,23,0.09), 0 12px 28px rgba(26,26,23,0.07)'

export default function ListingCard({
  listing, preview, onOpen,
}: {
  listing: VehicleListing
  preview: ListingImage | null | undefined
  onOpen: () => void
}) {
  const [hover, setHover] = useState(false)

  return (
    <Card style={{
      overflow: 'hidden',
      border: `1px solid ${hover ? C.lineStrong : C.line}`,
      boxShadow: hover ? HOVER_SHADOW : CARD_SHADOW,
      transition: 'box-shadow 0.15s, border-color 0.15s',
    }}>
      <button
        onClick={onOpen}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        onFocus={() => setHover(true)}
        onBlur={() => setHover(false)}
        style={{
          display: 'block', width: '100%', textAlign: 'left', padding: 0,
          background: 'none', border: 'none', cursor: 'pointer',
        }}
      >
        <div style={{
          aspectRatio: '4 / 3', background: C.bone, display: 'flex',
          alignItems: 'center', justifyContent: 'center',
        }}>
          {preview ? (
            <AuthedImage
              src={preview.image_url}
              alt={`Main photograph of the ${listing.title}`}
              style={{ width: '100%', height: '100%', display: 'block' }}
            />
          ) : (
            <span style={{
              fontFamily: MONO, fontSize: 11, letterSpacing: '0.08em',
              color: C.inkSoft, textTransform: 'uppercase',
            }}>
              {preview === undefined ? 'Loading' : 'No photographs'}
            </span>
          )}
        </div>

        <div style={{ padding: '14px 16px' }}>
          <p style={{
            fontFamily: SANS, fontSize: 16, fontWeight: 500, margin: '0 0 6px',
            color: hover ? C.forest : C.ink, transition: 'color 0.15s',
          }}>
            {listing.title}
          </p>
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            gap: 12,
          }}>
            <span style={{
              fontFamily: MONO, fontSize: 11, letterSpacing: '0.06em', color: C.inkSoft,
            }}>
              {listing.image_count} photo{listing.image_count === 1 ? '' : 's'}
              {listing.stock_number ? ` · #${listing.stock_number}` : ''}
            </span>
            <StatusPill status={listing.processing_status} />
          </div>
        </div>
      </button>
    </Card>
  )
}
