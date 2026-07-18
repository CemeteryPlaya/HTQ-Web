/**
 * lib/serviceUnavailableBus.ts
 *
 * Module-level pub/sub so `api/client.ts` (an axios interceptor, outside
 * React) can notify the UI that a backend service answered 503 with the
 * `service_disabled` envelope, without importing React or holding any
 * component state itself.
 *
 * A single listener (see components/ServiceUnavailableListener.tsx, mounted
 * once near the app root) subscribes and renders the ServiceUnavailableDialog.
 */

type Listener = (service: string) => void;

const listeners = new Set<Listener>();

/** Called by the axios response interceptor on a `service_disabled` 503. */
export function emitServiceDisabled(service: string): void {
  listeners.forEach((listener) => listener(service));
}

/** Subscribes to service-disabled notifications; returns an unsubscribe fn. */
export function subscribeServiceDisabled(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
