/**
 * Мобильный UI/UX рабочих разделов — то, что открывает сотрудник с телефона.
 *
 * Проверки те же, что и для публичной части (`01_visitor.spec.ts`), но под
 * авторизацией: токен кладётся в localStorage до загрузки приложения.
 * Здесь же ловятся ошибки рендера — рабочий экран, упавший в белый экран,
 * «удобным» не считается независимо от геометрии.
 */
import { test, expect } from './fixtures';
import { auditMobilePage, settlePage, formatViolations, distinctOffenders } from './mobileAudit';
import { employeePages } from './pages';
import { baselineFor } from './baseline';

for (const pageCase of employeePages) {
  test(`${pageCase.name} (${pageCase.path}) — мобильная вёрстка`, async ({ authedPage }) => {
    const pageErrors: string[] = [];
    authedPage.on('pageerror', (err) => pageErrors.push(err.message));

    await authedPage.goto(pageCase.path, { waitUntil: 'commit' });
    await settlePage(authedPage);

    // Экран должен что-то показать: пустой <main> означает, что до вёрстки
    // дело не дошло и остальные проверки ничего не значат.
    const rendered = await authedPage.evaluate(
      () => (document.querySelector('main, [role="main"]') ?? document.body).textContent?.trim().length ?? 0,
    );
    expect(rendered, 'Страница не отрисовала содержимое').toBeGreaterThan(0);
    expect(pageErrors, `Ошибки выполнения на странице:\n${pageErrors.join('\n')}`).toHaveLength(0);

    const violations = await auditMobilePage(authedPage, {
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

    const offenders = distinctOffenders(touch);
    const allowed = baselineFor(pageCase.path);
    expect(
      offenders.length,
      `Компонентов с тач-целями меньше 44px: ${offenders.length}, допустимо по базе ${allowed}.\n` +
        `Стало меньше — опустите значение в baseline.ts.\n${formatViolations(touch)}`,
    ).toBeLessThanOrEqual(allowed);
  });
}
