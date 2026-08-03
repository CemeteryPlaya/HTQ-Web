import "@testing-library/jest-dom";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

// Minimal synchronous i18n instance for tests. Components call
// `t(key, "Russian fallback")` throughout the app, so an empty resource
// bundle is enough — react-i18next renders the fallback text when the key
// is missing. This avoids depending on the async HTTP backend the real app
// uses (src/i18n.js), which would leave components unready during tests.
if (!i18n.isInitialized) {
  i18n.use(initReactI18next).init({
    lng: "ru",
    fallbackLng: "ru",
    resources: { ru: { translation: {} }, en: { translation: {} } },
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

// cmdk (the Command/combobox popovers used across the app, e.g. hr/EmployeeFormDialog)
// measures its list with ResizeObserver, which jsdom doesn't implement. Any test that
// actually opens one of these popovers needs the constructor to exist at all — a no-op
// stub is enough since we never assert on resize callbacks in tests.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
Object.defineProperty(window, "ResizeObserver", {
  writable: true,
  value: ResizeObserverStub,
});

// Same cmdk gap: it calls scrollIntoView on the highlighted item, which jsdom
// doesn't implement either.
if (!window.HTMLElement.prototype.scrollIntoView) {
  window.HTMLElement.prototype.scrollIntoView = () => {};
}
