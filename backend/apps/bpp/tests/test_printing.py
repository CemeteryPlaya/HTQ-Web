"""Печать документов модуля в PDF (``services/core/printing.py``, задача 6).

HTML не зависит от WeasyPrint и проверяется всегда. PDF требует системных
библиотек Pango — на Windows-хосте разработчика их нет, и импорт
``weasyprint`` падает ``OSError`` (печать импортирует его лениво, поэтому
падает только она, а не Django). Тогда тест PDF пропускается с явной
причиной — но только вне CI: в GitHub Actions (переменная ``CI``) и в Docker
библиотеки поставлены явно (``backend/Dockerfile``,
``.github/workflows/backend-full.yml``), и молчаливый пропуск там спрятал бы
сломанную печать.
"""

from __future__ import annotations

import os
import re
import zlib

import pytest

from apps.bpp.services.core import printing

CONTEXT = {
    "document_title": "Заявка на закупку",
    "number": "ЗК-000123",
    "status_label": "На согласовании",
    "author_name": "Иванов И.И.",
    "created_at": "27.09.2026",
    "table": {
        "columns": ["№", "Наименование", "Сумма"],
        "rows": [["1", "Металлопрокат", "1 250 000,00 KZT"]],
        "total": ["", "Итого", "1 250 000,00 KZT"],
    },
    "signoff_stages": [
        {"title": "Согласование ТД", "actor_name": "Петров П.П.",
         "decision": "Согласовано", "comment": "", "decided_at": "27.09.2026 10:00"},
    ],
}


def test_render_html_has_number_status_author_table_and_signoff_sheet():
    html = printing.render_html(printing.BASE_TEMPLATE, CONTEXT)
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "ЗК-000123" in html
    assert "На согласовании" in html
    assert "Иванов И.И." in html
    assert "27.09.2026" in html
    assert "Металлопрокат" in html and "Итого" in html
    assert "Лист согласования" in html
    assert "Петров П.П." in html
    assert "Согласовано" in html


def test_render_html_without_stages_omits_the_signoff_section():
    """Заодно сторож комментария шаблона: многострочный ``{# #}`` Django
    выводит текстом, и «Лист согласования» из него попал бы в документ."""
    html = printing.render_html(printing.BASE_TEMPLATE, {**CONTEXT, "signoff_stages": []})
    assert "Лист согласования" not in html
    assert "Контекст:" not in html


def test_render_html_escapes_document_data():
    html = printing.render_html(printing.BASE_TEMPLATE,
                                {**CONTEXT, "author_name": "<script>x</script>"})
    assert "<script>x</script>" not in html


def _weasyprint_missing() -> str | None:
    """``None`` — WeasyPrint работает; иначе — причина пропуска теста."""
    try:
        from weasyprint import HTML

        HTML(string="<p>проба</p>").write_pdf()
        return None
    except OSError as exc:
        if os.environ.get("CI"):
            raise  # в CI библиотеки обязаны быть — пропуск спрятал бы поломку
        return (f"WeasyPrint: нет системных библиотек Pango на этом хосте — PDF "
                f"проверяется в Docker/CI ({exc})")


def _with_inflated_streams(data: bytes) -> bytes:
    """PDF вместе с распакованными потоками FlateDecode. WeasyPrint кладёт
    словари шрифтов в сжатые потоки объектов (``/ObjStm``), и в сырых байтах
    ``/Identity-H`` не видно, хотя шрифт вложен."""
    chunks = [data]
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        try:
            chunks.append(zlib.decompressobj().decompress(match.group(1)))
        except zlib.error:
            continue  # поток не FlateDecode — в нём словарей нет
    return b"\n".join(chunks)


def test_with_inflated_streams_sees_dictionaries_inside_object_streams():
    packed = b"%PDF-1.7\n5 0 obj\n<</Type /ObjStm /Filter /FlateDecode>>\nstream\n" \
        + zlib.compress(b"<</Encoding /Identity-H>> <</FontFile2 7 0 R>>") \
        + b"\nendstream\nendobj\n%%EOF\n"
    assert b"/Identity-H" not in packed
    expanded = _with_inflated_streams(packed)
    assert b"/Identity-H" in expanded and b"/FontFile2" in expanded


def test_render_pdf_starts_with_signature_and_embeds_a_unicode_font():
    reason = _weasyprint_missing()
    if reason is not None:
        pytest.skip(reason)

    data = printing.render_pdf(printing.BASE_TEMPLATE, CONTEXT)

    assert data.startswith(b"%PDF-")
    assert data.rstrip().endswith(b"%%EOF")
    # Кириллица в PDF не лежит читаемыми байтами — текст на CID-шрифте
    # адресуется индексами глифов (Identity-H), а не литеральным Unicode.
    # Поэтому «кириллица встроена» проверяется тем, что для неё вообще есть
    # чем рендериться: PDF содержит вложенный Unicode-шрифт (CID + FontFile2),
    # а не только латинский base14 — без этого кириллица ушла бы «тофу»
    # (пустыми прямоугольниками) без единой ошибки. Словари шрифта WeasyPrint
    # кладёт в сжатые потоки объектов — ищем и в распакованных.
    expanded = _with_inflated_streams(data)
    assert b"/Identity-H" in expanded
    assert b"/FontFile2" in expanded


def test_pdf_response_is_inline_not_attachment():
    reason = _weasyprint_missing()
    if reason is not None:
        pytest.skip(reason)

    response = printing.pdf_response(printing.BASE_TEMPLATE, CONTEXT, filename="zk-123.pdf")

    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"] == 'inline; filename="zk-123.pdf"'
    assert response.content.startswith(b"%PDF-")
