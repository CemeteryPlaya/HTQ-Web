/**
 * components/ServiceUnavailableDialog.tsx
 *
 * Shown whenever the user hits a service the backend registry has switched
 * off (Task 0.5's `ServiceGateMiddleware` / Task 0.7). Two callers today:
 *   - proactively, before navigation (e.g. the conference sidebar entry —
 *     see components/profile/ProfileSidebar.tsx);
 *   - reactively, when any request comes back 503 with
 *     `{ code: "service_disabled" }` (see components/ServiceUnavailableListener.tsx
 *     + api/client.ts's response interceptor).
 */

import { useTranslation } from 'react-i18next';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';

export interface ServiceUnavailableDialogProps {
  /** Service registry name, e.g. "conference" — matches the `service` field
   * FastAPI/Django returns in the 503 envelope. */
  service: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export const ServiceUnavailableDialog: React.FC<ServiceUnavailableDialogProps> = ({
  service,
  open,
  onOpenChange,
}) => {
  const { t } = useTranslation();
  const serviceLabel = t(`serviceUnavailable.services.${service}`, service);

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {t('serviceUnavailable.title', 'Функция временно отключена')}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {t(
              'serviceUnavailable.description',
              '«{{service}}» сейчас недоступен. Попробуйте позже.',
              { service: serviceLabel },
            )}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogAction onClick={() => onOpenChange(false)}>
            {t('serviceUnavailable.close', 'Понятно')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};

export default ServiceUnavailableDialog;
