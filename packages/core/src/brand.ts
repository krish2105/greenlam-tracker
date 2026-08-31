/**
 * Greenlam brand tokens, read off the mark.
 *
 * The logo is a lime arch containing a peacock whose tail fans through the
 * full spectrum, over a deep-green wordmark. Three decisions follow from that:
 *
 * 1. LIME is the live/action colour. It is the loudest thing in the mark and
 *    it is what makes the product recognisably Greenlam rather than a generic
 *    industrial dashboard. Verified at 8.5:1 as a fill with dark ink, and
 *    10:1 as text on the night ground.
 * 2. FOREST is structure — wordmark, headings, rules. 7:1 on paper.
 * 3. The SPECTRUM is section identity, and nothing else. Eight sections, eight
 *    tail feathers; the fan is literally a plant fanning out into its
 *    sections. It never encodes a measurement, because scattering a rainbow
 *    across charts reads as clip-art rather than as the brand.
 *
 * Status uses its own restrained green → amber → rust ramp. Direction-of-good
 * differs per metric (a rising MTTR is bad), so status colour is applied by
 * the metric, never by whether a number went up.
 */

export const BRAND = {
  lime: '#A6CE39',
  forest: '#1F5F3F',
  paper: '#F7F6F2',
  night: '#131611',
} as const;

/**
 * Peacock tail, left to right.
 *
 * FILL AND RULE ONLY — never text. Most of these fail AA against one ground or
 * the other (yellow is 1.1:1 on paper), so they appear as a 4px identity bar
 * or a dot, always beside the section's name. Colour is never the only cue.
 */
export const PEACOCK = [
  'var(--feather-1)', // magenta
  'var(--feather-2)', // orange
  'var(--feather-3)', // yellow
  'var(--feather-4)', // green
  'var(--feather-5)', // cyan
  'var(--feather-6)', // blue
  'var(--feather-7)', // purple
  'var(--feather-8)', // lime — closes the fan on the arch colour
] as const;

/**
 * Stable colour per section.
 *
 * Keyed by sort_order so a section keeps its feather when another is renamed;
 * falls back to hashing the name so an unsorted or newly added section still
 * gets something deterministic rather than shifting between renders.
 */
export function sectionColour(sortOrder: number | null | undefined, name: string): string {
  const index =
    sortOrder === null || sortOrder === undefined
      ? [...name].reduce((acc, ch) => (acc * 31 + ch.charCodeAt(0)) >>> 0, 7)
      : sortOrder;
  return PEACOCK[Math.abs(index) % PEACOCK.length] as string;
}

/** Health ramp. Separate from the spectrum on purpose. */
export type StatusTone = 'good' | 'watch' | 'bad' | 'neutral';

/**
 * Direction-of-good, per metric.
 *
 * Spec §6.2: "green means improving, not high". A rising MTTR is bad and a
 * rising output is good, so the caller states the direction rather than the
 * component guessing from the sign of the delta.
 */
export function toneForDelta(
  deltaPercent: number,
  higherIsBetter: boolean,
): StatusTone {
  if (Math.abs(deltaPercent) < 1) return 'neutral';
  const improving = higherIsBetter ? deltaPercent > 0 : deltaPercent < 0;
  return improving ? 'good' : 'bad';
}

/**
 * Pick a master-data name in the reader's language.
 *
 * Section and category names live in the database, not in the i18n bundle,
 * because the plant can rename a section and that must not require a frontend
 * deploy. The consequence is that the client has to do the language selection
 * itself, and has to do it defensively: `name_hi` is nullable, and a plant that
 * has not filled it in must get the English name rather than an empty string.
 *
 * The fallback chain is deliberate. `hi-Latn` falls back to `hi` before English,
 * because a Hinglish reader can read Devanagari — slowly — whereas English may
 * be a language they do not read at all.
 */
export interface LocalisedName {
  name: string;
  name_hi?: string | null;
  name_hi_latn?: string | null;
}

export function localName(entity: LocalisedName, locale: string): string {
  if (locale === 'hi') return entity.name_hi || entity.name;
  if (locale === 'hi-Latn') return entity.name_hi_latn || entity.name_hi || entity.name;
  return entity.name;
}
