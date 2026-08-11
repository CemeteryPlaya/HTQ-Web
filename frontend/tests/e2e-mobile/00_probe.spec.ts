/**
 * Разведочный прогон: не утверждает ничего, только печатает сводку нарушений
 * по всем экранам. Нужен, чтобы видеть картину целиком перед правками и чтобы
 * заполнять `baseline.ts`.
 *
 * Запуск: npm run test:mobile:probe
 *
 * Каждый экран открывается в СВОЁМ контексте: за один проход набирается больше
 * тридцати тяжёлых SPA-страниц, и переиспользование одной вкладки роняло её по
 * памяти на середине списка.
 */
import { test, fetchTokens, applyTokens } from './fixtures';
import { auditMobilePage, settlePage, formatViolations, distinctOffenders } from './mobileAudit';
import { visitorPages, employeePages } from './pages';

test('сводка нарушений по всем экранам', async ({ browser }) => {
  test.setTimeout(30 * 60_000);
  const tokens = await fetchTokens();
  const summary: string[] = [];

  for (const group of [
    // Гостевые экраны снимаем БЕЗ токена — иначе шапка, нижняя навигация и
    // футер рендерятся в «сотрудничьем» варианте, и замер описывает не ту
    // страницу, которую видит посетитель.
    { title: 'ПОСЕТИТЕЛЬ', cases: visitorPages, authed: false },
    { title: 'СОТРУДНИК', cases: employeePages, authed: true },
  ]) {
    summary.push(`\n═══ ${group.title} ═══`);
    for (const pageCase of group.cases) {
      const context = await browser.newContext();
      const page = await context.newPage();
      try {
        if (group.authed) await applyTokens(page, tokens);
        await page.goto(pageCase.path, { waitUntil: 'commit' });
        await settlePage(page);
        const violations = await auditMobilePage(page, {
          overflowAllow: pageCase.overflowAllow,
          touchAllow: pageCase.touchAllow,
        });
        const counts = new Map<string, number>();
        for (const v of violations) counts.set(v.rule, (counts.get(v.rule) ?? 0) + 1);
        const touchOffenders = distinctOffenders(violations.filter((v) => v.rule === 'touch-target'));
        const brief = [...counts].map(([r, c]) => `${r}=${c}`).join(' ') || 'чисто';
        // BASELINE-строка готова к переносу в baseline.ts.
        summary.push(`${pageCase.name} (${pageCase.path}): ${brief}`);
        summary.push(`  BASELINE '${pageCase.path}': ${touchOffenders.length},`);
        if (violations.length) summary.push(formatViolations(violations));
      } catch (err) {
        summary.push(`${pageCase.name} (${pageCase.path}): ОШИБКА ${(err as Error).message.slice(0, 120)}`);
      } finally {
        await context.close();
      }
    }
  }

  console.log(summary.join('\n'));
});
