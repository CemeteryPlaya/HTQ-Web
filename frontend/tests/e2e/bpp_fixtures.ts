/* eslint-disable @typescript-eslint/no-explicit-any -- ответы API здесь не типизированы */
/**
 * Общие помощники сценариев приёмки модуля БЗО SC-001…SC-006
 * (этап 6 A, задача 7; D-S6-6, ТЗ §28.2).
 *
 * Сценарии идут против тестового стека `docker-compose.test-local.yml` и
 * пилотной компании, подготовленной `scripts/bpp-e2e-seed.sh`:
 *
 *   ./scripts/bpp-e2e-seed.sh
 *   cd frontend && npx playwright test tests/e2e/3*_bpp_* --project=msedge
 *
 * Компания определяется поддоменом: `group.localhost:3000` — Vite-прокси
 * кладёт `X-HTQ-Company` (dev-эквивалент nginx). Edge/Chromium сами считают
 * `*.localhost` петлёй, настраивать hosts не нужно.
 *
 * Что здесь есть:
 *  - `openAs(browser, role)` — новый контекст браузера, вход ЧЕРЕЗ ЭКРАН входа под
 *    пользователем нужной роли (у каждой роли свой origin-localStorage → контексты
 *    независимы, и в одном сценарии можно работать за нескольких людей);
 *  - `Api` — запросы к бэкенду напрямую (:8000, заголовок компании ставим сами):
 *    подготовка данных и решения согласующих «Ждёт меня», которые сценарию нужны
 *    как условие, а не как проверяемое действие;
 *  - файлы-образцы: PDF и выписка 1С (1CClientBankExchange);
 *  - UI-мелочи (Radix Select, диалог подтверждения).
 *
 * Сценарии не зависят друг от друга: каждый заводит СВОЙ проект с уникальным
 * кодом (`uniq`) и свой утверждённый бюджет, поэтому повторный запуск ничего не
 * ломает и порядок запуска не важен.
 */
import {
  expect,
  request as pwRequest,
  type APIRequestContext,
  type Browser,
  type BrowserContext,
  type Locator,
  type Page,
} from "@playwright/test";

import { writeFile } from "node:fs/promises";
import { test } from "@playwright/test";

export { expect, test } from "@playwright/test";

// ── окружение ────────────────────────────────────────────────────────

export const COMPANY = process.env.E2E_BPP_COMPANY || "hi-tech-group";
/** Метка хоста пилота — псевдоним компании (`Company.subdomain`), его ставит сид. */
export const HOST_LABEL = process.env.E2E_BPP_HOST_LABEL || "group";
/** Адрес SPA пилотной компании. */
export const BPP_BASE =
  process.env.E2E_BPP_BASE || `http://${HOST_LABEL}.localhost:3000`;
/** Бэкенд напрямую: минуем Vite, компанию задаём заголовком. */
export const BPP_API =
  process.env.E2E_BPP_API || "http://localhost:8000";
export const PASSWORD = process.env.E2E_BPP_PASSWORD || "demo12345";

/** IBAN счёта организации, заведённого `scripts/bpp-e2e-seed.sh`. */
export const ORG_IBAN = "KZ869980000000000001";

/** Порог «счёт без договора» (ТЗ BR-040): 1000 МРП при МРП 4 325 ₸. */
export const INVOICE_THRESHOLD = 4_325_000;

export type Role = "fd" | "td" | "od" | "gd" | "sn" | "pm" | "buh";

/** Держатели ролей оргструктуры холдинга (seed_hr_demo; почта — `email_for`). */
export const USERS: Record<Role, { email: string; title: string }> = {
  fd: { email: "tulegenov.a@htq.kz", title: "Финансовый директор" },
  td: { email: "nurseitov.d@htq.kz", title: "Технический директор" },
  od: { email: "kim.v@htq.kz", title: "Операционный директор" },
  gd: { email: "abdrahmanov.e@htq.kz", title: "Генеральный директор" },
  sn: { email: "dyusenov.m@htq.kz", title: "Менеджер по закупкам" },
  pm: { email: "ermekov.t@htq.kz", title: "Руководитель проекта" },
  buh: { email: "doszhanova.a@htq.kz", title: "Бухгалтер" },
};

/** Уникальный хвост для кодов и номеров — повторный прогон не сталкивается с прошлым. */
export function uniq(): string {
  return `${Date.now().toString(36)}${Math.floor(Math.random() * 1296).toString(36)}`.toUpperCase();
}

// ── файлы-образцы ────────────────────────────────────────────────────

/** Минимальный PDF: подсистема файлов проверяет сигнатуру, а не только расширение. */
export const PDF_BYTES = Buffer.from(
  "%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n" +
    "2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n" +
    "trailer\n<< /Root 1 0 R >>\n%%EOF\n",
);

export function pdfFile(name = "e2e-document.pdf") {
  return { name, mimeType: "application/pdf", buffer: PDF_BYTES };
}

export interface StatementDoc {
  number: string;
  /** ДД.ММ.ГГГГ */
  date: string;
  amount: string;
  recipientBin: string;
  recipient: string;
  purpose: string;
}

export function ddmmyyyy(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()}`;
}

/**
 * Выписка 1С (1CClientBankExchange) — по образцу фикстур тестов выписки
 * (`backend/apps/bpp/tests/bank/common.py::onec_bytes`). Кодировка — UTF-8 с BOM:
 * парсер (`parsers/onec.py::_decode`) по BOM переключается на UTF-8, а кодировщика
 * cp1251 в Node нет.
 */
export function onecStatement(
  iban: string,
  docs: StatementDoc[],
  period: [string, string],
) {
  const lines = [
    "1CClientBankExchange",
    "ВерсияФормата=1.03",
    "Кодировка=Windows",
    "Отправитель=Бухгалтерия",
    `ДатаНачала=${period[0]}`,
    `ДатаКонца=${period[1]}`,
    "СекцияРасчСчет",
    `РасчСчет=${iban}`,
    "КонецРасчСчет",
  ];
  for (const d of docs) {
    lines.push(
      "СекцияДокумент=Платежное поручение",
      `Номер=${d.number}`,
      `Дата=${d.date}`,
      `Сумма=${d.amount}`,
      `ПлательщикИИК=${iban}`,
      `ПолучательБИН=${d.recipientBin}`,
      `Получатель1=${d.recipient}`,
      "ПолучательИИК=",
      `НазначениеПлатежа=${d.purpose}`,
      "КонецДокумента",
    );
  }
  lines.push("КонецФайла");
  return {
    name: "kl_to_1c.txt",
    mimeType: "text/plain",
    buffer: Buffer.concat([
      Buffer.from([0xef, 0xbb, 0xbf]),
      Buffer.from(lines.join("\r\n") + "\r\n", "utf-8"),
    ]),
  };
}

// ── вход через UI ────────────────────────────────────────────────────

export interface Session {
  context: BrowserContext;
  page: Page;
  role: Role;
}

const opened: Session[] = [];

/**
 * Сценарий приёмки: тест на 4 минуты, при падении — скриншот каждой открытой
 * страницы (`test-results/…/screenshot-<роль>.png`) и её адрес в консоль,
 * в конце — закрытие контекстов. Playwright закрывает контексты, созданные
 * через `browser.newContext`, ДО afterEach, поэтому разбор — здесь, в теле.
 */
export function scenario(title: string, body: (browser: Browser) => Promise<void>) {
  test(title, async ({ browser }, testInfo) => {
    test.setTimeout(240_000);
    try {
      await body(browser);
    } catch (error) {
      for (const s of opened) {
        try {
          const file = testInfo.outputPath(`screenshot-${s.role}.png`);
          await s.page.screenshot({ path: file, fullPage: true });
          await testInfo.attach(`screenshot-${s.role}`, { path: file, contentType: "image/png" });
          const text = await s.page.locator("main, body").first().innerText();
          await writeFile(testInfo.outputPath(`text-${s.role}.txt`), text);
          console.log(`[${s.role}] страница при падении: ${s.page.url()} → ${file}`);
        } catch (e) {
          console.log("скриншот не снят:", String(e));
        }
      }
      throw error;
    } finally {
      for (const s of opened.splice(0)) await s.context.close().catch(() => undefined);
    }
  });
}

/** Отдельный контекст браузера, вход через форму под ролью. */
export async function openAs(browser: Browser, role: Role): Promise<Session> {
  const context = await browser.newContext({
    baseURL: BPP_BASE,
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 900 },
  });
  await context.addInitScript(() => {
    // Язык прибиваем явно: LanguageDetector иначе берёт локаль машины.
    window.localStorage.setItem("i18nextLng", "ru");
  });
  // Действия без своего таймаута иначе висят до таймаута всего теста (3 минуты).
  context.setDefaultTimeout(20_000);
  const page = await context.newPage();
  opened.push({ context, page, role });
  await page.goto("/login");
  const password = page.locator('input[type="password"]').first();
  await expect(password).toBeVisible({ timeout: 30_000 });
  await page.locator('input[type="text"]').first().fill(USERS[role].email);
  await password.fill(PASSWORD);
  await page.locator('button[type="submit"]').first().click();
  await page.waitForURL((url) => !url.pathname.includes("/login"), {
    timeout: 30_000,
  });
  return { context, page, role };
}

// ── API ──────────────────────────────────────────────────────────────

/** Клиент бэкенда под ролью: подготовка данных и решения согласующих. */
export class Api {
  private constructor(
    private readonly ctx: APIRequestContext,
    readonly role: Role,
    /** user_id из токена — «руководитель проекта», автор и т.п. */
    readonly userId: number,
  ) {}

  static async as(role: Role): Promise<Api> {
    const anon = await pwRequest.newContext({
      baseURL: BPP_API,
      extraHTTPHeaders: { "X-HTQ-Company": HOST_LABEL },
    });
    const resp = await anon.post("/api/users/v1/token/", {
      data: { email: USERS[role].email, password: PASSWORD },
    });
    if (!resp.ok()) {
      throw new Error(`вход ${role} не удался: ${resp.status()} ${await resp.text()}`);
    }
    const { access } = await resp.json();
    await anon.dispose();
    const ctx = await pwRequest.newContext({
      baseURL: BPP_API,
      extraHTTPHeaders: {
        "X-HTQ-Company": HOST_LABEL,
        Authorization: `Bearer ${access}`,
      },
    });
    const payload = JSON.parse(
      Buffer.from(String(access).split(".")[1], "base64url").toString("utf-8"),
    );
    return new Api(ctx, role, Number(payload.user_id));
  }

  async get<T = any>(path: string): Promise<T> {
    const resp = await this.ctx.get(path);
    expect(resp.ok(), `GET ${path}: ${resp.status()} ${await resp.text()}`).toBeTruthy();
    return resp.json();
  }

  async post<T = any>(path: string, data?: unknown, expectOk = true): Promise<T> {
    const resp = await this.ctx.post(path, {
      data: data ?? {},
      headers: { "Idempotency-Key": `e2e-${uniq()}-${Math.random()}` },
    });
    if (expectOk) {
      expect(resp.ok(), `POST ${path}: ${resp.status()} ${await resp.text()}`).toBeTruthy();
    }
    return (await resp.json().catch(() => ({}))) as T;
  }

  async patch<T = any>(path: string, data: unknown): Promise<T> {
    const resp = await this.ctx.patch(path, {
      data,
      headers: { "Idempotency-Key": `e2e-${uniq()}-${Math.random()}` },
    });
    expect(resp.ok(), `PATCH ${path}: ${resp.status()} ${await resp.text()}`).toBeTruthy();
    return resp.json();
  }

  /** POST без проверки статуса — для проверок отказов (код ошибки конверта БЗО). */
  async postRaw(path: string, data?: unknown): Promise<{ status: number; body: any }> {
    const resp = await this.ctx.post(path, {
      data: data ?? {},
      headers: { "Idempotency-Key": `e2e-${uniq()}-${Math.random()}` },
    });
    return { status: resp.status(), body: await resp.json().catch(() => ({})) };
  }

  async upload(path: string, file: { name: string; mimeType: string; buffer: Buffer }, form: Record<string, string> = {}) {
    const resp = await this.ctx.post(path, { multipart: { ...form, file } });
    expect(resp.ok(), `UPLOAD ${path}: ${resp.status()} ${await resp.text()}`).toBeTruthy();
    return resp.json();
  }

  /**
   * Согласовать документ за роль: берём задачи «Ждёт меня» по предмету и
   * принимаем решение (то же, что кнопка «Согласовать» в очереди).
   * Возвращает число принятых решений.
   */
  async approveSubject(subjectId: string, comment = "Согласовано в сценарии приёмки"): Promise<number> {
    const inbox: any[] = await this.get("/api/signoff/v1/tasks/mine");
    const mine = inbox.filter((i) => String(i.subject_id) === String(subjectId));
    for (const task of mine) {
      await this.post(`/api/signoff/v1/tasks/${task.task_id}/decision`, {
        decision: "approve",
        comment,
      });
    }
    return mine.length;
  }

  async dispose() {
    await this.ctx.dispose();
  }
}

// ── подготовка данных (условия сценариев, не проверяемые действия) ──

export interface Project {
  id: string;
  code: string;
  name: string;
}

/** Проект с уникальным кодом; руководитель — ПМ (по ТЗ ПМ видит только свои проекты). */
export async function createProject(fd: Api, pm: Api, tag: string): Promise<Project> {
  const code = `E2E-${tag}`;
  const row = await fd.post("/api/project/v1/projects", {
    code,
    name: `E2E проект ${tag}`,
    country_code: "KZ",
    manager_user_id: pm.userId,
  });
  return { id: row.id, code, name: row.name };
}

/** id статьи справочника по коду (статьи E2E-* заводит bpp-e2e-seed.sh). */
export async function articleId(api: Api, code: "E2E-MET" | "E2E-ELE" | "E2E-DES"): Promise<string> {
  const rows: any[] = await api.get("/api/refdata/v1/articles?active=true");
  const row = rows.find((r) => r.code === code);
  expect(row, `статья ${code} не найдена — запущен ли scripts/bpp-e2e-seed.sh?`).toBeTruthy();
  return row.id;
}

/** Утверждённый бюджет проекта (версия 1) — условие SC-002…SC-005. */
export async function createApprovedBudget(
  fd: Api,
  projectId: string,
  lines: { article_id: string; limit_amount: string }[],
) {
  const draft = await fd.post("/api/bpp/v1/budgets", {
    project_id: projectId,
    currency: "KZT",
    lines,
  });
  const card = await fd.post(`/api/bpp/v1/budgets/${draft.id}/approve`, { version: draft.version });
  return card;
}


/** БИН/ИИН: 11 цифр + контрольный разряд (алгоритм РК, `seed_bpp_demo.bin_with_checksum`). */
export function binWithChecksum(body11: string): string {
  const digits = [...body11].map(Number);
  for (const weights of [
    [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
    [3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2],
  ]) {
    const rest = digits.reduce((acc, d, i) => acc + d * weights[i], 0) % 11;
    if (rest !== 10) return body11 + String(rest);
  }
  throw new Error(`для ${body11} контрольный разряд не вычисляется`);
}

/** Уникальный действительный БИН под тест. */
export function uniqueBin(): string {
  for (;;) {
    const body = String(990_000_000_00 + Math.floor(Math.random() * 9_000_000)).padStart(11, "0");
    try {
      return binWithChecksum(body);
    } catch {
      /* пробуем другое тело */
    }
  }
}

export interface Counterparty {
  id: string;
  name: string;
  bin: string;
}

/** Контрагент-юрлицо РК, плательщик НДС, с меткой «Проверенный» (подтверждения при отправке не будет). */
export async function createCounterparty(fd: Api, tag: string): Promise<Counterparty> {
  const bin = uniqueBin();
  const name = `ТОО Е2Е ${tag}`;
  const row = await fd.post("/api/bpp/v1/counterparties", {
    name,
    short_name: name,
    kind: "legal",
    country_code: "KZ",
    reg_number: bin,
    is_vat_payer: true,
  });
  await fd.post(`/api/bpp/v1/counterparties/${row.id}/verified`, {
    version: row.version,
    verified: true,
  });
  return { id: row.id, name, bin };
}

export interface RequestItemSpec {
  name: string;
  qty: string;
  price: string;
}

/** Заявка сразу в статусе «Утверждена»: создана и отправлена ролью, ТД и ОД согласовали. */
export async function createApprovedRequest(
  author: Api,
  role: "sn" | "pm",
  projectId: string,
  articleId: string,
  items: RequestItemSpec[],
) {
  const uoms: any[] = await author.get("/api/refdata/v1/uoms?active=true");
  const pcs = uoms.find((u) => u.code === "pcs") ?? uoms[0];
  const need = new Date(Date.now() + 30 * 86_400_000).toISOString().slice(0, 10);
  const draft = await author.post("/api/bpp/v1/requests", {
    initiator_role: role,
    project_id: projectId,
    article_id: articleId,
    purchase_type: "goods",
    need_date: need,
    justification: "Закупка для сценария приёмки модуля (е2е), обоснование не короче десяти знаков",
    items: items.map((i) => ({ ...i, uom_id: pcs.id, need_date: need })),
  });
  await author.post(`/api/bpp/v1/requests/${draft.id}/submit`, { version: draft.version });
  await approveRoute(draft.id, ["td", "od"]);
  const card = await author.get(`/api/bpp/v1/requests/${draft.id}`);
  expect(card.status, `заявка ${card.number}`).toBe("approved");
  return card;
}

/** Дата `ДД.ММ.ГГГГ` → ISO для API. */
export function isoToday(offsetDays = 0): string {
  return new Date(Date.now() + offsetDays * 86_400_000).toISOString().slice(0, 10);
}

/**
 * Счёт без договора в статусе «На рассмотрении ФД»: оформлен из позиций Плана
 * закупок автора, дозаполнен, файл счёта приложен, отправлен (условие SC-005/SC-006).
 * Возвращает карточку счёта.
 */
export async function createSubmittedInvoice(
  author: Api,
  role: "sn" | "pm",
  projectId: string,
  counterparty: Counterparty,
  opts: { amount: string; purchaseType: "goods" | "works"; extNumber: string },
) {
  const plan = await author.get(`/api/bpp/v1/plan?project_id=${projectId}&role=${role}&page_size=100`);
  const ids: string[] = (plan.items ?? []).map((i: any) => i.id);
  expect(ids.length, `в плане ${role} нет позиций проекта ${projectId}`).toBeGreaterThan(0);
  const draft = await author.post("/api/bpp/v1/invoices", { item_ids: ids, role });
  const patched = await author.patch(`/api/bpp/v1/invoices/${draft.id}`, {
    version: draft.version,
    basis: "no_contract",
    counterparty_id: counterparty.id,
    ext_number: opts.extNumber,
    ext_date: isoToday(),
    amount: opts.amount,
    purchase_type: opts.purchaseType,
  });
  await author.upload(`/api/files/v1/bpp.invoice/${draft.id}/files/`, pdfFile("schet.pdf"), {
    file_type: "invoice",
  });
  return author.post(`/api/bpp/v1/invoices/${draft.id}/submit`, { version: patched.version });
}

/**
 * Провести документ по маршруту: роли решают по очереди, пока предмет не
 * перестанет ждать решений. Порядок ролей — как в маршруте.
 */
export async function approveRoute(subjectId: string, roles: Role[]) {
  for (const role of roles) {
    const api = await Api.as(role);
    try {
      const n = await api.approveSubject(subjectId);
      expect(n, `у ${role} нет задачи по ${subjectId}`).toBeGreaterThan(0);
    } finally {
      await api.dispose();
    }
  }
}

// ── UI-мелочи ────────────────────────────────────────────────────────

/** Radix Select: открыть список и выбрать пункт по тексту. */
export async function pick(page: Page, trigger: Locator, option: string | RegExp) {
  await trigger.click();
  await page.getByRole("option", { name: option }).first().click();
}

/**
 * Панель файлов документа (`FilesPanel`): тип документа → «Прикрепить» → файл.
 * Скрытый `input[type=file]` включается после выбора типа.
 */
export async function attachFile(
  page: Page,
  typeName: string | RegExp,
  file: { name: string; mimeType: string; buffer: Buffer },
) {
  // У документов модуля панель файлов лежит на вкладке «Файлы».
  await page.getByRole("tab", { name: "Файлы" }).click();
  await pick(page, page.getByRole("combobox", { name: "Тип документа" }), typeName);
  await page.locator('input[type="file"]:not([disabled])').first().setInputFiles(file);
  await expect(page.getByText(file.name).first()).toBeVisible();
}

/** Подтверждение в диалоге (кнопка «Подтвердить»/«Да»/…), если диалог появился. */
export async function confirmDialog(page: Page, comment?: string) {
  const dialog = page.getByRole("alertdialog").or(page.getByRole("dialog")).last();
  await expect(dialog).toBeVisible();
  if (comment) {
    const box = dialog.locator("textarea").first();
    if (await box.count()) await box.fill(comment);
  }
  await dialog.getByRole("button", { name: /Подтвердить|Да|Утвердить|ОК|Отправить|Выполнить/i }).last().click();
}
