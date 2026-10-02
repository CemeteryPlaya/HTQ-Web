import { useQuery } from '@tanstack/react-query';

import { contractsApi } from '@/api/contracts';
import { companyFromHost } from '@/lib/auth/companySwitch';
import { getAccessToken } from '@/lib/auth/profileStorage';

/**
 * Заморожен ли раздел «Договоры» у компании (A6.2, D-S6-4).
 *
 * После переноса в «Закупки и оплаты» сервер отвечает 403 `contracts_frozen`
 * на любую запись под `/api/contracts/`; чтение остаётся. Флаг нужен, чтобы
 * не рисовать кнопок, которые ответят 403: экраны раздела показывают плашку
 * и прячут правку, шапка уводит пункт «Договоры» в «Закупки и оплаты» как
 * «Архив договоров».
 *
 * Запрос уходит только с токеном и на поддомене компании: заморозка —
 * свойство компании, а хук стоит в шапке, то есть и на публичных страницах.
 * Пока ответа нет — `frozen: false`: это лишь вид экрана, запись всё равно
 * сторожит сервер.
 */
export interface ContractsFreezeState {
  frozen: boolean;
  frozenAt: string | null;
  comment: string;
  isLoading: boolean;
}

export const CONTRACTS_FREEZE_KEY = ['contracts', 'freeze'] as const;

/** `active=false` — не спрашивать (общий компонент, документ не из раздела). */
export function useContractsFreeze(active = true): ContractsFreezeState {
  const enabled = active
    && Boolean(getAccessToken())
    && typeof window !== 'undefined'
    && companyFromHost(window.location.host) !== null;
  const { data, isLoading } = useQuery({
    queryKey: CONTRACTS_FREEZE_KEY,
    // Модуль «Договоры» выключен (503 service_disabled) — это «не заморожен», а не
    // ошибка: ответ-значение react-query держит свежим (staleTime), ошибку —
    // перезапрашивал бы на каждом переходе (M-2 итогового ревью).
    queryFn: () => contractsApi.getFreeze().then((r) => r.data).catch((err: unknown) => {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 503) return { frozen: false, frozen_at: null, comment: '' };
      throw err;
    }),
    enabled,
    // Морозят раз в жизни компании — дёргать ручку на каждой странице незачем.
    staleTime: 10 * 60 * 1000,
    retry: false,
  });
  return {
    frozen: data?.frozen ?? false,
    frozenAt: data?.frozen_at ?? null,
    comment: data?.comment ?? '',
    isLoading: enabled && isLoading,
  };
}

export default useContractsFreeze;
