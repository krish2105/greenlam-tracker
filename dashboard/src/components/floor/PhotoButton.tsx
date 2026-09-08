/**
 * Take a photo, on a phone, with one tap.
 *
 * `capture="environment"` opens the rear camera directly rather than a file
 * picker. On a factory floor the alternative is a technician standing beside a
 * stopped press navigating a photo gallery.
 *
 * WHY IT DOWNSCALES BEFORE UPLOADING
 *
 * A modern phone camera produces 3-5 MB per shot, and the floor is on personal
 * phones paying for their own mobile data. Nobody needs 4000 pixels of a
 * delivery receipt: 1600 on the long edge is legible, lands around 200 KB, and
 * uploads over a bad signal in a second rather than a minute.
 *
 * The resize happens in a canvas, which also quietly strips EXIF — including
 * the GPS tag a phone writes by default. That is a BYOD app taking a photo on
 * somebody's personal device, and it has no business recording where they were.
 */

import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

const MAX_EDGE = 1600;
const QUALITY = 0.82;

async function downscale(file: File): Promise<Blob> {
  // HEIC has no decoder in most browsers, so it cannot be drawn to a canvas.
  // Sending it untouched is correct — the server accepts it, and an iPhone
  // photo arriving whole beats one that fails to convert.
  if (!/^image\/(jpeg|png|webp)$/.test(file.type)) return file;

  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  if (scale === 1 && file.size < 400_000) return file;

  const canvas = document.createElement('canvas');
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  const ctx = canvas.getContext('2d');
  if (!ctx) return file;
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();

  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, 'image/jpeg', QUALITY),
  );
  return blob ?? file;
}

export function PhotoButton({
  label,
  onCapture,
  disabled,
  done,
}: {
  label: string;
  onCapture: (photo: Blob) => Promise<void>;
  disabled?: boolean;
  /** Already taken. The button stays, because a second angle is often useful. */
  done?: boolean;
}) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function handle(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError('');
    try {
      await onCapture(await downscale(file));
    } catch (e) {
      setError(e instanceof Error ? e.message : t('photo.failed'));
    } finally {
      setBusy(false);
      // Cleared so taking the same photo twice still fires a change event.
      if (input.current) input.current.value = '';
    }
  }

  return (
    <div>
      <input
        ref={input}
        type="file"
        accept="image/*"
        capture="environment"
        className="sr-only"
        onChange={(e) => void handle(e.target.files?.[0])}
      />
      <button
        type="button"
        onClick={() => input.current?.click()}
        disabled={busy || disabled}
        className="arch flex w-full items-center justify-center gap-2 border py-3 font-medium disabled:opacity-60"
        style={{
          borderColor: done ? 'var(--accent)' : 'var(--line-strong)',
          background: done ? 'var(--accent-quiet)' : 'var(--surface)',
          color: 'var(--ink)',
        }}
      >
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M14.5 4h-5L8 6H4v14h16V6h-4l-1.5-2z" />
          <circle cx="12" cy="13" r="3.5" />
        </svg>
        {busy ? t('photo.saving') : done ? t('photo.another') : label}
      </button>
      {error && (
        <p className="mt-1" style={{ color: 'var(--rust)', fontSize: 'var(--text-sm)' }}>
          {error}
        </p>
      )}
    </div>
  );
}
