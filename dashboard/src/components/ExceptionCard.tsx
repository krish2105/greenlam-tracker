/**
 * One line of "what needs you".
 *
 * Shared between the floor and the board because the judgement — what counts
 * as an exception, and how urgent it is — belongs on the server, not in two
 * divergent UI opinions. What differs by surface is only size.
 *
 * `onOpen` is undefined for corporate roles: the API sends no ticket id, so
 * there is nothing to drill into and the card must not pretend otherwise.
 *
 * The sentence is rendered HERE, from `item.kind` and `item.params`, not taken
 * from the server's `item.headline`. This block is the most-read text in the
 * product and it was the last thing still hardcoded to English — a Hindi user
 * got a fully translated screen with four English sentences in the middle of
 * it. The server decides which message applies; the client decides what
 * language it is in. `headline`/`detail` remain the fallback for a `kind` the
 * client has no string for, so a new server-side exception type degrades to
 * English rather than to a blank card.
 */

import { useTranslation } from 'react-i18next';

import type { ExceptionItem } from '../lib/api';
import { useSectionName } from '../lib/masterNames';

const KIND_TONE: Record<string, { fg: string; bg: string }> = {
  escalated: { fg: 'var(--rust)', bg: 'var(--rust-tint)' },
  ageing: { fg: 'var(--amber)', bg: 'var(--amber-tint)' },
  repeat: { fg: 'var(--rust)', bg: 'var(--rust-tint)' },
  reopened: { fg: 'var(--amber)', bg: 'var(--amber-tint)' },
  awaiting_root_cause: { fg: 'var(--info)', bg: 'var(--info-tint)' },
};

export function ExceptionCard({
  item,
  onOpen,
  compact = false,
}: {
  item: ExceptionItem;
  onOpen?: () => void;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  const sectionName = useSectionName();
  const tone = KIND_TONE[item.kind] ?? {
    fg: 'var(--ink-muted)',
    bg: 'var(--surface-muted)',
  };

  const body = (
    <>
      <div className="flex items-start gap-2.5">
        <span
          aria-hidden="true"
          className="mt-1.5 inline-block h-2 w-2 shrink-0 rounded-full"
          style={{ background: tone.fg }}
        />
        <div className="min-w-0 flex-1">
          <p
            className="font-semibold"
            style={{
              color: 'var(--ink)',
              fontSize: compact ? 'var(--text-sm)' : 'var(--text-base)',
            }}
          >
            {t(`feed.${item.kind}.headline`, {
              ...item.params,
              defaultValue: item.headline,
            })}
          </p>
          {/* Colour is never the only signal — the kind is spelled out. */}
          <p
            className="mt-0.5"
            style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}
          >
            {t(`feed.${item.kind}.detail`, {
              ...item.params,
              defaultValue: item.detail,
            })}
          </p>
          <p
            className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5"
            style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}
          >
            <span style={{ color: tone.fg, fontWeight: 500 }}>
              {t(`exception.${item.kind}`)}
            </span>
            <span aria-hidden="true">·</span>
            <span>{sectionName(item.section_name)}</span>
            {item.priority && (
              <>
                <span aria-hidden="true">·</span>
                <span>{item.priority}</span>
              </>
            )}
          </p>
        </div>
      </div>
    </>
  );

  const style = {
    borderColor: 'var(--line)',
    background: 'var(--surface)',
    borderLeftWidth: '4px',
    borderLeftColor: tone.fg,
  };

  if (!onOpen) {
    return (
      <div className="arch lift border px-3 py-3" style={style}>
        {body}
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={onOpen}
      className="arch lift w-full border px-3 py-3 text-left"
      style={style}
    >
      {body}
    </button>
  );
}
