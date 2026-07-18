# Lark processes — normalized overview

27 processes with accessible config. Widget types resolved to Lark palette labels; workflow nodes to kinds.


## Авансовый отчёт KZ

**Form (3 top-level widgets):**

- `mutableGroup` **Data from Base** *(req)* — Base table: "Заявка на подотчётные средства" — 6 sub-fields: Наименование администратора программы(radioV2), Цель(radioV2), Сумма, запрашиваемая(number), Сумма, запрашиваемая-Currency(radioV2), Системный номер заявки(radioV2), Status(radioV2)
- `fieldList` **Отчет** *(req)* — 5 sub-fields: Наименование затрат(input), Data from Base(mutableGroup), Data from Base(mutableGroup), Сумма расходов(amount), Подтверждающие документы(attachmentV2)
- `formula` **Остаток** *(req)*

**Workflow (3 nodes):** Submit → Auto-approve → End

## Авансовый отчёт UZ

**Form (2 top-level widgets):**

- `mutableGroup` **Data from Base** *(req)* — Base table: "Заявка на cash UZ" — 6 sub-fields: Администратор бюджета(radioV2), Цель(radioV2), Сумма, запрашиваемая(number), Сумма, запрашиваемая-Currency(radioV2), Status(radioV2), Системный номер заявки(radioV2)
- `fieldList` **Отчет** *(req)* — 5 sub-fields: Наименование затрат(input), Data from Base(mutableGroup), Data from Base(mutableGroup), Сумма расходов(amount), Подтверждающие документы(attachmentV2)

**Workflow (7 nodes):** Submit → Condition/branch → Approval → Фильтр → parallel-aggregation → Контроль → End
_(1 conditional edge(s))_

## Договор UZ

**Form (10 top-level widgets):**

- `mutableGroup` **Data from Base** *(req)* — Base table: "Бюджет проекта" — 2 sub-fields: Администратор бюджета(radioV2), Бюджетная программа(radioV2)
- `mutableGroup` **Data from Base-Copy** *(req)* — Base table: "Специфика бюджета проекта" — 1 sub-fields: Специфика(radioV2)
- `input` **Наименование договора** *(req)*
- `radioV2` **НДС** *(req)* — options: С НДС / Без НДС
- `radioV2` **РиУ/ТМЦ** *(req)* — options: ТМЦ / РиУ
- `radioV2` **Тип оплаты** *(req)* — options: Предоплата / Пост. оплата
- `number` **ИНН Поставщика** *(req)*
- `amount` **Общая сумма договора** *(req)* — currencies: UZS
- `attachmentV2` **Договор + приложение** *(req)*
- `serialNumber` **Системный номер**

**Workflow (4 nodes):** Submit → Согласование → Утверждение → End

## Договор UZ (главный)

**Form (12 top-level widgets):**

- `input` **Наименование договора** *(req)*
- `mutableGroup` **Data from Base** *(req)* — Base table: "Бюджет проекта" — 3 sub-fields: Администратор бюджета(radioV2), Бюджетная программа(radioV2), Пояснение(radioV2)
- `mutableGroup` **Data from Base-Copy** *(req)* — Base table: "Специфика бюджета проекта" — 2 sub-fields: Специфика(radioV2), Определение(radioV2)
- `radioV2` **НДС** *(req)* — options: С НДС / Без НДС
- `radioV2` **Тип договора** *(req)* — options: Рамочный договор / Фиксированный договор
- `radioV2` **Тип поставки** *(req)* — options: ТМЦ / РиУ
- `radioV2` **Форма оплаты** *(req)* — options: Предоплата / Постоплата
- `number` **ИНН Поставщика** *(req)*
- `amount` **Общая сумма договора** *(req)* — currencies: UZS
- `attachmentV2` **Проект договора** *(req)*
- `attachmentV2` **Подписанный договор + приложение**
- `serialNumber` **Системный номер договора**

**Workflow (9 nodes):** Submit → Condition/branch → TUTIY-Согласование → OLGA-Согласование → SAZAGAN-Согласование → Согласование ГД → Прикрепить подписанный договор → Утверждение ГД → End
_(2 conditional edge(s))_

## Договора KZ

**Form (11 top-level widgets):**

- `input` **Наименование договора** *(req)*
- `mutableGroup` **Data from Base** *(req)* — Base table: "Формирование бюджета проекта" — 2 sub-fields: Наименование администратора программы(radioV2), Бюджет проекта_Программа бюджета(radioV2)
- `mutableGroup` **Data from Base-Copy** *(req)* — Base table: "Специфика" — 1 sub-fields: Номер специфики(radioV2)
- `radioV2` **Договор на поставку** *(req)* — options: ТМЦ / РиУ
- `radioV2` **НДС** *(req)* — options: С НДС / Без НДС
- `input` **Общая сумма договора** *(req)*
- `radioV2` **Валюта** *(req)* — options: KZT / UZS / USD / RUB
- `date` **Срок договора** *(req)*
- `attachmentV2` **Договор + приложение** *(req)*
- `attachmentV2` **Справка о благонадежности поставщика**
- `serialNumber` **Системный номер договора**

**Conditional visibility:** 1 rule(s)

**Workflow (5 nodes):** Submit → Согласование → Согласование → Утверждение ГД → End

## Договора UZ

**Form (14 top-level widgets):**

- `input` **Наименование договора** *(req)*
- `radioV2` **Договор на поставку** *(req)* — options: ТМЦ / РиУ
- `radioV2` **Тип договора** *(req)* — options: Рамочный договор поставки / Типовой договор поставки
- `radioV2` **Условия оплаты** *(req)* — options: Постоплата/АВР / Предоплата
- `radioV2` **НДС** *(req)* — options: С НДС / Без НДС
- `input` **Общая сумма договора** *(req)*
- `radioV2` **Валюта** *(req)* — options: KZT / USD / UZS / KGS / RUB / CNY / EUR
- `radioV2` **Условие поставки (Инкотермс)** *(req)* — options: DDP – Delivered Duty Paid (поставка с пошлиной) / DAP – Delivered At Place (поставка в пункте) / DPU – Delivered at Place Unloaded (с разгрузкой) / EXW – Ex Works (самовывоз с завода) / FCA – Free Carrier (свободно у перевозчика) / CPT – Carriage Paid To (перевозка оплачена до) / CIP – Carriage and Insurance Paid To (перевозка и страхование оплачены до)
- `input` **Описание условия поставки (Инкотермс)**
- `date` **Срок поставки** *(req)*
- `attachmentV2` **Договор + приложение** *(req)*
- `attachmentV2` **Справка о благонадежности поставщика**
- `serialNumber` **Системный номер договора**
- `input` **Системный номер СТ** *(req)*

**Conditional visibility:** 4 rule(s)

**Workflow (5 nodes):** Submit → Согласование → Согласование → Утверждение ГД → End

## Доп. соглашение к договору KZ

**Form (5 top-level widgets):**

- `serialNumber` **Системный номер**
- `mutableGroup` **Data from Base** *(req)* — Base table: "Договора KZ" — 6 sub-fields: Наименование администратора программы(radioV2), Бюджет проекта_Программа бюджета(radioV2), Номер специфики(radioV2), Системный номер договора(radioV2), Status(radioV2), Наименование договора(radioV2)
- `radioV2` **Дополнения/Изменения в части:** *(req)* — options: Суммы / Условий
- `number` **На сумму** *(req)*
- `attachmentV2` **Дополнительное соглашение** *(req)*

**Conditional visibility:** 1 rule(s)

**Workflow (3 nodes):** Submit → Approval → End

## Доп. соглашение к договору UZ

**Form (5 top-level widgets):**

- `serialNumber` **Системный номер**
- `mutableGroup` **Data from Base** *(req)* — Base table: "Договора UZ 2.0" — 6 sub-fields: Администратор бюджета(radioV2), Бюджетная программа(radioV2), Специфика(radioV2), Системный номер договора(radioV2), Наименование договора(radioV2), Status(radioV2)
- `radioV2` **Дополнения/Изменения в части:** *(req)* — options: Суммы / Условий
- `number` **На сумму** *(req)*
- `attachmentV2` **Дополнительное соглашение** *(req)*

**Conditional visibility:** 1 rule(s)

**Workflow (3 nodes):** Submit → Approval → End

## Журнал регистрации инцидентов, происшествий и несчастных случаев

**Form (9 top-level widgets):**

- `serialNumber` **Системный номер**
- `date` **Дата инцидента** *(req)*
- `input` **Место происшествия** *(req)*
- `input` **Участники (ФИО, должность)** *(req)*
- `textarea` **Описание инцидента** *(req)*
- `radioV2` **Степень последствий** *(req)* — options: нет / лёгкая / тяжёлая / смертельная
- `textarea` **Принятые меры / устранение** *(req)*
- `input` **Ответственный за устранение** *(req)*
- `attachmentV2` **Фото**

**Workflow (3 nodes):** Submit → Approval → End

## Журнал регистрации подрядчиков

**Form (12 top-level widgets):**

- `serialNumber` **Регистрационный номер**
- `date` **Дата регистрации** *(req)*
- `input` **Наименование подрядной организации** *(req)*
- `input` **Представитель подрядчика (ФИО)** *(req)*
- `input` **Представитель подрядчика (Должность)** *(req)*
- `input` **Контактный телефон** *(req)*
- `input` **Электронная почта** *(req)*
- `mutableGroup` **Data from Base** *(req)* — Base table: "Договора KZ" — 2 sub-fields: Общая сумма договора(radioV2), Системный номер договора(radioV2)
- `radioV2` **Вид работ / услуги** *(req)* — options: Строительно-монтажные работы / Земляные работы / Отделочные работы / Электромонтажные работы / Сантехнические работы / Проектные работы / Пуско-наладочные работы / Ремонт оборудования / Техническое обслуживание / Аренда техники / Транспортные услуги / Грузоперевозки / Уборка помещений / Охранные услуги / Консультационные услуги / Юридические услуги / Бухгалтерские услуги / ИТ-услуги / Маркетинговые услуги / Дизайн и визуализация / Обучение и тренинги / Проживание / Питание / кейтеринг
- `input` **Пропуск на объект (номер пропуска)** *(req)*
- `date` **Пропуск на объект (дата)** *(req)*
- `radioV2` **Отметка о завершении работ** *(req)* — options: Завершено / В работе

**Workflow (3 nodes):** Submit → Approval → End

## Заявка на закупку UZ

**Form (2 top-level widgets):**

- `fieldList` **Список ТРУ** *(req)* — 8 sub-fields: Data from Base(mutableGroup), Data from Base(mutableGroup), Наименование ТРУ(input), Единица измерения(input), Кол-во(number), Дата потребности(date), Комментарий(textarea), Файл(attachmentV2)
- `serialNumber` **Системный номер заявки**

**Workflow (5 nodes):** Submit → Согласование → Согласование → Утверждение ГД → End

## Заявка на подотчётные средства KZ

**Form (6 top-level widgets):**

- `mutableGroup` **Data from Base** *(req)* — Base table: "Формирование бюджета проекта" — 1 sub-fields: Наименование администратора программы(radioV2)
- `amount` **Сумма, запрашиваемая** *(req)* — currencies: KZT
- `textarea` **Цель** *(req)*
- `serialNumber` **Системный номер заявки**
- `input` **Референс операции АБИС/ Рег. номер**
- `input` **Код назначения платежа**

**Workflow (6 nodes):** Submit → Согласование → Согласование → Утверждение → Этап оплаты → End

## Заявка на ФОТ

**Form (1 top-level widgets):**

- `fieldList` **Согласование выплаты по ФОТ** *(req)* — 8 sub-fields: Период(date), Выбрать страну(radioV2), Data from Base(mutableGroup), Data from Base-Copy(mutableGroup), Сумма за месяц(amount), Номер платежи(input), Референс(attachmentV2), Прикрепить табель(attachmentV2)

**Conditional visibility:** 4 rule(s)

**Workflow (7 nodes):** Submit → Согласование → Утверждение → Condition/branch → Обработка КЗ → Обработка УЗ → End
_(1 conditional edge(s))_

## Заявка на cash UZ

**Form (7 top-level widgets):**

- `mutableGroup` **Data from Base** *(req)* — Base table: "Бюджет проекта" — 2 sub-fields: Администратор бюджета(radioV2), Бюджетная программа(radioV2)
- `amount` **Сумма, запрашиваемая** *(req)* — currencies: UZS
- `textarea` **Цель** *(req)*
- `attachmentV2` **Attachment**
- `serialNumber` **Системный номер заявки**
- `input` **Референс операции АБИС/ Рег. номер**
- `input` **Код назначения платежа**

**Workflow (7 nodes):** Submit → Согласование → Approval → Согласование → Утверждение → Этап оплаты → End

## Код транзакции

**Form (2 top-level widgets):**

- `mutableGroup` **Data from Base** *(req)* — Base table: "Оплата РиУ по договору" — 1 sub-fields: Номер АВР(radioV2)
- `input` **Код транзакции** *(req)*

**Workflow (3 nodes):** Submit → Approval → End

## Наличные расходы KZ

**Form (3 top-level widgets):**

- `serialNumber` **Системный номер ND**
- `fieldList` **Наличные расходы** *(req)* — 7 sub-fields: Data from Base(mutableGroup), Data from Base-Copy(mutableGroup), Наименование ТМЦ/РиУ(input), Кол-во(number), Е.И.(input), Цена за е.д.(amount), Сумма итого(formula)
- `attachmentV2` **Чек при наличии**

**Workflow (6 nodes):** Submit → Согласование → Согласование → Утверждение ГД → Обработка бухгалтерией → End

## Наличные расходы UZ

**Form (4 top-level widgets):**

- `serialNumber` **Системный номер ND**
- `fieldList` **Бюджет ОУП Hi-Tech Group** *(req)* — 2 sub-fields: Data from Base(mutableGroup), Data from Base-Copy(mutableGroup)
- `fieldList` **Наличные расходы** *(req)* — 4 sub-fields: Наименование ТМЦ(input), Кол-во(number), Е.И.(input), Сумма(amount)
- `attachmentV2` **Чек при наличии**

**Workflow (6 nodes):** Submit → Согласование → Согласование → Утверждение ГД → Обработка бухгалтерией → End

## Отчет Варваринское

**Form (1 top-level widgets):**

- `fieldList` **Суточный отчет** *(req)* — 4 sub-fields: Data from Base(mutableGroup), Объем работ(number), Дата(date), Комментарий(textarea)

**Workflow (3 nodes):** Submit → Auto-approve → End

## Платежные документы UZ

**Form (10 top-level widgets):**

- `radioV2` **Тип оплаты** *(req)* — options: Постоплата / Предоплата
- `radioV2` **Документ предоплаты** *(req)* — options: Договор ТМЦ/РиУ без Счета на оплату / Договор ТМЦ/РиУ со Счетом на оплату / Счет на оплату без договора
- `radioV2` **Документ постоплаты** *(req)* — options: Акт выполненных работ/услуг / Товарно-транспортная накладная
- `fieldList` **АВР** *(req)* — 5 sub-fields: Data from Base(mutableGroup), Сумма АВР(amount), Акт выполненных работ(attachmentV2), Счет фактура(attachmentV2), Платежное поручение(attachmentV2)
- `fieldList` **Накладная** *(req)* — 5 sub-fields: Data from Base(mutableGroup), Сумма накладной(amount), Товарно-транспортная накладная(attachmentV2), Счет фактура(attachmentV2), Платежное поручение(attachmentV2)
- `fieldList` **По договору со Счетом на оплату** *(req)* — 6 sub-fields: Data from Base(mutableGroup), Сумма счета на оплату(amount), Счет на оплату(attachmentV2), Товарно-транспортная накладная.(attachmentV2), Счет фактура(attachmentV2), Платежное поручение(attachmentV2)
- `fieldList` **По договору без счета на оплату** *(req)* — 4 sub-fields: Data from Base(mutableGroup), Сумма авансового платежа(amount), Счет фактура(attachmentV2), Платежное поручение(attachmentV2)
- `fieldList` **Счет на оплату без договора** *(req)* — 10 sub-fields: Наименование потребности(input), Пояснительная записка(textarea), Data from Base(mutableGroup), Связать служебную записку на закупку(connect), Data from Base-Copy(mutableGroup), Сумма аванса(amount), Счет на оплату(attachmentV2), Накладная(attachmentV2), Счет фактура(attachmentV2), Платежное поручение(attachmentV2)
- `input` **Референс операции АБИС/ Рег. номер**
- `input` **Код назначения платежа**

**Conditional visibility:** 7 rule(s)

**Workflow (10 nodes):** Submit → Condition/branch → TUTIY-Согласование → OLGA-Согласование → SAZAGAN-Согласование → Утверждение ГД → Обработка бухгалтерией → Обработка заявителем → Завершение бухгалтерия → End
_(2 conditional edge(s))_

## Приказы / Распоряжения

**Form (5 top-level widgets):**

- `serialNumber` **Системный номер приказа**
- `date` **Дата**
- `textarea` **Краткое содержание** *(req)*
- `attachmentV2` **Вложения** *(req)*
- `connect` **Связанные документы**

**Workflow (5 nodes):** Submit → Этап согласования → Утверждение и подписание → Уведомления → End

## Протокол собрания

**Form (8 top-level widgets):**

- `text` **Description 1** *(req)*
- `text` **Description 2** *(req)*
- `text` **-Copy** *(req)*
- `text` **-Copy-Copy** *(req)*
- `serialNumber` **Номер протокола**
- `date` **Дата и время собрания** *(req)*
- `textarea` **Повестка дня** *(req)*
- `fieldList` **Решения и задачи** *(req)* — 3 sub-fields: Задача(input), Ответственный(contact), Срок исполнения(date)

**Workflow (5 nodes):** Submit → Утверждение протокола → Ознакомление → Уведомление → End

## Рег. вхд /исх корреспонденции

**Form (15 top-level widgets):**

- `serialNumber` **Системный номер**
- `radioV2` **Тип корреспонденции** *(req)* — options: Входящая / Исходящая
- `date` **Дата получения** *(req)*
- `input` **Входящий №** *(req)*
- `input` **От кого поступило** *(req)*
- `textarea` **Краткое содержание письма** *(req)*
- `input` **Адресат / кому направлено** *(req)*
- `input` **Резолюция / Примечание** *(req)*
- `date` **Дата отправки** *(req)*
- `input` **Исходящий №** *(req)*
- `input` **Кому отправлено** *(req)*
- `textarea` **Краткое содержание** *(req)*
- `input` **Подписал** *(req)*
- `input` **Способ отправки** *(req)*
- `attachmentV2` **Attachment**

**Conditional visibility:** 12 rule(s)

**Workflow (3 nodes):** Submit → Auto-approve → End

## Сравнительная таблица KZ

**Form (3 top-level widgets):**

- `fieldList` **Сравнительная таблица** *(req)* — 7 sub-fields: Наименование поставщика(input), ИИН/БИН(input), Дата КП(date), Условия поставки(radioV2), Условия оплаты(radioV2), Сумма поставщика(amount), Примечение(textarea)
- `mutableGroup` **Data from Base** *(req)* — Base table: "Заявка на покупку ТРУ" — 1 sub-fields: Системный номер заявки(radioV2)
- `serialNumber` **Системный номер СТ**

**Workflow (5 nodes):** Submit → Согласование → Согласование → Утверждение ГД → End

## Сравнительная таблица UZ

**Form (3 top-level widgets):**

- `fieldList` **Бюджет** *(req)* — 2 sub-fields: Data from Base(mutableGroup), Data from Base-Copy(mutableGroup)
- `fieldList` **Сравнительная таблица** *(req)* — 9 sub-fields: Наименование поставщика(input), ИИН/БИН(input), Дата КП(date), Условия поставки(radioV2), Условия оплаты(radioV2), Сумма поставщика(amount), Примечение(textarea), Data from Base(mutableGroup), Номер заявки на закупку(input)
- `serialNumber` **Системный номер СТ**

**Workflow (5 nodes):** Submit → Согласование → Согласование → Утверждение ГД → End

## Счет на оплату KZ

**Form (5 top-level widgets):**

- `radioV2` **Наличие договора** *(req)* — options: По договору / Без договора
- `fieldList` **Счет на оплату без договора** *(req)* — 14 sub-fields: Наименование ТРУ(input), Data from Base(mutableGroup), Data from Base(mutableGroup), Единица измерения(input), Кол-во(input), Сумма(amount), Номер счета на оплату(input), Сведения о поставщике наименование(input), Сведения о поставщике ИИН/БИН-Copy(input), Сведения о поставщике номер телефона(input), Сведения о поставщике адрес(input), Цель закупки(textarea), Необходимая дата оплаты(date), Счет на оплату(attachmentV2)
- `fieldList` **Счет на оплату по договору** *(req)* — 5 sub-fields: Наименование счета(input), Data from Base(mutableGroup), Номер счета на оплату(input), Сумма(amount), Счет на оплату(attachmentV2)
- `input` **Референс операции АБИС/ Рег. номер**
- `input` **Код назначения платежа**

**Conditional visibility:** 2 rule(s)

**Workflow (8 nodes):** Submit → Согласование → Согласование → Утверждение ГД → Обработка бухгалтерией → Заявитель - вложить закрывающие документы → Подтверждение получения всех документов → End

## Счет на оплату UZ

**Form (3 top-level widgets):**

- `radioV2` **Наличие договора** *(req)* — options: По договору / Без договора
- `fieldList` **Счет на оплату без договора** *(req)* — 14 sub-fields: Наименование ТРУ(input), Data from Base(mutableGroup), Data from Base(mutableGroup), Единица измерения(input), Кол-во(input), Сумма(amount), Номер счета на оплату(input), Сведения о поставщике наименование(input), Сведения о поставщике ИИН/БИН-Copy(input), Сведения о поставщике номер телефона(input), Сведения о поставщике адрес(input), Цель закупки(textarea), Необходимая дата оплаты(date), Счет на оплату(attachmentV2)
- `fieldList` **Счет на оплату по договору** *(req)* — 5 sub-fields: Data from Base(mutableGroup), Номер счета на оплату(input), Наименование(input), Сумма(amount), Счет на оплату(attachmentV2)

**Conditional visibility:** 2 rule(s)

**Workflow (8 nodes):** Submit → Согласование → Согласование → Утверждение ГД → Обработка бухгалтерией → Заявитель - вложить подтверждающие документы → Подтверждение получения документов → End

## Формирование бюджета проекта

**Form (3 top-level widgets):**

- `serialNumber` **Системный номер бюджета**
- `input` **Наименование администратора программы** *(req)*
- `fieldList` **Бюджет проекта** *(req)* — 3 sub-fields: Программа бюджета(input), Заложенная сумма(amount), Файл(attachmentV2)

**Workflow (3 nodes):** Submit → Утверждение ГД → End
