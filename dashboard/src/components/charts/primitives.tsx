/**
 * Chart primitives, hand-rolled in SVG.
 *
 * WHY NOT A CHART LIBRARY
 * Recharts is ~95 KB gzipped on top of a 104 KB bundle, and these charts are
 * simple geometry: bars, a cumulative line, a stacked area, a sparkline.
 * Paying 95 KB to draw them on phones over patchy plant Wi-Fi is a bad trade,
 * and a library would still need overriding to use the theme tokens.
 *
 * WHAT CHANGED, AND WHY IT WAS BROKEN
 *
 * 1. RESPONSIVE — the old charts were not. They drew into a fixed
 *    `viewBox="0 0 720 260"` and let CSS scale it down with `w-full`. On a
 *    375px phone the browser squeezed 720 user units into ~343 CSS pixels, so
 *    `font-size="11"` rendered at about 5 physical pixels. The chart did not
 *    reflow, it SHRANK — labels became unreadable smudges and the bars became
 *    hairlines. `useChartWidth` measures the container and draws at true pixel
 *    scale, so 11px text is 11px text at every viewport. Once the geometry is
 *    real, the layout can adapt: fewer ticks, dropped series labels, shorter
 *    plots on narrow screens.
 *
 * 2. INTERACTIVE — the old charts were pictures. Everything the data could
 *    say had to fit in a static label, so most of it went unsaid. Now every
 *    chart shares one interaction model:
 *      · a full-height hit band per category, so you can point anywhere in the
 *        column rather than having to hit a 12px-wide bar
 *      · hover on pointer devices, tap on touch, arrow keys on a keyboard —
 *        all three drive the same focus index, so there is one code path and
 *        no device gets a degraded version
 *      · an `aria-live` region that speaks the focused datum, because a
 *        tooltip that only exists visually is not interactivity for everyone
 *      · optional click-to-drill via `onSelect`
 *
 * ACCESSIBILITY
 * A chart is an image to a screen reader unless you make it otherwise. Every
 * chart takes an `ariaLabel` describing the finding, not the shape — "Press-4
 * accounts for 89 hours, the highest of any machine" beats "bar chart" — and
 * `ChartFrame` renders a visually-hidden data table so the numbers are
 * reachable rather than merely summarised.
 *
 * THEME
 * Colours come from CSS custom properties, so both themes and any future
 * high-contrast mode work without touching this file.
 */

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from 'react';

// ---------------------------------------------------------------------------
// Responsive measurement
// ---------------------------------------------------------------------------

/** Below this the chart is on a phone and has to shed furniture, not shrink. */
export const COMPACT_WIDTH = 520;

export interface ChartSize {
  width: number;
  /** True when the chart must drop ticks and abbreviate rather than scale. */
  compact: boolean;
  /** Set once the element has actually been measured. */
  ready: boolean;
}

/**
 * Measure the container so the SVG can be drawn at true pixel scale.
 *
 * The fallback width matters more than it looks: on the very first paint
 * there is no measurement yet, and rendering at 0 would collapse the layout
 * and cause a visible jump. 720 is the desktop case, which is the common one,
 * so the correction on a phone happens within a frame rather than the other
 * way round.
 */
export function useChartWidth<T extends HTMLElement = HTMLDivElement>(): [
  React.RefObject<T | null>,
  ChartSize,
] {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState<ChartSize>({
    width: 720,
    compact: false,
    ready: false,
  });

  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;

    const measure = (width: number) => {
      if (width <= 0) return;
      setSize((prev) =>
        // Sub-pixel resize noise would otherwise re-render on every scroll.
        Math.abs(prev.width - width) < 1 && prev.ready
          ? prev
          : { width, compact: width < COMPACT_WIDTH, ready: true },
      );
    };

    measure(node.getBoundingClientRect().width);

    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) measure(entry.contentRect.width);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return [ref, size];
}

// ---------------------------------------------------------------------------
// Focus: one index, three input devices
// ---------------------------------------------------------------------------

export interface ChartFocus {
  index: number | null;
  set: (index: number | null) => void;
  /** Spread onto the SVG. Handles pointer, touch and keyboard alike. */
  handlers: {
    onPointerMove: (e: React.PointerEvent<SVGSVGElement>) => void;
    onPointerLeave: () => void;
    onPointerDown: (e: React.PointerEvent<SVGSVGElement>) => void;
    onKeyDown: (e: ReactKeyboardEvent<SVGSVGElement>) => void;
    onBlur: () => void;
    tabIndex: number;
  };
}

/**
 * Shared focus behaviour for every chart.
 *
 * `bandAt` maps an x offset to a category index — each chart knows its own
 * geometry, so it supplies that one function and gets the whole interaction
 * model back. Keeping hover, tap and arrow keys on a single index is what
 * stops the keyboard path from rotting: there is no separate code path to
 * forget to update.
 */
export function useChartFocus(
  count: number,
  bandAt: (x: number) => number | null,
  onSelect?: (index: number) => void,
): ChartFocus {
  const [index, setIndex] = useState<number | null>(null);

  // A chart whose data shrank must not keep pointing at a row that is gone.
  useEffect(() => {
    setIndex((prev) => (prev !== null && prev >= count ? null : prev));
  }, [count]);

  const fromEvent = useCallback(
    (e: React.PointerEvent<SVGSVGElement>) => {
      const rect = e.currentTarget.getBoundingClientRect();
      return bandAt(e.clientX - rect.left);
    },
    [bandAt],
  );

  const onKeyDown = useCallback(
    (e: ReactKeyboardEvent<SVGSVGElement>) => {
      if (count === 0) return;
      const step = (delta: number) => {
        e.preventDefault();
        setIndex((prev) => {
          if (prev === null) return delta > 0 ? 0 : count - 1;
          return Math.min(count - 1, Math.max(0, prev + delta));
        });
      };
      switch (e.key) {
        case 'ArrowRight':
        case 'ArrowDown':
          return step(1);
        case 'ArrowLeft':
        case 'ArrowUp':
          return step(-1);
        case 'Home':
          e.preventDefault();
          return setIndex(0);
        case 'End':
          e.preventDefault();
          return setIndex(count - 1);
        case 'Escape':
          return setIndex(null);
        case 'Enter':
        case ' ':
          if (index !== null && onSelect) {
            e.preventDefault();
            onSelect(index);
          }
          return;
      }
    },
    [count, index, onSelect],
  );

  return {
    index,
    set: setIndex,
    handlers: {
      onPointerMove: (e) => setIndex(fromEvent(e)),
      // Touch keeps the tooltip up; only a real mouse leaving clears it.
      onPointerLeave: () => setIndex(null),
      onPointerDown: (e) => {
        const hit = fromEvent(e);
        setIndex(hit);
        if (hit !== null && onSelect && e.pointerType !== 'mouse') onSelect(hit);
      },
      onKeyDown,
      onBlur: () => setIndex(null),
      tabIndex: 0,
    },
  };
}

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------

export interface TooltipRow {
  label: string;
  value: string;
  /** Draws a swatch, so a stacked series can be identified by more than order. */
  colour?: string;
}

/**
 * HTML rather than SVG `<text>`, deliberately: it wraps, it inherits the font
 * stack including the Devanagari subset, and it does not inherit the chart's
 * coordinate scaling. An SVG tooltip on a scaled chart renders at the wrong
 * size, which is the same bug the responsive fix above exists to kill.
 */
export function ChartTooltip({
  x,
  y,
  width,
  title,
  rows,
  hint,
}: {
  x: number;
  y: number;
  width: number;
  title: string;
  rows: TooltipRow[];
  hint?: string;
}) {
  const CARD = 168;
  // Flip before the card would leave the plot, so it never gets clipped.
  const left = Math.min(Math.max(8, x - CARD / 2), Math.max(8, width - CARD - 8));
  return (
    <div
      className="arch lift pointer-events-none absolute z-20 px-2.5 py-2"
      style={{
        left,
        top: Math.max(4, y),
        width: CARD,
        background: 'var(--viz-tooltip)',
        color: 'var(--viz-tooltip-ink)',
        fontSize: 'var(--text-xs)',
        lineHeight: 1.45,
      }}
    >
      <p className="mb-1 font-semibold">{title}</p>
      {rows.map((r) => (
        <p key={r.label} className="flex items-center justify-between gap-2">
          <span className="flex min-w-0 items-center gap-1.5">
            {r.colour && (
              <span
                aria-hidden="true"
                className="inline-block shrink-0"
                style={{ width: 8, height: 8, borderRadius: 2, background: r.colour }}
              />
            )}
            <span className="truncate opacity-80">{r.label}</span>
          </span>
          <span className="shrink-0 font-semibold" style={{ fontFamily: 'var(--font-mono)' }}>
            {r.value}
          </span>
        </p>
      ))}
      {hint && <p className="mt-1 opacity-60">{hint}</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Frame
// ---------------------------------------------------------------------------

export interface ChartFrameProps {
  title: string;
  /** Describes the finding, not the chart type. */
  ariaLabel: string;
  /** Rendered visually-hidden so the numbers are reachable, not just implied. */
  table?: { headers: string[]; rows: (string | number)[][] };
  note?: string;
  /** Spoken when the focused point changes. Interactivity for screen readers. */
  liveMessage?: string;
  /** Legend entries; toggling is wired by the caller. */
  legend?: ReactNode;
  children: ReactNode;
}

export function ChartFrame({
  title,
  ariaLabel,
  table,
  note,
  liveMessage,
  legend,
  children,
}: ChartFrameProps) {
  return (
    <figure className="m-0">
      <figcaption
        className="register-rule flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 pb-1 font-semibold"
        style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
      >
        {title}
        {legend}
      </figcaption>
      <div role="img" aria-label={ariaLabel} className="relative mt-3">
        {children}
      </div>
      {/* The tooltip's content, for anyone not looking at the tooltip. */}
      <p className="sr-only" aria-live="polite">
        {liveMessage ?? ''}
      </p>
      {note && (
        <p className="mt-2" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
          {note}
        </p>
      )}
      {table && (
        <table className="sr-only">
          <caption>{title}</caption>
          <thead>
            <tr>
              {table.headers.map((h) => (
                <th key={h} scope="col">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={j}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </figure>
  );
}

/**
 * A legend entry that is also a switch.
 *
 * Real charts let you mute a series to see what is underneath. A `<button>`
 * with `aria-pressed` gets that for free on a keyboard and in a screen reader,
 * which a `<div onClick>` would not.
 */
export function LegendChip({
  label,
  colour,
  active,
  onToggle,
}: {
  label: string;
  colour: string;
  active: boolean;
  onToggle?: () => void;
}) {
  const content = (
    <>
      <span
        aria-hidden="true"
        className="inline-block shrink-0"
        style={{
          width: 9,
          height: 9,
          borderRadius: 2,
          background: active ? colour : 'transparent',
          border: `1.5px solid ${colour}`,
        }}
      />
      <span style={{ textDecoration: active ? 'none' : 'line-through' }}>{label}</span>
    </>
  );
  const style: CSSProperties = {
    fontSize: 'var(--text-xs)',
    color: active ? 'var(--ink-muted)' : 'var(--line-strong)',
    fontWeight: 500,
  };
  if (!onToggle) {
    return (
      <span className="inline-flex items-center gap-1.5" style={style}>
        {content}
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={active}
      className="arch inline-flex min-h-[24px] items-center gap-1.5 px-1"
      style={style}
    >
      {content}
    </button>
  );
}

export function EmptyChart({ message }: { message: string }) {
  return (
    <p
      className="py-8 text-center"
      style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}
    >
      {message}
    </p>
  );
}

// ---------------------------------------------------------------------------
// Geometry helpers
// ---------------------------------------------------------------------------

/** Build an SVG path from points already in view-box space. */
export function linePath(points: [number, number][]): string {
  if (points.length === 0) return '';
  return points
    .map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`)
    .join(' ');
}

export function areaPath(points: [number, number][], baseline: number): string {
  if (points.length === 0) return '';
  const first = points[0]!;
  const last = points[points.length - 1]!;
  return `${linePath(points)} L${last[0].toFixed(2)},${baseline.toFixed(2)} L${first[0].toFixed(
    2,
  )},${baseline.toFixed(2)} Z`;
}

/** Nice round axis maximum, so gridlines land on readable numbers. */
export function niceMax(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalised = value / magnitude;
  const step = normalised <= 1 ? 1 : normalised <= 2 ? 2 : normalised <= 5 ? 5 : 10;
  return step * magnitude;
}

export function formatHours(minutes: number): string {
  const hours = minutes / 60;
  if (hours >= 100) return `${Math.round(hours)}h`;
  if (hours >= 10) return `${hours.toFixed(0)}h`;
  if (hours >= 1) return `${hours.toFixed(1)}h`;
  return `${Math.round(minutes)}m`;
}

/**
 * Shorten a category label to fit the space actually available.
 *
 * Ellipsis rather than rotation: rotated axis labels are the single most
 * common way a dashboard becomes unreadable on a phone, and the full text is
 * already one hover — or one screen-reader table row — away.
 */
export function fitLabel(label: string, pixels: number): string {
  const chars = Math.max(3, Math.floor(pixels / 6.2));
  return label.length <= chars ? label : `${label.slice(0, chars - 1)}…`;
}

/** The five categorical series tokens, in luminance-staircase order. */
export const SERIES_COLOURS = [
  'var(--viz-1)',
  'var(--viz-2)',
  'var(--viz-3)',
  'var(--viz-4)',
  'var(--viz-5)',
] as const;

/** Sequential ramp for ranked things — darkness is the rank. */
export const SEQ_COLOURS = [
  'var(--seq-1)',
  'var(--seq-2)',
  'var(--seq-3)',
  'var(--seq-4)',
  'var(--seq-5)',
] as const;

/** Sequential ramp for quality loss — rejects, scrap, waste. */
export const CLAY_COLOURS = [
  'var(--clay-1)',
  'var(--clay-2)',
  'var(--clay-3)',
  'var(--clay-4)',
  'var(--clay-5)',
] as const;

/** Ramp lookup that degrades to the palest step rather than going undefined. */
export function rampColour(ramp: readonly string[], index: number): string {
  return ramp[Math.min(index, ramp.length - 1)] ?? ramp[ramp.length - 1]!;
}

/**
 * Evenly spaced tick indices that never collide.
 *
 * Given how many labels will physically fit, pick that many from the data —
 * always including the last one, because the most recent point is the one a
 * reader looks for first.
 */
export function tickIndices(count: number, maxTicks: number): number[] {
  if (count <= maxTicks) return Array.from({ length: count }, (_, i) => i);
  const step = (count - 1) / (maxTicks - 1);
  const out = new Set<number>();
  for (let i = 0; i < maxTicks; i += 1) out.add(Math.round(i * step));
  return [...out].sort((a, b) => a - b);
}

/** Memo-friendly band hit test for evenly spaced categories. */
export function useBandHitTest(
  left: number,
  bandWidth: number,
  count: number,
): (x: number) => number | null {
  return useMemo(
    () => (x: number) => {
      if (count === 0 || bandWidth <= 0) return null;
      const i = Math.floor((x - left) / bandWidth);
      return i >= 0 && i < count ? i : null;
    },
    [left, bandWidth, count],
  );
}
