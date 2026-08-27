import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Building2, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { contractsApi } from '@/api/contracts';
import type { Counterparty, CounterpartyStatus, Country } from '@/types/contracts';

/**
 * Правка карточки контрагента.
 *
 * В отличие от формы создания страну здесь только ВЫБИРАЮТ из справочника —
 * вписать новую нельзя: правка карточки не то место, где заводят страну, а
 * PATCH-схема принимает готовый `country_id` (`CounterpartyUpdate`). Кто
 * может править, решает бэкенд (операция админская + карточка должна быть
 * редактируема по оси согласования); форма лишь показывает то же право
 * кнопкой «Редактировать» в карточке.
 *
 * Загрузчик и форма разделены по той же причине, что в `InvoiceEdit`:
 * `<Select>` встаёт с нужным значением, только если оно есть с ПЕРВОГО
 * рендера, поэтому тело монтируется уже с готовыми данными и
 * инициализируется прямо из них.
 */

/** Казахстанский БИН/ИИН — 12 цифр; иностранные номера другой формы, поэтому
 *  это подсказка, а не жёсткая проверка (бэкенд их тоже принимает). */
const KZ_BIN_RE = /^\d{12}$/;

/** Черновая проверка e-mail — поймать опечатку до запроса; окончательное
 *  слово за бэкендом (схема `CounterpartyUpdate`). */
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

type Errors = Record<string, string>;

const CounterpartyEdit = () => {
  const { id } = useParams<{ id: string }>();
  const counterpartyId = Number(id);

  const { data: counterparty, isLoading, isError } = useQuery({
    queryKey: ['contracts', 'counterparty', counterpartyId],
    queryFn: () => contractsApi.getCounterparty(counterpartyId).then((r) => r.data),
    enabled: Number.isFinite(counterpartyId),
  });
  const { data: countries = [], isLoading: countriesLoading } = useQuery({
    queryKey: ['contracts', 'countries'],
    queryFn: () => contractsApi.listCountries().then((r) => r.data),
  });

  const backTo = `/contracts/counterparties/${counterpartyId}`;
  const loading = isLoading || !counterparty || countriesLoading;

  return (
    <ContractsShell>
      <div className="max-w-3xl">
        <div className="mb-6 flex flex-col gap-4">
          <Link
            to={backTo}
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors w-fit"
          >
            <ArrowLeft className="h-4 w-4" />
            К карточке контрагента
          </Link>
          <div className="flex items-center gap-3">
            <Building2 className="h-7 w-7 text-muted-foreground" />
            <h1 className="text-3xl font-bold">Правка контрагента</h1>
          </div>
        </div>

        {isError ? (
          <p className="text-sm text-destructive">Контрагент не найден или недоступен.</p>
        ) : loading ? (
          <div className="space-y-4">
            <Skeleton className="h-56 w-full" />
            <Skeleton className="h-40 w-full" />
          </div>
        ) : (
          <CounterpartyEditForm counterparty={counterparty} countries={countries} />
        )}
      </div>
    </ContractsShell>
  );
};

interface FormProps {
  counterparty: Counterparty;
  countries: Country[];
}

/** Тело формы. Монтируется только с готовыми данными — состояние
 *  инициализируется прямо из них (см. докстринг загрузчика). */
const CounterpartyEditForm = ({ counterparty, countries }: FormProps) => {
  const counterpartyId = counterparty.id;
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: enums } = useQuery({
    queryKey: ['contracts', 'enums'],
    queryFn: () => contractsApi.getEnums().then((r) => r.data),
  });

  const [binIin, setBinIin] = useState(counterparty.bin_iin);
  const [name, setName] = useState(counterparty.name);
  const [countryId, setCountryId] = useState(String(counterparty.country_id));
  const [vat, setVat] = useState(counterparty.vat);
  const [contactName, setContactName] = useState(counterparty.contact_name);
  const [phone, setPhone] = useState(counterparty.phone);
  const [email, setEmail] = useState(counterparty.email);
  const [address, setAddress] = useState(counterparty.address);
  const [status, setStatus] = useState<CounterpartyStatus>(counterparty.status);
  const [errors, setErrors] = useState<Errors>({});

  const countryOptions = useMemo(
    () => countries.map((row) => ({ id: row.id, label: row.name, hint: row.iso_code })),
    [countries],
  );

  const statusOptions = enums?.counterparty_status ?? [
    { value: 'active', label: 'Активен' },
    { value: 'inactive', label: 'Неактивен' },
    { value: 'blocked', label: 'Заблокирован' },
  ];

  const binLooksForeign = binIin.trim().length > 0 && !KZ_BIN_RE.test(binIin.trim());

  const validate = (): Errors => {
    const next: Errors = {};
    if (!binIin.trim()) next.binIin = 'Укажите БИН/ИИН';
    if (!name.trim()) next.name = 'Укажите наименование';
    if (!countryId) next.country = 'Выберите страну';
    if (email.trim() && !EMAIL_RE.test(email.trim())) next.email = 'Похоже, это не e-mail';
    return next;
  };

  const mutation = useMutation({
    mutationFn: () =>
      contractsApi
        .updateCounterparty(counterpartyId, {
          bin_iin: binIin.trim(),
          name: name.trim(),
          country_id: Number(countryId),
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
      toast.success(`Контрагент «${row.name}» сохранён`);
      navigate(`/contracts/counterparties/${counterpartyId}`);
    },
    onError: (error: unknown) => {
      const err = error as {
        response?: { status?: number; data?: { detail?: unknown } };
      };
      const httpStatus = err.response?.status;
      const detail = err.response?.data?.detail;
      // 409 — обычно дубль БИН/ИИН либо карточка заперта согласованием;
      // 403 — правит не автор и не администратор. Тексты с бэкенда осмысленные.
      if ((httpStatus === 409 || httpStatus === 403) && typeof detail === 'string') {
        toast.error(detail);
        return;
      }
      if (httpStatus === 422 && Array.isArray(detail)) {
        toast.error(detail.map((item) => (item as { msg?: string }).msg).join('; '));
        return;
      }
      toast.error('Не удалось сохранить контрагента');
    },
  });

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length > 0) {
      toast.error('Проверьте заполнение формы');
      return;
    }
    mutation.mutate();
  };

  const fieldError = (key: string) =>
    errors[key] ? <p className="text-sm text-destructive mt-1">{errors[key]}</p> : null;

  const backTo = `/contracts/counterparties/${counterpartyId}`;

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Реквизиты</CardTitle>
          <CardDescription>
            БИН/ИИН уникален по реестру — сменить его на уже занятый не
            получится.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label htmlFor="bin-iin">БИН / ИИН</Label>
              <Input
                id="bin-iin"
                value={binIin}
                onChange={(event) => setBinIin(event.target.value)}
                placeholder="123456789012"
                className={errors.binIin ? 'border-destructive' : undefined}
              />
              {fieldError('binIin')}
              {binLooksForeign && !errors.binIin && (
                <p className="text-xs text-muted-foreground mt-1">
                  Не похоже на казахстанский БИН/ИИН (12 цифр) — для
                  иностранного контрагента это нормально.
                </p>
              )}
            </div>

            <div>
              <Label htmlFor="name">Наименование</Label>
              <Input
                id="name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="ТОО «Альфа»"
                className={errors.name ? 'border-destructive' : undefined}
              />
              {fieldError('name')}
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label htmlFor="country">Страна</Label>
              <Select value={countryId} onValueChange={setCountryId}>
                <SelectTrigger
                  id="country"
                  className={errors.country ? 'border-destructive' : undefined}
                >
                  <SelectValue placeholder="Выберите" />
                </SelectTrigger>
                <SelectContent>
                  {countryOptions.map((row) => (
                    <SelectItem key={row.id} value={String(row.id)}>
                      {row.label}
                      {row.hint && ` — ${row.hint}`}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {fieldError('country')}
            </div>

            <div>
              <Label htmlFor="status">Статус</Label>
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

          <div className="flex items-start gap-3">
            <Switch id="vat" checked={vat} onCheckedChange={setVat} />
            <div>
              <Label htmlFor="vat">Плательщик НДС</Label>
              <p className="text-xs text-muted-foreground mt-1">
                Только признак «с НДС / без НДС». Ставка и номер свидетельства
                здесь не ведутся.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Контактные данные</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Label htmlFor="contact-name">Генеральный директор</Label>
              <Input
                id="contact-name"
                value={contactName}
                onChange={(event) => setContactName(event.target.value)}
                placeholder="Петров Пётр Петрович"
                maxLength={200}
              />
            </div>
            <div>
              <Label htmlFor="phone">Телефон</Label>
              <Input
                id="phone"
                type="tel"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                placeholder="+7 700 000 00 00"
                maxLength={30}
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
            <Label htmlFor="address">Адрес</Label>
            <Textarea
              id="address"
              value={address}
              onChange={(event) => setAddress(event.target.value)}
              rows={2}
              placeholder="Алматы, ул. Абая 1"
            />
          </div>
        </CardContent>
      </Card>

      <div className="flex gap-3">
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          Сохранить
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => navigate(backTo)}
          disabled={mutation.isPending}
        >
          Отмена
        </Button>
      </div>
    </form>
  );
};

export default CounterpartyEdit;
