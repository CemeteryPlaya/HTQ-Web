import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { emailApi } from '@/api/email';
import type { EmailAccount } from '@/pages/Email/types';

const ACCOUNTS_KEY = ['email', 'accounts'] as const;

export function useEmailAccounts() {
  return useQuery<EmailAccount[]>({
    queryKey: ACCOUNTS_KEY,
    queryFn: emailApi.listAccounts,
    staleTime: 30_000,
  });
}

export function useSetDefaultAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: emailApi.setDefaultAccount,
    onSuccess: () => qc.invalidateQueries({ queryKey: ACCOUNTS_KEY }),
  });
}

export function useSyncAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: emailApi.syncAccount,
    onSuccess: () => qc.invalidateQueries({ queryKey: ACCOUNTS_KEY }),
  });
}

export function useDisconnectAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: emailApi.disconnectAccount,
    onSuccess: () => qc.invalidateQueries({ queryKey: ACCOUNTS_KEY }),
  });
}
