# Модуль БЗО: роли и права — на утверждение Алгазы

Основание — ТЗ §17. Признаки: V — видит, C — создаёт, E — меняет / выполняет операцию, D — удаляет. Пусто — запрет. «Свои» (свои статьи, свои проекты, свои документы) режет сервис по принадлежности, а не роль.

| Узел | ФД | ТД | ОД | ГД | БУХ | СН | ПМ | АДМ |
|---|---|---|---|---|---|---|---|---|
| `bpp.budgets` | VCED | V | V | V | | V (свои статьи) | V (свои статьи и проекты) | V |
| `bpp.budgets.approve` | E | | | | | | | |
| `bpp.requests` | V | V | V | V | | VCED (свои) | VCED (свои) | V |
| `bpp.requests.cancel_approved` | E | | | | | | | |
| `bpp.plan` | V | | | | | VE (свой) | VE (свой) | |
| `bpp.plan.all` | V | | | | | | | |
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

Главный бухгалтер и бухгалтер — одна роль «БУХ» (D-40). АДМ не видит финансовые документы (ТЗ §17): у него только справочники, настройки, проекты и просмотр реестров без сумм — просмотр бюджетов, заявок и договоров остаётся, как в ТЗ. Роли утверждаются при создании (Q-C14): до мерджа миграции `access/0014` — подтверждение Алгазы.
