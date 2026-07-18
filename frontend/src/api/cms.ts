import api from './client';
import { apiPath } from './endpoints';
import type {
  CategoryRef,
  NewsItem,
  NewsListParams,
  NewsPage,
  NewsWritePayload,
  TagRef,
} from '@/types/news';

export const cmsApi = {
  // News
  listNews: (params?: NewsListParams) =>
    api.get<NewsPage>(apiPath('cms', 'news/'), { params }),
  getNewsById: (id: number) => api.get<NewsItem>(apiPath('cms', `news/${id}`)),
  getNewsBySlug: (slug: string) =>
    api.get<NewsItem>(apiPath('cms', `news/by-slug/${encodeURIComponent(slug)}`)),
  createNews: (payload: NewsWritePayload) =>
    api.post<NewsItem>(apiPath('cms', 'news/'), payload),
  updateNews: (id: number, payload: Partial<NewsWritePayload>) =>
    api.patch<NewsItem>(apiPath('cms', `news/${id}`), payload),
  deleteNews: (id: number) => api.delete(apiPath('cms', `news/${id}`)),

  // Categories
  listCategories: () => api.get<CategoryRef[]>(apiPath('cms', 'categories/')),
  createCategory: (data: Pick<CategoryRef, 'slug' | 'name' | 'description'>) =>
    api.post<CategoryRef>(apiPath('cms', 'categories/'), data),
  updateCategory: (id: number, data: Partial<CategoryRef>) =>
    api.patch<CategoryRef>(apiPath('cms', `categories/${id}`), data),
  deleteCategory: (id: number) => api.delete(apiPath('cms', `categories/${id}`)),

  // Tags
  listTags: () => api.get<TagRef[]>(apiPath('cms', 'tags/')),
  createTag: (data: Pick<TagRef, 'slug' | 'name'>) =>
    api.post<TagRef>(apiPath('cms', 'tags/'), data),
  updateTag: (id: number, data: Partial<TagRef>) =>
    api.patch<TagRef>(apiPath('cms', `tags/${id}`), data),
  deleteTag: (id: number) => api.delete(apiPath('cms', `tags/${id}`)),

  // Legacy
  createContactRequest: (data: any) => api.post(apiPath('cms', 'contact-requests/'), data),
  getConferenceConfig: () => api.get(apiPath('cms', 'conference/config')),
};
