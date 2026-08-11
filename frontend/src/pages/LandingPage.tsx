// Public landing page: nav, hero, configurator, how-it-works, footer.
//
// Ported from the Figma Make export with its inline copy of the design tokens
// removed — everything visual now comes from design.ts.

import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import DemoModal from '../components/DemoModal'
import LoginModal from '../components/LoginModal'
import PreviewToggle from '../components/PreviewToggle'
import { SolidBtn, TextBtn } from '../components/primitives'
import { C, CARD_SHADOW, CONTENT_MAX_WIDTH, MONO, RADIUS_CARD, RADIUS_CONTROL, SANS, serif } from '../design'
import { ANGLE_THUMBS, RESULT_IMAGES, VEHICLE_THUMBS } from './landingImages'
import { useIsCompact, useIsMobile } from '../useMediaQuery'
import { UNSPLASH } from '../design'

const NAV_LINKS = ['Product', 'How it works', 'Privacy', 'Dealer groups']

function Nav({ onDemo, onLogin }: { onDemo: () => void; onLogin: () => void }) {
  const [hovLink, setHovLink] = useState<string | null>(null)
  const compact = useIsCompact()
  return (
    <nav style={{ position: 'sticky', top: 0, zIndex: 50, background: C.bone, borderBottom: `1px solid ${C.line}` }}>
      <div style={{ maxWidth: CONTENT_MAX_WIDTH, margin: '0 auto', padding: '0 32px', height: 64, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 32 }}>
        <span style={{ ...serif(20), color: C.ink, letterSpacing: '-0.01em', flexShrink: 0 }}>AutoPivot Agent</span>
        <div style={{
          display: compact ? 'none' : 'flex',
          gap: 32, alignItems: 'center', flex: 1, justifyContent: 'center',
        }}>
          {NAV_LINKS.map(link => (
            <a key={link} href="#" style={{ fontFamily: SANS, fontSize: 14, color: hovLink === link ? C.ink : C.inkSoft, textDecoration: 'none', transition: 'color 0.15s' }}
              onMouseEnter={() => setHovLink(link)} onMouseLeave={() => setHovLink(null)}>{link}</a>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0 }}>
          <TextBtn onClick={onLogin}>Log in</TextBtn>
          <SolidBtn onClick={onDemo}>Request a demo</SolidBtn>
        </div>
      </div>
    </nav>
  )
}

function Hero() {
  const mobile = useIsMobile()
  return (
    <section style={{ background: C.ink, padding: mobile ? '56px 20px 48px' : '88px 32px 72px' }}>
      <div style={{ maxWidth: 900, margin: '0 auto', textAlign: 'center' }}>
        <div style={{ fontFamily: MONO, fontSize: 11, color: C.bone, opacity: 0.45, letterSpacing: '0.14em', textTransform: 'uppercase', marginBottom: 24 }}>
          Australia &amp; New Zealand
        </div>
        <h1 style={{ ...serif(mobile ? 36 : 56), color: C.bone, margin: '0 0 24px', lineHeight: 1.05, letterSpacing: '-0.02em' }}>
          Photographed,<br />not pasted.
        </h1>
        <p style={{ fontFamily: SANS, fontSize: 18, color: C.bone, opacity: 0.65, margin: '0 auto 48px', lineHeight: 1.6, maxWidth: 520 }}>
          The backdrop is chosen to agree with the angle the car was shot from — so nothing about the result reads as a cut-out.
        </p>
        <div style={{ aspectRatio: '16/9', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(226,222,214,0.12)', borderRadius: RADIUS_CARD, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 14, position: 'relative', overflow: 'hidden' }}>
          <div style={{ position: 'absolute', inset: 0, backgroundImage: 'linear-gradient(rgba(245,242,236,0.025) 1px, transparent 1px), linear-gradient(90deg, rgba(245,242,236,0.025) 1px, transparent 1px)', backgroundSize: '48px 48px' }} />
          <div style={{ width: 52, height: 52, borderRadius: '50%', border: '1.5px solid rgba(245,242,236,0.28)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M6 4.5L14 9L6 13.5V4.5Z" fill={C.bone} fillOpacity={0.7} /></svg>
          </div>
          <span style={{ fontFamily: MONO, fontSize: 11, color: C.bone, opacity: 0.3, letterSpacing: '0.1em' }}>PRODUCT OVERVIEW</span>
        </div>
      </div>
    </section>
  )
}

const VEHICLES_CFG = [
  { id: 'cx5', label: 'Mazda CX-5' },
  { id: 'hilux', label: 'Toyota Hilux' },
  { id: 'ranger', label: 'Ford Ranger' },
]
const BACKDROPS_CFG = [
  { id: 'studio-grey', label: 'Studio Grey', thumb: 'photo-1542282088-72c9c27ed0cd' },
  { id: 'forecourt', label: 'Forecourt', thumb: 'photo-1574023240744-64c47c8c0676' },
  { id: 'open-sky', label: 'Open Sky', thumb: 'photo-1517026575980-3e1e2dedeab4' },
]
const ANGLES_CFG = [
  { id: 'front3q', label: 'Front 3/4' }, { id: 'front', label: 'Front' }, { id: 'side', label: 'Side' },
  { id: 'rear3q', label: 'Rear 3/4' }, { id: 'interior', label: 'Interior' }, { id: 'wheel', label: 'Wheel detail' },
]

function SelectorRow({ img, label, selected, onClick }: { img: string; label: string; selected: boolean; onClick: () => void }) {
  const [hov, setHov] = useState(false)
  return (
    <button onClick={onClick} onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      aria-pressed={selected}
      style={{ display: 'flex', alignItems: 'center', gap: 12, width: '100%', background: selected ? C.forestTint : hov ? 'rgba(26,26,23,0.03)' : 'none', border: selected ? `1px solid ${C.forest}` : '1px solid transparent', borderRadius: RADIUS_CONTROL, padding: 12, cursor: 'pointer', textAlign: 'left', transition: 'background 0.15s, border-color 0.15s' }}>
      <div style={{ width: 72, height: 48, borderRadius: 8, flexShrink: 0, overflow: 'hidden', backgroundColor: '#cccac3', backgroundImage: `url(${img})`, backgroundSize: 'cover', backgroundPosition: 'center' }} />
      <span style={{ fontFamily: SANS, fontSize: 15, fontWeight: 500, color: C.ink }}>{label}</span>
    </button>
  )
}

function SelectorCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ background: C.white, borderRadius: RADIUS_CARD, border: `1px solid ${C.line}`, boxShadow: CARD_SHADOW, padding: 20 }}>
      <p style={{ fontFamily: SANS, fontSize: 15, fontWeight: 500, color: C.ink, margin: '0 0 12px' }}>{title}</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>{children}</div>
    </div>
  )
}

function Configurator({ onDemo }: { onDemo: () => void }) {
  const compact = useIsCompact()
  const [vehicle, setVehicle] = useState('cx5')
  const [backdrop, setBackdrop] = useState('studio-grey')
  const [angle, setAngle] = useState('front3q')

  const resultUrl = RESULT_IMAGES[`${vehicle}-${backdrop}-${angle}`] ?? UNSPLASH('photo-1617469767068-d84dc5a9d404')

  return (
    <section style={{ background: C.paper, padding: compact ? '56px 20px' : '80px 32px' }}>
      <div style={{ maxWidth: CONTENT_MAX_WIDTH, margin: '0 auto' }}>
        <div style={{ marginBottom: 40 }}>
          <div style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '0.1em', color: C.inkSoft, marginBottom: 12, textTransform: 'uppercase' }}>See it on your stock</div>
          <h2 style={{ ...serif(40), color: C.ink, margin: 0, letterSpacing: '-0.02em', lineHeight: 1.1 }}>Any vehicle. Any backdrop. Any angle.</h2>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: compact ? '1fr' : '320px 1fr', gap: 16, marginBottom: 16 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <SelectorCard title="Select vehicle">
              {VEHICLES_CFG.map(v => <SelectorRow key={v.id} img={VEHICLE_THUMBS[v.id]} label={v.label} selected={vehicle === v.id} onClick={() => setVehicle(v.id)} />)}
            </SelectorCard>
            <SelectorCard title="Select backdrop">
              {BACKDROPS_CFG.map(b => <SelectorRow key={b.id} img={UNSPLASH(b.thumb, 144, 96)} label={b.label} selected={backdrop === b.id} onClick={() => setBackdrop(b.id)} />)}
            </SelectorCard>
          </div>
          <div style={{ borderRadius: RADIUS_CARD, overflow: 'hidden', border: `1px solid ${C.line}`, boxShadow: CARD_SHADOW, position: 'relative', minHeight: 320, backgroundImage: `url(${resultUrl})`, backgroundSize: 'cover', backgroundPosition: 'center', backgroundColor: '#c8c6bf' }}>
            <div style={{ position: 'absolute', top: 16, left: 16, fontFamily: MONO, fontSize: 10, color: 'rgba(245,242,236,0.5)', letterSpacing: '0.08em' }}>
              {vehicle.toUpperCase()} · {backdrop.toUpperCase()} · {angle.toUpperCase()}
            </div>
            <div style={{ position: 'absolute', bottom: 20, right: 20 }}>
              <button onClick={onDemo} style={{ fontFamily: SANS, fontSize: 13, fontWeight: 500, color: C.ink, background: C.white, border: 'none', borderRadius: 999, padding: '10px 16px 10px 18px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 10, boxShadow: '0 2px 8px rgba(26,26,23,0.2)' }}>
                Request a demo
                <span style={{ width: 22, height: 22, borderRadius: '50%', background: C.forest, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M2 5H8M8 5L5.5 2.5M8 5L5.5 7.5" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
                </span>
              </button>
            </div>
          </div>
        </div>
        <div style={{ background: C.white, borderRadius: RADIUS_CARD, border: `1px solid ${C.line}`, boxShadow: CARD_SHADOW, padding: 20, display: 'flex', alignItems: compact ? 'flex-start' : 'center', flexDirection: compact ? 'column' : 'row', gap: compact ? 12 : 24 }}>
          <p style={{ fontFamily: SANS, fontSize: 15, fontWeight: 500, color: C.ink, margin: 0, flexShrink: 0 }}>Select angle</p>
          <div style={{ display: 'flex', gap: 8, flex: 1, flexWrap: 'wrap' }}>
            {ANGLES_CFG.map(a => (
              <button key={a.id} onClick={() => setAngle(a.id)} aria-pressed={angle === a.id}
                style={{ padding: 0, background: 'none', border: 'none', cursor: 'pointer', borderRadius: RADIUS_CONTROL, overflow: 'hidden', outline: angle === a.id ? `1px solid ${C.forest}` : '1px solid transparent', transition: 'outline-color 0.15s' }}>
                <div style={{ width: 96, height: 64, backgroundImage: `url(${ANGLE_THUMBS[a.id]})`, backgroundSize: 'cover', backgroundPosition: 'center', backgroundColor: '#cccac3' }} />
                <div style={{ fontFamily: MONO, fontSize: 10, color: angle === a.id ? C.forest : C.inkSoft, background: C.white, padding: '4px 6px', textAlign: 'center', letterSpacing: '0.04em', borderTop: `1px solid ${C.line}` }}>{a.label}</div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

const HOW_STEPS = [
  { num: '01', title: 'Shoot', body: 'Photograph the vehicle on any phone. No studio, no lighting rig, no training.' },
  { num: '02', title: 'Send', body: 'Upload the set, or paste the listing link and let AutoPivot pull the images itself.' },
  { num: '03', title: 'Receive', body: 'Publish-ready images come back with matched backdrops and masked plates.' },
  { num: '04', title: 'Sell', body: 'Consistent, professional listings across every platform you advertise on.' },
]

function HowItWorks() {
  const compact = useIsCompact()
  const mobile = useIsMobile()
  return (
    <section style={{ background: C.paper, padding: compact ? '0 20px 64px' : '0 32px 88px' }}>
      <div style={{ maxWidth: CONTENT_MAX_WIDTH, margin: '0 auto' }}>
        <div style={{ borderTop: `1px solid ${C.line}`, paddingTop: 64, marginBottom: 48 }}>
          <h2 style={{ ...serif(40), color: C.ink, margin: 0, letterSpacing: '-0.02em', lineHeight: 1.1 }}>How it fits your day.</h2>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: mobile ? '1fr' : compact ? 'repeat(2, 1fr)' : 'repeat(4, 1fr)', rowGap: compact ? 32 : 0 }}>
          {HOW_STEPS.map((step, i) => (
            <div key={step.num} style={{ paddingRight: compact ? 20 : 36, borderLeft: !compact && i > 0 ? `1px solid ${C.line}` : 'none', paddingLeft: !compact && i > 0 ? 36 : 0 }}>
              <div style={{ fontFamily: MONO, fontSize: 12, color: C.forest, letterSpacing: '0.08em', marginBottom: 16 }}>{step.num}</div>
              <h3 style={{ ...serif(28), color: C.ink, margin: '0 0 12px', letterSpacing: '-0.01em', lineHeight: 1.2 }}>{step.title}</h3>
              <p style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: 0, lineHeight: 1.65 }}>{step.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function Footer({ onLogin }: { onLogin: () => void }) {
  return (
    <footer style={{ background: C.bone, borderTop: `1px solid ${C.line}`, padding: '40px 32px' }}>
      <div style={{ maxWidth: CONTENT_MAX_WIDTH, margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 32, flexWrap: 'wrap' }}>
        <span style={{ ...serif(18), color: C.ink, letterSpacing: '-0.01em' }}>AutoPivot Agent</span>
        <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap' }}>
          {NAV_LINKS.map(link => (
            <a key={link} href="#" style={{ fontFamily: SANS, fontSize: 13, color: C.inkSoft, textDecoration: 'none' }}>{link}</a>
          ))}
          <button onClick={onLogin} style={{ fontFamily: SANS, fontSize: 13, color: C.inkSoft, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>Log in</button>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <span style={{ fontFamily: MONO, fontSize: 11, color: C.inkSoft, opacity: 0.55, letterSpacing: '0.04em' }}>
            © {new Date().getFullYear()} AutoPivot Agent
          </span>
          <PreviewToggle current="preview" />
        </div>
      </div>
    </footer>
  )
}

type ModalState = 'none' | 'login' | 'demo'

export default function LandingPage() {
  const [modal, setModal] = useState<ModalState>('none')
  const navigate = useNavigate()

  return (
    <div style={{ background: C.bone }}>
      {modal === 'demo' && <DemoModal onClose={() => setModal('none')} />}
      {modal === 'login' && (
        <LoginModal
          onClose={() => setModal('none')}
          onSuccess={() => { setModal('none'); navigate('/app') }}
          onSwitchToDemo={() => setModal('demo')}
        />
      )}
      <Nav onDemo={() => setModal('demo')} onLogin={() => setModal('login')} />
      <Hero />
      <Configurator onDemo={() => setModal('demo')} />
      <HowItWorks />
      <Footer onLogin={() => setModal('login')} />
    </div>
  )
}
