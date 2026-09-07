/**
 * Logging a paper roll through the impregnator.
 *
 * THE WARNING IS THE WHOLE POINT, AND IT APPEARS BEFORE SUBMIT
 *
 * VC is checked against the grade's window as the operator types, so the
 * warning is on screen while the roll is still on the floor. Waiting for the
 * server round trip would show it after the fact; waiting for tomorrow's chart
 * would make it a post-mortem. Only a warning that arrives before the paper
 * reaches the press can change an outcome.
 *
 * The client check is a courtesy — the server decides `out_of_spec` and stores
 * it — but the courtesy is the feature.
 *
 * IT NEVER BLOCKS SUBMIT
 *
 * An out-of-spec roll saves. It is flagged, it is visible on the board, and
 * the operator is told plainly — but the button stays enabled. Force somebody
 * to choose between an honest reading and finishing their shift and they stop
 * entering honest readings, at which point the data this feature depends on
 * quietly becomes fiction.
 *
 * FORM ORDER FOLLOWS THE PROCESS, NOT THE DATABASE
 *
 * Identity, then what came in, then what came out — the order the paper
 * physically moves. A form grouped by data type would put both thicknesses
 * together, which is convenient for nobody standing at the machine.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { localName } from '@greenlam/core';

import * as api from '../../lib/api';
import { Sheet } from '../Sheet';

function toNumber(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

/** Which limits a reading misses, computed locally so the warning is instant. */
function breaches(
  grade: api.PaperGrade | undefined,
  rc: number | null,
  vc: number | null,
  t: (k: string, o?: Record<string, unknown>) => string,
): string[] {
  if (!grade) return [];
  const out: string[] = [];
  const check = (label: string, value: number | null, lo: string | null, hi: string | null) => {
    if (value === null) return;
    if (lo !== null && value < Number(lo)) {
      out.push(t('roll.belowMin', { label, value, limit: Number(lo), grade: grade.name }));
    } else if (hi !== null && value > Number(hi)) {
      out.push(t('roll.aboveMax', { label, value, limit: Number(hi), grade: grade.name }));
    }
  };
  check('RC', rc, grade.rc_min, grade.rc_max);
  check('VC', vc, grade.vc_min, grade.vc_max);
  return out;
}

export function LogRollSheet({
  onClose,
  onLogged,
  machineId: preselected = null,
}: {
  onClose: () => void;
  onLogged: (roll: api.ImpregnationRoll) => void;
  /** Set when the machine was already chosen on the production screen. */
  machineId?: number | null;
}) {
  const { t, i18n } = useTranslation();
  const [machines, setMachines] = useState<api.Machine[]>([]);
  const [grades, setGrades] = useState<api.PaperGrade[]>([]);
  const [companies, setCompanies] = useState<api.Vocab[]>([]);
  const [sizes, setSizes] = useState<api.Vocab[]>([]);
  const [shifts, setShifts] = useState<api.Shift[]>([]);

  const [machineId, setMachineId] = useState<number | null>(preselected);
  const [shiftId, setShiftId] = useState<number | null>(null);
  const [rollNo, setRollNo] = useState('');
  // The resin this roll is being impregnated with. Optional: an operator who
  // does not know it should still record the roll rather than abandon the
  // entry, and a blank is honest where a guess would put a fabricated cause
  // under a real defect later.
  const [batches, setBatches] = useState<api.ResinBatch[]>([]);
  const [resinBatchId, setResinBatchId] = useState<string | null>(null);
  const [gsm, setGsm] = useState('');
  const [thickBefore, setThickBefore] = useState('');
  const [gradeId, setGradeId] = useState<number | null>(null);
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [cutSizeId, setCutSizeId] = useState<number | null>(null);
  const [thickAfter, setThickAfter] = useState('');
  const [rc, setRc] = useState('');
  const [vc, setVc] = useState('');

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const rollRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void api.listResinBatches().then(setBatches).catch(() => setBatches([]));
    void Promise.all([
      api.listMachines(),
      api.listPaperGrades(),
      api.listPaperCompanies(),
      api.listSizes(),
      api.listShifts(),
    ]).then(([m, g, c, s, sh]) => {
      // Only impregnators. Offering all 42 machines would invite a roll being
      // logged against a press, which corrupts the traceability chain at its
      // source.
      setMachines(m.filter((x) => x.code.toUpperCase().startsWith('IMP-')));
      setGrades(g);
      setCompanies(c);
      setSizes(s);
      setShifts(sh);
    });
    rollRef.current?.focus();
  }, []);

  const numberedBatches = useMemo(() => batches.filter((b) => b.batch_no), [batches]);

  const grade = useMemo(() => grades.find((g) => g.id === gradeId), [grades, gradeId]);
  const warnings = useMemo(
    () => breaches(grade, toNumber(rc), toNumber(vc), t),
    [grade, rc, vc, t],
  );

  const name = (v: { name: string; name_hi: string | null; name_hi_latn: string | null }) =>
    localName(v, i18n.language);

  async function submit() {
    if (machineId === null) return setError(t('roll.errors.pickMachine'));
    if (!rollNo.trim()) return setError(t('roll.errors.needRoll'));
    setBusy(true);
    setError('');
    try {
      onLogged(
        await api.logRoll({
          machine_id: machineId,
          shift_id: shiftId,
          log_date: new Date().toISOString().slice(0, 10),
          roll_no: rollNo.trim(),
          resin_batch_id: resinBatchId,
          gsm: toNumber(gsm),
          thickness_before: toNumber(thickBefore),
          paper_grade_id: gradeId,
          paper_company_id: companyId,
          cut_size_id: cutSizeId,
          thickness_after: toNumber(thickAfter),
          rc_percent: toNumber(rc),
          vc_percent: toNumber(vc),
        }),
      );
    } catch (e) {
      setError(
        e instanceof api.ApiError && e.status === 409
          ? t('roll.errors.duplicate', { roll: rollNo.trim() })
          : t('roll.errors.failed'),
      );
    } finally {
      setBusy(false);
    }
  }

  const field = {
    borderColor: 'var(--line-strong)',
    background: 'var(--surface)',
    color: 'var(--ink)',
  } as const;
  const labelStyle = { fontSize: 'var(--text-sm)', color: 'var(--ink)' } as const;

  const Picker = ({
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
    options: { id: number; name: string; name_hi: string | null; name_hi_latn: string | null }[];
  }) => (
    <div>
      <label htmlFor={id} className="mb-1 block font-medium" style={labelStyle}>
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
            {name(o)}
          </option>
        ))}
      </select>
    </div>
  );

  const Num = ({
    id,
    label,
    value,
    onChange,
    hint,
    tone,
  }: {
    id: string;
    label: string;
    value: string;
    onChange: (v: string) => void;
    hint?: string;
    tone?: string;
  }) => (
    <div>
      <label htmlFor={id} className="mb-1 block font-medium" style={labelStyle}>
        {label}
      </label>
      <input
        id={id}
        // Numeric keypad on a phone, and no spinner arrows to fat-finger.
        type="text"
        inputMode="decimal"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="arch w-full border px-3 py-3"
        style={{ ...field, borderColor: tone ?? field.borderColor }}
      />
      {hint && (
        <p className="mt-1" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
          {hint}
        </p>
      )}
    </div>
  );

  const window_ = (lo: string | null, hi: string | null) =>
    lo !== null && hi !== null ? t('roll.window', { lo: Number(lo), hi: Number(hi) }) : undefined;

  return (
    <Sheet title={t('roll.title')} onClose={onClose}>
      <div className="space-y-5">
        {/* --- identity --------------------------------------------------- */}
        <div>
          <label htmlFor="roll-no" className="mb-1 block font-medium" style={labelStyle}>
            {t('roll.rollNo')}
          </label>
          <input
            id="roll-no"
            ref={rollRef}
            value={rollNo}
            onChange={(e) => setRollNo(e.target.value)}
            placeholder={t('roll.rollNoPlaceholder')}
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            className="arch w-full border px-3 py-3"
            style={field}
          />
          <p className="mt-1" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
            {t('roll.rollNoHint')}
          </p>
        </div>

        {/* The step that makes the chain complete: resin batch -> this roll ->
            the sheets pressed from it. Only offered when batches exist, so a
            plant that has not started recording them sees nothing.

            Only NUMBERED batches are offered. A batch recorded without a number
            is legitimate (V5 §6.2) but cannot be picked out of a list — five
            entries reading "· Resin Kettle-3" are five coin flips, and a roll
            pointed at the wrong one is a false trace, which is worse than no
            trace. */}
        {numberedBatches.length > 0 && (
          <div>
            <label htmlFor="roll-resin" className="mb-1 block font-medium" style={labelStyle}>
              {t('roll.resinBatch')}
            </label>
            <select
              id="roll-resin"
              value={resinBatchId ?? ''}
              onChange={(e) => setResinBatchId(e.target.value || null)}
              className="arch w-full border px-3 py-3"
              style={field}
            >
              <option value="">{t('roll.resinBatchNone')}</option>
              {numberedBatches.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.batch_no} · {b.machine_code}
                </option>
              ))}
            </select>
            <p className="mt-1" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
              {t('roll.resinBatchHint')}
            </p>
          </div>
        )}

        <Picker
          id="roll-machine"
          label={t('roll.machine')}
          value={machineId}
          onChange={setMachineId}
          options={machines.map((m) => ({
            id: m.id,
            name: m.code,
            name_hi: null,
            name_hi_latn: null,
          }))}
        />

        <Picker
          id="roll-shift"
          label={t('production.shift')}
          value={shiftId}
          onChange={setShiftId}
          options={shifts.map((s) => ({
            id: s.id,
            name: s.name,
            name_hi: null,
            name_hi_latn: null,
          }))}
        />

        {/* --- incoming paper --------------------------------------------- */}
        <fieldset
          className="arch border px-3 pt-2 pb-3"
          style={{ borderColor: 'var(--line)' }}
        >
          <legend
            className="px-1 font-semibold"
            style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
          >
            {t('roll.beforeDrying')}
          </legend>
          <div className="grid gap-3 sm:grid-cols-2">
            <Num id="gsm" label={t('roll.gsm')} value={gsm} onChange={setGsm} />
            <Num
              id="tb"
              label={t('roll.thicknessBefore')}
              value={thickBefore}
              onChange={setThickBefore}
            />
            <Picker
              id="grade"
              label={t('roll.grade')}
              value={gradeId}
              onChange={setGradeId}
              options={grades}
            />
            <Picker
              id="company"
              label={t('roll.company')}
              value={companyId}
              onChange={setCompanyId}
              options={companies}
            />
          </div>
        </fieldset>

        {/* --- treated paper ---------------------------------------------- */}
        <fieldset
          className="arch border px-3 pt-2 pb-3"
          style={{ borderColor: 'var(--line)' }}
        >
          <legend
            className="px-1 font-semibold"
            style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
          >
            {t('roll.afterDrying')}
          </legend>
          <div className="grid gap-3 sm:grid-cols-2">
            <Picker
              id="cut"
              label={t('roll.cutSize')}
              value={cutSizeId}
              onChange={setCutSizeId}
              options={sizes}
            />
            <Num
              id="ta"
              label={t('roll.thicknessAfter')}
              value={thickAfter}
              onChange={setThickAfter}
            />
            <Num
              id="rc"
              label={t('roll.rc')}
              value={rc}
              onChange={setRc}
              hint={grade ? window_(grade.rc_min, grade.rc_max) : undefined}
            />
            <Num
              id="vc"
              label={t('roll.vc')}
              value={vc}
              onChange={setVc}
              hint={grade ? window_(grade.vc_min, grade.vc_max) : undefined}
              // The one field that gets a coloured border, because it is the
              // one that predicts a blister.
              tone={warnings.some((w) => w.includes('VC')) ? 'var(--rust)' : undefined}
            />
          </div>
        </fieldset>

        {/* The warning. Live, specific, and never a blocker. */}
        {warnings.length > 0 && (
          <div
            role="alert"
            className="arch border px-3 py-2.5"
            style={{
              borderColor: 'var(--rust)',
              borderLeftWidth: '4px',
              background: 'var(--rust-tint)',
            }}
          >
            <p className="font-semibold" style={{ color: 'var(--rust)' }}>
              {t('roll.outOfSpec')}
            </p>
            <ul className="mt-1 space-y-0.5">
              {warnings.map((w) => (
                <li key={w} style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}>
                  {w}
                </li>
              ))}
            </ul>
            <p className="mt-1.5" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
              {t('roll.saveAnyway')}
            </p>
          </div>
        )}

        {error && (
          <p
            role="alert"
            className="arch px-3 py-2"
            style={{ background: 'var(--rust-tint)', color: 'var(--rust)' }}
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
          {busy ? t('roll.saving') : t('roll.submit')}
        </button>
      </div>
    </Sheet>
  );
}
