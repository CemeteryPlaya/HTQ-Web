import { useMutation, useQueryClient } from '@tanstack/react-query';
import { emailApi } from '@/api/email';

export function useSendMessage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: emailApi.send,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['email', 'folder'] });
      qc.invalidateQueries({ queryKey: ['email', 'unread'] });
    },
  });
}

export function useStartConnect() {
  return useMutation({
    mutationFn: emailApi.startConnect,
  });
}
