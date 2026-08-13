/**
 * Движок мобильного UI/UX-аудита.
 *
 * Весь разбор идёт одним `page.evaluate` — так проверка видит настоящую
 * геометрию после лэйаута, а не то, что мы предполагаем по классам. Каждая
 * проверка возвращает список нарушений с описанием элемента, чтобы падение
 * теста сразу показывало, что именно чинить.
 *
 * Почему не «скриншотные» тесты: эталонные картинки на этом проекте пришлось
 * бы перегенерировать при каждой правке вёрстки, и они не отвечают на вопрос
 * «удобно ли пальцем». Проверяем измеримые свойства, а не пиксели.
 */
import type { Page } from '@playwright/test';

/** Минимальная сторона тач-цели. 44px — рекомендация Apple HIG. */
export const MIN_TOUCH_TARGET = 44;

/**
 * Минимальный кегль поля ввода. Safari на iOS зумит вёрстку при фокусе в поле
 * с кеглем меньше 16px и обратно её не отматывает.
 */
export const MIN_INPUT_FONT_SIZE = 16;

export interface Violation {
  /** Тип проверки, по которому нарушение сгруппировано в отчёте. */
  rule: string;
  /** `tag.class` — чтобы найти место в исходниках. */
  element: string;
  /** Человекочитаемая суть: что именно не так и с какими числами. */
  detail: string;
  /** Первые слова текста элемента — быстрый ориентир на странице. */
  text?: string;
}

export interface AuditOptions {
  /**
   * Селекторы, чьё поддерево исключено из проверки переполнения. Нужен для
   * намеренно «широких» вещей вроде бегущей строки логотипов: она едет внутри
   * `overflow-hidden` и обязана быть шире экрана.
   */
  overflowAllow?: string[];
  /** Селекторы, исключённые из проверки размера тач-целей. */
  touchAllow?: string[];
}

/**
 * Гоняет весь набор проверок на текущем состоянии страницы.
 *
 * Важно: страницу нужно предварительно прокрутить донизу (`settlePage`) —
 * до этого секции под `LazySection` ещё не смонтированы и аудит их не увидит.
 */
export async function auditMobilePage(
  page: Page,
  options: AuditOptions = {},
): Promise<Violation[]> {
  return auditGeometry(page, options);
}

/**
 * Уникальные «виновники» вместо числа срабатываний.
 *
 * На страницах со списками одно и то же место вёрстки даёт по нарушению на
 * каждую строку, и порог начинает зависеть от объёма данных в базе, а не от
 * качества вёрстки. Схлопываем по описанию элемента: интересен компонент,
 * который надо починить, а не сколько раз он отрисовался.
 */
export function distinctOffenders(violations: Violation[]): string[] {
  return [...new Set(violations.map((v) => v.element))].sort();
}

/*
 * Проверки «перекрыт ли элемент» здесь намеренно нет.
 *
 * Две попытки её формализовать дали разные наборы ложных срабатываний: сам
 * факт «элемент сейчас под панелью» дефектом не является — пользователь его
 * прокрутит, — а отличить это от настоящего «прокруткой уже не достать»
 * одним замером геометрии не выходит: мешают липкая шапка с её анимацией
 * высоты и то, что у верхнего и нижнего края правило зеркальное.
 *
 * Вместо ненадёжной эвристики на 35 экранов оставлен один точный тест в
 * `03_interactions.spec.ts`: страница прокручивается до упора вниз, и там
 * проверяется, что нижняя навигация ничего под собой не прячет. У него
 * однозначное определение и воспроизводимый замер.
 */

async function auditGeometry(page: Page, options: AuditOptions): Promise<Violation[]> {
  return page.evaluate(
    ({ overflowAllow, touchAllow, MIN_TOUCH_TARGET, MIN_INPUT_FONT_SIZE }) => {
      const vw = document.documentElement.clientWidth;
      const violations: Array<{
        rule: string;
        element: string;
        detail: string;
        text?: string;
      }> = [];

      const describe = (el: Element) => {
        const cls = (el.getAttribute('class') || '').trim().split(/\s+/).slice(0, 4).join('.');
        return cls ? `${el.tagName.toLowerCase()}.${cls}` : el.tagName.toLowerCase();
      };
      const label = (el: Element) => (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40);

      const matchesAny = (el: Element, selectors: string[]) =>
        selectors.some((sel) => {
          try {
            return el.matches(sel) || el.closest(sel) !== null;
          } catch {
            return false;
          }
        });

      const isVisible = (el: Element) => {
        const s = getComputedStyle(el);
        if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      };

      /** Внутри горизонтального скроллера выезд за экран — штатное поведение. */
      const insideHorizontalScroller = (el: Element) => {
        for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
          const ox = getComputedStyle(p).overflowX;
          if (ox === 'auto' || ox === 'scroll') return true;
        }
        return false;
      };

      // ── 1. Горизонтальное переполнение ───────────────────────────────────
      // `body { overflow-x: hidden }` прячет симптом, поэтому scrollWidth
      // документа доверять нельзя — смотрим геометрию каждого элемента.
      const contentSelector = 'h1, h2, h3, h4, p, img, a, button, input, textarea, select, table, li, label';
      for (const el of Array.from(document.querySelectorAll(contentSelector))) {
        if (!isVisible(el)) continue;
        if (insideHorizontalScroller(el)) continue;
        if (matchesAny(el, overflowAllow)) continue;
        const r = el.getBoundingClientRect();
        if (r.right > vw + 1) {
          violations.push({
            rule: 'horizontal-overflow',
            element: describe(el),
            detail: `правый край ${Math.round(r.right)}px при ширине экрана ${vw}px (вылет ${Math.round(r.right - vw)}px)`,
            text: label(el),
          });
        }
      }

      /**
       * Эффективная зона нажатия. У мелких по виду контролов (переключатель)
       * она расширена невидимым `::after` — тогда элемент помечен
       * `data-touch-expanded`, и мы досчитываем вылет псевдоэлемента по его
       * вычисленным отступам. Маркеру не доверяем: если расширение не дотянуло
       * до 44px, нарушение всё равно засчитается.
       */
      const effectiveHitBox = (el: Element) => {
        const r = el.getBoundingClientRect();
        let { width, height } = r;
        if (el.hasAttribute('data-touch-expanded')) {
          const after = getComputedStyle(el, '::after');
          if (after.content && after.content !== 'none') {
            const grow = (v: string) => {
              const n = parseFloat(v);
              return Number.isFinite(n) && n < 0 ? -n : 0;
            };
            height += grow(after.top) + grow(after.bottom);
            width += grow(after.left) + grow(after.right);
          }
        }
        return { width, height };
      };

      // ── 2. Размер тач-целей ──────────────────────────────────────────────
      const interactiveSelector =
        'a[href], button, [role="button"], [role="tab"], input:not([type="hidden"]), select, textarea, summary';
      for (const el of Array.from(document.querySelectorAll(interactiveSelector))) {
        if (!isVisible(el)) continue;
        if (matchesAny(el, touchAllow)) continue;
        // Ссылка внутри абзаца — часть текста, её размер задаёт строка.
        const inProse = el.tagName === 'A' && el.closest('p, li, span[class*="prose"]') !== null;
        if (inProse) continue;
        // Скрытые чекбоксы/радио, на которые кликают через <label>.
        if (el instanceof HTMLInputElement && (el.type === 'checkbox' || el.type === 'radio')) continue;
        const box = effectiveHitBox(el);
        const side = Math.min(box.width, box.height);
        if (side < MIN_TOUCH_TARGET) {
          violations.push({
            rule: 'touch-target',
            element: describe(el),
            detail: `${Math.round(box.width)}×${Math.round(box.height)}px, минимальная сторона ${Math.round(side)}px < ${MIN_TOUCH_TARGET}px`,
            text: label(el),
          });
        }
      }

      // ── 3. Автозум iOS на полях ввода ────────────────────────────────────
      const zoomProne = 'input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]):not([type="range"]), textarea, select';
      for (const el of Array.from(document.querySelectorAll(zoomProne))) {
        if (!isVisible(el)) continue;
        const size = parseFloat(getComputedStyle(el).fontSize);
        if (size < MIN_INPUT_FONT_SIZE) {
          violations.push({
            rule: 'input-zoom',
            element: describe(el),
            detail: `font-size ${size}px < ${MIN_INPUT_FONT_SIZE}px — Safari на iOS зумит страницу при фокусе`,
            text: (el as HTMLInputElement).placeholder || label(el),
          });
        }
      }

      return violations;
    },
    {
      overflowAllow: options.overflowAllow ?? [],
      touchAllow: options.touchAllow ?? [],
      MIN_TOUCH_TARGET,
      MIN_INPUT_FONT_SIZE,
    },
  );
}

/**
 * Доводит страницу до состояния, пригодного для замера: ждёт сеть, прокручивает
 * донизу (главная монтирует секции через `LazySection`/IntersectionObserver, до
 * прокрутки половины страницы просто нет), затем возвращается наверх.
 */
export async function settlePage(page: Page): Promise<void> {
  await page.waitForLoadState('load');
  await page.waitForTimeout(1200);

  // Шаг 1. Прокрутка донизу — она и запускает IntersectionObserver в LazySection.
  for (let step = 0; step < 60; step++) {
    const atEnd = await page.evaluate(() => {
      window.scrollBy(0, 500);
      return window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 5;
    });
    await page.waitForTimeout(220);
    if (atEnd) break;
  }

  // Шаг 2. Ждём, пока DOM перестанет расти. Без этого замер зависит от того,
  // успела ли доехать последняя секция: один и тот же экран давал то 0, то 16
  // нарушений просто потому, что ContactSection ещё не смонтировался.
  let previous = -1;
  let stable = 0;
  for (let attempt = 0; attempt < 40 && stable < 3; attempt++) {
    const fingerprint = await page.evaluate(() => {
      // Дотягиваемся до низа ещё раз: смонтированная секция сдвигает границу.
      window.scrollTo(0, document.documentElement.scrollHeight);
      return document.querySelectorAll('*').length + document.documentElement.scrollHeight;
    });
    stable = fingerprint === previous ? stable + 1 : 0;
    previous = fingerprint;
    await page.waitForTimeout(300);
  }

  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(400);
}

/** Группирует нарушения в читаемый текст для сообщения об ошибке. */
export function formatViolations(violations: Violation[]): string {
  const byRule = new Map<string, Violation[]>();
  for (const v of violations) {
    const list = byRule.get(v.rule) ?? [];
    list.push(v);
    byRule.set(v.rule, list);
  }
  const lines: string[] = [];
  for (const [rule, list] of byRule) {
    lines.push(`  [${rule}] нарушений: ${list.length}`);
    for (const v of list.slice(0, 8)) {
      lines.push(`    - ${v.element} — ${v.detail}${v.text ? ` («${v.text}»)` : ''}`);
    }
    if (list.length > 8) lines.push(`    … ещё ${list.length - 8}`);
  }
  return lines.join('\n');
}
