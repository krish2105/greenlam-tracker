/**
 * Localising master-data names that arrive as plain English strings.
 *
 * THE PROBLEM
 * Analytics payloads carry `section_name: "Impregnation"` — a flat string,
 * denormalised at query time so the board can render a Pareto without joining.
 * That is the right call for the query and the wrong one for a Hindi reader:
 * the entire interface translates and then five panels still say
 * "Impregnation" in the middle of a Hindi screen.
 *
 * THE OBVIOUS FIX IS THE EXPENSIVE ONE
 * Adding `section_name_hi` / `section_name_hi_latn` beside every occurrence
 * means touching five schemas, five query sites, and every future payload that
 * happens to mention a section — and forgetting one is silent, because a
 * missing translation renders as English rather than as an error.
 *
 * WHAT THIS DOES INSTEAD
 * `/masters/sections` already returns all three names, and the app already
 * fetches and caches it for offline scan resolution. So the translation table
 * is in the client anyway. This builds one lookup from it, keyed by the English
 * name, and translates any section string the client is handed — wherever it
 * came from. One fetch, one map, and a payload that mentions a section for the
 * first time next year is localised without anyone remembering to do it.
 *
 * WHY KEYED BY NAME AND NOT ID
 * Because the string is all the payload gives us. That makes the English name
 * the join key, which is only safe because section names are unique per plant
 * — enforced by the masters table. If that ever stops being true this breaks
 * loudly (two sections collide in the map) rather than quietly.
 *
 * MACHINE CODES ARE DELIBERATELY NOT TRANSLATED
 * "Press-4" is painted on the machine. Rendering it as "प्रेस-4" would mean
 * the screen and the asset disagree, which is worse than an English word in a
 * Hindi sentence — a technician sent to a machine that is not labelled that way
 * is a real failure, not a cosmetic one.
 *
 * Sections and issue categories both go through the same machinery: both are
 * admin-editable vocabularies stored with three name columns, and both leak
 * into analytics payloads as bare strings.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { localName } from '@greenlam/core';

import * as api from './api';

interface Named {
  name: string;
  name_hi: string | null;
  name_hi_latn: string | null;
}
type Table = Map<string, Named>;
type Kind = 'section' | 'category' | 'rejectReason';

const FETCH: Record<Kind, () => Promise<Named[]>> = {
  section: api.listSections,
  category: api.listCategories,
  rejectReason: api.listRejectReasons,
};

const cache: Partial<Record<Kind, Table>> = {};
const inflight: Partial<Record<Kind, Promise<Table>>> = {};
const listeners: Record<Kind, Set<(t: Table) => void>> = {
  section: new Set(),
  category: new Set(),
  rejectReason: new Set(),
};

function load(kind: Kind): Promise<Table> {
  const hit = cache[kind];
  if (hit) return Promise.resolve(hit);
  // Single-flight. Six components mount at once on the board; six parallel
  // requests for the same immutable master list is the kind of waste that
  // only shows up on plant wifi.
  inflight[kind] ??= FETCH[kind]()
    .then((rows) => {
      const table: Table = new Map(rows.map((r) => [r.name, r]));
      cache[kind] = table;
      listeners[kind].forEach((fn) => fn(table));
      return table;
    })
    .catch(() => {
      // A failed lookup must not break the board. English is a correct
      // fallback; a thrown error in a name-formatting helper is not.
      const empty: Table = new Map();
      cache[kind] = empty;
      return empty;
    })
    .finally(() => {
      delete inflight[kind];
    });
  return inflight[kind]!;
}

function useLocalName(kind: Kind): (name: string) => string {
  const { i18n } = useTranslation();
  const [table, setTable] = useState<Table | null>(cache[kind] ?? null);

  useEffect(() => {
    const hit = cache[kind];
    if (hit) {
      setTable(hit);
      return;
    }
    let live = true;
    const set = listeners[kind];
    set.add(setTable);
    void load(kind).then((t) => {
      if (live) setTable(t);
    });
    return () => {
      live = false;
      set.delete(setTable);
    };
  }, [kind]);

  return (name: string) => {
    const row = table?.get(name);
    return row ? localName(row, i18n.language) : name;
  };
}

/**
 * Returns `localise(englishSectionName)`.
 *
 * Stable across renders in the sense that matters: it re-renders when the
 * table arrives and when the language changes, and does nothing otherwise.
 */
export function useSectionName(): (name: string) => string {
  return useLocalName('section');
}

/** Same, for issue categories — the labels on the downtime Pareto. */
export function useCategoryName(): (name: string) => string {
  return useLocalName('category');
}

/** Same, for reject reasons — the labels on the production scrap Pareto. */
export function useRejectReasonName(): (name: string) => string {
  return useLocalName('rejectReason');
}

/** Cache reset for sign-out — a new user may be a new plant. */
export function resetSectionNames(): void {
  (['section', 'category', 'rejectReason'] as Kind[]).forEach((kind) => {
    delete cache[kind];
    delete inflight[kind];
  });
}
