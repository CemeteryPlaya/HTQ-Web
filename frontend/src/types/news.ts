export type NewsStatus = 'draft' | 'scheduled' | 'published' | 'archived';

export interface CategoryRef {
  id: number;
  slug: string;
  name: string;
  description?: string;
}

export interface TagRef {
  id: number;
  slug: string;
  name: string;
}

export interface NewsItem {
  id: number;
  title: string;
  slug: string;
  excerpt: string;
  summary?: string;
  content: string;
  image: string | null;
  category: CategoryRef | null;
  category_id: number | null;
  tags: TagRef[];
  author_id: number | null;
  status: NewsStatus;
  published: boolean;
  published_at: string | null;
  scheduled_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface NewsPage {
  items: NewsItem[];
  page: number;
  page_size: number;
  total: number;
  has_next: boolean;
}

export interface NewsListParams {
  page?: number;
  page_size?: number;
  category?: string;
  tag?: string;
  status?: NewsStatus;
  q?: string;
}

export interface NewsWritePayload {
  title: string;
  slug: string;
  excerpt: string;
  content: string;
  image?: string | null;
  category_id?: number | null;
  tag_ids: number[];
  status: NewsStatus;
  scheduled_at?: string | null;
}
