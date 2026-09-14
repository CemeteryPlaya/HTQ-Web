import { useQuery } from '@tanstack/react-query';

import { companiesApi } from '@/api/companies';
import type { MyCompany } from '@/types/companies';

/** Компании, куда пользователя пускают (членство, действующие). Кэш 5 минут — как у usePermissions. */
export function useMyCompanies(options: { enabled?: boolean } = {}) {
  const query = useQuery({
    queryKey: ['companies', 'me'],
    queryFn: async () => (await companiesApi.myCompanies()).data,
    enabled: options.enabled ?? true,
    staleTime: 5 * 60 * 1000,
  });
  return {
    companies: (query.data ?? []) as MyCompany[],
    isLoading: query.isLoading,
    isError: query.isError,
  };
}
