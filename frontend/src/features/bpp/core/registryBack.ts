/**
 * Ссылка «К списку» с формы документа обратно в реестр — на то же место.
 *
 * Реестр держит страницу и быстрый поиск в адресе (`?page=`, `?q=`), а
 * голый адрес реестра означает «открыли из меню» и сбрасывает место. Кнопка
 * «Назад» браузера место сохраняет, а ссылка на форме вела бы на голый
 * адрес и теряла его. Поэтому `BppRegistry`, открывая строку, кладёт свою
 * строку запроса в состояние перехода (`registryOpenState`), а форма
 * строит ссылку назад хуком `useRegistryBackHref(base)`. Документ открыли
 * не из реестра (прямая ссылка, уведомление, новая вкладка) — состояния
 * нет, и ссылка ведёт на голый адрес, как из меню.
 */
import { useLocation } from 'react-router-dom';

export interface RegistryOpenState {
  /** `location.search` реестра в момент открытия строки (`?page=2&q=…`). */
  registrySearch: string;
}

/** Состояние перехода со строки реестра на форму документа. */
export const registryOpenState = (search: string): RegistryOpenState => ({
  registrySearch: search,
});

const isRegistryOpenState = (state: unknown): state is RegistryOpenState =>
  typeof state === 'object' && state !== null
  && typeof (state as { registrySearch?: unknown }).registrySearch === 'string';

/** Строка запроса реестра из состояния перехода; чужое состояние — пусто. */
export const registrySearchOf = (state: unknown): string => {
  if (!isRegistryOpenState(state)) return '';
  const search = state.registrySearch;
  // Только строка запроса: путь или адрес другого сайта сюда не попадёт.
  return search.startsWith('?') ? search : '';
};

/** Адрес ссылки «К списку»: реестр `base` с тем местом, откуда открыли документ. */
export function useRegistryBackHref(base: string): string {
  const location = useLocation();
  return base + registrySearchOf(location.state);
}
