import js from "@eslint/js";
import globals from "globals";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      react,
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    settings: {
      react: { version: "detect" },
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "@typescript-eslint/no-unused-vars": "off",

      // Ловим ровно тот класс ошибок, который довёл /hr/employees до
      // рантайм-падения: мердж 35bceaa оставил в JSX <Dialog> и ссылки на
      // form/saveMutation, чьи импорты и объявления выбросил. Ни сборка
      // (vite build не проверяет типы), ни `tsc -p tsconfig.json` (solution-
      // файл с "files": [], проверяет НОЛЬ файлов) этого не видели.
      "react/jsx-no-undef": "error",
    },
  },
  // no-undef включён ТОЛЬКО для обычного JS. Для .ts/.tsx его намеренно гасит
  // typescript-eslint, и не зря: правило не видит типовое пространство TS и на
  // этом коде даёт 105 ложных срабатываний (`ScrollBehavior`, `React` как
  // namespace, `process`) при нуле настоящих. Undefined-идентификаторы в TS
  // ловит компилятор — но для этого его надо запускать: `npm run typecheck`,
  // а НЕ `tsc -p tsconfig.json`, который в этом репозитории проверяет ноль
  // файлов (solution-конфиг с "files": []).
  {
    files: ["**/*.{js,mjs,cjs}"],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      "no-undef": ["error", { typeof: false }],
    },
  },
);
