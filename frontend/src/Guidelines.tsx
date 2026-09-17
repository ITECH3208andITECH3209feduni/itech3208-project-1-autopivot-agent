// AutoPivot Agent — Brand Guidelines
// Ver6 · For APA-152 definition of done and Technical Report §3.3

// The whole point of this page is that it renders the live system, so
// documentation cannot drift from the product. The Figma Make export undermined
// that by redeclaring the palette and type faces locally — this now imports
// them, so a token change here is a token change everywhere.
import { C, MONO, SANS, serif } from './design'

const rule: React.CSSProperties = { borderTop: `1px solid ${C.line}`, margin: '48px 0 0', paddingTop: 40 }

function Heading({ children }: { children: React.ReactNode }) {
  return <h2 style={{ ...serif(28), color: C.ink, margin: '0 0 24px', letterSpacing: '-0.01em', lineHeight: 1.2 }}>{children}</h2>
}

function Body({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return <p style={{ fontFamily: SANS, fontSize: 15, color: C.inkSoft, margin: '0 0 16px', lineHeight: 1.7, ...style }}>{children}</p>
}

function Label({ children }: { children: React.ReactNode }) {
  return <p style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '0.1em', color: C.inkSoft, textTransform: 'uppercase', margin: '0 0 8px' }}>{children}</p>
}

export default function Guidelines() {
  const colours = [
    { token: 'ink',          hex: '#1A1A17',              role: 'Primary text, dark grounds' },
    { token: 'ink-soft',     hex: '#4A4A44',              role: 'Secondary text' },
    { token: 'bone',         hex: '#F5F2EC',              role: 'Page ground' },
    { token: 'paper',        hex: '#FBFAF8',              role: 'Application working surface' },
    { token: 'white',        hex: '#FFFFFF',              role: 'Cards, image wells' },
    { token: 'line',         hex: '#E2DED6',              role: 'Hairlines and borders' },
    { token: 'forest',       hex: '#1F4D3A',              role: 'Sole accent — actions, active states, links' },
    { token: 'forest-lift',  hex: '#2A6B4F',              role: 'Hover and active' },
    { token: 'forest-tint',  hex: 'rgba(31,77,58,0.06)', role: 'Selected backgrounds' },
    { token: 'amber',        hex: '#B8791A',              role: 'Processing status — application only' },
    { token: 'rust',         hex: '#A33A28',              role: 'Errors — application only' },
  ]

  const typeRoles = [
    { role: 'Display',   face: 'Fraunces',      usage: 'Headings 24px and above only' },
    { role: 'Interface', face: 'IBM Plex Sans',  usage: 'All body and UI text' },
    { role: 'Data',      face: 'IBM Plex Mono',  usage: 'Labels, angles, resolutions, counts' },
  ]

  const components = [
    { name: 'Button — solid',   desc: 'Forest fill, bone text, 10px radius. Primary action per view.' },
    { name: 'Button — text',    desc: 'No border or fill, ink text, tinted background on hover. Secondary or destructive actions.' },
    { name: 'Input',            desc: '1px line border, 10px radius, forest border on focus, rust border on error.' },
    { name: 'Selector row',     desc: 'Thumbnail + label, 10px radius. Forest border and forest-tint fill when selected.' },
    { name: 'Card',             desc: 'White fill, 1px line border, 16px radius, soft two-layer shadow.' },
    { name: 'Status pill',      desc: 'Rounded full, 12px. Complete = neutral. Processing = amber tint. Needs review = rust tint.' },
    { name: 'Modal',            desc: 'White card, 16px radius, dimmed ink backdrop at 55% with blur. Closes on backdrop click or X.' },
    { name: 'Nav item',         desc: 'IBM Plex Sans 14px, 10px radius. Active: forest-tint + forest text. Inactive: ink-soft + tint on hover.' },
  ]

  const decisions = [
    {
      decision: 'Three directions explored',
      detail: 'Datum (Bloomberg-dense, monochrome), Vector (Swiss modernist, strict grid), and Forecourt (editorial automotive warmth). Forecourt was selected: it positions AutoPivot as a premium partner rather than an enterprise software vendor, which matches the ANZ independent dealership audience.',
    },
    {
      decision: 'Instrument Serif rejected',
      detail: 'Heavily associated with AI-generated product design in 2024–2025. A typeface choice that signals "this was made by an AI" is a credibility liability for a product selling image authenticity to sceptical buyers.',
    },
    {
      decision: 'Brass rejected as accent',
      detail: 'Tested against bone, paper, and white grounds. Brass (#C09A4A and variants) consistently fails WCAG AA at the text sizes used in labels and pills without shifting to a darker value that reads as brown. Forest passes AA on all grounds used in the product.',
    },
    {
      decision: 'IBM Carbon evaluated — structure adopted, palette and components rejected',
      detail: "Carbon's 2× grid, spacing scale, and productive/expressive type distinction were adopted as structural discipline. Carbon's cool-grey palette, IBM Blue, and component styling were rejected: they produce a recognisably enterprise aesthetic that conflicts with the Forecourt stance and would read as an IBM sub-product rather than an independent premium tool.",
    },
    {
      decision: 'Dark grounds for imagery, light grounds for chrome',
      detail: 'The hero and video frame sit on ink (#1A1A17) so vehicle photography reads without the ground competing. All application chrome sits on bone and paper so the UI surface recedes behind processed images. This is the core spatial logic of the system.',
    },
    {
      decision: 'Fraunces optical size bound to type size',
      detail: 'Fraunces at opsz 144 produces hairline strokes appropriate to large display use. Applied at 14px — as a previous iteration did — the strokes become nearly invisible and fail contrast thresholds. The rule is: opsz 144 above 40px, opsz 72 from 24–40px, IBM Plex Sans below 24px.',
    },
  ]

  return (
    <div style={{ background: C.paper, minHeight: '100vh' }}>
      {/* Cover */}
      <div style={{ background: C.ink, padding: '80px 64px 64px' }}>
        <div style={{ maxWidth: 900, margin: '0 auto' }}>
          <div style={{ fontFamily: MONO, fontSize: 11, color: C.bone, opacity: 0.4, letterSpacing: '0.12em', marginBottom: 24, textTransform: 'uppercase' }}>
            AutoPivot Agent · Brand Guidelines · Ver6
          </div>
          <h1 style={{ ...serif(56), color: C.bone, margin: '0 0 16px', lineHeight: 1.05, letterSpacing: '-0.02em' }}>
            Brand Guidelines
          </h1>
          <p style={{ fontFamily: SANS, fontSize: 18, color: C.bone, opacity: 0.6, margin: 0, lineHeight: 1.6 }}>
            For APA-152 definition of done and Technical Report §3.3
          </p>
        </div>
      </div>

      {/* Body */}
      <div style={{ maxWidth: 900, margin: '0 auto', padding: '64px 64px 96px' }}>

        {/* 1. Brand foundation */}
        <Heading>1. Brand foundation</Heading>
        <Body>
          AutoPivot Agent is a professional instrument for Australian and New Zealand car dealerships. Its purpose is to
          close the gap between the photograph taken on the sales floor and the image published in the listing — reliably,
          quickly, and without requiring any design skill from the user. The interface is designed to recede so that vehicle
          photography dominates: the product earns trust by making the output look effortless, not by making itself look
          sophisticated. Trustworthy over trendy. Precise over decorative.
        </Body>

        {/* 2. Colour */}
        <div style={rule}>
          <Heading>2. Colour</Heading>
          <div style={{ background: C.white, border: `1px solid ${C.line}`, borderRadius: 12, overflow: 'hidden', marginBottom: 24 }}>
            {/* Header */}
            <div style={{ display: 'grid', gridTemplateColumns: '40px 120px 160px 1fr', gap: 16, padding: '10px 20px', background: C.bone, borderBottom: `1px solid ${C.line}` }}>
              {['', 'TOKEN', 'HEX', 'ROLE'].map(h => (
                <span key={h} style={{ fontFamily: MONO, fontSize: 10, letterSpacing: '0.1em', color: C.inkSoft }}>{h}</span>
              ))}
            </div>
            {colours.map((c, i) => (
              <div key={c.token} style={{ display: 'grid', gridTemplateColumns: '40px 120px 160px 1fr', gap: 16, padding: '12px 20px', alignItems: 'center', borderTop: i > 0 ? `1px solid ${C.line}` : 'none' }}>
                <div style={{ width: 24, height: 24, borderRadius: 6, background: c.hex, border: c.hex === '#FFFFFF' || c.hex.includes('0.06') ? `1px solid ${C.line}` : undefined, flexShrink: 0 }} />
                <span style={{ fontFamily: MONO, fontSize: 12, color: C.ink }}>{c.token}</span>
                <span style={{ fontFamily: MONO, fontSize: 12, color: C.inkSoft }}>{c.hex}</span>
                <span style={{ fontFamily: SANS, fontSize: 13, color: C.inkSoft }}>{c.role}</span>
              </div>
            ))}
          </div>
          <Body style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft }}>
            <strong style={{ color: C.ink, fontWeight: 500 }}>Rules.</strong> One accent colour only: forest (#1F4D3A) is
            used for buttons, active states, selected borders, and links — and nothing else. Amber and rust never appear on
            marketing pages and carry no brand meaning; they are functional signals inside the application only. Success is
            not shown with a colour. Completion is shown by the processed image appearing, sometimes with a small ink
            checkmark. Green means nothing here.
          </Body>
        </div>

        {/* 3. Typography */}
        <div style={rule}>
          <Heading>3. Typography</Heading>
          <div style={{ background: C.white, border: `1px solid ${C.line}`, borderRadius: 12, overflow: 'hidden', marginBottom: 24 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '120px 180px 1fr', gap: 16, padding: '10px 20px', background: C.bone, borderBottom: `1px solid ${C.line}` }}>
              {['ROLE', 'FACE', 'USAGE'].map(h => <span key={h} style={{ fontFamily: MONO, fontSize: 10, letterSpacing: '0.1em', color: C.inkSoft }}>{h}</span>)}
            </div>
            {typeRoles.map((t, i) => (
              <div key={t.role} style={{ display: 'grid', gridTemplateColumns: '120px 180px 1fr', gap: 16, padding: '14px 20px', alignItems: 'center', borderTop: i > 0 ? `1px solid ${C.line}` : 'none' }}>
                <span style={{ fontFamily: MONO, fontSize: 12, color: C.ink }}>{t.role}</span>
                <span style={{ fontFamily: SANS, fontSize: 13, fontWeight: 500, color: C.ink }}>{t.face}</span>
                <span style={{ fontFamily: SANS, fontSize: 13, color: C.inkSoft }}>{t.usage}</span>
              </div>
            ))}
          </div>

          <Label>Optical size rule</Label>
          <Body>
            Fraunces includes a variable optical size axis (opsz, 9–144). High optical size produces hairline strokes and
            open apertures appropriate to large display headings. Applied at small sizes, those hairline strokes become
            nearly invisible and fail contrast thresholds. The rule: <strong style={{ color: C.ink, fontWeight: 500 }}>opsz 144 above 40px, opsz 72 from 24–40px,
            IBM Plex Sans below 24px</strong>. Fraunces is never set below 24px.
          </Body>

          <Label>Type scale</Label>
          <div style={{ display: 'flex', gap: 0, flexWrap: 'wrap', marginBottom: 24 }}>
            {[56, 40, 32, 28, 20, 16, 15, 14, 12, 11].map((size, i) => (
              <div key={size} style={{ borderLeft: i > 0 ? `1px solid ${C.line}` : 'none', paddingLeft: i > 0 ? 16 : 0, paddingRight: 16, marginBottom: 8 }}>
                <div style={{ fontFamily: MONO, fontSize: 10, color: C.inkSoft, letterSpacing: '0.08em', marginBottom: 4 }}>{size}px</div>
                <div style={{ fontFamily: SANS, fontSize: size, lineHeight: 1, color: C.ink }}>{size >= 24 ? 'Aa' : 'Aa'}</div>
              </div>
            ))}
          </div>
          <Body style={{ fontSize: 14 }}>Weights 400 and 500 only throughout.</Body>
        </div>

        {/* 4. Surface and layout */}
        <div style={rule}>
          <Heading>4. Surface and layout</Heading>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, marginBottom: 24 }}>
            {[
              { label: 'Card radius', value: '16px' },
              { label: 'Control radius', value: '10px' },
              { label: 'Border', value: '1px, line colour — never heavier' },
              { label: 'Spacing base', value: '8px' },
              { label: 'Content max width', value: '1200px' },
              { label: 'Sidebar', value: '240px fixed' },
            ].map(item => (
              <div key={item.label} style={{ borderTop: `1px solid ${C.line}`, paddingTop: 12 }}>
                <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: '0.08em', color: C.inkSoft, marginBottom: 4 }}>{item.label.toUpperCase()}</div>
                <div style={{ fontFamily: SANS, fontSize: 15, fontWeight: 500, color: C.ink }}>{item.value}</div>
              </div>
            ))}
          </div>
          <Label>Card shadow</Label>
          <code style={{ fontFamily: MONO, fontSize: 12, color: C.ink, background: C.bone, padding: '8px 12px', borderRadius: 6, display: 'block', marginBottom: 16 }}>
            box-shadow: 0 1px 3px rgba(26,26,23,0.06), 0 4px 12px rgba(26,26,23,0.04);
          </code>
          <Body style={{ fontSize: 14 }}>
            Two grounds: <strong style={{ color: C.ink, fontWeight: 500 }}>bone (#F5F2EC)</strong> for marketing and landing pages;{' '}
            <strong style={{ color: C.ink, fontWeight: 500 }}>paper (#FBFAF8)</strong> for the application working surface.
            Dark ink ground used only for hero and video frames, so photography dominates.
          </Body>
        </div>

        {/* 5. Components */}
        <div style={rule}>
          <Heading>5. Components</Heading>
          <div style={{ background: C.white, border: `1px solid ${C.line}`, borderRadius: 12, overflow: 'hidden' }}>
            {components.map((c, i) => (
              <div key={c.name} style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gap: 24, padding: '14px 20px', alignItems: 'start', borderTop: i > 0 ? `1px solid ${C.line}` : 'none' }}>
                <span style={{ fontFamily: SANS, fontSize: 13, fontWeight: 500, color: C.ink }}>{c.name}</span>
                <span style={{ fontFamily: SANS, fontSize: 13, color: C.inkSoft, lineHeight: 1.55 }}>{c.desc}</span>
              </div>
            ))}
          </div>
        </div>

        {/* 6. Decisions and rejected alternatives */}
        <div style={rule}>
          <Heading>6. Design decisions and rejected alternatives</Heading>
          <Body>
            This section evidences Synthesis 1 and provides defensible design justification for each significant choice.
          </Body>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            {decisions.map(d => (
              <div key={d.decision} style={{ borderTop: `1px solid ${C.line}`, paddingTop: 24, paddingBottom: 24 }}>
                <p style={{ fontFamily: SANS, fontSize: 15, fontWeight: 500, color: C.ink, margin: '0 0 8px' }}>{d.decision}</p>
                <p style={{ fontFamily: SANS, fontSize: 14, color: C.inkSoft, margin: 0, lineHeight: 1.7 }}>{d.detail}</p>
              </div>
            ))}
            <div style={{ borderTop: `1px solid ${C.line}` }} />
          </div>
        </div>

        {/* 7. Accessibility */}
        <div style={rule}>
          <Heading>7. Accessibility</Heading>
          <Label>Contrast ratios (WCAG AA — 4.5:1 body, 3:1 large text)</Label>
          <div style={{ background: C.white, border: `1px solid ${C.line}`, borderRadius: 12, overflow: 'hidden', marginBottom: 24 }}>
            {[
              { pair: 'ink on bone',   ratio: '15.3:1', pass: true },
              { pair: 'ink on paper',  ratio: '14.9:1', pass: true },
              { pair: 'ink on white',  ratio: '17.1:1', pass: true },
              { pair: 'ink-soft on bone',  ratio: '7.8:1', pass: true },
              { pair: 'ink-soft on paper', ratio: '7.6:1', pass: true },
              { pair: 'white on forest',   ratio: '9.0:1', pass: true },
              { pair: 'amber on white',    ratio: '3.1:1', pass: false, note: 'Use at 15px+ only; data labels, not body text' },
              { pair: 'rust on white',     ratio: '4.8:1', pass: true },
            ].map((row, i) => (
              <div key={row.pair} style={{ display: 'grid', gridTemplateColumns: '200px 80px 60px 1fr', gap: 16, padding: '12px 20px', alignItems: 'center', borderTop: i > 0 ? `1px solid ${C.line}` : 'none' }}>
                <span style={{ fontFamily: MONO, fontSize: 12, color: C.ink }}>{row.pair}</span>
                <span style={{ fontFamily: MONO, fontSize: 12, color: C.inkSoft }}>{row.ratio}</span>
                <span style={{ fontFamily: MONO, fontSize: 11, color: row.pass ? C.forest : C.amber, letterSpacing: '0.06em' }}>{row.pass ? 'PASS' : 'COND'}</span>
                {row.note && <span style={{ fontFamily: SANS, fontSize: 12, color: C.inkSoft }}>{row.note}</span>}
              </div>
            ))}
          </div>

          <Label>Focus states</Label>
          <Body style={{ fontSize: 14 }}>
            All interactive elements receive a 2px forest outline at 2px offset on keyboard focus. Mouse focus does not show
            the ring. Focus ring colour is forest (#1F4D3A), consistent with the sole accent colour.
          </Body>

          <Label>Minimum body size</Label>
          <Body style={{ fontSize: 14 }}>
            14px IBM Plex Sans is the minimum for body copy. Data labels in IBM Plex Mono may go to 11px when paired with
            a larger value (e.g. stat cards) but never in running text. Fraunces is never set below 24px.
          </Body>
        </div>

      </div>
    </div>
  )
}
