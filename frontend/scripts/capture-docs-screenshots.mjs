/**
 * Съёмка скриншотов для docs/dev/images/.
 *
 * Запуск (стек уже должен быть поднят):
 *   cd frontend
 *   node scripts/capture-docs-screenshots.mjs
 *
 * Chromium в окружении не установлен — работаем на канале msedge, который
 * есть на Windows-хосте (см. docs/dev/testing.md, раздел 4).
 *
 * Скрипт намеренно НЕ падает на первой неудаче: снимает всё, что доступно, и
 * в конце печатает список пропущенного с причиной. Половина снимков лучше,
 * чем ноль, а знать, чего не хватает, важнее, чем получить нулевой код
 * возврата.
 */
import { chromium } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const OUT = join(ROOT, 'docs', 'dev', 'images');

const FRONTEND = process.env.DOCS_FRONTEND_URL ?? 'http://127.0.0.1:3000';
const BACKEND = process.env.DOCS_BACKEND_URL ?? 'http://127.0.0.1:8000';
const ADMIN_USER = process.env.DOCS_ADMIN_USER ?? 'admin';
const ADMIN_PASSWORD = process.env.DOCS_ADMIN_PASSWORD ?? 'admin12345';

const VIEWPORT = { width: 1440, height: 900 };

const skipped = [];
const captured = [];

async function shoot(page, name, { fullPage = false } = {}) {
  const path = join(OUT, `${name}.png`);
  await page.screenshot({ path, fullPage });
  captured.push(name);
  console.log(`  ✓ ${name}.png`);
}

async function step(name, fn) {
  try {
    await fn();
  } catch (err) {
    skipped.push(`${name}: ${err.message.split('\n')[0]}`);
    console.log(`  ✗ ${name} — ${err.message.split('\n')[0]}`);
  }
}

const main = async () => {
  await mkdir(OUT, { recursive: true });

  const browser = await chromium.launch({ channel: 'msedge' });
  const context = await browser.newContext({ viewport: VIEWPORT, locale: 'ru-RU' });
  const page = await context.newPage();

  console.log('Публичная часть:');

  await step('landing', async () => {
    // ?lng=ru — i18next-browser-languagedetector по умолчанию смотрит
    // querystring первым. Без этого страница снимается по-английски:
    // язык подхватывается из navigator браузера, а не из fallbackLng.
    await page.goto(FRONTEND + '/?lng=ru', { waitUntil: 'networkidle', timeout: 45000 });
    await page.waitForTimeout(1500);
    await shoot(page, 'frontend-landing');
  });

  await step('login', async () => {
    await page.goto(FRONTEND + '/login?lng=ru', { waitUntil: 'networkidle', timeout: 45000 });
    await page.waitForTimeout(800);
    await shoot(page, 'frontend-login');
  });

  console.log('django-admin:');

  await step('admin-login', async () => {
    await page.goto(BACKEND + '/django-admin/login/', { waitUntil: 'domcontentloaded', timeout: 45000 });
    await page.waitForTimeout(500);
    await shoot(page, 'django-admin-login');
  });

  await step('admin-dashboard', async () => {
    await page.goto(BACKEND + '/django-admin/login/', { waitUntil: 'domcontentloaded', timeout: 45000 });
    // Заполняем и отправляем форму прямо из DOM. Обычные fill/click/press
    // здесь виснут до таймаута: у элементов этой темы админки не проходит
    // проверка «actionable» (Playwright ждёт, пока элемент перестанет
    // двигаться, и не дожидается). Прямой submit обходит эту проверку.
    await page.evaluate(({ user, password }) => {
      document.getElementById('id_username').value = user;
      document.getElementById('id_password').value = password;
      document.getElementById('login-form').submit();
    }, { user: ADMIN_USER, password: ADMIN_PASSWORD });

    await page.waitForSelector('#content, .dashboard, #site-name', { timeout: 30000 });
    await page.waitForTimeout(1000);
    await shoot(page, 'django-admin-dashboard', { fullPage: true });
  });

  await browser.close();

  console.log(`\nСнято: ${captured.length}`);
  if (skipped.length) {
    console.log(`Пропущено: ${skipped.length}`);
    for (const s of skipped) console.log(`  - ${s}`);
  }
};

main().catch((err) => {
  console.error('Скрипт упал целиком:', err);
  process.exit(1);
});
