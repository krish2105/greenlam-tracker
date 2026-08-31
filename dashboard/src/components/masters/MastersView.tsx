/**
 * Editing the master vocabularies.
 *
 * WHY THIS SCREEN HAD TO EXIST
 *
 * `editMasters` has been a dashboard capability since the two-tier model
 * landed, and the API has had the endpoints since designs and paper grades
 * were added — but there was no interface. A capability nobody can exercise
 * without curl is a capability the product does not have, and it blocked the
 * one thing the plant most needs to do on day one: replace every placeholder
 * in here with their own values.
 *
 * DEACTIVATE, NEVER DELETE
 *
 * A design that stops being made still appears in two years of history. Delete
 * it and every past row loses its label; deactivate it and it simply stops
 * being offered on new entries. The API models this with `is_active`, and this
 * screen never offers a delete.
 *
 * PAPER GRADES GET A DIFFERENT FORM
 *
 * They carry the RC and VC window every roll is judged against — the most
 * consequential numbers in the system. An inverted window (minimum above
 * maximum) would flag every roll and train people to ignore the warning, so
 * the server refuses it and this form surfaces the reason.
 *
 * ALL THREE NAMES AT ENTRY
 *
 * Not English now and translations later. A name that ships English-only
 * becomes the one untranslated word on a Hindi screen, and nobody ever goes
 * back for it — the list below marks exactly which rows are missing one.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { localName } from '@greenlam/core';

import * as api from '../../lib/api';

type Kind =
  | 'designs'
  | 'sizes'
  | 'textures'
  | 'thicknesses'
  | 'paper-grades'
  | 'paper-companies';

const KINDS: Kind[] = [
  'designs',
  'sizes',
  'textures',
  'thicknesses',
  'paper-grades',
  'paper-companies',
];

const LOADERS: Record<Kind, () => Promise<api.Vocab[]>> = {
  designs: api.listDesigns,
  sizes: api.listSizes,
  textures: api.listTextures,
  thicknesses: api.listThicknesses,
  'paper-companies': api.listPaperCompanies,
  'paper-grades': () => api.listPaperGrades() as unknown as Promise<api.Vocab[]>,
};

export function MastersView() {
  const { t, i18n } = useTranslation();
  const [kind, setKind] = useState<Kind>('designs');
  const [rows, setRows] = useState<api.Vocab[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const [name, setName] = useState('');
  const [nameHi, setNameHi] = useState('');
  const [nameLatn, setNameLatn] = useState('');
  const [limits, setLimits] = useState({ rc_min: '', rc_max: '', vc_min: '', vc_max: '' });

  const load = useCallback(() => {
    void LOADERS[kind]()
      .then(setRows)
      .catch(() => setRows([]));
  }, [kind]);

  useEffect(load, [load]);

  function clearForm() {
    setName('');
    setNameHi('');
    setNameLatn('');
    setLimits({ rc_min: '', rc_max: '', vc_min: '', vc_max: '' });
  }

  async function add() {
    if (!name.trim()) {
      setError(t('masters.needName'));
      return;
    }
    setBusy(true);
    setError('');
    const num = (v: string) => (v.trim() ? Number(v) : null);
    try {
      if (kind === 'paper-grades') {
        await api.createPaperGrade({
          name: name.trim(),
          name_hi: nameHi.trim() || null,
          name_hi_latn: nameLatn.trim() || null,
          rc_min: num(limits.rc_min),
          rc_max: num(limits.rc_max),
          vc_min: num(limits.vc_min),
          vc_max: num(limits.vc_max),
        });
      } else {
        await api.createVocab(kind, {
          name: name.trim(),
          name_hi: nameHi.trim() || null,
          name_hi_latn: nameLatn.trim() || null,
        });
      }
      clearForm();
      load();
    } catch (e) {
      setError(e instanceof api.ApiError ? e.message : t('masters.saveFailed'));
    } finally {
      setBusy(false);
    }
  }

  const field = {
    borderColor: 'var(--line-strong)',
    background: 'var(--surface)',
    color: 'var(--ink)',
  } as const;

  const Text = ({
    id,
    label,
    value,
    onChange,
    lang,
    placeholder,
  }: {
    id: string;
    label: string;
    value: string;
    onChange: (v: string) => void;
    lang?: string;
    placeholder?: string;
  }) => (
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
        lang={lang}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="arch w-full border px-3 py-2.5"
        style={field}
      />
    </div>
  );

  return (
    <div className="space-y-6 pb-12">
      <header>
        <h1 className="font-semibold" style={{ fontSize: 'var(--text-xl)', color: 'var(--ink)' }}>
          {t('masters.manageTitle')}
        </h1>
        <p className="mt-1" style={{ color: 'var(--ink-muted)' }}>
          {t('masters.manageSubtitle')}
        </p>
        <p
          className="arch mt-3 border px-3 py-2"
          style={{
            fontSize: 'var(--text-sm)',
            borderColor: 'var(--line)',
            borderLeftWidth: '4px',
            borderLeftColor: 'var(--amber)',
            background: 'var(--surface)',
            color: 'var(--ink)',
          }}
        >
          {t('masters.placeholderWarning')}
        </p>
      </header>

      {/* All six visible. This screen exists to be worked through, not
          navigated, so a select that hides five of them would be wrong. */}
      <div
        role="radiogroup"
        aria-label={t('masters.manageTitle')}
        className="flex flex-wrap gap-1.5"
      >
        {KINDS.map((k) => (
          <button
            key={k}
            type="button"
            role="radio"
            aria-checked={kind === k}
            onClick={() => {
              setKind(k);
              clearForm();
              setError('');
            }}
            className="arch min-h-[38px] border px-3 font-medium"
            style={{
              fontSize: 'var(--text-sm)',
              borderColor: kind === k ? 'var(--accent)' : 'var(--line)',
              background: kind === k ? 'var(--accent-quiet)' : 'transparent',
              color: kind === k ? 'var(--ink)' : 'var(--ink-muted)',
            }}
          >
            {t(`masters.kind.${k}`)}
          </button>
        ))}
      </div>

      <section
        aria-labelledby="add-master"
        className="arch border px-4 py-3.5"
        style={{ borderColor: 'var(--line)', background: 'var(--surface)' }}
      >
        <h2
          id="add-master"
          className="font-semibold"
          style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
        >
          {t('masters.addTo', { kind: t(`masters.kind.${kind}`) })}
        </h2>

        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <Text id="m-en" label={t('masters.nameEn')} value={name} onChange={setName} />
          <Text
            id="m-hi"
            label={t('masters.nameHi')}
            value={nameHi}
            onChange={setNameHi}
            lang="hi"
          />
          <Text
            id="m-latn"
            label={t('masters.nameLatn')}
            value={nameLatn}
            onChange={setNameLatn}
            lang="hi-Latn"
          />
        </div>

        {kind === 'paper-grades' && (
          <fieldset
            className="arch mt-3 border px-3 pt-2 pb-3"
            style={{ borderColor: 'var(--line)' }}
          >
            <legend
              className="px-1 font-semibold"
              style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
            >
              {t('masters.specWindow')}
            </legend>
            <div className="grid gap-3 sm:grid-cols-4">
              {(['rc_min', 'rc_max', 'vc_min', 'vc_max'] as const).map((key) => (
                <Text
                  key={key}
                  id={`g-${key}`}
                  label={t(`masters.${key}`)}
                  value={limits[key]}
                  onChange={(v) => setLimits((prev) => ({ ...prev, [key]: v }))}
                  placeholder="%"
                />
              ))}
            </div>
            <p className="mt-2" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
              {t('masters.specNote')}
            </p>
          </fieldset>
        )}

        {error && (
          <p
            role="alert"
            className="arch mt-3 px-3 py-2"
            style={{ background: 'var(--rust-tint)', color: 'var(--rust)' }}
          >
            {error}
          </p>
        )}

        <button
          type="button"
          onClick={() => void add()}
          disabled={busy}
          className="arch mt-3 min-h-[44px] px-5 font-semibold disabled:opacity-50"
          style={{ background: 'var(--accent)', color: 'var(--accent-ink)' }}
        >
          {busy ? t('masters.saving') : t('masters.add')}
        </button>
      </section>

      <section aria-labelledby="master-list">
        <h2
          id="master-list"
          className="register-rule pb-1 font-semibold"
          style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
        >
          {t(`masters.kind.${kind}`)} · {rows.length}
        </h2>
        {rows.length === 0 ? (
          <p className="py-4" style={{ color: 'var(--ink-muted)' }}>
            {t('masters.emptyList')}
          </p>
        ) : (
          <ul className="mt-2 space-y-1">
            {rows.map((row) => (
              <li
                key={row.id}
                className="arch flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border px-3 py-2"
                style={{ borderColor: 'var(--line)', background: 'var(--surface)' }}
              >
                <span style={{ color: 'var(--ink)' }}>{localName(row, i18n.language)}</span>
                <span style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
                  {/* Surface what is MISSING. An untranslated name is exactly
                      the thing this screen exists to let somebody fix. */}
                  {!row.name_hi || !row.name_hi_latn
                    ? t('masters.missingTranslation')
                    : row.name}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
