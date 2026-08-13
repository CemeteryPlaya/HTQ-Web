import { useTranslation } from 'react-i18next';
import { ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { cmsApi } from '@/api/cms';
import { NewsCard, NewsCardSkeleton } from '@/components/news/NewsCard';
import { Button } from '@/components/ui/button';
import type { NewsItem } from '@/types/news';

const PREVIEW_LIMIT = 3;

export const NewsSection = () => {
  const { t } = useTranslation();

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
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
            className="group inline-flex items-center gap-2 font-semibold text-primary transition-all hover:gap-4 min-h-[44px] px-3 py-2 rounded-xl hover:bg-accent/40 w-fit"
          >
            {t('news.view_all')}
            <ArrowRight size={18} className="transition-transform group-hover:translate-x-1" />
          </Link>
        </div>

        {/* Error handling */}
        {isError ? (
          <div className="rounded-2xl border bg-card/70 p-8 text-center">
            <p className="text-muted-foreground">{t('news.loadError')}</p>
            <Button
              variant="outline"
              className="mt-4 min-h-[44px]"
              onClick={() => refetch()}
              disabled={isFetching}
            >
              {isFetching ? t('common.loading') : t('common.retry')}
            </Button>
          </div>
        ) : (
          <>
            <div className="flex md:grid md:grid-cols-2 lg:grid-cols-3 overflow-x-auto snap-x snap-mandatory gap-4 md:gap-8 scrollbar-none pb-4 md:pb-0">
              {isLoading
                ? Array.from({ length: PREVIEW_LIMIT }).map((_, i) => (
                    <div key={i} className="shrink-0 w-[85vw] max-w-[340px] sm:w-[320px] md:w-auto snap-center">
                      <NewsCardSkeleton />
                    </div>
                  ))
                : items.map((item) => (
                    <div key={item.id} className="shrink-0 w-[85vw] max-w-[340px] sm:w-[320px] md:w-auto snap-center">
                      <NewsCard item={item} />
                    </div>
                  ))}
            </div>

            {!isLoading && items.length === 0 && (
              <div className="mt-6 rounded-2xl border bg-card/70 p-8 text-center text-muted-foreground">
                {t('news.empty')}
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
};
