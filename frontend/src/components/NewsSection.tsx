import { useTranslation } from 'react-i18next';
import { ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { cmsApi } from '@/api/cms';
import { NewsCard, NewsCardSkeleton } from '@/components/news/NewsCard';
import type { NewsItem } from '@/types/news';

const PREVIEW_LIMIT = 3;

export const NewsSection = () => {
  const { t } = useTranslation();

  const { data, isLoading, isError } = useQuery({
    queryKey: ['news', 'preview', PREVIEW_LIMIT],
    queryFn: () => cmsApi.listNews({ page: 1, page_size: PREVIEW_LIMIT }).then((r) => r.data),
    staleTime: 5 * 60_000,
    retry: false,
  });

  const items: NewsItem[] = data?.items ?? [];

  return (
    <section id="news" className="section-padding bg-background">
      <div className="container-custom">
        <div className="mb-12 flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <div>
            <span className="text-sm font-semibold uppercase tracking-wider text-secondary">
              {t('news.tag')}
            </span>
            <h2 className="mt-2 font-display text-4xl font-bold text-foreground md:text-5xl">
              {t('news.title')}
            </h2>
          </div>
          <Link
            to="/news"
            className="group inline-flex items-center gap-2 font-semibold text-primary transition-all hover:gap-4"
          >
            {t('news.view_all')}
            <ArrowRight size={18} className="transition-transform group-hover:translate-x-1" />
          </Link>
        </div>

        <div className="grid gap-8 md:grid-cols-2 lg:grid-cols-3">
          {isLoading || isError
            ? Array.from({ length: PREVIEW_LIMIT }).map((_, i) => <NewsCardSkeleton key={i} />)
            : items.map((item) => <NewsCard key={item.id} item={item} />)}
        </div>

        {!isLoading && !isError && items.length === 0 && (
          <div className="mt-6 rounded-2xl border bg-card/70 p-8 text-center text-muted-foreground">
            {t('news.empty', { defaultValue: 'Пока нет опубликованных новостей.' })}
          </div>
        )}
      </div>
    </section>
  );
};
