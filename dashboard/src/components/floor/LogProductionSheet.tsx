/**
 * Log a shift's output.
 *
 * Same discipline as raising a breakdown: the shortest path that still
 * produces analysable data. Machine, produced, rejected — and the reject
 * reason appears only when there is something to explain, so a clean shift is
 * four taps.
 *
 * The reason field is required the moment `rejected > 0`, in the UI, in the
 * API, and in a database CHECK. Three layers because a Pareto with an
 * "Unrecorded" bar taller than every named cause is worse than no Pareto: it
 * looks like information.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { localName, sectionColour } from '@greenlam/core';

import * as api from '../../lib/api';
import { Sheet } from '../Sheet';


export function LogProductionSheet({
  onClose,
  onLogged,
  onDrafted,
  machineId: preselected = null,
  draft = null,
}: {
  onClose: () => void;
  onLogged: () => void;
  /** Saved but not finished. The caller closes the sheet and refreshes its
      draft list; the entry has reached nothing else. */
  onDrafted: () => void;
  /** Set when the machine was already chosen on the production screen. The
      sheet then skips its own picker rather than asking twice. */
  machineId?: number | null;
  /** Resuming an unfinished entry (V5 §6.3). The form comes back exactly as it
      was left, and Done submits that row rather than creating a second one. */
  draft?: api.ProductionDraft | null;
}) {
  const { t, i18n } = useTranslation();
  const [machines, setMachines] = useState<api.Machine[]>([]);
  const [sections, setSections] = useState<api.Section[]>([]);
  const [shifts, setShifts] = useState<api.Shift[]>([]);
  const [reasons, setReasons] = useState<api.RejectReason[]>([]);

  const [query, setQuery] = useState('');
  const [machineId, setMachineId] = useState<number | null>(draft?.machine_id ?? preselected);
  const [shiftId, setShiftId] = useState<number | null>(draft?.shift_id ?? null);
  // The legacy free-text pair. Still sent so existing rows and the Excel
  // import keep round-tripping, but derived from the master selection rather
  // than typed — the *_id columns are what the analysis groups by.
  const [size] = useState('8x4 ft');
  const [texture] = useState<string>('Glossy');
  const [designs, setDesigns] = useState<api.Vocab[]>([]);
  const [sizes, setSizes] = useState<api.Vocab[]>([]);
  const [textures, setTextures] = useState<api.Vocab[]>([]);
  const [thicknesses, setThicknesses] = useState<api.Vocab[]>([]);
  const [rolls, setRolls] = useState<string[]>([]);
  const [designId, setDesignId] = useState<number | null>(draft?.design_id ?? null);
  const [sizeId, setSizeId] = useState<number | null>(draft?.size_id ?? null);
  const [textureId, setTextureId] = useState<number | null>(draft?.texture_id ?? null);
  const [thicknessId, setThicknessId] = useState<number | null>(draft?.thickness_id ?? null);
  const [rollNo, setRollNo] = useState(draft?.roll_no ?? '');
  const [loadNo, setLoadNo] = useState(draft?.load_no ?? '');
  // A draft may legitimately hold nothing yet, which is a different thing from
  // holding zero — an empty box invites the number, a typed 0 asserts it.
  const [produced, setProduced] = useState(draft ? String(draft.produced_qty || '') : '');
  const [rejected, setRejected] = useState(draft ? String(draft.rejected_qty) : '0');
  const [reasonId, setReasonId] = useState<number | null>(draft?.reject_reason_id ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    void Promise.all([
      api.listMachines(),
      api.listSections(),
      api.listShifts().catch(() => []),
      api.listRejectReasons().catch(() => []),
      api.listDesigns().catch(() => []),
      api.listSizes().catch(() => []),
      api.listTextures().catch(() => []),
      api.listThicknesses().catch(() => []),
      api.recentRollNumbers().catch(() => []),
    ]).then(([m, s, sh, r, d, sz, tx, th, rl]) => {
      setMachines(m);
      setSections(s);
      setShifts(sh);
      setReasons(r);
      setDesigns(d);
      setSizes(sz);
      setTextures(tx);
      setThicknesses(th);
      setRolls(rl);
      if (sh.length) setShiftId(sh[0]!.id);
      // Preselect the commonest values so the fast path stays fast. A form
      // that opens with four empty dropdowns is four more taps per entry, and
      // production is logged every shift on every machine.
      if (sz.length) setSizeId(sz[0]!.id);
      if (tx.length) setTextureId(tx[0]!.id);
      if (th.length) setThicknessId(th[0]!.id);
    });
  }, []);

  /** A master-list dropdown, localised. Four of these on this form. */
  const VocabField = ({
    id,
    label,
    value,
    onChange,
    options,
  }: {
    id: string;
    label: string;
    value: number | null;
    onChange: (v: number | null) => void;
    options: api.Vocab[];
  }) => (
    <div>
      <label
        htmlFor={id}
        className="mb-1 block font-medium"
        style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
      >
        {label}
      </label>
      <select
        id={id}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
        className="arch w-full border px-3 py-3"
        style={field}
      >
        <option value="">—</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {localName(o, i18n.language)}
          </option>
        ))}
      </select>
    </div>
  );

  const sectionById = useMemo(() => new Map(sections.map((s) => [s.id, s])), [sections]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase().replace(/[\s-]/g, '');
    if (!q) return machines.slice(0, 6);
    return machines
      .filter((m) => m.code.toLowerCase().replace(/[\s-]/g, '').includes(q))
      .slice(0, 6);
  }, [machines, query]);

  const selected = machines.find((m) => m.id === machineId) ?? null;
  // The press is the one place a Load No. is required. It is what the press
  // cycle is planned around, and it is the only handle a finished sheet has
  // back to the load it belongs to — miss it here and every downstream row
  // referencing the same load points at nothing.
  const loadRequired = selected?.production_form === 'press';
  const rejectedCount = Number(rejected) || 0;
  const producedCount = Number(produced) || 0;

  function fields() {
    return {
      machine_id: machineId!,
      shift_id: shiftId,
      size: size.trim(),
      texture,
      design_id: designId,
      size_id: sizeId,
      texture_id: textureId,
      thickness_id: thicknessId,
      roll_no: rollNo.trim() || null,
      load_no: loadNo.trim() || null,
      produced_qty: producedCount,
      rejected_qty: rejectedCount,
      reject_reason_id: rejectedCount > 0 ? reasonId : null,
    };
  }

  async function submit() {
    if (machineId === null) return setError(t('production.errors.needMachine'));
    if (!producedCount) return setError(t('production.errors.needQty'));
    if (rejectedCount > producedCount) return setError(t('production.errors.tooManyRejects'));
    if (rejectedCount > 0 && reasonId === null) return setError(t('production.errors.needReason'));
    if (loadRequired && !loadNo.trim()) return setError(t('production.errors.needLoad'));

    setBusy(true);
    setError('');
    try {
      if (draft) {
        // Two calls, and they have to be two: the values go up first, then the
        // Done press validates what is actually stored. Submitting and then
        // saving would let a row become final and change afterwards.
        await api.updateDraft(draft.id, fields());
        await api.submitProduction(draft.id);
      } else {
        await api.logProduction(fields());
      }
      onLogged();
    } catch (e) {
      setError(e instanceof Error ? e.message : t('production.errors.failed'));
    } finally {
      setBusy(false);
    }
  }

  /**
   * Save for later (V5 §6.3).
   *
   * The only thing checked is the machine, because a row has to belong to
   * something to exist at all. Everything else — the sheet count, the reject
   * reason, the Load No. — is exactly what the operator has come back to
   * finish, and refusing to save without them would make the button useless on
   * the one form it exists for.
   */
  async function saveDraft() {
    if (machineId === null) return setError(t('production.errors.needMachine'));
    setBusy(true);
    setError('');
    try {
      if (draft) await api.updateDraft(draft.id, fields());
      else await api.logProduction({ ...fields(), draft: true });
      onDrafted();
    } catch (e) {
      setError(e instanceof Error ? e.message : t('production.errors.failed'));
    } finally {
      setBusy(false);
    }
  }

  const field = {
    borderColor: 'var(--line-strong)',
    background: 'var(--surface)',
    color: 'var(--ink)',
  };

  return (
    <Sheet title={draft ? t('production.resumeTitle') : t('production.logTitle')} onClose={onClose}>
      <div className="space-y-5">
        <div>
          <label
            htmlFor="prod-machine"
            className="mb-1 block font-medium"
            style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
          >
            {t('production.machine')}
          </label>
          {selected ? (
            <div
              className="arch flex items-center justify-between border px-3 py-3"
              style={{ borderColor: 'var(--accent)', background: 'var(--accent-quiet)' }}
            >
              <span className="font-semibold" style={{ color: 'var(--ink)' }}>
                {selected.code}
              </span>
              <button
                type="button"
                onClick={() => {
                  setMachineId(null);
                  setQuery('');
                }}
                className="px-2 py-1"
                style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}
              >
                {t('raise.change')}
              </button>
            </div>
          ) : (
            <>
              <input
                id="prod-machine"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t('raise.machinePlaceholder')}
                autoComplete="off"
                autoCapitalize="characters"
                className="arch w-full border px-3 py-3"
                style={field}
              />
              <ul className="mt-2 grid grid-cols-2 gap-2">
                {matches.map((m) => {
                  const section = sectionById.get(m.section_id);
                  return (
                    <li key={m.id}>
                      <button
                        type="button"
                        onClick={() => setMachineId(m.id)}
                        className="feather arch w-full border py-3 pr-2 pl-2.5 text-left"
                        style={
                          {
                            borderColor: 'var(--line)',
                            background: 'var(--surface)',
                            '--feather': sectionColour(section?.sort_order, section?.name ?? ''),
                          } as React.CSSProperties
                        }
                      >
                        <span className="block font-semibold" style={{ color: 'var(--ink)' }}>
                          {m.code}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </div>

        {shifts.length > 0 && (
          <fieldset>
            <legend
              className="mb-1 font-medium"
              style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
            >
              {t('production.shift')}
            </legend>
            <div className="grid grid-cols-3 gap-2">
              {shifts.map((s) => (
                <Chip
                  key={s.id}
                  active={s.id === shiftId}
                  onClick={() => setShiftId(s.id)}
                  label={s.name}
                />
              ))}
            </div>
          </fieldset>
        )}

        {/* Placed above the counts, not below with the other optional fields.
            It is the first thing on the load plan the operator is holding, and
            on a press it is the reason this entry can be traced at all.
            Uppercased on the way in because a load plan is printed in capitals
            and "load-4471" would not match "LOAD-4471" in a filter. */}
        <div>
          <label
            htmlFor="load-no"
            className="mb-1 block font-medium"
            style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
          >
            {loadRequired ? t('production.loadNo') : t('production.loadNoOptional')}
          </label>
          <input
            id="load-no"
            value={loadNo}
            onChange={(e) => setLoadNo(e.target.value.toUpperCase())}
            placeholder={t('production.loadNoPlaceholder')}
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            required={loadRequired}
            aria-describedby="load-no-hint"
            className="arch w-full border px-3 py-3"
            style={{
              ...field,
              borderColor: loadRequired && !loadNo.trim() ? 'var(--rust)' : 'var(--line-strong)',
            }}
          />
          <p
            id="load-no-hint"
            className="mt-1"
            style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
          >
            {t('production.loadNoHint')}
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <NumberField
            id="produced"
            label={t('production.produced')}
            value={produced}
            onChange={setProduced}
          />
          <NumberField
            id="rejected"
            label={t('production.rejected')}
            value={rejected}
            onChange={setRejected}
          />
        </div>

        {/* Appears only when there is something to explain. A clean shift never
            sees this field. */}
        {rejectedCount > 0 && (
          <fieldset>
            <legend
              className="mb-1 font-medium"
              style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
            >
              {t('production.rejectReason')}
            </legend>
            <div className="flex flex-wrap gap-2">
              {reasons.map((r) => (
                <Chip
                  key={r.id}
                  active={r.id === reasonId}
                  onClick={() => setReasonId(r.id)}
                  label={r.name}
                />
              ))}
            </div>
          </fieldset>
        )}

        {/* Design, size, texture and thickness all come from master lists now.
            They used to be free text and a hardcoded array, which is how one
            texture ended up spelled three ways and split itself across three
            rows of every reject breakdown. */}
        <div className="grid grid-cols-2 gap-3">
          <VocabField
            id="design"
            label={t('production.design')}
            value={designId}
            onChange={setDesignId}
            options={designs}
          />
          <VocabField
            id="size"
            label={t('production.size')}
            value={sizeId}
            onChange={setSizeId}
            options={sizes}
          />
          <VocabField
            id="texture"
            label={t('production.texture')}
            value={textureId}
            onChange={setTextureId}
            options={textures}
          />
          <VocabField
            id="thickness"
            label={t('production.thickness')}
            value={thicknessId}
            onChange={setThicknessId}
            options={thicknesses}
          />
        </div>

        {/* The traceability link. Optional on purpose — the habit of labelling
            rolls has to exist on the floor before this can be required, and a
            mandatory field nobody can answer is a field people learn to fake.
            Newest first, because the operator wants today's roll. */}
        <div>
          <label
            htmlFor="roll"
            className="mb-1 block font-medium"
            style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
          >
            {t('production.fromRoll')}
          </label>
          <input
            id="roll"
            list="recent-rolls"
            value={rollNo}
            onChange={(e) => setRollNo(e.target.value)}
            placeholder={t('production.fromRollPlaceholder')}
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            className="arch w-full border px-3 py-3"
            style={field}
          />
          <datalist id="recent-rolls">
            {rolls.map((r) => (
              <option key={r} value={r} />
            ))}
          </datalist>
          <p className="mt-1" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
            {t('production.fromRollHint')}
          </p>
        </div>

        {error && (
          <p
            role="alert"
            className="arch px-3 py-2"
            style={{
              background: 'var(--rust-tint)',
              color: 'var(--rust)',
              fontSize: 'var(--text-sm)',
            }}
          >
            {error}
          </p>
        )}

        <button
          type="button"
          onClick={() => void submit()}
          disabled={busy}
          className="arch w-full py-4 font-semibold disabled:opacity-60"
          style={{ background: 'var(--accent)', color: 'var(--accent-ink)' }}
        >
          {busy ? t('production.submitting') : t('production.submit')}
        </button>

        {/* Deliberately quieter than Done, and below it. The job is to finish
            the entry; saving half of it is the fallback, not the goal. */}
        <button
          type="button"
          onClick={() => void saveDraft()}
          disabled={busy}
          className="arch w-full border py-3 font-medium disabled:opacity-60"
          style={{ borderColor: 'var(--line-strong)', color: 'var(--ink)' }}
        >
          {t('production.saveDraft')}
        </button>
        <p style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
          {t('production.draftHint')}
        </p>
      </div>
    </Sheet>
  );
}

function Chip({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className="arch border px-3 py-2.5 font-medium"
      style={{
        fontSize: 'var(--text-sm)',
        borderColor: active ? 'var(--accent)' : 'var(--line)',
        background: active ? 'var(--accent-quiet)' : 'var(--surface)',
        color: active ? 'var(--ink)' : 'var(--ink-muted)',
      }}
    >
      {label}
    </button>
  );
}

function NumberField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="mb-1 block font-medium"
        style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
      >
        {label}
      </label>
      <input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value.replace(/\D/g, ''))}
        // inputMode rather than type="number": the numeric keypad without the
        // spinners, the stray minus sign, or the scroll-wheel accidents.
        inputMode="numeric"
        className="tabular arch w-full border px-3 py-3"
        style={{
          borderColor: 'var(--line-strong)',
          background: 'var(--surface)',
          color: 'var(--ink)',
        }}
      />
    </div>
  );
}
