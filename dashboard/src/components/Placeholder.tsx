/**
 * Honest placeholder for a surface that arrives in a later phase.
 *
 * It names the phase rather than saying "coming soon", so anyone clicking
 * around — including a champion being shown the app in week one — knows this
 * is planned rather than broken.
 */

export function Placeholder({ title, body }: { title: string; body: string }) {
  return (
    <div>
      <h1
        className="font-semibold"
        style={{ fontSize: 'var(--text-xl)', color: 'var(--ink)' }}
      >
        {title}
      </h1>
      <p className="mt-2" style={{ color: 'var(--ink-muted)' }}>
        {body}
      </p>
    </div>
  );
}
