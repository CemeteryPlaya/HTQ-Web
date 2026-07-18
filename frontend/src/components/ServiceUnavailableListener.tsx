/**
 * components/ServiceUnavailableListener.tsx
 *
 * Mounted once near the app root (see App.tsx, alongside ConferenceNotifier).
 * Subscribes to the module-level bus that api/client.ts's response
 * interceptor writes to on any `503 { code: "service_disabled" }` and pops
 * the ServiceUnavailableDialog naming whichever service the backend
 * rejected — independent of the proactive conference-entry gating in
 * ProfileSidebar.
 */

import { useEffect, useState } from 'react';
import { ServiceUnavailableDialog } from '@/components/ServiceUnavailableDialog';
import { subscribeServiceDisabled } from '@/lib/serviceUnavailableBus';

export const ServiceUnavailableListener = () => {
  const [service, setService] = useState<string | null>(null);

  useEffect(() => subscribeServiceDisabled(setService), []);

  if (!service) return null;

  return (
    <ServiceUnavailableDialog
      service={service}
      open={Boolean(service)}
      onOpenChange={(open) => {
        if (!open) setService(null);
      }}
    />
  );
};

export default ServiceUnavailableListener;
