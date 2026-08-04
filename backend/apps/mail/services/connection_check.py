"""Проверка связи с почтовым сервером — общая для CLI и кнопки в интерфейсе.

Логика живёт здесь, а не в management-команде, ровно потому, что проверять
подключение нужно из двух мест: ``manage.py mail_check`` (когда есть доступ к
серверу) и кнопка «Проверить» на странице «Корпоративные ящики» (когда его
нет). Дублировать её означало бы получить два расходящихся диагноста.

Проверки идут В ПОРЯДКЕ ЗАВИСИМОСТИ и обрываются на первом провале: если
порт закрыт, сообщать вдобавок «IMAP не отвечает» и «SMTP не отвечает» —
значит утопить настоящую причину в производных. Каждый шаг несёт ``hint`` —
конкретное действие, а не констатацию.

Секреты сюда попадают (пароль ящика для проверки логина), но НАРУЖУ не
уходят никогда: в ``CheckStep`` кладётся только текст без пароля, и это
закреплено тестом.
"""
from __future__ import annotations

import smtplib
import socket
import ssl
from dataclasses import asdict, dataclass, field

from apps.mail.services import provisioning
from apps.mail.services.imap_client import ImapClient, ImapError, ImapNotConfigured
from apps.mail.services.mail_config import get_config

OK = "ok"
FAIL = "fail"
SKIP = "skip"


@dataclass
class CheckStep:
    key: str
    title: str
    status: str                 # ok | fail | skip
    detail: str = ""
    hint: str = ""
    #: произвольные подробности шага (список папок, счётчики писем и т.п.)
    data: dict = field(default_factory=dict)


@dataclass
class CheckReport:
    ok: bool = True
    steps: list[CheckStep] = field(default_factory=list)

    def add(self, step: CheckStep) -> CheckStep:
        if step.status == FAIL:
            self.ok = False
        self.steps.append(step)
        return step

    def to_dict(self) -> dict:
        return {"ok": self.ok, "steps": [asdict(s) for s in self.steps]}


def _tcp_reachable(host: str, port: int, timeout: int) -> str | None:
    """None — порт отвечает; иначе текст ошибки."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return None
    except OSError as exc:
        return str(exc)


TUNNEL_HINT = (
    "Если хост — mail-tunnel, контейнер туннеля не поднят или упал:\n"
    "  docker compose --profile mail-tunnel up -d mail-tunnel\n"
    "  docker compose logs --tail=50 mail-tunnel"
)


def run_check(
    *, mailbox: str | None = None, password: str | None = None,
    send_to: str | None = None, timeout: int = 10,
) -> CheckReport:
    """Пройти цепочку проверок и вернуть структурированный отчёт.

    ``mailbox``/``password`` необязательны: без них проверяются настройки и
    доступность портов — этого достаточно, чтобы отладить туннель, и не
    требуется ни одного секрета. ``send_to`` шлёт НАСТОЯЩЕЕ письмо, поэтому
    срабатывает только при явной передаче.
    """
    report = CheckReport()
    cfg = get_config()
    info = provisioning.describe()

    # ── 1. настройки ────────────────────────────────────────────────────
    if not cfg.domain:
        report.add(CheckStep(
            key="config", title="Настройки", status=FAIL,
            detail="Домен ящиков не задан",
            hint="Укажите домен (например htq.group) в поле «Домен ящиков» — "
                 "голый домен, без «@» и «https://».",
        ))
    elif info["provisioner"] == "none":
        report.add(CheckStep(
            key="config", title="Настройки", status=FAIL,
            detail="Почтовый сервер не подключён — ящики останутся только в базе платформы",
            hint="Задайте IMAP-хост (режим IMAP/SMTP) либо адрес и ключ Mailcow API.",
            data=info,
        ))
    else:
        report.add(CheckStep(
            key="config", title="Настройки", status=OK,
            detail=f"Режим {info['provisioner']}, домен {cfg.domain}", data=info,
        ))

    # ── 2. доступность портов ───────────────────────────────────────────
    imap_error = None
    if not cfg.imap_host:
        report.add(CheckStep(
            key="imap_port", title="IMAP: порт", status=SKIP,
            detail="IMAP-хост не задан",
        ))
        imap_error = "не задан"
    else:
        imap_error = _tcp_reachable(cfg.imap_host, cfg.imap_port, timeout)
        report.add(CheckStep(
            key="imap_port", title="IMAP: порт",
            status=FAIL if imap_error else OK,
            detail=(f"{cfg.imap_host}:{cfg.imap_port} — "
                    + (f"недоступен ({imap_error})" if imap_error else "отвечает")),
            hint=TUNNEL_HINT if imap_error else "",
        ))

    smtp_host, smtp_port = cfg.effective_smtp_host(), cfg.smtp_port
    smtp_error: str | None
    if not smtp_host:
        report.add(CheckStep(
            key="smtp_port", title="SMTP: порт", status=SKIP, detail="SMTP-хост не задан",
        ))
        smtp_error = "не задан"
    else:
        smtp_error = _tcp_reachable(smtp_host, smtp_port, timeout)
        report.add(CheckStep(
            key="smtp_port", title="SMTP: порт",
            status=FAIL if smtp_error else OK,
            detail=(f"{smtp_host}:{smtp_port} — "
                    + (f"недоступен ({smtp_error})" if smtp_error else "отвечает")),
            hint=TUNNEL_HINT if smtp_error else "",
        ))

    # ── 3. IMAP ─────────────────────────────────────────────────────────
    if imap_error:
        report.add(CheckStep(
            key="imap", title="IMAP", status=SKIP,
            detail="Порт недоступен — проверять протокол смысла нет",
        ))
    else:
        _check_imap(report, cfg, mailbox, password)

    # ── 4. SMTP ─────────────────────────────────────────────────────────
    if smtp_error:
        report.add(CheckStep(
            key="smtp", title="SMTP", status=SKIP,
            detail="Порт недоступен — проверять протокол смысла нет",
        ))
    else:
        _check_smtp(report, cfg, mailbox, password, send_to, timeout)

    return report


def _check_imap(report: CheckReport, cfg, mailbox: str | None, password: str | None) -> None:
    try:
        client = ImapClient.from_settings()
    except ImapNotConfigured as exc:
        report.add(CheckStep(key="imap", title="IMAP", status=FAIL, detail=str(exc)))
        return

    try:
        conn = client._open_connection()
    except ssl.SSLError as exc:
        report.add(CheckStep(
            key="imap", title="IMAP: соединение", status=FAIL,
            detail=f"TLS-рукопожатие не удалось: {exc}",
            hint="Через SSH-туннель TLS обычно не нужен — шифрует сам SSH: "
                 "снимите «Использовать SSL» и STARTTLS.\n"
                 "Если TLS нужен, а сертификат выписан на другое имя — задайте "
                 "«Имя для проверки сертификата».",
        ))
        return
    except Exception as exc:  # noqa: BLE001
        report.add(CheckStep(
            key="imap", title="IMAP: соединение", status=FAIL,
            detail=f"Не удалось открыть соединение: {exc}",
        ))
        return

    report.add(CheckStep(
        key="imap", title="IMAP: соединение", status=OK,
        detail="Сервер ответил приветствием",
    ))
    try:
        conn.logout()
    except Exception:  # noqa: BLE001
        pass

    if not mailbox:
        report.add(CheckStep(
            key="imap_login", title="IMAP: вход", status=SKIP,
            detail="Не проверялся — укажите адрес и пароль ящика",
        ))
        return

    if not password:
        report.add(CheckStep(
            key="imap_login", title="IMAP: вход", status=FAIL,
            detail=f"Нет пароля для {mailbox}",
            hint="Введите пароль ящика или заведите ящик в разделе "
                 "«Корпоративные ящики» — тогда пароль сохранится.",
        ))
        return

    try:
        with ImapClient.from_settings().login(mailbox, password) as imap:
            report.add(CheckStep(
                key="imap_login", title="IMAP: вход", status=OK, detail=f"{mailbox} — успешно",
            ))

            folders = imap.list_folders()
            missing = [f for f in cfg.sync_folders if f not in folders]
            counts = {}
            for folder in (f for f in cfg.sync_folders if f in folders):
                state = imap.select(folder)
                counts[folder] = {
                    "messages": len(imap.search_uids()),
                    "uidvalidity": state.get("uidvalidity"),
                }
            report.add(CheckStep(
                key="folders", title="Папки синхронизации",
                status=FAIL if missing else OK,
                detail=(f"Не найдены на сервере: {', '.join(missing)}" if missing
                        else f"Найдены: {', '.join(cfg.sync_folders)}"),
                hint=("Имена папок регистрозависимы и у разных серверов разные "
                      "(«Sent» / «Sent Items» / «Отправленные»). Возьмите точные "
                      "имена из списка и впишите их в «Папки синхронизации»."
                      if missing else ""),
                data={"available": folders, "expected": list(cfg.sync_folders), "counts": counts},
            ))
    except ImapError as exc:
        report.add(CheckStep(
            key="imap_login", title="IMAP: вход", status=FAIL,
            detail=f"Вход не выполнен: {exc}",
            hint="Проверьте адрес и пароль на самом почтовом сервере. "
                 "Некоторые серверы требуют отдельный пароль приложения для IMAP.",
        ))


def _check_smtp(
    report: CheckReport, cfg, mailbox: str | None, password: str | None,
    send_to: str | None, timeout: int,
) -> None:
    host, port = cfg.effective_smtp_host(), cfg.smtp_port
    try:
        smtp = (smtplib.SMTP_SSL(host, port, timeout=timeout) if cfg.smtp_ssl
                else smtplib.SMTP(host, port, timeout=timeout))
    except Exception as exc:  # noqa: BLE001
        report.add(CheckStep(
            key="smtp", title="SMTP: соединение", status=FAIL,
            detail=f"Не удалось открыть соединение: {exc}",
        ))
        return

    try:
        with smtp:
            smtp.ehlo()
            report.add(CheckStep(
                key="smtp", title="SMTP: соединение", status=OK,
                detail=f"{host}:{port} — сервер ответил",
            ))

            if not cfg.smtp_ssl and cfg.smtp_starttls:
                try:
                    smtp.starttls()
                    smtp.ehlo()
                    report.add(CheckStep(
                        key="smtp_tls", title="SMTP: STARTTLS", status=OK, detail="Установлен",
                    ))
                except Exception as exc:  # noqa: BLE001
                    report.add(CheckStep(
                        key="smtp_tls", title="SMTP: STARTTLS", status=FAIL,
                        detail=f"Не удался: {exc}",
                        hint="Через SSH-туннель STARTTLS обычно не нужен — снимите галочку.",
                    ))
                    return

            if not mailbox or not password:
                report.add(CheckStep(
                    key="smtp_login", title="SMTP: вход", status=SKIP,
                    detail="Не проверялся — нужны адрес и пароль ящика",
                ))
                return

            try:
                smtp.login(mailbox, password)
            except smtplib.SMTPException as exc:
                report.add(CheckStep(
                    key="smtp_login", title="SMTP: вход", status=FAIL,
                    detail=f"Вход не выполнен: {exc}",
                    hint="Учётка для отправки может отличаться от IMAP-овой.",
                ))
                return
            report.add(CheckStep(
                key="smtp_login", title="SMTP: вход", status=OK, detail=f"{mailbox} — успешно",
            ))

            if not send_to:
                report.add(CheckStep(
                    key="probe", title="Тестовое письмо", status=SKIP,
                    detail="Не отправлялось — укажите адрес получателя",
                ))
                return
            _send_probe(report, smtp, mailbox, send_to)
    except Exception as exc:  # noqa: BLE001
        report.add(CheckStep(key="smtp", title="SMTP", status=FAIL, detail=str(exc)))


def _send_probe(report: CheckReport, smtp, sender: str, recipient: str) -> None:
    from email.message import EmailMessage

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = "HTQWeb: проверка подключения корпоративной почты"
    message.set_content(
        "Это тестовое письмо отправлено проверкой подключения HTQWeb.\n"
        "Если вы его получили — отправка через корпоративный SMTP работает."
    )
    try:
        smtp.send_message(message)
    except Exception as exc:  # noqa: BLE001
        report.add(CheckStep(
            key="probe", title="Тестовое письмо", status=FAIL, detail=f"Не отправлено: {exc}",
        ))
        return
    report.add(CheckStep(
        key="probe", title="Тестовое письмо", status=OK, detail=f"Отправлено на {recipient}",
    ))
