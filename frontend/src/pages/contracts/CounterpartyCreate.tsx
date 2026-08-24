import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Building2, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import { BinIinInput } from '@/components/ui/bin-iin-input';
import { Button } from '@/components/ui/button';
import { InternationalPhoneInput } from '@/components/ui/international-phone-input';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  ReferenceCombobox,
  type ReferenceValue,
} from '@/components/contracts/ReferenceCombobox';
import { contractsApi } from '@/api/contracts';
import type { CounterpartyStatus } from '@/types/contracts';
import { useTranslation } from 'react-i18next';

/**
 * Карточка контрагента (раздел «Реестр контрагентов»).
 *
 * Устроена как форма бюджета: страну можно выбрать из справочника или
 * вписать новую прямо здесь, и всё уходит одним запросом
 * (POST /counterparties/full), который бэкенд разбирает в одной
 * транзакции. Отдельно заводить страну не нужно.
 *
 * «НДС» — переключатель признака плательщика, не ставка. Контакты — три
 * отдельных поля (ФИО, телефон, e-mail) вместо прежней свободной строки: по
 * ним теперь можно и написать, и позвонить, не разбирая текст глазами.
 * Должности среди них нет намеренно — см. модель Counterparty.
 */

/** Казахстанский БИН/ИИН — 12 цифр. Иностранные номера другой формы, поэтому
 *  это подсказка, а не жёсткая проверка: бэкенд их тоже принимает. */
const KZ_BIN_RE = /^\d{12}$/;

/** Черновая проверка e-mail — ровно чтобы поймать опечатку до запроса;
 *  окончательное слово за бэкендом (схема CounterpartyFullCreate). */
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

type Errors = Record<string, string>;

const CounterpartyCreate = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: countries = [], isLoading: countriesLoading } = useQuery({
    queryKey: ['contracts', 'countries'],
    queryFn: () => contractsApi.listCountries().then((r) => r.data),
  });
  const { data: enums } = useQuery({
    queryKey: ['contracts', 'enums'],
    queryFn: () => contractsApi.getEnums().then((r) => r.data),
  });

  const [binIin, setBinIin] = useState('');
  const [name, setName] = useState('');
  const [country, setCountry] = useState<ReferenceValue>(null);
  const [isoCode, setIsoCode] = useState('');
  const [vat, setVat] = useState(false);
  const [contactName, setContactName] = useState('');
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');
  const [address, setAddress] = useState('');
  const [status, setStatus] = useState<CounterpartyStatus>('active');

  const [errors, setErrors] = useState<Errors>({});

  const countryOptions = useMemo(
    () => countries.map((row) => ({ id: row.id, label: row.name, hint: row.iso_code })),
    [countries],
  );

  const statusOptions = enums?.counterparty_status ?? [
    { value: 'active', label: t('contracts.status.active') },
    { value: 'inactive', label: t('contracts.status.inactive') },
    { value: 'blocked', label: t('contracts.status.blocked') },
  ];

  const binLooksForeign = binIin.trim().length > 0 && !KZ_BIN_RE.test(binIin.trim());

  const validate = (): Errors => {
    const next: Errors = {};
    if (!binIin.trim()) next.binIin = t('contracts.counterpartyForm.errors.bin');
    if (!name.trim()) next.name = t('contracts.counterpartyForm.errors.name');
    if (!country) next.country = t('contracts.counterpartyForm.errors.country');
    // E-mail необязателен, но заполненный обязан быть адресом: бэкенд его
    // проверяет и вернёт 422 — лучше сказать об этом до отправки формы.
    if (email.trim() && !EMAIL_RE.test(email.trim())) next.email = t('contracts.counterpartyForm.errors.email');
    return next;
  };

  const mutation = useMutation({
    mutationFn: () =>
      contractsApi
        .createCounterpartyFull({
          bin_iin: binIin.trim(),
          name: name.trim(),
          country:
            country!.kind === 'existing'
              ? { id: country!.id }
              : { name: country!.label, iso_code: isoCode.trim().toUpperCase() },
          vat,
          contact_name: contactName.trim(),
          phone: phone.trim(),
          email: email.trim(),
          address: address.trim(),
          status,
        })
        .then((r) => r.data),
    onSuccess: (row) => {
      queryClient.invalidateQueries({ queryKey: ['contracts'] });
      toast.success(t('contracts.counterpartyForm.added', { name: row.name }));
      navigate('/contracts/counterparties');
    },
    onError: (error: unknown) => {
      const axiosError = error as import('axios').AxiosError<{
        detail?: unknown;
      }>;
      const httpStatus = axiosError?.response?.status;
      const detail = axiosError?.response?.data?.detail;
      if (httpStatus === 409 && typeof detail === 'string') {
        // Практически всегда — дубль БИН/ИИН. Текст с бэкенда осмысленный.
        toast.error(detail);
        return;
      }
      if (httpStatus === 422 && Array.isArray(detail)) {
        toast.error(detail.map((item) => (item as { msg?: string }).msg ?? '').join('; '));
        return;
      }
      toast.error(t('contracts.counterpartyForm.addError'));
    },
  });

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length > 0) {
      toast.error(t('contracts.formInvalid'));
      return;
    }
    mutation.mutate();
  };

  const fieldError = (key: string) =>
    errors[key] ? <p className="text-sm text-destructive mt-1">{errors[key]}</p> : null;

  return (
    <ContractsShell>
    <div className="max-w-3xl">
        <div className="mb-6 flex flex-col gap-4">
          <Link
            to="/contracts/counterparties"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors w-fit"
          >
            <ArrowLeft className="h-4 w-4" />
            {t('contracts.counterpartyForm.backToList')}
          </Link>
          <div className="flex items-center gap-3">
            <Building2 className="h-7 w-7 text-muted-foreground" />
            <div>
              <h1 className="text-3xl font-bold">{t('contracts.newCounterparty')}</h1>
              <p className="text-muted-foreground text-sm mt-1">
                {t('contracts.counterpartyForm.subtitle')}
              </p>
            </div>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>{t('contracts.counterparty.details')}</CardTitle>
              <CardDescription>
                {t('contracts.counterpartyForm.binHint')}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <Label htmlFor="bin-iin">{t('contracts.counterparty.bin')}</Label>
                  <BinIinInput
                    id="bin-iin"
                    value={binIin}
                    onChange={setBinIin}
                    className={errors.binIin ? 'border-destructive' : undefined}
                  />
                  {fieldError('binIin')}
                  {binLooksForeign && !errors.binIin && (
                    <p className="text-xs text-muted-foreground mt-1">
                      {t('contracts.counterpartyForm.binWarning')}
                    </p>
                  )}
                </div>

                <div>
                  <Label htmlFor="name">{t('contracts.columns.title')}</Label>
                  <Input
                    id="name"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder={t('contracts.counterpartyForm.namePlaceholder')}
                    className={errors.name ? 'border-destructive' : undefined}
                  />
                  {fieldError('name')}
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <Label htmlFor="country">{t('contracts.counterparty.country')}</Label>
                  <ReferenceCombobox
                    id="country"
                    options={countryOptions}
                    value={country}
                    onChange={(next) => {
                      setCountry(next);
                      if (next?.kind !== 'new') setIsoCode('');
                    }}
                    placeholder={t('contracts.pickOrTypeNewF')}
                    createLabel={(input) => t('contracts.createCountry', { input })}
                    loading={countriesLoading}
                    invalid={Boolean(errors.country)}
                  />
                  {fieldError('country')}
                </div>

                <div>
                  <Label htmlFor="status">{t('contracts.columns.status')}</Label>
                  <Select
                    value={status}
                    onValueChange={(value) => setStatus(value as CounterpartyStatus)}
                  >
                    <SelectTrigger id="status">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {statusOptions.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {/* Код ISO нужен только для новой страны — у выбранной он уже есть. */}
              {country?.kind === 'new' && (
                <div className="sm:w-40">
                  <Label htmlFor="iso-code">{t('contracts.isoCode')}</Label>
                  <Input
                    id="iso-code"
                    value={isoCode}
                    onChange={(event) => setIsoCode(event.target.value)}
                    placeholder="KZ"
                    maxLength={3}
                  />
                </div>
              )}

              <div className="flex items-start gap-3">
                <Switch id="vat" checked={vat} onCheckedChange={setVat} />
                <div>
                  <Label htmlFor="vat">{t('contracts.counterpartyForm.vatPayer')}</Label>
                  <p className="text-xs text-muted-foreground mt-1">
                    {t('contracts.counterpartyForm.vatHint')}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t('contracts.counterpartyForm.contacts')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <Label htmlFor="contact-name">{t('contracts.counterparty.ceo')}</Label>
                  <Input
                    id="contact-name"
                    value={contactName}
                    onChange={(event) => setContactName(event.target.value)}
                    placeholder={t('contracts.counterpartyForm.ceoPlaceholder')}
                    maxLength={200}
                  />
                </div>
                <div>
                  <Label htmlFor="phone">{t('profile.phone')}</Label>
                  <InternationalPhoneInput
                    id="phone"
                    value={phone}
                    onChange={setPhone}
                  />
                </div>
                <div>
                  <Label htmlFor="email">E-mail</Label>
                  <Input
                    id="email"
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="info@alfa.kz"
                    maxLength={254}
                    className={errors.email ? 'border-destructive' : undefined}
                  />
                  {fieldError('email')}
                </div>
              </div>
              <div>
                <Label htmlFor="address">{t('contracts.counterparty.address')}</Label>
                <Textarea
                  id="address"
                  value={address}
                  onChange={(event) => setAddress(event.target.value)}
                  rows={2}
                  placeholder={t('contracts.counterpartyForm.addressPlaceholder')}
                />
              </div>
            </CardContent>
          </Card>

          <div className="flex gap-3">
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t('contracts.counterpartyForm.submit')}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => navigate('/contracts/counterparties')}
              disabled={mutation.isPending}
            >
              {t('common.cancel')}
            </Button>
          </div>
        </form>
    </div>
    </ContractsShell>
  );
};

export default CounterpartyCreate;
