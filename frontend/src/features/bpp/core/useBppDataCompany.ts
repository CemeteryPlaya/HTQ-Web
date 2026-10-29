/**
 * Где ведётся БЗО текущей компании (решение 19.10).
 *
 * Hi-Tech Group LTD ведёт БЗО в головном офисе: запросы раздела с её адреса
 * сервер выполняет в данных головного офиса, права на них выдаются там же
 * (`/access/v1/me` уже отдаёт узлы `bpp.*`/`project.*` оттуда). Фронту это
 * знать нужно только для подсказок: плашка в разделе и ссылки, которые ведут
 * мимо БЗО (доска задач живёт в задачах головного офиса, а не здесь).
 *
 * `company: null` — БЗО ведётся у себя.
 */
import { useMyCompanies } from '@/hooks/useMyCompanies';

export interface BppDataCompany {
  slug: string;
  name: string;
}

export function useBppDataCompany(): { company: BppDataCompany | null; isLoading: boolean } {
  const { companies, isLoading } = useMyCompanies();
  const current = companies.find((c) => c.is_current);
  const slug = current?.bpp_data_company_slug;
  return {
    company: slug ? { slug, name: current?.bpp_data_company_name || slug } : null,
    isLoading,
  };
}
