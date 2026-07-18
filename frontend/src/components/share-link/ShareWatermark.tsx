/**
 * ShareWatermark — diagonal CSS overlay that prints viewer label, opened-at
 * timestamp, and IP tail across the org chart.
 *
 * Cosmetic deterrent (not a security control). Prevents trivial screenshot
 * sharing by making the recipient's identifier visible in any capture.
 */
import { useMemo } from 'react';

export interface WatermarkPayload {
  viewer_label?: string | null;
  text?: string | null;
  opened_at?: string | null;
  ip_tail?: string | null;
}

interface Props {
  payload: WatermarkPayload | null | undefined;
}

const ROW_COUNT = 8;
const COL_COUNT = 6;

export function ShareWatermark({ payload }: Props) {
  const label = useMemo(() => {
    if (!payload) return '';
    const parts: string[] = [];
    if (payload.viewer_label) parts.push(payload.viewer_label);
    if (payload.text) parts.push(payload.text);
    if (payload.opened_at) {
      try {
        parts.push(new Date(payload.opened_at).toLocaleString('ru'));
      } catch {
        parts.push(payload.opened_at);
      }
    }
    if (payload.ip_tail) parts.push(`#${payload.ip_tail}`);
    return parts.join(' · ');
  }, [payload]);

  if (!label) return null;

  // Repeat the label in a grid so it cannot be cropped out of a screenshot.
  const cells = Array.from({ length: ROW_COUNT * COL_COUNT });

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 z-50 select-none overflow-hidden"
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${COL_COUNT}, 1fr)`,
        gridTemplateRows: `repeat(${ROW_COUNT}, 1fr)`,
      }}
    >
      {cells.map((_, i) => (
        <div
          key={i}
          style={{
            transform: 'rotate(-30deg)',
            opacity: 0.08,
            color: 'currentColor',
            fontSize: '0.85rem',
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            whiteSpace: 'nowrap',
          }}
        >
          {label}
        </div>
      ))}
    </div>
  );
}
