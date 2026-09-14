import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { AxiosError } from 'axios';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { companiesApi } from '@/api/companies';
import { Switch } from '@/components/ui/switch';

export function CompanyModulesPanel({ slug, canEdit }: { slug: string; canEdit: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ['companies', slug, 'modules'], queryFn: async () => (await companiesApi.modules(slug)).data });
  const mutation = useMutation({
    mutationFn: ({ appLabel, enabled }: { appLabel: string; enabled: boolean }) =>
      companiesApi.setModule(slug, appLabel, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['companies', slug, 'modules'] }),
    onError: (e: AxiosError<{ detail?: string }>) =>
      toast.error(e.response?.data?.detail ?? t('companies.modules.failed', 'Не удалось переключить модуль')),
  });

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        {t('companies.modules.hint', 'Модули ядра есть у каждой компании и не выключаются. Выключенный модуль отвечает 503 только в этой компании.')}
      </p>
      <ul className="divide-y rounded-lg border">
        {(query.data ?? []).map((m) => (
          <li key={m.app_label} className="flex items-center justify-between px-3 py-2 text-sm">
            <span className="font-mono">{m.app_label}{m.is_core && <span className="ml-2 text-xs text-muted-foreground">{t('companies.modules.core', 'ядро')}</span>}</span>
            <Switch aria-label={m.app_label} checked={m.enabled} disabled={m.is_core || !canEdit || mutation.isPending}
              onCheckedChange={(enabled) => mutation.mutate({ appLabel: m.app_label, enabled })} />
          </li>
        ))}
      </ul>
    </div>
  );
}
