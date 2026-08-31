/**
 * Board-only visual treatment.
 *
 * Adapted from the WinBack Engine design language. Everything here is
 * pointer-driven or GPU-costly, which is exactly why it lives on `/board` and
 * never on the floor: `TiltCard` reads `onMouseMove` and is dead code on a
 * touchscreen, and `Aurora` is a blur(90px) filter that costs a real share of
 * the frame budget on the mid-range Android in a press hall.
 *
 * Correct on a desktop or a wall-mounted screen. Wrong in someone's hand.
 */

import {
  motion,
  useMotionValue,
  useReducedMotion,
  useSpring,
  useTransform,
} from 'motion/react';
import { useRef, useState, type ReactNode } from 'react';

/** Ambient glow behind the board. Purely decorative, hidden from assistive tech. */
export function Aurora() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="aurora aurora-1" />
      <div className="aurora aurora-2" />
    </div>
  );
}

/**
 * 3D-lite card: perspective tilt plus a spotlight that tracks the cursor.
 *
 * No WebGL. Two transforms and a radial gradient give most of the depth cue at
 * none of the cost, and it degrades to a plain card under reduced-motion or on
 * any device without a pointer.
 */
export function TiltCard({
  children,
  className,
  style,
  strength = 4,
}: {
  children: ReactNode;
  className?: string;
  style?: React.CSSProperties;
  strength?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  const [lit, setLit] = useState(false);
  const mx = useMotionValue(0.5);
  const my = useMotionValue(0.5);
  const rotateX = useSpring(useTransform(my, [0, 1], [strength, -strength]), {
    stiffness: 200,
    damping: 20,
  });
  const rotateY = useSpring(useTransform(mx, [0, 1], [-strength, strength]), {
    stiffness: 200,
    damping: 20,
  });
  // Neutral light, and only where the pointer is. The colour comes from the
  // theme so paper can opt out of a highlight entirely (`--spotlight` is
  // transparent in light mode) without this component knowing about themes.
  const spotlight = useTransform(
    [mx, my],
    ([px, py]: number[]) =>
      `radial-gradient(420px circle at ${px * 100}% ${py * 100}%, var(--spotlight), transparent 65%)`,
  );

  function onMove(event: React.MouseEvent) {
    if (reduce || !ref.current) return;
    if (!lit) setLit(true);
    const r = ref.current.getBoundingClientRect();
    mx.set((event.clientX - r.left) / r.width);
    my.set((event.clientY - r.top) / r.height);
  }

  return (
    <motion.div
      ref={ref}
      onMouseMove={onMove}
      onMouseLeave={() => {
        // Off, not re-centred. Leaving it on at the centre is exactly how the
        // highlight became a permanent tint on every tile: mx/my default to
        // 0.5, so "at rest" put a 420px glow through the middle of the card.
        setLit(false);
        mx.set(0.5);
        my.set(0.5);
      }}
      style={
        reduce ? style : { ...style, rotateX, rotateY, transformPerspective: 900 }
      }
      className={`relative [transform-style:preserve-3d] ${className ?? ''}`}
    >
      {!reduce && (
        <motion.div
          aria-hidden
          className="pointer-events-none absolute inset-0 rounded-[inherit] transition-opacity duration-200 ease-out"
          style={{ background: spotlight, opacity: lit ? 1 : 0 }}
        />
      )}
      {children}
    </motion.div>
  );
}

/**
 * Headline that rises word by word on load.
 *
 * Deliberately fast — 400ms with a 20ms stagger, so a twelve-word headline is
 * fully readable in about 0.6s. The landing-page version of this effect runs
 * at 700ms/45ms, which on a control-room board means someone glancing at the
 * screen sees an empty space where the headline should be. An entrance
 * animation must never delay the primary content of an operations dashboard.
 *
 * The full string stays in `aria-label` and the animated spans are hidden, so
 * a screen reader gets one clean sentence rather than a stutter of words.
 */
export function SplitHeadline({
  text,
  className,
  delay = 0,
}: {
  text: string;
  className?: string;
  delay?: number;
}) {
  const reduce = useReducedMotion();
  if (reduce) return <span className={className}>{text}</span>;

  return (
    <span className={className} aria-label={text}>
      {text.split(' ').map((word, i) => (
        <span key={i} className="inline-block overflow-hidden align-bottom">
          <motion.span
            aria-hidden
            className="inline-block"
            initial={{ y: '110%' }}
            animate={{ y: 0 }}
            transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1], delay: delay + i * 0.02 }}
          >
            {word}&nbsp;
          </motion.span>
        </span>
      ))}
    </span>
  );
}

/**
 * Fade-and-rise on mount.
 *
 * Deliberately NOT `whileInView`. Scroll-triggered reveals gate visibility on
 * an IntersectionObserver, and when that misfires — as it did here, leaving the
 * plant map frozen at opacity 0.085 — operational data is simply invisible with
 * no error anywhere. That is the same failure class as a dashboard reporting
 * zero downtime because it could not read the data.
 *
 * On a marketing page a stranded reveal costs nothing. On a board a plant head
 * makes decisions from, content must never depend on a scroll heuristic to
 * exist. Mount-based animation is deterministic: it always finishes.
 */
export function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  const reduce = useReducedMotion();
  if (reduce) return <div className={className}>{children}</div>;

  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1], delay }}
    >
      {children}
    </motion.div>
  );
}
