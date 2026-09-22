import { Building2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useMyCompanies } from '@/hooks/useMyCompanies';
import { companyFromHost, hostLabelOf, switchCompany } from '@/lib/auth/companySwitch';

/**
 * Переключатель компании — навигация на поддомен, не запрос к API
 * (см. lib/auth/companySwitch.ts).
 *
 * Правило видимости — режим перехода (roadmap §3): компаний больше одной,
 * ЛИБО хост уже содержит поддомен компании. Одна компания на голом домене —
 * переключателя нет: принудительный уход на поддомен требует HTTPS и
 * wildcard-сертификата, которых у стенда может не быть.
 */
export function CompanySwitcher({ enabled = true }: { enabled?: boolean }) {
  const { t } = useTranslation();
  const { companies } = useMyCompanies({ enabled });
  const current = typeof window !== 'undefined' ? companyFromHost(window.location.host) : null;

  if (companies.length === 0) return null;
  if (companies.length === 1 && current === null) return null;

  // Значение пункта — метка хоста (псевдоним или слаг, блок I.2), а не слаг:
  // `current` берётся из хоста, и сравнивать надо в одной системе координат.
  const value = current
    ?? hostLabelOf(companies.find((c) => c.is_current) ?? companies[0]);

  const onValueChange = (label: string) => {
    if (label === current) return;
    const target = companies.find((c) => hostLabelOf(c) === label);
    if (target) switchCompany(target);
  };

  return (
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger
        className="h-10 w-auto min-w-[12rem] gap-2 rounded-full"
        aria-label={t('companies.switcher.label', 'Компания')}
      >
        <Building2 className="h-4 w-4 shrink-0 text-primary" />
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {companies.map((c) => (
          <SelectItem key={c.slug} value={hostLabelOf(c)}>{c.name}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export default CompanySwitcher;
