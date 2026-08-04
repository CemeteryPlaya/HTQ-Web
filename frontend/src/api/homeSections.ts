/**
 * Блоки главной страницы.
 *
 * Два контура намеренно разделены:
 *   * `fetchPublicHomeSections` — то, что читает сам лендинг: уже
 *     локализованные строки под один язык, только видимые секции, без токена;
 *   * `homeAdminApi` — редакторский: оба языка сразу, включая скрытые секции.
 *
 * Лендинг не должен ходить в админский эндпойнт даже под админом: иначе на
 * странице у редактора появлялись бы скрытые блоки, которых не видят гости.
 */
import api from './client';
import { apiPath } from './endpoints';

export interface HomeItemPublic {
  id: number;
  title: string;
  description: string;
  value: string;
  icon: string;
  image: string;
  link: string;
}

export interface HomeSectionPublic {
  id: number;
  key: string;
  layout: string;
  is_system: boolean;
  tag: string;
  title: string;
  description: string;
  items: HomeItemPublic[];
}

export interface HomeItemAdmin {
  id: number;
  title_ru: string;
  title_en: string;
  description_ru: string;
  description_en: string;
  value: string;
  icon: string;
  image: string;
  link: string;
  is_visible: boolean;
  order: number;
}

export interface HomeSectionAdmin {
  id: number;
  key: string;
  layout: string;
  /** Одна из девяти исходных секций: у неё свой React-компонент, удалять нельзя. */
  is_system: boolean;
  tag_ru: string;
  tag_en: string;
  title_ru: string;
  title_en: string;
  description_ru: string;
  description_en: string;
  is_visible: boolean;
  order: number;
  items: HomeItemAdmin[];
}

/** Публичное чтение. `lang` — код i18next (`ru`, `en`, `en-US`); бэкенд сам
 *  обрезает регион и откатывается на русский для незаполненных переводов. */
export const fetchPublicHomeSections = async (lang: string): Promise<HomeSectionPublic[]> => {
  const res = await api.get<HomeSectionPublic[]>(apiPath('cms', 'home/sections'), {
    params: { lang },
  });
  return res.data;
};

export const homeAdminApi = {
  list: async (): Promise<HomeSectionAdmin[]> => {
    const res = await api.get<HomeSectionAdmin[]>(apiPath('cms', 'home/admin/sections'));
    return res.data;
  },
  updateSection: async (id: number, patch: Partial<HomeSectionAdmin>) => {
    const res = await api.patch<HomeSectionAdmin>(
      apiPath('cms', `home/admin/sections/${id}`), patch,
    );
    return res.data;
  },
  createSection: async (data: {
    title_ru: string; title_en?: string; layout: string;
    tag_ru?: string; description_ru?: string;
  }): Promise<HomeSectionAdmin> => {
    const res = await api.post<HomeSectionAdmin>(apiPath('cms', 'home/admin/sections'), data);
    return res.data;
  },
  deleteSection: (id: number) => api.delete(apiPath('cms', `home/admin/sections/${id}`)),
  reorderSections: (ids: number[]) =>
    api.post(apiPath('cms', 'home/admin/sections/reorder'), { ids }),
  createItem: async (sectionId: number, data: Partial<HomeItemAdmin>) => {
    const res = await api.post<HomeItemAdmin>(
      apiPath('cms', `home/admin/sections/${sectionId}/items`), data,
    );
    return res.data;
  },
  updateItem: async (itemId: number, patch: Partial<HomeItemAdmin>) => {
    const res = await api.patch<HomeItemAdmin>(
      apiPath('cms', `home/admin/items/${itemId}`), patch,
    );
    return res.data;
  },
  deleteItem: (itemId: number) => api.delete(apiPath('cms', `home/admin/items/${itemId}`)),
  reorderItems: (sectionId: number, ids: number[]) =>
    api.post(apiPath('cms', `home/admin/sections/${sectionId}/items/reorder`), { ids }),
};
