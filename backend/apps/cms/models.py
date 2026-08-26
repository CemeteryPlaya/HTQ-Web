"""CMS domain models — idiomatic Django, built from scratch in the default
``public`` schema.

Historical note: this app started as a schema-preserving port of the ``cms``
FastAPI microservice (its own ``cms`` Postgres schema, alembic-named
constraints/indexes, a custom ``cms.news_status`` PG enum). The customer
clarified (2026-07-19) that this repo is a standalone copy that never runs
side-by-side with the live FastAPI stack, so there is no reason to preserve
those FastAPI-specific schema details. The models below are plain, idiomatic
Django: default ``public`` schema, Django-generated table/constraint/index
names, and ``TextChoices`` instead of a database enum type.

``db_default=`` is kept on the timestamp/text/bool columns — real DB-level
defaults are a good Django 5.2 idiom (and were a deliberate earlier fix), not
an alembic-parity artifact.

One piece of FastAPI business logic is intentionally preserved: a Postgres
trigger that keeps the legacy ``published``/``published_at`` columns in sync
with ``status`` (see migration ``0002_news_sync_published_trigger``, its
``RunSQL`` operation). Task 1.3 added the News CRUD endpoints
(``apps.cms.services.news_service``) and, per that task's brief, left the
trigger in place rather than folding it into ``save()``/a signal: the
service layer's ``apply_status_side_effects`` computes the same
``published``/``published_at`` values in Python (so the ORM object handed
back to a view reflects the correct values immediately, without a DB round
trip) and always does a full, unrestricted ``News.save()`` so ``status`` is
always part of the UPDATE's column list and the trigger reliably fires too
— the two aren't fighting, they're computing the same thing twice on
purpose. ``scheduled_at`` clearing on publish is the one bit the trigger
does NOT do, and is real (non-duplicate) Python-side logic.
"""

import uuid

from django.db import models
from django.db.models.functions import Now


class NewsStatus(models.TextChoices):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Category(models.Model):
    slug = models.CharField(max_length=120, unique=True)
    name = models.CharField(max_length=160)
    description = models.CharField(max_length=500, default="", blank=True, db_default="")
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        verbose_name = "Категория"
        verbose_name_plural = "Категории"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Category id={self.id} slug={self.slug!r}>"


class Tag(models.Model):
    slug = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        verbose_name = "Тег"
        verbose_name_plural = "Теги"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Tag id={self.id} slug={self.slug!r}>"


class News(models.Model):
    title = models.CharField(max_length=300)
    slug = models.CharField(max_length=320, unique=True)

    # Editorial
    excerpt = models.CharField(max_length=500, default="", blank=True, db_default="")
    summary = models.TextField(default="", blank=True, db_default="")
    content = models.TextField(default="", blank=True, db_default="")
    image = models.CharField(max_length=500, null=True, blank=True)

    # Taxonomy
    category = models.CharField(max_length=100, default="", blank=True, db_default="", db_index=True)
    # `category_ref` is a ForeignKey — Django already creates an index on FK
    # columns by default, so no redundant `db_index=True` here.
    category_ref = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="news",
    )
    author_id = models.IntegerField(null=True, blank=True, db_index=True)

    # Lifecycle
    status = models.CharField(
        max_length=20, choices=NewsStatus.choices, default=NewsStatus.DRAFT, db_default=NewsStatus.DRAFT,
        db_index=True,
    )
    published = models.BooleanField(default=False, db_default=False, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    scheduled_at = models.DateTimeField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now(), db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    # A bare M2M — alembic parity (which required an explicit composite-PK
    # through model to avoid a surrogate `id` column) is no longer a goal,
    # so Django is left to manage its own join table normally.
    tags = models.ManyToManyField(Tag, related_name="news_set", blank=True)

    class Meta:
        verbose_name = "Новость"
        verbose_name_plural = "Новости"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<News id={self.id} slug={self.slug!r} status={self.status}>"


class ContactRequest(models.Model):
    first_name = models.CharField(max_length=150, default="", blank=True, db_default="")
    last_name = models.CharField(max_length=150, default="", blank=True, db_default="")
    email = models.EmailField(max_length=254)
    message = models.TextField(default="", blank=True, db_default="")
    handled = models.BooleanField(default=False, db_default=False, db_index=True)
    replied_at = models.DateTimeField(null=True, blank=True, db_index=True)
    # FK-less: User lives in a different app/service boundary than cms owns.
    replied_by_id = models.IntegerField(null=True, blank=True)
    reply_message = models.TextField(default="", blank=True, db_default="")
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now(), db_index=True)

    class Meta:
        verbose_name = "Обращение с сайта"
        verbose_name_plural = "Обращения с сайта"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ContactRequest id={self.id} email={self.email!r} handled={self.handled}>"


class NewsAttachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    news = models.ForeignKey(News, on_delete=models.CASCADE, related_name="attachments")
    role = models.CharField(max_length=20, default="attachment", blank=True, db_default="attachment")  # attachment | cover
    filename = models.CharField(max_length=255)
    size = models.IntegerField()
    content_type = models.CharField(max_length=255)
    storage_path = models.CharField(max_length=1024)
    uploaded_by = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        verbose_name = "Вложение новости"
        verbose_name_plural = "Вложения новостей"


class AuditLog(models.Model):
    user_id = models.IntegerField(null=True, blank=True, db_index=True)
    action = models.CharField(max_length=100, db_index=True)
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    changes = models.JSONField(null=True, blank=True)
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    correlation_id = models.CharField(max_length=36, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, db_default=Now())

    class Meta:
        verbose_name = "Запись аудита"
        verbose_name_plural = "Журнал аудита"


# ═══════════════════════════════════════════════════════════════════════════
#  Блоки главной страницы — управляемый лендинг
# ═══════════════════════════════════════════════════════════════════════════
#
# До этого вся главная была захардкожена: тексты приходили из i18n-файлов
# (`t('hero.title')`), а списки услуг/проектов — из `frontend/src/data/*.ts`,
# где прямо стояло «TODO: будут редактироваться через admin panel». Правка
# любой запятой требовала пересборки фронта.
#
# ПОЧЕМУ ДВЕ МОДЕЛИ, А НЕ ОДНА С JSON. Все секции лендинга оказались одной
# формы: подпись-тег, заголовок, описание и СПИСОК однотипных элементов
# (направления, услуги, проекты, цифры, карточки миссии). Список — это строки,
# которые надо поштучно двигать, прятать и редактировать; в JSON-поле они
# превратились бы в неатомарные правки (двое редакторов затирают друг друга
# целиком) и потеряли бы валидацию. Поэтому элементы — отдельная таблица.
#
# ПОЧЕМУ ДВА ЯЗЫКА КОЛОНКАМИ, А НЕ ТАБЛИЦЕЙ ПЕРЕВОДОВ. Языка ровно два и
# добавление третьего — событие уровня «переверстать сайт», а не рутина.
# Колонки дают простой запрос без джойнов и понятную форму с вкладками RU/EN.


class HomeSection(models.Model):
    """Секция главной страницы.

    ``key`` — стабильный идентификатор, по которому компонент фронтенда
    находит свои данные (``hero``, ``directions``, ``projects``…). Именно он,
    а не ``id``, потому что у каждой секции свой макет в React: связь
    «запись ↔ компонент» должна переживать пересоздание строки и перенос
    между окружениями.

    Секцию НЕЛЬЗЯ создать из интерфейса — только отредактировать, скрыть или
    подвинуть. Новая секция означает новый React-компонент, то есть работу
    разработчика; кнопка «добавить» в UI обещала бы то, чего система не умеет.
    """

    class Layout(models.TextChoices):
        """Готовые макеты для блоков, созданных из интерфейса.

        Секции лендинга свелись к четырём формам — именно поэтому создание
        блоков вообще возможно: bespoke в них только фотографии и иконки, а
        каркас повторяется. У девяти исходных секций свои React-компоненты
        (``is_system``), и ``layout`` для них не используется.
        """
        FEATURES = "features_grid", "Сетка карточек (иконка, заголовок, текст)"
        STATS = "stats", "Цифры (значение и подпись)"
        CTA = "cta", "Призыв к действию (заголовок, текст, кнопка)"
        TEXT_MEDIA = "text_media", "Текст с картинкой"

    key = models.SlugField(max_length=64, unique=True)
    layout = models.CharField(max_length=32, choices=Layout.choices, default=Layout.FEATURES)
    # Девять исходных секций: у каждой свой React-компонент со своей вёрсткой.
    # Их можно прятать, двигать и править, но НЕ удалять: строка в БД лишь
    # питает компонент, и пересоздать её из интерфейса нельзя — новый блок
    # получил бы generic-макет и выглядел иначе. У созданных из UI — False.
    is_system = models.BooleanField(default=False)
    # Русский обязателен, английский — нет: непереведённое поле отдаётся
    # по-русски, а не пустотой (см. схемы и `localized()` ниже).
    tag_ru = models.CharField(max_length=120, blank=True, default="")
    tag_en = models.CharField(max_length=120, blank=True, default="")
    title_ru = models.CharField(max_length=255, blank=True, default="")
    title_en = models.CharField(max_length=255, blank=True, default="")
    description_ru = models.TextField(blank=True, default="")
    description_en = models.TextField(blank=True, default="")
    is_visible = models.BooleanField(default=True)
    # Разреженный шаг (10, 20, 30…) в сиде: вставить между соседями можно без
    # переписывания всей таблицы.
    order = models.IntegerField(default=0, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "Блок главной страницы"
        verbose_name_plural = "Блоки главной страницы"

    def __str__(self) -> str:
        return f"{self.order}. {self.title_ru or self.key}"


class HomeSectionItem(models.Model):
    """Элемент внутри секции: направление, услуга, проект, цифра, карточка.

    Поля намеренно обобщённые, а не «одна модель на каждый тип секции»: все
    элементы лендинга сводятся к «заголовок + описание (+ число / иконка /
    картинка / ссылка)», и десять почти одинаковых таблиц дали бы десять почти
    одинаковых форм и вьюх. Незаполненные поля просто не рисуются — какие
    именно нужны, решает макет конкретной секции.
    """

    section = models.ForeignKey(HomeSection, on_delete=models.CASCADE, related_name="items")
    title_ru = models.CharField(max_length=255, blank=True, default="")
    title_en = models.CharField(max_length=255, blank=True, default="")
    description_ru = models.TextField(blank=True, default="")
    description_en = models.TextField(blank=True, default="")
    # Строка, а не число: сюда попадают и «722», и «90+», и «10+ лет».
    # Анимацию счётчика фронт включает сам, если строка начинается с цифр.
    value = models.CharField(max_length=64, blank=True, default="")
    # Имя иконки lucide-react (`Zap`, `Sun`…) — рендерится по словарю на
    # фронте. Хранить сам SVG незачем: набор иконок фиксирован сборкой.
    icon = models.CharField(max_length=64, blank=True, default="")
    # Путь/URL картинки. Свободная строка, а не FK в media_files: на лендинге
    # лежат и статические файлы из `public/images`, и будущие загрузки.
    image = models.CharField(max_length=512, blank=True, default="")
    link = models.CharField(max_length=512, blank=True, default="")
    is_visible = models.BooleanField(default=True)
    order = models.IntegerField(default=0, db_index=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "Элемент блока"
        verbose_name_plural = "Элементы блоков"

    def __str__(self) -> str:
        return f"{self.section.key} / {self.order}. {self.title_ru or '—'}"

class ConferenceInvite(models.Model):
    """Ссылка-приглашение в комнату видеоконференции.

    Зачем отдельная сущность, а не просто адрес ``/room/<id>``. Комнату
    создаёт браузер, её идентификатор — случайная строка, и до сих пор
    единственным способом позвать человека было переслать этот id. Для
    сотрудника это работало (он всё равно входит под своей учёткой), а для
    внешнего участника — нет: маршрут комнаты требует авторизации, и SFU
    пускает только по платформенному токену.

    Приглашение — это то, что превращает ссылку в право войти:

    * ``token`` в адресе, а не ``room_id``: по нему нельзя догадаться о
      других комнатах, его можно отозвать, не трогая саму встречу, и он
      живёт своим сроком;
    * ``allow_guests`` разделяет «позвать коллег» и «позвать наружу» —
      второе выдаёт гостевой JWT человеку без учётки, и включать это надо
      осознанно, а не по умолчанию;
    * счётчик входов и ``revoked_at`` дают ответ на вопрос «кто и когда
      заходил по этой ссылке» и возможность её закрыть.

    FK на пользователя нет намеренно: ``cms`` не владеет таблицей людей
    (правило изоляции аппок), поэтому автор хранится числом.
    """

    room_id = models.CharField(max_length=64, db_index=True)
    token = models.CharField(max_length=64, unique=True)
    #: Название встречи — показывается на странице входа, чтобы человек
    #: понимал, куда его позвали, ещё до включения камеры.
    title = models.CharField(max_length=255, default="", blank=True, db_default="")
    created_by_id = models.IntegerField(null=True, blank=True, db_index=True)
    allow_guests = models.BooleanField(default=True, db_default=True)
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    #: 0 — без ограничения. Иначе ссылка перестаёт работать после N входов.
    max_uses = models.PositiveIntegerField(default=0, db_default=0)
    uses = models.PositiveIntegerField(default=0, db_default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)
    #: Язык интерфейса для того, кто откроет ссылку — "ru"/"en" либо пусто.
    #: Пусто — язык НЕ задан (обычный случай для старых ссылок и для тех, кто
    #: не выбирал язык явно): страница входа ведёт себя как раньше, ничего не
    #: переключая. Заказчик просил ровно это: у иностранного гостя нет
    #: профиля и переключателя языка под рукой, поэтому язык должен ехать
    #: вместе со ссылкой, а не угадываться по браузеру гостя. Поле — простой
    #: CharField без ограничения значений на уровне БД (ручная правка строки
    #: в базе технически может записать что угодно), поэтому сервис
    #: (`conference_invite_service.normalize_locale`) приводит значение к
    #: "ru"/"en"/"" не только при записи, но и на КАЖДОМ пути чтения — так
    #: что мусор не долетает до пользователя, даже если он оказался здесь в
    #: обход `create_invite`.
    locale = models.CharField(max_length=8, blank=True, default="", db_default="")
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        verbose_name = "Приглашение в конференцию"
        verbose_name_plural = "Приглашения в конференцию"
        ordering = ("-created_at",)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ConferenceInvite room={self.room_id!r} token={self.token[:8]}…>"
