/**
 * Мобильные взаимодействия: то, что нельзя проверить замером геометрии.
 *
 * Здесь проверяется, что элементами реально можно пользоваться пальцем —
 * меню открывается и закрывается, нижняя навигация никуда не ведёт мимо,
 * карусели листаются, диалог помещается в экран и закрывается.
 */
import { test, expect } from './fixtures';
import { settlePage } from './mobileAudit';

test.describe('Шапка и мобильное меню', () => {
  test('меню открывается, блокирует прокрутку страницы и закрывается по фону', async ({ page }) => {
    await page.goto('/', { waitUntil: 'commit' });
    await page.waitForLoadState('load');

    const toggle = page.getByRole('button', { name: 'Toggle mobile navigation menu' });
    await expect(toggle).toBeVisible();

    await toggle.tap();
    const drawer = page.locator('nav.container-custom').first();
    await expect(drawer).toBeVisible();

    // Пока меню открыто, страница под ним не должна прокручиваться — иначе
    // список уезжает вместе с фоном и пункт под пальцем меняется.
    await expect
      .poll(() => page.evaluate(() => document.body.style.overflow))
      .toBe('hidden');

    // Тап по затемнению — самый частый способ закрыть меню на телефоне.
    // Бьём координатами у нижнего края: затемнение растянуто на весь экран, но
    // его центр накрыт самой шторкой меню, и клик по центру попал бы в неё.
    const viewport = page.viewportSize()!;
    await page.touchscreen.tap(viewport.width / 2, viewport.height - 40);
    await expect(drawer).toBeHidden();
    await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe('');
  });

  test('кнопка «Назад» появляется только на внутренних страницах', async ({ page }) => {
    const backButton = page.locator('header button[aria-label]').filter({ hasText: /Назад|Back/ });

    await page.goto('/', { waitUntil: 'commit' });
    await page.waitForLoadState('load');
    await expect(backButton).toHaveCount(0);

    await page.goto('/projects', { waitUntil: 'commit' });
    await page.waitForLoadState('load');
    await expect(backButton.first()).toBeVisible();
  });
});

test.describe('Нижняя навигация сотрудника', () => {
  const NAV_TARGETS = ['/myprofile', '/messenger', '/email', '/calendar', '/tasks'];

  test('видна на телефоне и ведёт в свои разделы', async ({ authedPage }) => {
    await authedPage.goto('/myprofile', { waitUntil: 'commit' });
    await settlePage(authedPage);

    const bottomNav = authedPage.locator('div.fixed.bottom-0').first();
    await expect(bottomNav).toBeVisible();

    for (const href of NAV_TARGETS) {
      await expect(bottomNav.locator(`a[href="${href}"]`)).toHaveCount(1);
    }
  });

  test('не перекрывает нижний край содержимого', async ({ authedPage }) => {
    await authedPage.goto('/myprofile', { waitUntil: 'commit' });
    await settlePage(authedPage);
    await authedPage.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await authedPage.waitForTimeout(500);

    // В самой нижней точке страницы под панелью не должно оказаться ничего
    // интерактивного: проверяем, что точка над панелью принадлежит контенту,
    // а не спрятанной под ней кнопке.
    const covered = await authedPage.evaluate(() => {
      const nav = document.querySelector('div.fixed.bottom-0');
      if (!nav) return [];
      const navTop = nav.getBoundingClientRect().top;
      const hidden: string[] = [];
      for (const el of Array.from(document.querySelectorAll('a[href], button'))) {
        if (nav.contains(el)) continue;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        // Центр элемента лежит под панелью и в пределах экрана по вертикали.
        const cy = r.top + r.height / 2;
        if (cy > navTop && cy < window.innerHeight) {
          hidden.push(`${el.tagName}.${(el.getAttribute('class') || '').slice(0, 40)} "${(el.textContent || '').trim().slice(0, 25)}"`);
        }
      }
      return hidden;
    });

    expect(covered, `Под нижней навигацией спрятаны элементы:\n${covered.join('\n')}`).toHaveLength(0);
  });
});

test.describe('Карусели на главной', () => {
  test('блоки листаются вбок, а не обрезаются', async ({ page }) => {
    await page.goto('/', { waitUntil: 'commit' });
    await settlePage(page);

    // Горизонтальные ленты должны действительно скроллиться: если содержимое
    // не шире контейнера, значит карточки схлопнулись и листать нечего.
    const tracks = await page.evaluate(() => {
      const out: Array<{ cls: string; items: number; scrollWidth: number; clientWidth: number }> = [];
      for (const el of Array.from(document.querySelectorAll('.snap-x'))) {
        const s = getComputedStyle(el);
        if (s.overflowX !== 'auto' && s.overflowX !== 'scroll') continue;
        out.push({
          cls: (el.getAttribute('class') || '').slice(0, 50),
          items: el.childElementCount,
          scrollWidth: el.scrollWidth,
          clientWidth: el.clientWidth,
        });
      }
      return out;
    });

    expect(tracks.length, 'На главной не нашлось ни одной мобильной карусели').toBeGreaterThan(0);
    // Ленты с данными из API (новости) на пустой базе содержат ноль карточек —
    // листать там нечего, и это не дефект вёрстки. Требуем прокрутку только от
    // лент, где карточек больше одной.
    const filled = tracks.filter((t) => t.items > 1);
    expect(filled.length, 'Ни одна карусель не наполнена карточками').toBeGreaterThan(0);
    for (const track of filled) {
      expect(
        track.scrollWidth,
        `Лента «${track.cls}» (${track.items} карточек) не листается: ` +
          `scrollWidth ${track.scrollWidth} ≤ clientWidth ${track.clientWidth}`,
      ).toBeGreaterThan(track.clientWidth);
    }
  });

  test('индикаторы направлений переключают слайд', async ({ page }) => {
    await page.goto('/', { waitUntil: 'commit' });
    await settlePage(page);

    // Секцию находим по самим индикаторам: класс `ring-secondary` встречается и
    // в других блоках главной, поэтому искать его по всей странице нельзя.
    const section = page.locator('section:has(button[aria-label^="Go to slide"])');
    const dots = section.locator('button[aria-label^="Go to slide"]');
    await expect(dots.first()).toBeVisible();
    expect(await dots.count()).toBeGreaterThan(1);

    // Активный слайд помечен кольцом. Он всегда ровно один — и до тапа, и
    // после: проверяем, что метка переехала именно на выбранную карточку.
    await expect(section.locator('.ring-secondary')).toHaveCount(1);
    await dots.nth(1).tap();
    await expect(section.locator('.ring-secondary')).toHaveCount(1);
    const activeIndex = await section.evaluate((el) => {
      const cards = [...el.querySelectorAll('.snap-center')];
      return cards.findIndex((c) => c.className.includes('ring-secondary'));
    });
    expect(activeIndex, 'Тап по индикатору не переключил активный слайд').toBe(1);
  });
});

test.describe('Диалоги', () => {
  test('карточка проекта помещается в экран и закрывается', async ({ page }) => {
    await page.goto('/projects', { waitUntil: 'commit' });
    await settlePage(page);

    const card = page.locator('[class*="cursor-pointer"]').first();
    if ((await card.count()) === 0) test.skip(true, 'На странице проектов нет карточек');
    await card.tap();

    const close = page.getByRole('button', { name: 'Close modal' });
    await expect(close).toBeVisible();

    const fits = await page.evaluate(() => {
      const vw = document.documentElement.clientWidth;
      const modal = document.querySelector('[class*="max-w-4xl"]');
      if (!modal) return null;
      const r = modal.getBoundingClientRect();
      return { left: Math.round(r.left), right: Math.round(r.right), vw };
    });
    expect(fits, 'Модальное окно не найдено').not.toBeNull();
    expect(fits!.left).toBeGreaterThanOrEqual(0);
    expect(fits!.right).toBeLessThanOrEqual(fits!.vw);

    await close.tap();
    await expect(close).toBeHidden();
  });
});
