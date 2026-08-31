/**
 * Isometric plant map — the board's signature element.
 *
 * WHY THIS AND NOT WEBGL
 * Spatial orientation is the one job a 3D view genuinely beats a table at:
 * "where is the problem, and is it clustered?" is a question a sorted list
 * cannot answer. Everything else on this board — how much, how long, which
 * cause — a table answers better.
 *
 * So this is drawn as isometric SVG rather than React Three Fiber. It costs
 * roughly nothing against ~150KB gzipped for a WebGL stack, needs no 3D model
 * of a plant that nobody has built, works with no GPU, prints, and stays
 * inspectable. The same call the WinBack repo made with its "3D-lite tilt card
 * (no WebGL)" comment.
 *
 * LAYOUT IS SCHEMATIC, AND SAYS SO
 * Real floor coordinates do not exist yet — spec §12.1 Q6 is still open. Tiles
 * are laid out deterministically by section and machine order, so the map is a
 * consistent schematic rather than a survey. The caption says as much, because
 * a plant head who reads it as the real floor plan will be looking in the wrong
 * corner of the building.
 *
 * ACCESSIBILITY
 * A canvas-style view is opaque to assistive tech unless you make it otherwise.
 * Every tile is a real <button> in the DOM with a spoken label, tab order runs
 * section by section, and a visually-hidden table carries the same data.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useSectionName } from '../../lib/masterNames';
import { CLAY_COLOURS, SEQ_COLOURS, rampColour } from '../charts/primitives';

import type { MachineLoad, SectionSummary } from '../../lib/api';

// Isometric projection. 2:1 is the classic game-art ratio — it keeps tile edges
// on clean pixel slopes, which matters at this size.
const TILE_W = 58;
const TILE_H = 29;
const TILE_LIFT = 13; // extruded height, so a tile reads as a solid block

interface PlantMapProps {
  machines: MachineLoad[];
  sections: SectionSummary[];
  /** Machine codes currently escalated or flagged, from the exception feed. */
  alerting?: Set<string>;
  onSelect?: (machineCode: string) => void;
}

interface Tile {
  code: string;
  section: string;
  sectionOrder: number;
  minutes: number;
  count: number;
  col: number;
  row: number;
  alerting: boolean;
}

export function PlantMap({ machines, sections, alerting, onSelect }: PlantMapProps) {
  const { t } = useTranslation();
  const sectionName = useSectionName();
  const [hovered, setHovered] = useState<string | null>(null);
  const [pressed, setPressed] = useState<string | null>(null);

  const sectionOrder = useMemo(() => {
    const m = new Map<string, number>();
    sections.forEach((s) => m.set(s.section_name, s.sort_order));
    return m;
  }, [sections]);

  /**
   * Sections become BAYS arranged in a grid; machines sit inside their bay.
   *
   * The first version incremented one shared row per section, which under
   * isometric projection sent each section down-and-left — the map read as a
   * staircase rather than a floor. A plant is organised in bays side by side,
   * so the map has to be too.
   */
  const { tiles, bays } = useMemo(() => {
    const bySection = new Map<string, MachineLoad[]>();
    for (const m of machines) {
      const list = bySection.get(m.section_name) ?? [];
      list.push(m);
      bySection.set(m.section_name, list);
    }

    const ordered = [...bySection.entries()].sort(
      (a, b) => (sectionOrder.get(a[0]) ?? 99) - (sectionOrder.get(b[0]) ?? 99),
    );

    const BAYS_ACROSS = 3;
    const BAY_W = 3; // machines across inside a bay
    const BAY_PITCH = 4; // tiles between bay origins, leaving an aisle

    const out: Tile[] = [];
    const bayLabels: { name: string; col: number; row: number; order: number }[] = [];

    ordered.forEach(([section, list], bayIndex) => {
      const bayCol = (bayIndex % BAYS_ACROSS) * BAY_PITCH;
      const bayRow = Math.floor(bayIndex / BAYS_ACROSS) * BAY_PITCH;
      bayLabels.push({
        name: section,
        col: bayCol,
        row: bayRow,
        order: sectionOrder.get(section) ?? 0,
      });

      list.forEach((m, i) => {
        out.push({
          code: m.machine_code,
          section,
          sectionOrder: sectionOrder.get(section) ?? 0,
          minutes: m.minutes,
          count: m.count,
          col: bayCol + (i % BAY_W),
          row: bayRow + Math.floor(i / BAY_W),
          alerting: alerting?.has(m.machine_code) ?? false,
        });
      });
    });

    return { tiles: out, bays: bayLabels };
  }, [machines, sectionOrder, alerting]);

  if (tiles.length === 0) {
    return (
      <p className="py-8 text-center" style={{ color: 'var(--ink-muted)' }}>
        {t('plantMap.empty')}
      </p>
    );
  }

  const worst = Math.max(...tiles.map((x) => x.minutes), 1);
  const maxCol = Math.max(...tiles.map((x) => x.col));
  const maxRow = Math.max(...tiles.map((x) => x.row));

  // Isometric transform: x and y both contribute to screen x and y.
  const sx = (c: number, r: number) => (c - r) * (TILE_W / 2);
  const sy = (c: number, r: number) => (c + r) * (TILE_H / 2);

  const xs = tiles.map((x) => sx(x.col, x.row));
  const ys = tiles.map((x) => sy(x.col, x.row));
  const minX = Math.min(...xs) - TILE_W;
  const maxX = Math.max(...xs) + TILE_W;
  // Headroom must clear the tallest block PLUS its alert dot PLUS the bay
  // label above that — the topmost marker was being cropped by the viewBox.
  const minY = Math.min(...ys) - TILE_LIFT - 34;
  const maxY = Math.max(...ys) + TILE_H + TILE_LIFT + 8;

  // Painter's algorithm: back to front, so nearer blocks overlap further ones.
  const painted = [...tiles].sort((a, b) => a.col + a.row - (b.col + b.row));

  return (
    <figure className="m-0">
      <figcaption
        className="register-rule flex flex-wrap items-baseline justify-between gap-2 pb-1"
        style={{ fontSize: 'var(--text-sm)' }}
      >
        <span className="font-semibold" style={{ color: 'var(--ink)' }}>
          {t('plantMap.title')}
        </span>
        <span style={{ color: 'var(--ink-muted)', fontWeight: 400 }}>
          {t('plantMap.schematic')}
        </span>
      </figcaption>

      <div
        role="img"
        aria-label={t('plantMap.summary', {
          machines: tiles.length,
          sections: new Set(tiles.map((x) => x.section)).size,
          alerting: tiles.filter((x) => x.alerting).length,
        })}
        className="mt-3 overflow-x-auto"
      >
        <svg
          viewBox={`${minX} ${minY} ${maxX - minX} ${maxY - minY}`}
          className="h-auto w-full"
          style={{ minWidth: `${Math.min(720, (maxCol + maxRow) * 34)}px` }}
          preserveAspectRatio="xMidYMid meet"
        >
          {painted.map((tile) => {
            const x = sx(tile.col, tile.row);
            const y = sy(tile.col, tile.row);
            // Downtime drives height. The tallest block is the worst machine,
            // which is the finding a plant head is scanning for.
            const lift = TILE_LIFT * (0.35 + 0.65 * (tile.minutes / worst));
            const isHot = tile.alerting;
            /*
             * Colour encodes SEVERITY, not section.
             *
             * These blocks used to be painted in the section's brand feather,
             * which put hot magenta, bright yellow and violet solids across a
             * facility schematic — the single most toy-like object on the
             * board. It also wasted the map's best channel: a reader looking at
             * a plant layout is asking "where is it bad", and hue was answering
             * "which department", which the written labels already say.
             *
             * Now the same quantity drives both height and shade, so the worst
             * bays are tall AND dark and read as one signal instead of two
             * competing ones. Alerting bays switch to the warm ramp — the only
             * hue change on the map, so it means exactly one thing.
             */
            const severity = Math.min(4, Math.floor((1 - tile.minutes / worst) * 5));
            const face = isHot
              ? rampColour(CLAY_COLOURS, severity)
              : rampColour(SEQ_COLOURS, severity);
            const focused = hovered === tile.code;

            return (
              <g
                key={tile.code}
                transform={`translate(${x} ${y - lift})`}
                onMouseEnter={() => setHovered(tile.code)}
                onMouseLeave={() => setHovered(null)}
                onClick={() => onSelect?.(tile.code)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onSelect?.(tile.code);
                  }
                }}
                // The blocks were never clickable: this group had a pointer
                // cursor and no handler, and BoardView never passed onSelect at
                // all. So the map LOOKED interactive and did nothing, which is
                // worse than looking static — a reader who clicks and gets no
                // response concludes the whole board is broken.
                role={onSelect ? 'button' : undefined}
                tabIndex={onSelect ? 0 : undefined}
                aria-label={t('plantMap.tileLabel', {
                  machine: tile.code,
                  section: sectionName(tile.section),
                  hours: Math.round(tile.minutes / 60),
                  count: tile.count,
                  state: tile.alerting
                    ? t('plantMap.needsAttention')
                    : t('plantMap.normal'),
                })}
                style={{
                  cursor: onSelect ? 'pointer' : 'default',
                  // Press feedback, transform-only so it stays on the
                  // compositor. A 58x29 diamond is under the 44px touch
                  // target, which is exactly why the chips below exist — but a
                  // mouse user still expects the block itself to respond.
                  transform: pressed === tile.code ? 'scale(0.97)' : undefined,
                  transformOrigin: `${x}px ${y - lift}px`,
                  transition: 'transform 120ms ease-out',
                  outline: 'none',
                }}
                onPointerDown={() => setPressed(tile.code)}
                onPointerUp={() => setPressed(null)}
                onPointerCancel={() => setPressed(null)}
              >
                {/* Left wall — darkened so the extrusion reads as a solid. */}
                <path
                  d={`M${-TILE_W / 2},0 L0,${TILE_H / 2} L0,${TILE_H / 2 + lift} L${-TILE_W / 2},${lift} Z`}
                  fill={face}
                  opacity="0.42"
                />
                {/* Right wall */}
                <path
                  d={`M${TILE_W / 2},0 L0,${TILE_H / 2} L0,${TILE_H / 2 + lift} L${TILE_W / 2},${lift} Z`}
                  fill={face}
                  opacity="0.62"
                />
                {/* Top face */}
                <path
                  d={`M0,${-TILE_H / 2} L${TILE_W / 2},0 L0,${TILE_H / 2} L${-TILE_W / 2},0 Z`}
                  fill={face}
                  stroke={isHot ? 'var(--rust)' : focused ? 'var(--ink)' : 'var(--canvas)'}
                  strokeWidth={isHot || focused ? 2 : 1}
                />
                {/* Alert marker. Colour is never the only cue — the tile also
                    gets a ring, and the label below says so in words. */}
                {isHot && (
                  <circle
                    cx="0"
                    cy={-TILE_H / 2 - 9}
                    r="4"
                    fill="var(--rust)"
                    stroke="var(--canvas)"
                    strokeWidth="1.5"
                  />
                )}

                {/* Labels only where they carry information: the machines
                    that need attention, and whatever is under the cursor.
                    Labelling all 33 produced a pile of overlapping text —
                    "Resin Kettle-1" was half-covered by the tile in front. */}
                {(isHot || focused) && (
                  <text
                    x="0"
                    y={TILE_H / 2 + lift + 13}
                    textAnchor="middle"
                    fontSize="10"
                    fontFamily="var(--font-mono)"
                    fill="var(--ink)"
                    stroke="var(--canvas)"
                    strokeWidth="3"
                    paintOrder="stroke"
                  >
                    {tile.code}
                  </text>
                )}
              </g>
            );
          })}

          {/* Bay names, painted last.
              They used to be drawn FIRST, which meant every tile painted over
              them — on a three-across grid "Impregnation" sat half-buried
              under a Press block, which reads as a rendering bug rather than a
              label. Drawn last and haloed against the canvas, the same
              treatment the machine labels already had. */}
          {bays.map((bay) => (
            <text
              key={bay.name}
              x={sx(bay.col, bay.row)}
              y={sy(bay.col, bay.row) - TILE_H / 2 - TILE_LIFT - 10}
              textAnchor="middle"
              fontSize="10.5"
              fontWeight="600"
              fill="var(--ink-muted)"
              stroke="var(--canvas)"
              strokeWidth="3.5"
              paintOrder="stroke"
              pointerEvents="none"
            >
              {sectionName(bay.name)}
            </text>
          ))}
        </svg>
      </div>

      {/* The tiles themselves are now the buttons — each carries role,
          tabIndex and an aria-label. A parallel sr-only list used to exist for
          that job; keeping it would give a screen-reader user two focus stops
          per machine, which is worse than none. The table below still carries
          the numbers in a form that can be read row by row. */}

      {/* Visible chips, so the map is operable by mouse and keyboard alike
          without depending on hitting a 58px diamond. */}
      <ul className="mt-3 flex flex-wrap gap-1.5">
        {tiles
          .filter((x) => x.alerting)
          .map((tile) => (
            <li key={tile.code}>
              <button
                type="button"
                onClick={() => onSelect?.(tile.code)}
                onFocus={() => setHovered(tile.code)}
                onBlur={() => setHovered(null)}
                onMouseEnter={() => setHovered(tile.code)}
                onMouseLeave={() => setHovered(null)}
                className="rounded-full border px-2.5 py-1 font-medium"
                style={{
                  fontSize: 'var(--text-xs)',
                  borderColor: 'var(--rust)',
                  color: 'var(--rust)',
                }}
              >
                {tile.code}
              </button>
            </li>
          ))}
      </ul>

      <table className="sr-only">
        <caption>{t('plantMap.title')}</caption>
        <thead>
          <tr>
            <th scope="col">{t('chart.machine')}</th>
            <th scope="col">{t('masters.sections')}</th>
            <th scope="col">{t('chart.downtime')}</th>
            <th scope="col">{t('chart.issues')}</th>
          </tr>
        </thead>
        <tbody>
          {tiles.map((tile) => (
            <tr key={tile.code}>
              <td>{tile.code}</td>
              <td>{sectionName(tile.section)}</td>
              <td>{Math.round(tile.minutes / 60)}h</td>
              <td>{tile.count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
