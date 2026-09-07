/**
 * The app mark — the Greenlam peacock in its arch.
 *
 * Drawn to the proportions of the official logo: the arched window, the
 * seven-feather fan, the bird's body rising through the centre, and the spread
 * base it stands on.
 *
 * The feather colours come from `--feather-1..7`, which are the brand hues
 * pulled to meet contrast on both themes rather than the raw brand values —
 * the raw yellow is 1.12:1 on paper and disappears. At this size the mark
 * reads as the logo; the exact artwork still belongs in Greenlam's asset
 * library, and `dashboard/public/greenlam-logo.svg` overrides this everywhere
 * the moment it exists (see `BrandLockup`).
 */

// One feather, pointing straight up from the origin, tip at y = -60.
const FEATHER =
  'M0 -3 C -7 -20, -8.6 -44, 0 -60 C 8.6 -44, 7 -20, 0 -3 Z';

const FEATHERS = [
  'var(--feather-1)',
  'var(--feather-2)',
  'var(--feather-3)',
  'var(--feather-4)',
  'var(--feather-5)',
  'var(--feather-6)',
  'var(--feather-7)',
];

export function ArchMark({ size = 28 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 120 128"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      {/* The arched window. Flat sides, semicircular top, sitting on its base. */}
      <path
        d="M8 120V52a52 52 0 0 1 104 0v68z"
        fill="var(--accent-quiet)"
        stroke="var(--primary)"
        strokeWidth="5"
        strokeLinejoin="round"
      />

      {/* The fan. Seven feathers at 22° apart, so the outermost pair sit at
          ±66° and the spread matches the logo rather than splaying flat.
          Each feather carries its rotation on an OUTER group: a CSS
          `transform` anywhere in the cascade overrides the SVG attribute, and
          the whole fan collapses to zero rotation when it does. */}
      <g transform="translate(60 104)">
        {FEATHERS.map((colour, i) => (
          <g key={colour} transform={`rotate(${(i - 3) * 22})`}>
            <g>
              <path d={FEATHER} fill={colour} />
              {/* The eye, the thing that makes a feather read as a feather. */}
              <circle cx="0" cy="-46" r="3.2" fill="var(--primary)" opacity="0.45" />
            </g>
          </g>
        ))}
      </g>

      {/* The bird: body rising through the fan, then the spread base. Drawn
          after the feathers so it sits in front of them, as in the logo. */}
      <g fill="var(--primary)">
        <path d="M60 104V64" stroke="var(--primary)" strokeWidth="5" strokeLinecap="round" />
        <circle cx="60" cy="60" r="6" />
        <path d="M60 58c0-5 3-8 7-8-2 4-3 6-7 8z" />
        <path d="M60 104c-14 0-30-4-42-14 14-2 30 2 42 8 12-6 28-10 42-8-12 10-28 14-42 14z" />
      </g>
    </svg>
  );
}
