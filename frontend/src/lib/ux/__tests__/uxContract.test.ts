/**
 * Заслон против двух способов оставить сотрудника без объяснения.
 *
 * Оба ловятся статически, по исходникам, — как и сырые i18n-ключи в
 * `lib/i18n/__tests__/translationKeys.test.ts`. Приём тот же и по той же
 * причине: ни typecheck, ни линт не видят разницы между «показали причину» и
 * «показали общую отписку», а видит её только человек — уже в проде.
 *
 * ── Проверка А: ошибка сервера проглочена ────────────────────────────────
 * В `onError` мутации нельзя показывать свой текст мимо `lib/apiError`:
 * бэкенд объясняет 409, 422, 400 и 502 словами, а «Не удалось сохранить»
 * это объяснение стирает. Исключений у проверки нет: `toast.error` рядом с
 * `reportApiError`/`explainedDetail` в одном обработчике разрешён — так
 * написаны места, где у одного статуса своя, более точная фраза.
 *
 * ── Проверка В: пара дат без проверки порядка ────────────────────────────
 * Форма, где вводят и начало, и окончание, обязана звать `datesOutOfOrder`
 * из `lib/validation`. Правило форме известно, а узнавать о нём от сервера
 * дороже: на части сущностей бэкенд до недавнего времени отвечал 500-й, а на
 * проекте не отвечал вовсе — перепутанные даты просто сохранялись.
 *
 * ── Проверка Б: пустой список без объяснения ─────────────────────────────
 * Селект, который кормится из `useQuery`, однажды окажется пустым: справочник
 * не заполнен, у администратора нет согласованных договоров, отделы ещё не
 * заведены. Пустой выпадающий список выглядит как поломка формы, поэтому
 * рядом должен стоять `PrerequisiteNotice` или ветка `length === 0`.
 *
 * Проверка Б — ЭВРИСТИКА, и это честнее, чем притворяться иначе. Она не
 * понимает, обязателен ли селект и бывает ли справочник пустым в принципе;
 * такие места перечислены в `ux-contract-allowlist.txt` с причиной. Список
 * обязан уменьшаться: строка в нём — долг, а не разрешение.
 */
import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(HERE, '../../../..');
const SRC = path.join(FRONTEND, 'src');

function sourceFiles(dir: string, acc: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== 'node_modules' && entry.name !== '__tests__') sourceFiles(full, acc);
    } else if (/\.tsx$/.test(entry.name) && !/\.(test|spec)\.tsx$/.test(entry.name)) {
      acc.push(full);
    }
  }
  return acc;
}

const rel = (file: string) => path.relative(SRC, file).split(path.sep).join('/');
const lineAt = (text: string, index: number) => text.slice(0, index).split('\n').length;

/** Строки вида `путь:ключ`; `#` — комментарий. */
function allowlist(): Set<string> {
  const file = path.join(FRONTEND, 'ux-contract-allowlist.txt');
  if (!fs.existsSync(file)) return new Set();
  return new Set(
    fs.readFileSync(file, 'utf-8')
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith('#')),
  );
}

/**
 * Тело обработчика `onError` — от стрелки до конца выражения.
 *
 * Скобки считаем вручную: обработчики бывают и однострочные, и с телом в
 * фигурных скобках, и регуляркой одно от другого не отличить.
 *
 * ⚠️ Счёт начинается ПОСЛЕ стрелки, а не от `onError:`. Иначе первая же пара
 * скобок — список параметров `(err) =>` — закрывает счётчик, тело остаётся
 * пустым, и проверка молча пропускает всё подряд. Ровно так она и вела себя,
 * пока в неё не подложили заведомое нарушение.
 */
function onErrorBodies(text: string): { index: number; body: string }[] {
  const found: { index: number; body: string }[] = [];
  for (const match of text.matchAll(/onError:/g)) {
    const start = match.index ?? 0;
    const arrow = text.indexOf('=>', start);
    // `onError: someHelper(...)` — стрелки нет, тело берём до конца строки.
    const from = arrow >= 0 && arrow - start < 120 ? arrow + 2 : start;
    let depth = 0;
    let opened = false;
    let i = from;
    for (; i < text.length; i += 1) {
      const char = text[i];
      if ('({['.includes(char)) { depth += 1; opened = true; } else if (')}]'.includes(char)) {
        if (opened && depth <= 1) break;
        depth -= 1;
      } else if (char === ',' && opened && depth === 0) break;
      else if (char.charCodeAt(0) === 10 && !opened) break;
    }
    found.push({ index: start, body: text.slice(start, i + 1) });
  }
  return found;
}

describe('договор об интерфейсе: ошибка сервера доходит до человека', () => {
  it('в onError нет показа своего текста мимо lib/apiError', () => {
    const offenders: string[] = [];
    for (const file of sourceFiles(SRC)) {
      const text = fs.readFileSync(file, 'utf-8');
      if (!text.includes('onError')) continue;
      for (const { index, body } of onErrorBodies(text)) {
        if (!/toast\.error\(|toast\(\{/.test(body)) continue;
        if (/reportApiError|explainedDetail/.test(body)) continue;
        const key = `${rel(file)}:onError`;
        if (allowlist().has(key)) continue;
        offenders.push(`${rel(file)}:${lineAt(text, index)}`);
      }
    }
    expect(
      offenders,
      'Показывайте причину: reportApiError(err, "запасная фраза") из @/lib/apiError.\n'
      + 'Валидация формы до отправки — не этот случай, она живёт вне onError.',
    ).toEqual([]);
  });
});

describe('договор об интерфейсе: пустой список объясняется', () => {
  const SELECT = /<SelectContent[^>]*>([\s\S]*?)<\/SelectContent>/g;
  const MAPPED = /\{\s*([A-Za-z_][\w.?]*)\s*\??\.map\(/g;
  const EXPLAINED = /PrerequisiteNotice|length === 0|CommandEmpty|noOptions/;

  it('селект из useQuery либо объясняет пустоту, либо записан в долг', () => {
    const allowed = allowlist();
    const offenders: string[] = [];
    for (const file of sourceFiles(SRC)) {
      const text = fs.readFileSync(file, 'utf-8');
      if (!text.includes('SelectContent')) continue;
      for (const block of text.matchAll(SELECT)) {
        const body = block[1];
        // Селект-фильтр («Все проекты») пустым не ломается: фильтровать
        // нечего ровно потому, что и данных нет.
        if (/value="all"|value='all'/.test(body)) continue;
        const start = block.index ?? 0;
        // Плашка стоит рядом с полем, а не внутри списка, поэтому смотрим и
        // на окружение — с запасом на длинную разметку самого селекта.
        const around = text.slice(Math.max(0, start - 1400), start + block[0].length + 700);
        if (EXPLAINED.test(around)) continue;
        for (const mapped of body.matchAll(MAPPED)) {
          const name = mapped[1].split('.')[0].replace('?', '');
          // Модульная константа (UPPER_CASE) и перечисления бэкенда пустыми
          // не бывают — это не справочник, а список значений типа.
          if (name === name.toUpperCase() || name === 'enums') continue;
          // Экранирование двойное: это ШАБЛОННАЯ строка, и одинарный  в
          // ней — символ забоя, а не граница слова. С таким «якорем» регулярка
          // не совпадала ни с чем, и проверка молча пропускала всё подряд.
          const fromQuery = new RegExp(
            `data:\\s*${name}\\b|\\b${name}\\s*=\\s*use(Query|Memo)`,
          );
          if (!fromQuery.test(text)) continue;
          const key = `${rel(file)}:${name}`;
          if (allowed.has(key)) continue;
          offenders.push(`${key} (строка ${lineAt(text, start)})`);
        }
      }
    }
    expect(
      offenders,
      'Поставьте рядом <PrerequisiteNotice variant="inline" …> со ссылкой туда,\n'
      + 'где недостающее заводится. Если пустым список не бывает или поле\n'
      + 'необязательное — впишите «путь:переменная» в frontend/ux-contract-allowlist.txt\n'
      + 'вместе с причиной.',
    ).toEqual([]);
  });

  it('нативного поля даты в коде приложения нет', () => {
    // Правило механическое и без эвристик: `<input type="date">` живёт только
    // внутри самого DateInput. Нативное поле выглядит как обычное, но на
    // несуществующей дате («31.02») молча отдаёт пустоту — человек видит
    // незаполненное поле и не понимает, что не так.
    const offenders: string[] = [];
    for (const file of sourceFiles(SRC)) {
      const name = rel(file);
      if (name === 'components/ui/date-input.tsx') continue;
      const text = fs.readFileSync(file, 'utf-8');
      if (!/type="date"/.test(text)) continue;
      if (allowlist().has(`${name}:dates`)) continue;
      offenders.push(`${name}:dates (строка ${lineAt(text, text.indexOf('type="date"'))})`);
    }
    expect(
      offenders,
      'Возьмите <DateInput> из @/components/ui/date-input: он даёт маску\n'
      + 'дд.мм.гггг, календарь и внятный отказ на несуществующей дате.',
    ).toEqual([]);
  });

  it('список на Popover/Command объясняет пустоту источника', () => {
    // Родня проверки Б, но для списков, которые построены не на Select:
    // `CommandEmpty` показывается и когда поиск ничего не нашёл, и когда
    // справочник пуст, — а делать в этих случаях надо разное.
    const allowed = allowlist();
    const offenders: string[] = [];
    for (const file of sourceFiles(SRC)) {
      const text = fs.readFileSync(file, 'utf-8');
      const at = text.indexOf('CommandEmpty>');
      if (at < 0) continue;
      // Плашка засчитывается по РАЗМЕТКЕ, а не по импорту: строка
      // `import { PrerequisiteNotice }` остаётся в файле и после того, как
      // саму плашку убрали, — на ней правило уже обманывалось.
      if (text.includes('<PrerequisiteNotice')) continue;
      // Ветка по длине засчитывается только про ИСТОЧНИК списка. Рядом с
      // `CommandEmpty` почти всегда есть посторонняя проверка длины — в
      // PositionPicker это `value.length === 0` про ВЫБРАННЫЕ должности, и
      // на ней правило проходило, ничего не проверив.
      // Источники берём ТОЛЬКО из самого списка (после CommandEmpty), а не
      // по всему файлу: у мультиселекта рядом есть ещё `{value.map(...)}` —
      // выбранные значения, — и `value.length === 0` про них закрывало
      // правило, хотя про источник не сказано ничего.
      const listBody = text.slice(at, at + 1200);
      const listed = [...listBody.matchAll(/\{\s*([A-Za-z_]\w*)\??\.map\(/g)]
        .map((m) => m[1]);
      // Берём ПЕРВЫЙ перебор после CommandEmpty — это и есть сам список;
      // всё, что дальше (чипы выбранных значений, например), к пустоте
      // источника отношения не имеет.
      const source = listed[0];
      if (source && new RegExp(`\\b${source}\\.length === 0`).test(text)) continue;
      const key = `${rel(file)}:emptySource`;
      if (allowed.has(key)) continue;
      offenders.push(key);
    }
    expect(
      offenders,
      'Разведите «ничего не найдено» и «справочник пуст»: во втором случае\n'
      + 'поставьте <PrerequisiteNotice variant="inline"> под полем со ссылкой\n'
      + 'туда, где справочник заполняется. Если ссылки быть не может —\n'
      + 'впишите «путь:emptySource» в frontend/ux-contract-allowlist.txt.',
    ).toEqual([]);
  });

  it('в списке долга нет строк про уже исправленные места', () => {
    const stale: string[] = [];
    for (const entry of allowlist()) {
      const [file] = entry.split(':');
      if (!fs.existsSync(path.join(SRC, file))) stale.push(entry);
    }
    expect(stale, 'Файла больше нет — удалите строку из ux-contract-allowlist.txt').toEqual([]);
  });
});
