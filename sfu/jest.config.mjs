/**
 * Конфигурация jest для SFU.
 *
 * package.json объявлял `npm test` ещё до появления тестов, но самого
 * конфига не было — прогон падал. Здесь он появляется вместе с первыми
 * тестами (запись конференций).
 *
 * Формат .mjs, а не .ts, намеренно: конфиг на TypeScript jest читает только
 * через ts-node, а тащить в зависимости ещё один транспайлер ради двадцати
 * строк настроек не стоит. Сами тесты при этом на TypeScript — их собирает
 * ts-jest.
 *
 * Два неочевидных пункта, оба — следствие того, что проект ESM
 * (`"type": "module"`) с явными расширениями `.js` в импортах:
 *
 * - `useESM` + `extensionsToTreatAsEsm`: иначе ts-jest соберёт CommonJS и
 *   `import ... from './config.js'` не разрешится;
 * - `moduleNameMapper` срезает `.js` у относительных импортов — на диске
 *   рядом лежит `.ts`, а расширение в исходнике указано целевое (так
 *   требует Node для ESM).
 */
export default {
  preset: 'ts-jest/presets/default-esm',
  testEnvironment: 'node',
  extensionsToTreatAsEsm: ['.ts'],
  roots: ['<rootDir>/src'],
  setupFiles: ['<rootDir>/jest.setup.mjs'],
  moduleNameMapper: {
    '^(\.{1,2}/.*)\.js$': '$1',
  },
  transform: {
    '^.+\.ts$': ['ts-jest', { useESM: true, tsconfig: { module: 'ESNext' } }],
  },
};
