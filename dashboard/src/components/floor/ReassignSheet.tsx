/**
 * Handing a ticket to a named person (V5 §3, §15.5).
 *
 * TWO DIFFERENT ACTS, ONE SHEET
 *
 * An engineer passing their own ticket on at shift changeover, and a manager
 * assigning somebody else's work. The server allows both — `work_ticket` for
 * the first, `reassign_ticket` for the second — and they want the same three
 * things on screen: who is free, tap a name, done.
 *
 * WHY THE LOAD IS SHOWN
 *
 * A manager choosing between two technicians is almost always asking which of
 * them is free. Without that number the choice gets made on who they last
 * spoke to, and the same person collects every ticket on a bad morning. The
 * list arrives least-loaded first for the same reason.
 *
 * NO REASON FIELD. Handoff happens twenty times a week at changeover, and a
 * mandatory box would be full of "shift" within a fortnight.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import * as api from '../../lib/api';
import { Sheet } from '../Sheet';

export function ReassignSheet({
  ticket,
  onClose,
  onReassigned,
}: {
  ticket: api.Ticket;
  onClose: () => void;
  onReassigned: () => void;
}) {
  const { t } = useTranslation();

  const [people, setPeople] = useState<api.Assignee[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    void api
      .assignableTo()
      .then(setPeople)
      .catch(() => setPeople([]))
      .finally(() => setLoading(false));
  }, []);

  async function assign(userId: number) {
    setBusy(userId);
    setError('');
    try {
      await api.handoffTicket(ticket.id, userId);
      onReassigned();
    } catch (e) {
      setError(e instanceof Error ? e.message : t('reassign.failed'));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Sheet
      title={t('reassign.title', { ticket: ticket.ticket_no ?? ticket.machine_code })}
      onClose={onClose}
    >
      <div className="space-y-4">
        <p style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)' }}>
          {t('reassign.blurb', { machine: ticket.machine_code })}
        </p>

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

        {loading ? (
          <p style={{ color: 'var(--ink-muted)' }}>{t('masters.loading')}</p>
        ) : people.length === 0 ? (
          // Nobody holds Maintenance yet. Saying so is more use than an empty
          // list, because the fix is on the Access screen, not this one.
          <p style={{ color: 'var(--ink-muted)' }}>{t('reassign.nobody')}</p>
        ) : (
          <ul className="space-y-2">
            {people.map((p) => (
              <li key={p.user_id}>
                <button
                  type="button"
                  onClick={() => void assign(p.user_id)}
                  disabled={busy !== null}
                  className="arch flex w-full items-center justify-between border px-3 py-4 text-left disabled:opacity-60"
                  style={{
                    borderColor: 'var(--line-strong)',
                    background: 'var(--surface)',
                    color: 'var(--ink)',
                  }}
                >
                  <span>
                    <span className="block font-semibold">{p.name}</span>
                    <span
                      className="mt-0.5 block"
                      style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)' }}
                    >
                      {p.employee_id}
                    </span>
                  </span>
                  <span
                    className="tabular ml-2 shrink-0"
                    style={{
                      // Somebody already holding four tickets is not the person
                      // to give a fifth to, and the number should say so at a
                      // glance rather than after arithmetic.
                      color: p.open_tickets === 0 ? 'var(--primary)' : 'var(--ink-muted)',
                      fontSize: 'var(--text-sm)',
                    }}
                  >
                    {busy === p.user_id
                      ? t('reassign.assigning')
                      : p.open_tickets === 0
                        ? t('reassign.free')
                        : t('reassign.holding', { count: p.open_tickets })}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Sheet>
  );
}
