import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';

import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useLanguageTransition } from '@/hooks/use-language-transition';
import { NewsCard, NewsCardSkeleton } from '@/components/news/NewsCard';
import { cmsApi } from '@/api/cms';
import type { NewsItem } from '@/types/news';

const PAGE_SIZE = 12;

const News = () => {
  const { t } = useTranslation();
  const isChanging = useLanguageTransition();

  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [category, setCategory] = useState<string | null>(null);
  const [tag, setTag] = useState<string | null>(null);

  // Debounce search to avoid hammering the API on each keystroke.
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(search.trim()), 300);
    return () => window.clearTimeout(id);
  }, [search]);

  const { data: categories = [] } = useQuery({
    queryKey: ['cms', 'categories'],
    queryFn: () => cmsApi.listCategories().then((r) => r.data),
    staleTime: 5 * 60_000,
  });

  const { data: tags = [] } = useQuery({
    queryKey: ['cms', 'tags'],
    queryFn: () => cmsApi.listTags().then((r) => r.data),
    staleTime: 5 * 60_000,
  });

  const queryKey = ['news', { q: debounced, category, tag }];
  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    isError,
  } = useInfiniteQuery({
    queryKey,
    initialPageParam: 1,
    queryFn: ({ pageParam = 1 }) =>
      cmsApi
        .listNews({
          page: pageParam as number,
          page_size: PAGE_SIZE,
          q: debounced || undefined,
          category: category || undefined,
          tag: tag || undefined,
        })
        .then((r) => r.data),
    getNextPageParam: (last) => (last.has_next ? last.page + 1 : undefined),
    staleTime: 60_000,
  });

  const items: NewsItem[] = useMemo(
    () =>
      data
        ? data.pages
            .flatMap((p) => p?.items ?? [])
            .filter((it): it is NewsItem => Boolean(it && it.id))
        : [],
    [data],
  );

  // Infinite scroll sentinel
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && hasNextPage && !isFetchingNextPage) {
          void fetchNextPage();
        }
      },
      { rootMargin: '300px' },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  const total = data?.pages[0]?.total ?? 0;

  return (
    <div className={`min-h-screen bg-background relative overflow-hidden language-transition ${isChanging ? 'language-changing' : ''}`}>
      {/* Decorative Background Elements */}
      <div className="pointer-events-none absolute left-0 top-0 -z-10 h-[600px] w-[600px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary/5 blur-[120px] dark:bg-primary/10" />
      <div className="pointer-events-none absolute right-0 top-1/4 -z-10 h-[500px] w-[500px] translate-x-1/3 rounded-full bg-secondary/5 blur-[100px] dark:bg-secondary/10" />

      <Header />
      
      <main className="section-padding relative z-10">
        <div className="container-custom">
          {/* Hero Section */}
          <div className="mb-10 flex flex-col gap-4 sm:mb-14 animate-fade-in-up">
            <span className="inline-block w-fit rounded-full bg-primary/10 px-3 py-1 text-xs font-bold uppercase tracking-widest text-primary dark:bg-primary/20">
              {t('news.tag')}
            </span>
            <h1 className="font-display text-4xl font-extrabold tracking-tight text-foreground md:text-5xl lg:text-6xl xl:text-7xl">
              {t('news.title')}
            </h1>
            {total > 0 && (
              <p className="text-lg font-medium text-muted-foreground/80">
                {t('news.totalCount', { count: total, defaultValue: 'Всего материалов: {{count}}' })}
              </p>
            )}
          </div>

          {/* Filters Bar - Glassmorphism */}
          <div className="mb-10 flex flex-col gap-4 rounded-3xl border border-white/20 bg-white/40 p-5 shadow-elevated backdrop-blur-xl dark:border-white/10 dark:bg-black/40 md:flex-row md:items-center animate-fade-in-up" style={{ animationDelay: '100ms' }}>
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('news.searchPlaceholder', { defaultValue: 'Поиск по новостям…' }) as string}
              className="h-12 rounded-xl bg-background/80 px-4 text-base shadow-sm focus-visible:ring-primary md:max-w-sm"
            />
            <div className="flex flex-1 flex-wrap gap-2">
              <Button
                size="sm"
                variant={category === null ? 'default' : 'outline'}
                onClick={() => setCategory(null)}
                className={`h-10 rounded-xl px-5 font-medium transition-all duration-300 ${category === null ? 'shadow-md shadow-primary/20' : 'bg-background/50 hover:bg-background/80'}`}
              >
                {t('news.allCategories', { defaultValue: 'Все' })}
              </Button>
              {categories.map((c) => (
                <Button
                  key={c.id}
                  size="sm"
                  variant={category === c.slug ? 'default' : 'outline'}
                  onClick={() => setCategory(c.slug)}
                  className={`h-10 rounded-xl px-5 font-medium transition-all duration-300 ${category === c.slug ? 'shadow-md shadow-primary/20' : 'bg-background/50 hover:bg-background/80'}`}
                >
                  {c.name}
                </Button>
              ))}
            </div>
          </div>

          {/* Tags */}
          {tags.length > 0 && (
            <div className="mb-10 flex flex-wrap items-center gap-2 animate-fade-in-up" style={{ animationDelay: '200ms' }}>
              <span className="mr-2 text-sm font-semibold uppercase tracking-wider text-muted-foreground">Теги:</span>
              <button
                onClick={() => setTag(null)}
                className={`rounded-full px-4 py-1.5 text-sm font-medium transition-all duration-300 ${
                  tag === null
                    ? 'bg-primary text-primary-foreground shadow-md shadow-primary/20 scale-105'
                    : 'bg-muted/50 text-muted-foreground hover:bg-muted hover:text-foreground'
                }`}
              >
                Все
              </button>
              {tags.slice(0, 24).map((tg) => (
                <button
                  key={tg.id}
                  onClick={() => setTag(tag === tg.slug ? null : tg.slug)}
                  className={`rounded-full px-4 py-1.5 text-sm font-medium transition-all duration-300 ${
                    tag === tg.slug
                      ? 'bg-primary text-primary-foreground shadow-md shadow-primary/20 scale-105'
                      : 'bg-muted/50 text-muted-foreground hover:bg-muted hover:text-foreground'
                  }`}
                >
                  #{tg.name}
                </button>
              ))}
            </div>
          )}

          {/* Error State */}
          {isError && (
            <div className="rounded-3xl border border-destructive/20 bg-destructive/5 p-8 text-center text-lg font-medium text-destructive backdrop-blur-sm">
              {t('news.loadError', { defaultValue: 'Не удалось загрузить новости. Пожалуйста, попробуйте позже.' })}
            </div>
          )}

          {/* Grid Layout */}
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:gap-8">
            {isLoading
              ? Array.from({ length: 6 }).map((_, i) => <NewsCardSkeleton key={i} />)
              : items.map((item, i) => (
                  <div key={item.id} className="animate-fade-in-up" style={{ animationDelay: `${(i % 12) * 50}ms` }}>
                    <NewsCard item={item} />
                  </div>
                ))}
            {isFetchingNextPage &&
              Array.from({ length: 3 }).map((_, i) => <NewsCardSkeleton key={`next-${i}`} />)}
          </div>

          {/* Empty State */}
          {!isLoading && items.length === 0 && (
            <div className="mt-12 flex flex-col items-center justify-center rounded-3xl border border-dashed border-muted-foreground/20 bg-muted/10 p-16 text-center backdrop-blur-sm">
              <div className="mb-4 rounded-full bg-muted/50 p-4">
                <svg className="h-8 w-8 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
              </div>
              <h3 className="text-2xl font-bold text-foreground">
                {t('news.noResults', { defaultValue: 'Ничего не найдено' })}
              </h3>
              <p className="mt-2 max-w-md text-muted-foreground">
                {t('news.noResultsHint', { defaultValue: 'Попробуйте изменить фильтры или поисковый запрос, чтобы найти то, что вы ищете.' })}
              </p>
              <Button 
                variant="outline" 
                className="mt-6 rounded-full"
                onClick={() => {
                  setSearch('');
                  setCategory(null);
                  setTag(null);
                }}
              >
                Сбросить фильтры
              </Button>
            </div>
          )}

          {/* IntersectionObserver sentinel */}
          <div ref={sentinelRef} className="h-20 w-full" aria-hidden="true" />
        </div>
      </main>
      <Footer />
    </div>
  );
};

export default News;
