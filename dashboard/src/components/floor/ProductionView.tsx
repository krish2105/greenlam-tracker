/**
 * Production: pick the machine, then get the form that machine deserves.
 *
 * WHY THE MACHINE COMES FIRST
 *
 * A press logs sheets against a Load No. A resin kettle logs a batch and a
 * quantity. An impregnator logs paper, RC, VC and the resin batch it drew
 * from. The AC room logs sheets conditioned for a load and makes nothing at
 * all. These are four different jobs that happen to share the word
 * "production", and one combined form showed a press operator eight paper
 * fields he could never fill.
 *
 * Choosing the machine first means the app already knows which of the four it
 * is by the time anything is asked. The dispatch is on `production_form`,
 * declared on the machine — not on its section, because a section says where a
 * machine stands rather than what it does.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import * as api from '../../lib/api';
import { useSectionName } from '../../lib/masterNames';
import { LogProductionSheet } from './LogProductionSheet';
import { ACRoomSheet } from './ACRoomSheet';
import { LogRollSheet } from './LogRollSheet';
import { ProductionLogView } from './ProductionLogView';
import { ResinBatchSheet } from './ResinBatchSheet';

export function ProductionView() {
  const { t, i18n } = useTranslation();
  const sectionName = useSectionName();

  const [machines, setMachines] = useState<api.Machine[]>([]);
  const [sections, setSections] = useState<api.Section[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [chosen, setChosen] = useState<api.Machine | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([api.listMachines(), api.listSections()])
      .then(([m, s]) => {
        setMachines(m.filter((x: api.Machine) => x.is_active));
        setSections(s);
      })
      .catch(() => setMachines([]))
      .finally(() => setLoading(false));
  }, []);

  const sectionOf = useMemo(
    () => new Map(sections.map((s) => [s.id, s])),
    [sections],
  );

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const named = (m: api.Machine) =>
      i18n.language.startsWith('hi') && m.name_hi ? m.name_hi : m.name;
    if (!q) return machines;
    return machines.filter(
      (m) =>
        m.code.toLowerCase().includes(q) ||
        named(m).toLowerCase().includes(q),
    );
  }, [machines, query, i18n.language]);

  // Grouped by section so the list reads like a walk through the plant rather
  // than an alphabetical dump of 33 codes.
  const grouped = useMemo(() => {
    const by = new Map<number, api.Machine[]>();
    for (const m of shown) {
      const list = by.get(m.section_id) ?? [];
      list.push(m);
      by.set(m.section_id, list);
    }
    return [...by.entries()].map(([id, list]) => ({
      id,
      name: sectionOf.has(id) ? sectionName(sectionOf.get(id)!.name) : '—',
      machines: list.sort((a, b) => a.code.localeCompare(b.code)),
    }));
  }, [shown, sectionOf, sectionName]);

  const close = () => setChosen(null);
  const done = (message: string) => {
    setChosen(null);
    setSaved(message);
    window.setTimeout(() => setSaved(null), 4000);
  };

  return (
    <div className="pt-2 pb-24">
      <h1 className="font-semibold" style={{ fontSize: 'var(--text-xl)', color: 'var(--ink)' }}>
        {t('production.pickMachine')}
      </h1>
      <p className="mt-1" style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)' }}>
        {t('production.pickMachineHint')}
      </p>

      {saved && (
        <p
          role="status"
          className="arch mt-3 border px-3 py-2"
          style={{ borderColor: 'var(--accent)', color: 'var(--ink)' }}
        >
          {saved}
        </p>
      )}

      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={t('production.searchMachine')}
        aria-label={t('production.searchMachine')}
        className="arch mt-4 w-full border px-3 py-3"
        style={{ borderColor: 'var(--line-strong)', background: 'var(--surface)', color: 'var(--ink)' }}
      />

      {loading ? (
        <p className="py-8" style={{ color: 'var(--ink-muted)' }}>{t('masters.loading')}</p>
      ) : grouped.length === 0 ? (
        <p className="py-8" style={{ color: 'var(--ink-muted)' }}>{t('production.noMachines')}</p>
      ) : (
        grouped.map((group) => (
          <section key={group.id} className="mt-5">
            <h2
              className="register-rule pb-1 font-semibold"
              style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
            >
              {group.name}
            </h2>
            <ul className="mt-2 grid gap-2 sm:grid-cols-2">
              {group.machines.map((m) => (
                <li key={m.id}>
                  <button
                    type="button"
                    onClick={() => setChosen(m)}
                    className="arch flex w-full items-center justify-between border px-3 py-3 text-left"
                    style={{ borderColor: 'var(--line-strong)', background: 'var(--surface)' }}
                  >
                    <span>
                      {/* The code is painted on the machine and is never
                          translated. The name is descriptive, and is. */}
                      <span className="font-semibold" style={{ color: 'var(--ink)' }}>
                        {m.code}
                      </span>
                      <span
                        className="ml-2"
                        style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)' }}
                      >
                        {i18n.language.startsWith('hi') && m.name_hi ? m.name_hi : m.name}
                      </span>
                    </span>
                    <span
                      className="ml-2 shrink-0"
                      style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-xs)' }}
                    >
                      {t(`production.form.${m.production_form}`)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}

      {/* What has already gone in today. Below the machine picker, because the
          job people came here to do is log an entry — but close enough to
          answer "has the last shift already done this?" before they start. */}
      <ProductionLogView />

      {/* Dispatch. An impregnator gets the roll form, a kettle the batch form,
          the AC room its own handling form, everything else the sheet-count
          form. */}
      {chosen?.production_form === 'impregnation' && (
        <LogRollSheet
          machineId={chosen.id}
          onClose={close}
          onLogged={() => done(t('production.savedRoll'))}
        />
      )}
      {chosen?.production_form === 'resin' && (
        <ResinBatchSheet
          machine={chosen}
          onClose={close}
          onSaved={() => done(t('production.savedBatch'))}
        />
      )}
      {chosen?.production_form === 'ac_room' && (
        <ACRoomSheet
          machine={chosen}
          onClose={close}
          onLogged={() => done(t('production.savedProduction'))}
        />
      )}
      {(chosen?.production_form === 'press' || chosen?.production_form === 'general') && (
        <LogProductionSheet
          machineId={chosen.id}
          onClose={close}
          onLogged={() => done(t('production.savedProduction'))}
        />
      )}
    </div>
  );
}
