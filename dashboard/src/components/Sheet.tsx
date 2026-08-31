/**
 * Bottom sheet.
 *
 * Slides from the bottom because that is where the thumb is and where the
 * trigger was. Escape closes it, focus moves into it on open and returns to
 * the trigger on close, and the scrim is heavy enough (55%) to actually
 * isolate the foreground rather than leaving the page competing behind it.
 */

import { useEffect, useRef, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

export function Sheet({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const panelRef = useRef<HTMLDivElement>(null);
  const returnFocusTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    returnFocusTo.current = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);

    // Stop the page behind from scrolling while the sheet owns the screen.
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previous;
      returnFocusTo.current?.focus();
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center">
      <div
        className="absolute inset-0"
        style={{ background: 'rgb(0 0 0 / 0.55)' }}
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className="relative max-h-[92dvh] w-full max-w-lg overflow-y-auto"
        style={{
          background: 'var(--surface-raised)',
          borderRadius: '18px 18px 0 0',
          boxShadow: 'inset 0 1px 0 var(--edge-light), 0 -8px 32px rgb(0 0 0 / 0.4)',
          paddingBottom: 'max(1.25rem, env(safe-area-inset-bottom))',
        }}
      >
        <div
          className="sticky top-0 z-10 flex items-center justify-between border-b px-4 py-3"
          style={{ background: 'var(--surface-raised)', borderColor: 'var(--line)' }}
        >
          <h2 className="font-semibold" style={{ color: 'var(--ink)' }}>
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close')}
            className="flex h-11 w-11 items-center justify-center rounded-full"
            style={{ color: 'var(--ink-muted)' }}
          >
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="px-4 pt-4">{children}</div>
      </div>
    </div>
  );
}
