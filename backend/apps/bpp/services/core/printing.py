"""Печать документов модуля в PDF (ТЗ §19/§21, мастер-план D-32; A2.2, задача 6).

HTML → PDF — WeasyPrint (с 53.0 не тянет GTK/cairo, только Pango+HarfBuzz
через cffi/dlopen — см. ``backend/requirements.txt``, ``backend/Dockerfile``).
Импорт ``weasyprint`` — ВНУТРИ функции, а не на уровне модуля: на
Windows-хосте без системных библиотек Pango он падает ``OSError`` уже при
импорте, и падать должна только печать, а не весь процесс Django. Шаблон —
``apps/bpp/templates/bpp/print/base.html`` (подхватывается ``APP_DIRS=True``,
см. ``htqweb/settings/base.py``); документы модуля наследуют его и
переопределяют блок ``body``.
"""

from __future__ import annotations

from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils.http import content_disposition_header

BASE_TEMPLATE = "bpp/print/base.html"


def render_html(template: str, context: dict) -> str:
    return render_to_string(template, context)


def render_pdf(template: str, context: dict) -> bytes:
    from weasyprint import HTML

    return HTML(string=render_html(template, context)).write_pdf()


def pdf_response(template: str, context: dict, *, filename: str) -> HttpResponse:
    """``inline``, а не ``attachment``: PDF открывается в браузере — печать
    документа, а не «скачать файл». Имя — ``filename*`` (RFC 6266), если в
    нём кириллица: заголовок HTTP — latin-1."""
    response = HttpResponse(render_pdf(template, context), content_type="application/pdf")
    response["Content-Disposition"] = content_disposition_header(False, filename)
    return response
