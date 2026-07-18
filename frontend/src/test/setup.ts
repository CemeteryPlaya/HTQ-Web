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
