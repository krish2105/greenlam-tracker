/**
 * The app mark.
 *
 * An arch — the silhouette of the window the peacock sits in on the Greenlam
 * logo — with a fan of feathers inside it. It is a geometric echo of the
 * proportions, not a reproduction of the logo artwork: the real mark is an
 * illustrated bird and belongs in Greenlam's own asset library, not
 * hand-redrawn in a component.
 *
 * Swap this for the official SVG once brand assets arrive (see README, "What
 * is still needed").
 */

export function ArchMark({ size = 28 }: { size?: number }) {
  const feathers = [
    'var(--feather-1)',
    'var(--feather-2)',
    'var(--feather-3)',
    'var(--feather-4)',
    'var(--feather-5)',
    'var(--feather-6)',
    'var(--feather-7)',
  ];

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      {/* The arch: flat sides, rounded top, sitting on a base line. */}
      <path
        d="M4 30V14a12 12 0 0 1 24 0v16z"
        fill="var(--accent-quiet)"
        stroke="var(--primary)"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      {/* The fan. Seven feathers, radiating — the same idea as the tail, drawn
          as geometry so it stays legible at 20px and in one colour if needed. */}
      <g transform="translate(16 22)">
        {feathers.map((colour, i) => (
          <rect
            key={colour}
            x="-1"
            y="-11"
            width="2"
            height="11"
            rx="1"
            fill={colour}
            transform={`rotate(${(i - 3) * 21})`}
          />
        ))}
      </g>
    </svg>
  );
}
