import "@testing-library/jest-dom";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import ru from "../../public/locales/ru/translation.json";

// Синхронный i18n для тестов — вместо async HTTP-backend из src/i18n.js,
// который оставлял бы компоненты «не готовыми».
//
// Ресурсы берём НАСТОЯЩИЕ (public/locales/ru). Раньше бандл был пустым в
// расчёте на то, что компоненты зовут `t(key, "фолбэк")` — но половина
// страниц зовёт `t(key)` без него, и в тестах вместо текста рендерился сырой
// ключ вида `hr.pages.positions.create`. Искать элементы приходилось бы по
// ключам, а тест переставал бы ловить регресс «ключ есть, перевода нет».
if (!i18n.isInitialized) {
  i18n.use(initReactI18next).init({
    lng: "ru",
    fallbackLng: "ru",
    resources: { ru: { translation: ru }, en: { translation: {} } },
    interpolation: { escapeValue: false },
    react: { useSuspense: false },
  });
}

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => {},
  }),
});

// ── Полифиллы под Radix в jsdom ─────────────────────────────────────────────
//
// Компоненты shadcn/ui построены на Radix, а тот в jsdom падает: Select и
// Dialog зовут API, которых в jsdom нет. Без этого блока компонентные тесты
// HR-страниц не проходят дальше первого открытия выпадающего списка.

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

if (!globalThis.IntersectionObserver) {
  globalThis.IntersectionObserver = class {
    readonly root = null;
    readonly rootMargin = "";
    readonly thresholds: readonly number[] = [];
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  } as unknown as typeof IntersectionObserver;
}

// jsdom не реализует Pointer Capture — Radix Select зовёт их при открытии.
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}

// Radix прокручивает активный пункт списка в видимую область.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
