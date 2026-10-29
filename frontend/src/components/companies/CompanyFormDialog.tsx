import { useEffect, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { companiesApi } from '@/api/companies';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { reportApiError } from '@/lib/apiError';
import { COMPANY_KIND_LABELS, type Company, type CompanyKind, type CompanyPatch } from '@/types/companies';

interface Props {
  company: Company;
  /** Кандидаты в родители: сама компания исключается здесь. */
  candidates: Company[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (company: Company) => void;
}

/** Нативные <select>: список из 4–5 значений, и тесты через selectOptions. */
export function CompanyFormDialog({ company, candidates, open, onOpenChange, onSaved }: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState(company.name);
  const [kind, setKind] = useState<CompanyKind>(company.kind);
  const [country, setCountry] = useState(company.country);
  const [parent, setParent] = useState(company.parent_slug ?? '');
  const [showExternalHolders, setShowExternalHolders] = useState(company.show_external_holders);
  const [subdomain, setSubdomain] = useState(company.subdomain ?? '');
  const [bppData, setBppData] = useState(company.bpp_data_company_slug ?? '');

  useEffect(() => {
    setName(company.name); setKind(company.kind); setCountry(company.country); setParent(company.parent_slug ?? '');
    setShowExternalHolders(company.show_external_holders);
    setSubdomain(company.subdomain ?? '');
    setBppData(company.bpp_data_company_slug ?? '');
  }, [company]);

  const mutation = useMutation({
    mutationFn: (body: CompanyPatch) => companiesApi.patch(company.slug, body),
    onSuccess: (res) => { toast.success(t('companies.saved', 'Сохранено')); onSaved(res.data); onOpenChange(false); },
    onError: (e) => reportApiError(e, t('companies.saveFailed', 'Не удалось сохранить')),
  });

  const submit = () => {
    const body: CompanyPatch = {};
    if (name !== company.name) body.name = name;
    if (kind !== company.kind) body.kind = kind;
    if (country !== company.country) body.country = country;
    if ((parent || null) !== company.parent_slug) body.parent_slug = parent || null;
    if (showExternalHolders !== company.show_external_holders) body.show_external_holders = showExternalHolders;
    // Как есть: пустая строка снимает короткий адрес, проверку формата,
    // зарезервированных меток и столкновений делает бэкенд (422).
    if (subdomain !== (company.subdomain ?? '')) body.subdomain = subdomain;
    // Пустая строка — «вести БЗО у себя»; остальные проверки (модуль, свои
    // «Проекты», цепочки) — на бэкенде, 422 `bpp_data_company_invalid`.
    if (bppData !== (company.bpp_data_company_slug ?? '')) body.bpp_data_company_slug = bppData;
    mutation.mutate(body);
  };

  const kinds = (Object.keys(COMPANY_KIND_LABELS) as CompanyKind[]).filter((k) => k !== 'regional' || company.kind === 'regional');
  // Цепочек не бывает: компания, сама ведущая БЗО в другой, данные не держит.
  // Текущее значение остаётся в списке всегда — иначе select его не покажет.
  const bppHosts = candidates.filter((c) => c.slug !== company.slug && (
    c.slug === company.bpp_data_company_slug || (c.status === 'active' && !c.bpp_data_company_slug)));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>{t('companies.editTitle', 'Компания')}: {company.name}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div><Label htmlFor="cf-name">{t('companies.field.name', 'Название')}</Label>
            <Input id="cf-name" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div><Label htmlFor="cf-kind">{t('companies.field.kind', 'Вид')}</Label>
            <select id="cf-kind" className="mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm" value={kind} onChange={(e) => setKind(e.target.value as CompanyKind)}>
              {kinds.map((k) => <option key={k} value={k}>{COMPANY_KIND_LABELS[k]}</option>)}
            </select></div>
          <div><Label htmlFor="cf-parent">{t('companies.field.parent', 'Вышестоящая')}</Label>
            <select id="cf-parent" className="mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm" value={parent} onChange={(e) => setParent(e.target.value)}>
              <option value="">{t('companies.noParent', '— нет (корень) —')}</option>
              {candidates.filter((c) => c.slug !== company.slug).map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
            </select></div>
          <div><Label htmlFor="cf-country">{t('companies.field.country', 'Страна')}</Label>
            <Input id="cf-country" maxLength={2} value={country} onChange={(e) => setCountry(e.target.value.toUpperCase())} /></div>
          <div className="flex items-center justify-between gap-2 rounded-lg border p-3">
            <div>
              <Label htmlFor="cf-external-holders">
                {t('companies.field.showExternalHolders', 'Показывать внешних держателей прав')}
              </Label>
              <p className="text-xs text-muted-foreground">
                {t('companies.showExternalHoldersHint',
                  'Список сотрудников вышестоящих компаний, чьи должности несут им права здесь. Настройка платформенного уровня.')}
              </p>
            </div>
            <Switch
              id="cf-external-holders"
              aria-label={t('companies.field.showExternalHolders', 'Показывать внешних держателей прав')}
              checked={showExternalHolders}
              onCheckedChange={setShowExternalHolders}
            />
          </div>
          <div><Label htmlFor="cf-subdomain">{t('companies.field.subdomain')}</Label>
            <Input id="cf-subdomain" maxLength={32} value={subdomain} placeholder={company.slug}
              aria-describedby="cf-subdomain-hint" onChange={(e) => setSubdomain(e.target.value)} />
            <p id="cf-subdomain-hint" className="mt-1 text-xs text-muted-foreground">
              {t('companies.subdomainHint')}
            </p></div>
          <div><Label htmlFor="cf-bpp-data">{t('companies.field.bppDataCompany', 'БЗО ведётся в компании')}</Label>
            <select id="cf-bpp-data" className="mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm"
              aria-describedby="cf-bpp-data-hint" value={bppData} onChange={(e) => setBppData(e.target.value)}>
              <option value="">{t('companies.bppDataOwn', '— у себя —')}</option>
              {bppHosts.map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
            </select>
            <p id="cf-bpp-data-hint" className="mt-1 text-xs text-muted-foreground">
              {t('companies.bppDataHint',
                '«Проекты», бюджеты, заявки, договоры и счета компании хранятся в выбранной компании; сотрудники работают с ними со своего адреса, права на них выдаются там. У компании не должно быть своих «Проектов».')}
            </p></div>
          <p className="text-xs text-muted-foreground">
            {t('companies.slugLocked', 'slug не правится: он — имя схемы данных и поддомен компании.')}
          </p>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t('common.cancel', 'Отмена')}</Button>
          <Button onClick={submit} disabled={mutation.isPending}>{t('common.save', 'Сохранить')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
