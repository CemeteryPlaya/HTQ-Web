/**
 * Мобильный UI/UX публичной части — то, что видит посетитель сайта.
 *
 * Здесь намеренно НЕТ авторизации: с токеном шапка, футер и нижняя навигация
 * рендерятся в «сотрудничьем» варианте, и замер описывал бы не ту страницу.
 *
 * Правила «переполнение» и «автозум» проверяются строго — они ловят поломки,
 * из-за которых страницей физически нельзя пользоваться (обрезанный заголовок,
 * уехавшая за экран кнопка, зум вёрстки при тапе в поле). Размеры тач-целей
 * идут через храповик из `baseline.ts` — пояснение там.
 */
import { test, expect } from './fixtures';
import { auditMobilePage, settlePage, formatViolations, distinctOffenders } from './mobileAudit';
import { visitorPages } from './pages';
import { baselineFor } from './baseline';

for (const pageCase of visitorPages) {
  test(`${pageCase.name} (${pageCase.path}) — мобильная вёрстка`, async ({ page }) => {
    await page.goto(pageCase.path, { waitUntil: 'commit' });
    await settlePage(page);

    const violations = await auditMobilePage(page, {
      overflowAllow: pageCase.overflowAllow,
      touchAllow: pageCase.touchAllow,
    });

    const overflow = violations.filter((v) => v.rule === 'horizontal-overflow');
    const zoom = violations.filter((v) => v.rule === 'input-zoom');
    const touch = violations.filter((v) => v.rule === 'touch-target');

    expect(
      overflow,
      `Контент уезжает за правый край экрана:\n${formatViolations(overflow)}`,
    ).toHaveLength(0);

    expect(
      zoom,
      `Поля ввода мельче 16px — iOS зумит вёрстку при фокусе:\n${formatViolations(zoom)}`,
    ).toHaveLength(0);

    // Считаем не срабатывания, а уникальные компоненты-виновники: иначе порог
    // зависел бы от числа строк в списке, а не от качества вёрстки.
    const offenders = distinctOffenders(touch);
    const allowed = baselineFor(pageCase.path);
    expect(
      offenders.length,
      `Компонентов с тач-целями меньше 44px: ${offenders.length}, допустимо по базе ${allowed}.\n` +
        `Стало меньше — опустите значение в baseline.ts.\n${formatViolations(touch)}`,
    ).toBeLessThanOrEqual(allowed);
  });
}
