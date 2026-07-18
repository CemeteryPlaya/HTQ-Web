import { Link } from 'react-router-dom';
import { Calendar, ArrowRight } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import type { NewsItem } from '@/types/news';

const FALLBACK_IMAGE = '/images/panels5.webp';

function formatDate(value: string | null | undefined): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
}

interface NewsCardProps {
  item: NewsItem;
  /** Optional CSS class for outer link */
  className?: string;
}

export function NewsCard({ item, className = '' }: NewsCardProps) {
  const cover = item.image || FALLBACK_IMAGE;
  const date = formatDate(item.published_at || item.scheduled_at || item.created_at);

  return (
    <Link
      to={`/news/${item.slug}`}
      className={`group flex h-full flex-col overflow-hidden rounded-[1.5rem] border border-border/50 bg-card/80 shadow-sm backdrop-blur-md
                  transition-all duration-500 ease-out
                  hover:-translate-y-2 hover:border-primary/40 hover:shadow-[var(--shadow-elevated)] focus-visible:outline-none
                  focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${className}`}
    >
      <div className="relative aspect-[16/10] w-full overflow-hidden bg-muted">
        <img
          src={cover}
          alt={item.title}
          loading="lazy"
          className="h-full w-full object-cover transition-transform duration-700 ease-in-out group-hover:scale-[1.08]"
        />
        {/* Subtle gradient overlay for better contrast */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-black/0 to-black/0 opacity-60 transition-opacity duration-500 group-hover:opacity-80" />
        
        {item.category && (
          <Badge className="absolute left-4 top-4 bg-primary/90 text-primary-foreground backdrop-blur-sm shadow-sm transition-transform duration-300 group-hover:scale-105">
            {item.category.name}
          </Badge>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-3 p-6">
        {date && (
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground/80">
            <Calendar size={14} className="text-primary/70" />
            <time dateTime={item.published_at || item.created_at}>{date}</time>
          </div>
        )}

        <h3 className="font-display text-xl font-bold leading-tight line-clamp-2 text-foreground transition-colors duration-300 group-hover:text-primary">
          {item.title}
        </h3>

        {item.excerpt && (
          <p className="mt-1 text-sm leading-relaxed text-muted-foreground line-clamp-3">
            {item.excerpt}
          </p>
        )}

        <div className="mt-auto pt-4 flex flex-col gap-4">
          {item.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {item.tags.slice(0, 3).map((tag) => (
                <span
                  key={tag.id}
                  className="rounded-lg bg-muted/60 px-2 py-1 text-xs font-medium text-muted-foreground transition-colors group-hover:bg-primary/10 group-hover:text-primary"
                >
                  #{tag.name}
                </span>
              ))}
              {item.tags.length > 3 && (
                <span className="rounded-lg bg-muted/60 px-2 py-1 text-xs font-medium text-muted-foreground">
                  +{item.tags.length - 3}
                </span>
              )}
            </div>
          )}
          
          <div className="flex items-center text-sm font-semibold text-primary opacity-0 transition-all duration-300 -translate-x-4 group-hover:opacity-100 group-hover:translate-x-0">
            Читать далее <ArrowRight className="ml-1.5 h-4 w-4" />
          </div>
        </div>
      </div>
    </Link>
  );
}

export function NewsCardSkeleton() {
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-[1.5rem] border border-border/30 bg-card/40 backdrop-blur-sm">
      <div className="aspect-[16/10] animate-pulse bg-muted/60" />
      <div className="flex flex-1 flex-col gap-4 p-6">
        <div className="flex gap-2">
          <div className="h-4 w-5 animate-pulse rounded bg-muted/60" />
          <div className="h-4 w-24 animate-pulse rounded bg-muted/60" />
        </div>
        <div className="h-7 w-full animate-pulse rounded-md bg-muted/60" />
        <div className="h-7 w-3/4 animate-pulse rounded-md bg-muted/60" />
        
        <div className="mt-2 space-y-2">
          <div className="h-4 w-full animate-pulse rounded bg-muted/40" />
          <div className="h-4 w-5/6 animate-pulse rounded bg-muted/40" />
        </div>
        
        <div className="mt-auto flex gap-2 pt-4">
          <div className="h-6 w-16 animate-pulse rounded-lg bg-muted/60" />
          <div className="h-6 w-20 animate-pulse rounded-lg bg-muted/60" />
        </div>
      </div>
    </div>
  );
}
