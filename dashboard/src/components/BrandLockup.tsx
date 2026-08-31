/**
 * The sign-in mark. The one place this product is allowed to be decorative.
 *
 * WHY THE FAN AND NOT A WORDMARK
 *
 * Greenlam's identity is a peacock — a spectrum fan inside an arched window.
 * The spectrum is the memorable half; the arch is the frame that makes it a
 * mark rather than a rainbow. So the fan gets the space and the motion, and
 * everything else on this screen stays quiet. Spend boldness once.
 *
 * A GEOMETRIC ECHO, NOT A REPRODUCTION
 *
 * The real logo is illustrated artwork and belongs in Greenlam's asset
 * library. Hand-redrawing it in SVG would produce a slightly-wrong version
 * that then has to be maintained. This takes the proportions and the spectrum
 * and builds them from geometry, so it stays crisp at any size and swaps out
 * for the official file in one component when brand assets arrive.
 *
 * FEATHERS ARE TAPERED, NOT BARS
 *
 * The first version drew seven rectangles, which reads as a bar chart — an
 * unfortunate thing for the mark of a data product to resemble. Each feather
 * is now a quill: narrow at the pivot, rounded at the tip, with an eye near
 * the top. At 28px that detail disappears and the silhouette still works,
 * which is the test.
 *
 * MOTION
 *
 * The fan opens once on load, 40ms apart, left to right. Pure CSS keyframes
 * rather than Motion: this is in the floor bundle, and an animation library
 * for one eight-element stagger is weight an operator's phone would carry on
 * every sign-in. Disabled entirely under `prefers-reduced-motion`, where the
 * fan simply starts open.
 */

const FEATHERS = [
  'var(--feather-1)',
  'var(--feather-2)',
  'var(--feather-3)',
  'var(--feather-4)',
  'var(--feather-5)',
  'var(--feather-6)',
  'var(--feather-7)',
  'var(--feather-8)',
] as const;

export function BrandLockup({ size = 96 }: { size?: number }) {
  // Eight feathers across 154°, so the outermost pair sit just inside the
  // arch's shoulders rather than clipping through them.
  const spread = 154;
  const step = spread / (FEATHERS.length - 1);

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 120 120"
      fill="none"
      role="img"
      aria-label="Greenlam"
      className="brand-lockup"
    >
      <defs>
        {/* A soft ground inside the arch so the pale feathers keep contrast on
            a dark canvas without a hard fill fighting the outline. */}
        <radialGradient id="arch-ground" cx="50%" cy="78%" r="72%">
          <stop offset="0%" stopColor="var(--accent-quiet)" stopOpacity="0.95" />
          <stop offset="100%" stopColor="var(--accent-quiet)" stopOpacity="0.35" />
        </radialGradient>
      </defs>

      {/* The arch: straight sides, a true semicircular head, open at the base. */}
      <path
        d="M18 112V52a42 42 0 0 1 84 0v60z"
        fill="url(#arch-ground)"
        stroke="var(--accent)"
        strokeWidth="4"
        strokeLinejoin="round"
      />

      {/* The fan, pivoting from a point low in the arch. */}
      <g transform="translate(60 100)">
        {/* TWO nested groups per feather, and the nesting is load-bearing.
            The outer one carries the fan angle as an SVG attribute; the inner
            one is what animates. A CSS `transform` OVERRIDES an SVG transform
            attribute rather than composing with it, so animating the same
            element collapsed every feather to rotation 0 — the fan rendered as
            three overlapping quills. */}
        {FEATHERS.map((colour, i) => (
          <g key={colour} transform={`rotate(${-spread / 2 + i * step})`}>
            <g className="feather-quill" style={{ animationDelay: `${i * 45}ms` }}>
              {/* Quill: narrow at the pivot, full-bellied, rounded at the tip. */}
              <path
                d="M0 -2 C -7 -20, -8.5 -44, 0 -60 C 8.5 -44, 7 -20, 0 -2 Z"
                fill={colour}
              />
              {/* The eye. Reads at this size, disappears harmlessly at 28px. */}
              <circle cx="0" cy="-46" r="3.1" fill="var(--canvas)" opacity="0.5" />
            </g>
          </g>
        ))}
      </g>

      {/* The base line the arch sits on, closing the silhouette. */}
      <path
        d="M14 112h92"
        stroke="var(--primary)"
        strokeWidth="4"
        strokeLinecap="round"
      />
    </svg>
  );
}
