/**
 * The first screen on the floor: Maintenance, or Production.
 *
 * WHY A CHOOSER AND NOT ONE SCREEN
 *
 * The two jobs are done by different people, in different moods, at different
 * moments. Someone reporting a stopped press is standing next to it and wants
 * one button. Someone logging a shift's output is sitting down with a sheet of
 * paper. Putting both on one screen meant four action buttons in a row and a
 * press operator scrolling past eight paper fields he can never fill.
 *
 * Two doors, each opening onto only what that person needs.
 */

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

function Door({
  to,
  title,
  detail,
  icon,
  tone,
}: {
  to: string;
  title: string;
  detail: string;
  icon: React.ReactNode;
  tone: 'accent' | 'quiet';
}) {
  const accent = tone === 'accent';
  return (
    <Link
      to={to}
      className="arch flex flex-col justify-between border p-5 no-underline"
      style={{
        // Tall enough to be hit with a glove on, without hunting.
        minHeight: '9.5rem',
        borderColor: accent ? 'var(--accent)' : 'var(--line-strong)',
        background: accent ? 'var(--accent-quiet)' : 'var(--surface)',
        color: 'var(--ink)',
      }}
    >
      <span aria-hidden="true" style={{ color: accent ? 'var(--primary)' : 'var(--ink-muted)' }}>
        {icon}
      </span>
      <span>
        <span className="block font-semibold" style={{ fontSize: 'var(--text-lg)' }}>
          {title}
        </span>
        <span
          className="mt-0.5 block"
          style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)' }}
        >
          {detail}
        </span>
      </span>
    </Link>
  );
}

export function FloorHome() {
  const { t } = useTranslation();

  return (
    <div className="pt-2">
      <h1 className="font-semibold" style={{ fontSize: 'var(--text-xl)', color: 'var(--ink)' }}>
        {t('floorHome.title')}
      </h1>
      <p className="mt-1" style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)' }}>
        {t('floorHome.subtitle')}
      </p>

      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        <Door
          to="/floor/maintenance"
          tone="accent"
          title={t('floorHome.maintenance')}
          detail={t('floorHome.maintenanceDetail')}
          icon={
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14.7 6.3a4 4 0 0 1-5.4 5.4L4 17v3h3l5.3-5.3a4 4 0 0 1 5.4-5.4l-2.5 2.5-1.4-1.4z" />
            </svg>
          }
        />
        <Door
          to="/floor/production"
          tone="quiet"
          title={t('floorHome.production')}
          detail={t('floorHome.productionDetail')}
          icon={
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 20h18M5 20V9l5 3.5V9l5 3.5V6l4 2.5V20" />
            </svg>
          }
        />
      </div>
    </div>
  );
}
