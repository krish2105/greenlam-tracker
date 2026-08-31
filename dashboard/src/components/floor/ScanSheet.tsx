/**
 * Scan a machine label.
 *
 * Two decoders, because neither covers the floor alone:
 *   - `BarcodeDetector` where the platform has it (Chrome/Android). Hardware
 *     accelerated, no library, nothing to download.
 *   - `@zxing/browser` lazily imported on iOS Safari, which still has no
 *     BarcodeDetector. Lazy because it is ~40KB nobody on Android should pay.
 *
 * And a third path that is not a fallback but a first-class option: TYPE THE
 * SHORT CODE. Labels in a laminate plant get scratched, get resin on them and
 * get scrubbed. Addendum §1.2 is explicit that the manual code is not optional,
 * because a damaged sticker must never stop someone reporting a dead press.
 *
 * Camera needs a secure context. On http://<lan-ip> — which is how a plant
 * intranet often serves things — getUserMedia is blocked outright, so the
 * failure is explained rather than shown as a dead black rectangle.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import * as api from '../../lib/api';
import { Sheet } from '../Sheet';

type Mode = 'starting' | 'scanning' | 'manual' | 'blocked';

export function ScanSheet({
  onClose,
  onResolved,
}: {
  onClose: () => void;
  onResolved: (result: api.ScanResolution) => void;
}) {
  const { t } = useTranslation();
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const stopRef = useRef<(() => void) | null>(null);
  const [mode, setMode] = useState<Mode>('starting');
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const resolve = useCallback(
    async (token: string, source: 'in_app' | 'native_camera') => {
      setBusy(true);
      setError('');
      try {
        onResolved(await api.resolveScan(token, source));
      } catch (err) {
        setError(err instanceof api.ApiError ? err.message : t('scan.errors.failed'));
        setBusy(false);
      }
    },
    [onResolved, t],
  );

  useEffect(() => {
    let cancelled = false;

    async function start() {
      // getUserMedia simply does not exist outside a secure context. Say so
      // rather than showing an empty viewfinder.
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        setMode('blocked');
        setError(t('scan.errors.insecure'));
        return;
      }

      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          // Rear camera. Without this the front camera opens and points at
          // the operator's face.
          video: { facingMode: { ideal: 'environment' } },
        });
        if (cancelled) {
          stream.getTracks().forEach((tr) => tr.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => {});
        }
        setMode('scanning');
        void loop();
      } catch {
        // Denied, or no camera at all. Manual entry is a real path, not a
        // consolation prize.
        setMode('manual');
        setError(t('scan.errors.noCamera'));
      }
    }

    async function loop() {
      const video = videoRef.current;
      if (!video) return;

      // Prefer the platform decoder.
      const DetectorCtor = (
        window as unknown as { BarcodeDetector?: new (o: object) => { detect: (s: CanvasImageSource) => Promise<{ rawValue: string }[]> } }
      ).BarcodeDetector;

      if (DetectorCtor) {
        const detector = new DetectorCtor({ formats: ['qr_code'] });
        const tick = async () => {
          if (cancelled || !videoRef.current) return;
          try {
            const found = await detector.detect(videoRef.current);
            if (found.length > 0 && found[0]) {
              handleRaw(found[0].rawValue);
              return;
            }
          } catch {
            /* a dropped frame is not an error worth surfacing */
          }
          requestAnimationFrame(() => void tick());
        };
        void tick();
        return;
      }

      // iOS Safari. Lazily pulled so Android never downloads it.
      try {
        const { BrowserQRCodeReader } = await import('@zxing/browser');
        const reader = new BrowserQRCodeReader();
        const controls = await reader.decodeFromVideoElement(video, (result) => {
          if (result) handleRaw(result.getText());
        });
        stopRef.current = () => controls.stop();
      } catch {
        setMode('manual');
        setError(t('scan.errors.noDecoder'));
      }
    }

    function handleRaw(raw: string) {
      if (cancelled) return;
      cancelled = true;
      // The label encodes {BASE_URL}/s/{token}. Take the last path segment so
      // the same handler works whether the code was scanned in-app or the
      // phone's own camera opened the URL.
      const token = raw.trim().replace(/\/+$/, '').split('/').pop() ?? raw;
      void resolve(token, 'in_app');
    }

    void start();
    return () => {
      cancelled = true;
      stopRef.current?.();
      streamRef.current?.getTracks().forEach((tr) => tr.stop());
    };
  }, [resolve, t]);

  return (
    <Sheet title={t('scan.title')} onClose={onClose}>
      <div className="space-y-4">
        {mode !== 'manual' && mode !== 'blocked' && (
          <div
            className="arch relative overflow-hidden"
            style={{ aspectRatio: '4 / 3', background: 'var(--surface-muted)' }}
          >
            <video
              ref={videoRef}
              className="h-full w-full object-cover"
              muted
              playsInline
              aria-label={t('scan.viewfinder')}
            />
            {/* Reticle. Purely a sighting aid, so hidden from assistive tech. */}
            <div
              aria-hidden
              className="pointer-events-none absolute inset-0 flex items-center justify-center"
            >
              <div
                className="arch"
                style={{
                  width: '58%',
                  aspectRatio: '1',
                  border: '3px solid var(--accent)',
                  boxShadow: '0 0 0 9999px rgb(0 0 0 / 0.35)',
                }}
              />
            </div>
          </div>
        )}

        <p style={{ fontSize: 'var(--text-sm)', color: 'var(--ink-muted)' }}>
          {mode === 'scanning' ? t('scan.hint') : t('scan.manualHint')}
        </p>

        {/* Always present, never buried behind a "having trouble?" link. A
            scratched sticker is the normal case, not the edge case. */}
        <div>
          <label
            htmlFor="short-code"
            className="mb-1 block font-medium"
            style={{ fontSize: 'var(--text-sm)', color: 'var(--ink)' }}
          >
            {t('scan.typeCode')}
          </label>
          <div className="flex gap-2">
            <input
              id="short-code"
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              placeholder="A7K2-M9"
              autoCapitalize="characters"
              autoComplete="off"
              spellCheck={false}
              className="tabular arch flex-1 border px-3 py-3 tracking-widest"
              style={{
                borderColor: 'var(--line-strong)',
                background: 'var(--surface)',
                color: 'var(--ink)',
              }}
            />
            <button
              type="button"
              disabled={busy || code.trim().length < 4}
              onClick={() => void resolve(code.trim(), 'in_app')}
              className="arch px-5 font-semibold disabled:opacity-50"
              style={{ background: 'var(--accent)', color: 'var(--accent-ink)' }}
            >
              {t('scan.go')}
            </button>
          </div>
          <p className="mt-1" style={{ fontSize: 'var(--text-xs)', color: 'var(--ink-muted)' }}>
            {t('scan.codeHint')}
          </p>
        </div>

        {error && (
          <p
            role="alert"
            className="arch px-3 py-2"
            style={{
              background: 'var(--amber-tint)',
              color: 'var(--amber)',
              fontSize: 'var(--text-sm)',
            }}
          >
            {error}
          </p>
        )}
      </div>
    </Sheet>
  );
}
