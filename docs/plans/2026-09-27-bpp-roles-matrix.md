# Модуль БЗО: роли и права

**Утверждено Алгазы 27.09.2026** (Q-C14). Вне матрицы — роль `platform-admin`: её денежные операции — вопрос [Q-E28](2026-09-25-bpp-open-questions.md#q-e28).

Основание — ТЗ §17. Признаки: V — видит, C — создаёт, E — меняет / выполняет операцию, D — удаляет. Пусто — запрет. «Свои» (свои статьи, свои проекты, свои документы) режет сервис по принадлежности, а не роль.

| Узел | ФД | ТД | ОД | ГД | БУХ | СН | ПМ | АДМ |
|---|---|---|---|---|---|---|---|---|
| `bpp.budgets` | VCED | V | V | V | | V (свои статьи) | V (свои статьи и проекты) | V |
| `bpp.budgets.approve` | E | | | | | | | |
| `bpp.requests` | V | V | V | V | | VCED (свои) | VCED (свои) | V |
| `bpp.requests.cancel_approved` | E | | | | | | | |
| `bpp.requests.all` | V | V | V | V | | | | V |
| `bpp.plan` | V | | | | | VE (свой) | VE (свой) | |
| `bpp.plan.all` | V | | | | | | | |
| `bpp.plan.reassign` | | | | | | | | E |
| `bpp.agreements` | VE | VE | VE | VE | V | VCE | VCE | V |
| `bpp.agreements.terminate` | E | | | | | | | |
| `bpp.invoices` | V | V | V | V | V | VCED (свои) | VCED (свои) | |
| `bpp.invoices.decision` | E | | | | | | | |
| `bpp.invoices.payment` | | | | | E | | | |
| `bpp.invoices.closing_docs` | E (от имени автора) | | | | | E (свои) | E (свои) | |
| `bpp.bank` | VCED | | | | V | | | |
| `bpp.dashboard` | V | V | V | V | V | | | |
| `bpp.counterparties` | VCE | V | V | V | VCE | VC | VC | |
| `bpp.counterparties.block` | E | | | | | | | |
| `bpp.alternatives` | V | V | V | V | | VC | V (свои документы) | |
| `bpp.alternatives.select` | E | | | E | | | | |
| `bpp.kpi` | VE | | V | V | | V (свои строки) | | |
| `bpp.accountable` | VE | | | | V | VC | VC | |
| `bpp.accountable.payment` | | | | | E | | | |
| `bpp.articles.supply` | V | V | V | V | V | V | | V |
| `bpp.articles.pm` | V | V | V | V | V | | V | V |
| `bpp.settings` | V | | | | | | | VCED |
| `refdata` | VCE | V | V | V | V | V | V | VCE |
| `project` | VCE | VCE | VCE | VCE | V | V | V | VCE |
| `project.members` | V | V | V | V | V | V | VE | VE |
| `project.all` | V | V | V | V | V | V | | V |

`project.all` — «все проекты, а не только участия» (мастер-план A1.3, миграция `access/0015`): без него список, карточка и участники ограничены проектами, где человек участник. `bpp.requests.all` — «все заявки, а не только свои», `bpp.plan.reassign` — переназначение исполнителя позиций плана (сверка B §7.3, миграция `access/0017`). Круг ролей тот же, что был до узлов: все заявки видели роли с просмотром заявок без создания, переназначал АДМ через `bpp.settings`. Смысл матрицы не меняется, у всех восьми ролей на обоих узлах явная строка. Главный бухгалтер и бухгалтер — одна роль «БУХ» (D-40). АДМ не видит финансовые документы (ТЗ §17): у него только справочники, настройки, проекты и просмотр реестров без сумм — просмотр бюджетов, заявок и договоров остаётся, как в ТЗ. Роли утверждаются при создании (Q-C14): матрица утверждена Алгазы 27.09.2026.
