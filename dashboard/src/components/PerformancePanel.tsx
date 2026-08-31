/**
 * "Your work" — a person's own numbers, and a supervisor's view of their team.
 *
 * The framing is the feature. Addendum §4.1 is blunt that individual metrics
 * are the most dangerous thing in this system: the moment floor staff read the
 * app as surveillance, they log late, close early, and write "belt issue" in
 * every root cause. So:
 *
 *   - Someone always sees their OWN numbers first, and can reach them without
 *     anyone granting them anything.
 *   - The team view compares each person to the TEAM AVERAGE, never to a
 *     ranked list. Ordering people by MTTR is a leaderboard whatever the
 *     heading says.
 *   - The copy is workload and support: "you handled 79 tickets, 9 of them
 *     Critical", not "you are below target".
 *
 * The API refuses to return anyone else's numbers to a peer or to any
 * corporate tier, so this component cannot leak what it never receives.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { formatDuration } from '@greenlam/core';

import * as api from '../lib/api';

export function PerformancePanel({ canSeeTeam }: { canSeeTeam: boolean }) {
  const { t } = useTranslation();
  const [mine, setMine] = useState<api.Performance | null>(null);
  const [team, setTeam] = useState<api.TeamPerformance | null>(null);
  const [tab, setTab] = useState<'me' | 'team'>('me');

  useEffect(() => {
    void api.myPerformance(30).then(setMine).catch(() => setMine(null));
    if (canSeeTeam) {
      void api.teamPerformance(30).then(setTeam).catch(() => setTeam(null));
    }
  }, [canSeeTeam]);

  if (!mine) return null;

  return (
    <section aria-labelledby="performance" className="mt-7">
      <div className="register-rule flex items-baseline justify-between pb-1">
        <h2
          id="performance"
          className="font-semibold"
          style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
        >
          {t('performance.title')}
        </h2>
        {canSeeTeam && team && (
          <div role="tablist" className="flex gap-1" aria-label={t('performance.title')}>
            {(['me', 'team'] as const).map((key) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={tab === key}
                onClick={() => setTab(key)}
                className="rounded-full px-3 py-1 font-medium"
                style={{
                  fontSize: 'var(--text-xs)',
                  background: tab === key ? 'var(--surface)' : 'transparent',
                  color: tab === key ? 'var(--ink)' : 'var(--ink-muted)',
                  boxShadow: tab === key ? 'var(--shadow)' : 'none',
                }}
              >
                {key === 'me' ? t('performance.mine') : t('performance.team')}
              </button>
            ))}
          </div>
        )}
      </div>

      {tab === 'me' ? <MyWork data={mine} /> : team ? <TeamWork data={team} /> : null}
    </section>
  );
}

function MyWork({ data }: { data: api.Performance }) {
  const { t } = useTranslation();
  const critical = data.workload_by_priority.Critical ?? 0;

  return (
    <div
      className="arch lift mt-2 border px-4 py-3.5"
      style={{ borderColor: 'var(--line)', background: 'var(--surface)' }}
    >
      {/* Volume first, phrased as workload. An operator raises and does not
          resolve, so the sentence follows whichever the person actually did —
          "resolved 0 breakdowns, 1 of them Critical" was nonsense. */}
      <p style={{ color: 'var(--ink)' }}>
        {data.resolved_count === 0 && data.raised_count === 0
          ? t('performance.nothingYet', { days: data.period_days })
          : `${
              data.resolved_count > 0
                ? // `count` drives the plural form in i18next — naming it
                  // anything else makes the string fall back to its key.
                  t('performance.summary', {
                    count: data.resolved_count,
                    days: data.period_days,
                  })
                : t('performance.summaryRaised', {
                    count: data.raised_count,
                    days: data.period_days,
                  })
            }${critical > 0 ? ' ' + t('performance.criticalOf', { count: critical }) : ''}`}
      </p>

      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
        <Metric
          term={t('performance.respond')}
          value={data.avg_ack_minutes != null ? formatDuration(data.avg_ack_minutes) : '—'}
        />
        <Metric
          term={t('performance.repair')}
          value={data.avg_repair_minutes != null ? formatDuration(data.avg_repair_minutes) : '—'}
        />
        <Metric
          term={t('performance.ftf')}
          value={
            data.first_time_fix_percent != null ? `${data.first_time_fix_percent}%` : '—'
          }
        />
        <Metric
          term={t('performance.writeUps')}
          value={
            data.root_cause_avg_score != null ? `${Math.round(data.root_cause_avg_score)}/100` : '—'
          }
        />
      </dl>

      {/* The one nudge, and only to the person themselves. */}
      {data.is_self && data.root_cause_avg_score != null && data.root_cause_avg_score < 60 && (
        <p
          className="arch mt-3 px-3 py-2"
          style={{
            background: 'var(--amber-tint)',
            color: 'var(--amber)',
            fontSize: 'var(--text-sm)',
          }}
        >
          {t('performance.writeUpNudge')}
        </p>
      )}

      <p className="mt-3" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
        {data.is_self ? t('performance.privateToYou') : t('performance.privateToReport')}
      </p>
    </div>
  );
}

/**
 * A supervisor's team.
 *
 * Every person is shown against the TEAM AVERAGE, not against each other, and
 * the list is alphabetical. That is the difference between "Imran's repairs run
 * longer than the team average — is he getting the hard jobs?" and a ranking.
 */
function TeamWork({ data }: { data: api.TeamPerformance }) {
  const { t } = useTranslation();

  return (
    <div className="mt-2 space-y-2">
      <p style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}>
        {t('performance.teamSummary', {
          count: data.member_count,
          resolved: data.total_resolved,
          days: data.period_days,
          avg:
            data.team_avg_repair_minutes != null
              ? formatDuration(data.team_avg_repair_minutes)
              : '—',
        })}
      </p>

      <ul className="space-y-2">
        {data.members.map((m) => {
          const vsTeam =
            m.avg_repair_minutes != null && data.team_avg_repair_minutes
              ? m.avg_repair_minutes - data.team_avg_repair_minutes
              : null;
          return (
            <li
              key={m.user_id}
              className="arch lift border px-3 py-2.5"
              style={{ borderColor: 'var(--line)', background: 'var(--surface)' }}
            >
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-medium" style={{ color: 'var(--ink)' }}>
                  {m.name}
                </span>
                <span
                  className="tabular"
                  style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}
                >
                  {t('performance.resolvedCount', { count: m.resolved_count })}
                </span>
              </div>
              <p
                className="tabular mt-0.5"
                style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}
              >
                {t('performance.repair')}{' '}
                {m.avg_repair_minutes != null ? formatDuration(m.avg_repair_minutes) : '—'}
                {vsTeam != null && (
                  <>
                    {' · '}
                    <span style={{ color: 'var(--ink-muted)' }}>
                      {t('performance.vsTeam', {
                        delta: formatDuration(Math.abs(vsTeam)),
                        direction:
                          vsTeam > 0 ? t('performance.longer') : t('performance.shorter'),
                      })}
                    </span>
                  </>
                )}
                {m.first_time_fix_percent != null && ` · ${t('performance.ftf')} ${m.first_time_fix_percent}%`}
              </p>
            </li>
          );
        })}
      </ul>

      <p style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
        {t('performance.teamPrivate')}
      </p>
    </div>
  );
}

function Metric({ term, value }: { term: string; value: string }) {
  return (
    <div>
      <dt style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>{term}</dt>
      <dd
        className="tabular font-semibold"
        style={{ fontSize: 'var(--text-lg)', color: 'var(--ink)', margin: 0 }}
      >
        {value}
      </dd>
    </div>
  );
}
