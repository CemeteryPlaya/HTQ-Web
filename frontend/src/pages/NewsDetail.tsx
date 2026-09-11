import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { ArrowLeft, Calendar, Globe, Loader2, RotateCcw, Clock, Share2 } from 'lucide-react';
import api from '@/api/client';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { cmsApi } from '@/api/cms';
import type { NewsItem } from '@/types/news';
import { useTranslation } from 'react-i18next';
import { copyText } from '@/lib/clipboard';

type Lang = 'ru' | 'en' | 'kk';

const LANG_CYCLE: Record<Lang, { next: Lang; icon: 'globe' | 'rotate'; label: string }> = {
  ru: { next: 'en', icon: 'globe', label: 'Read in English' },
  en: { next: 'kk', icon: 'globe', label: 'Оқу қазақша' },
  kk: { next: 'ru', icon: 'rotate', label: 'Читать на русском' },
};

interface TranslationCache {
  [lang: string]: { title: string; content: string };
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
}

function ArticleSkeleton() {
  return (
    <div className="mx-auto max-w-[80ch] animate-pulse space-y-8 py-10">
      <div className="space-y-4">
        <div className="h-6 w-1/4 rounded-full bg-muted/60" />
        <div className="h-14 w-full rounded-2xl bg-muted/60" />
        <div className="h-14 w-3/4 rounded-2xl bg-muted/60" />
      </div>
      <div className="aspect-[21/9] w-full rounded-[2rem] bg-muted/60" />
      <div className="space-y-4 pt-8">
        <div className="h-5 w-full rounded-lg bg-muted/40" />
        <div className="h-5 w-11/12 rounded-lg bg-muted/40" />
        <div className="h-5 w-full rounded-lg bg-muted/40" />
        <div className="h-5 w-5/6 rounded-lg bg-muted/40" />
        <div className="h-5 w-3/4 rounded-lg bg-muted/40" />
      </div>
    </div>
  );
}

const NewsDetail = () => {
  const { t } = useTranslation();
  const { slug } = useParams();
  const [news, setNews] = useState<NewsItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [translating, setTranslating] = useState(false);
  const [translations, setTranslations] = useState<TranslationCache>({});
  const [currentLang, setCurrentLang] = useState<Lang>('ru');

  useEffect(() => {
    if (!slug) return;
    setLoading(true);
    setCurrentLang('ru');
    setTranslations({});
    cmsApi
      .getNewsBySlug(slug)
      .then((res) => setNews(res.data))
      .catch((err) => setError(err?.response?.data?.detail || err.message))
      .finally(() => setLoading(false));
  }, [slug]);

  const handleToggleLanguage = async () => {
    if (!news) return;
    const { next } = LANG_CYCLE[currentLang];

    if (next === 'ru') {
      setCurrentLang('ru');
      return;
    }
    if (translations[next]) {
      setCurrentLang(next);
      return;
    }

    setTranslating(true);
    try {
      const res = await api.post(`cms/v1/news/${news.id}/translate`, { target: next });
      const translated_title = (res.data as any)?.translated_title;
      const translated_content = (res.data as any)?.translated_content;
      if (translated_title && translated_content) {
        setTranslations((prev) => ({
          ...prev,
          [next]: { title: translated_title, content: translated_content },
        }));
        setCurrentLang(next);
      } else {
        toast(t('news.detail.translationQueued'));
      }
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || t('news.detail.translationError'));
    } finally {
      setTranslating(false);
    }
  };

  const cached = currentLang !== 'ru' ? translations[currentLang] : null;
  const displayTitle = cached ? cached.title : news?.title;
  const displayContent = cached
    ? cached.content
    : news?.content || news?.excerpt || news?.summary || '';

  const { icon, label } = LANG_CYCLE[currentLang];
  const ButtonIcon = icon === 'globe' ? Globe : RotateCcw;
  const date = useMemo(
    () => formatDate(news?.published_at || news?.created_at),
    [news],
  );

  return (
    <div className="min-h-screen bg-background relative overflow-hidden">
      {/* Decorative Background */}
      <div className="pointer-events-none absolute left-1/2 top-0 -z-10 h-[800px] w-[100%] -translate-x-1/2 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-primary/10 via-background to-background dark:from-primary/5" />

      <Header />
      <main className="container-custom section-padding relative z-10">
        <div className="mx-auto max-w-[80ch]">
          <Link
            to="/news"
            className="group mb-8 inline-flex items-center gap-2 rounded-full bg-muted/50 px-4 py-2 text-sm font-medium text-muted-foreground backdrop-blur-sm transition-all hover:bg-primary/10 hover:text-primary"
          >
            <ArrowLeft className="h-4 w-4 transition-transform group-hover:-translate-x-1" />
            {t('news.detail.backToList')}
          </Link>

          {loading && <ArticleSkeleton />}
          {error && !loading && (
            <div className="rounded-3xl border border-destructive/20 bg-destructive/5 p-8 text-center text-lg font-medium text-destructive backdrop-blur-sm">
              {String(error)}
            </div>
          )}

          {!loading && news && (
            <article className="animate-fade-in-up">
              {/* Header section */}
              <header className="mb-10 space-y-6">
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div className="flex flex-wrap items-center gap-3">
                    {news.category && (
                      <Badge className="bg-primary/10 text-primary hover:bg-primary/20 border-transparent px-3 py-1 text-xs uppercase tracking-widest">
                        {news.category.name}
                      </Badge>
                    )}
                    {date && (
                      <span className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
                        <Clock className="h-4 w-4" />
                        <time dateTime={news.published_at || news.created_at}>{date}</time>
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      className="rounded-full border-primary/20 bg-background/50 backdrop-blur-sm hover:bg-primary/10 hover:text-primary"
                      onClick={() => {
                        if (navigator.share) {
                          navigator.share({
                            title: displayTitle,
                            url: window.location.href,
                          }).catch(console.error);
                        } else {
                          void copyText(window.location.href);
                          toast.success(t('common.linkCopied'));
                        }
                      }}
                    >
                      <Share2 className="mr-2 h-4 w-4" />
                      {t('common.share')}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleToggleLanguage}
                      disabled={translating}
                      className="rounded-full border-primary/20 bg-background/50 backdrop-blur-sm hover:bg-primary/10 hover:text-primary"
                    >
                      {translating ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Translating…
                        </>
                      ) : (
                        <>
                          <ButtonIcon className="mr-2 h-4 w-4" />
                          {label}
                        </>
                      )}
                    </Button>
                  </div>
                </div>

                <h1 className="font-display text-4xl font-extrabold leading-[1.1] tracking-tight text-foreground md:text-5xl lg:text-6xl text-balance">
                  {displayTitle}
                </h1>

                {news.excerpt && (
                  <p className="text-xl leading-relaxed text-muted-foreground/90 md:text-2xl text-balance">
                    {news.excerpt}
                  </p>
                )}
              </header>

              {/* Cover Image */}
              {news.image && (
                <div className="mb-12 overflow-hidden rounded-[2rem] border border-border/40 bg-muted shadow-elevated group relative">
                  <img
                    src={news.image}
                    alt={news.title}
                    className="aspect-[21/9] w-full object-cover transition-transform duration-1000 group-hover:scale-105"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/20 to-transparent opacity-0 transition-opacity duration-500 group-hover:opacity-100" />
                </div>
              )}

              {/* Content Body */}
              <div
                className="prose prose-slate prose-lg max-w-none dark:prose-invert
                           prose-headings:font-display prose-headings:font-bold prose-headings:tracking-tight
                           prose-h2:mt-12 prose-h2:mb-6 prose-h2:text-3xl
                           prose-h3:mt-8 prose-h3:mb-4 prose-h3:text-2xl
                           prose-p:leading-[1.8] prose-p:text-foreground/80 prose-p:mb-6
                           prose-img:rounded-[1.5rem] prose-img:border prose-img:border-border/50 prose-img:shadow-soft
                           prose-a:text-primary prose-a:font-medium prose-a:underline-offset-4 hover:prose-a:text-primary/80
                           prose-blockquote:border-l-4 prose-blockquote:border-primary prose-blockquote:bg-primary/5 prose-blockquote:px-6 prose-blockquote:py-4 prose-blockquote:rounded-r-2xl prose-blockquote:font-medium prose-blockquote:italic prose-blockquote:text-foreground/90
                           prose-code:rounded-md prose-code:bg-muted prose-code:px-1.5 prose-code:py-0.5 prose-code:text-sm prose-code:font-medium
                           prose-pre:rounded-2xl prose-pre:bg-zinc-950 prose-pre:shadow-lg prose-pre:border prose-pre:border-zinc-800"
                dangerouslySetInnerHTML={{ __html: displayContent }}
              />

              {/* Tags Footer */}
              {news.tags && news.tags.length > 0 && (
                <div className="mt-16 flex flex-wrap items-center gap-3 border-t border-border/50 pt-8">
                  <span className="text-sm font-bold uppercase tracking-widest text-muted-foreground">
                    {t('news.tagsLabel')}
                  </span>
                  {news.tags.map((tag) => (
                    <Link
                      key={tag.id}
                      to={`/news?tag=${encodeURIComponent(tag.slug)}`}
                      className="rounded-full bg-muted/50 px-4 py-1.5 text-sm font-medium text-muted-foreground backdrop-blur-sm transition-all hover:bg-primary hover:text-primary-foreground hover:shadow-md hover:-translate-y-0.5"
                    >
                      #{tag.name}
                    </Link>
                  ))}
                </div>
              )}
            </article>
          )}
        </div>
      </main>
      <Footer />
    </div>
  );
};

export default NewsDetail;
