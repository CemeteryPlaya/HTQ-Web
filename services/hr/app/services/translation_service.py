"""Translation helpers for HR display payloads."""

from __future__ import annotations

import copy
import html
from typing import Literal

import httpx
import structlog

from app.core.settings import settings

logger = structlog.get_logger()

OrgLanguage = Literal["ru", "en"]

TRANSLATABLE_META_FIELDS = (
    "department_name",
    "heads_department_name",
    "manager_position_title",
)


def _collect_tree_texts(tree: dict) -> tuple[list[str], list[tuple[str, int, str | None]]]:
    texts: list[str] = []
    refs: list[tuple[str, int, str | None]] = []

    for idx, node in enumerate(tree.get("nodes") or []):
        label = node.get("label")
        if isinstance(label, str) and label.strip():
            refs.append(("node", idx, None))
            texts.append(label)

        meta = node.get("meta")
        if not isinstance(meta, dict):
            continue
        for key in TRANSLATABLE_META_FIELDS:
            value = meta.get(key)
            if isinstance(value, str) and value.strip():
                refs.append(("meta", idx, key))
                texts.append(value)

    return texts, refs


def _apply_tree_texts(
    tree: dict,
    refs: list[tuple[str, int, str | None]],
    translated: list[str],
) -> dict:
    result = copy.deepcopy(tree)
    nodes = result.get("nodes") or []
    for ref, value in zip(refs, translated):
        kind, idx, key = ref
        if idx >= len(nodes):
            continue
        if kind == "node":
            nodes[idx]["label"] = value
            continue
        meta = nodes[idx].get("meta")
        if isinstance(meta, dict) and key:
            meta[key] = value
    return result


async def _translate_with_google(texts: list[str], target_lang: OrgLanguage) -> list[str] | None:
    api_key = settings.google_translate_api_key.strip()
    if not api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                settings.google_translate_api_base,
                params={"key": api_key},
                json={
                    "q": texts,
                    "source": "ru",
                    "target": target_lang,
                    "format": "text",
                },
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("org_tree_google_translation_failed", target_lang=target_lang, error=str(exc))
        return None

    rows = response.json().get("data", {}).get("translations", [])
    translated = [
        html.unescape(row.get("translatedText", ""))
        for row in rows
        if isinstance(row, dict)
    ]
    return translated if len(translated) == len(texts) else None


def _parse_libre_translated_text(payload: dict, expected_count: int) -> list[str] | None:
    value = payload.get("translatedText")
    if isinstance(value, list):
        translated = [html.unescape(str(item)) for item in value]
        return translated if len(translated) == expected_count else None
    if isinstance(value, str) and expected_count == 1:
        return [html.unescape(value)]
    return None


async def _translate_with_libretranslate(texts: list[str], target_lang: OrgLanguage) -> list[str] | None:
    base_url = settings.libre_translate_api_url.strip().rstrip("/")
    if not base_url:
        return None

    api_key = settings.libre_translate_api_key.strip()

    def payload(q: str | list[str]) -> dict:
        body = {
            "q": q,
            "source": "ru",
            "target": target_lang,
            "format": "text",
        }
        if api_key:
            body["api_key"] = api_key
        return body

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                batch_response = await client.post(f"{base_url}/translate", json=payload(texts))
                batch_response.raise_for_status()
                batch = _parse_libre_translated_text(batch_response.json(), len(texts))
                if batch is not None:
                    return batch
            except (httpx.HTTPError, ValueError) as exc:
                logger.info("org_tree_libretranslate_batch_failed", target_lang=target_lang, error=str(exc))

            translated: list[str] = []
            for text in texts:
                response = await client.post(f"{base_url}/translate", json=payload(text))
                response.raise_for_status()
                row = _parse_libre_translated_text(response.json(), 1)
                if row is None:
                    return None
                translated.extend(row)
            return translated
    except httpx.HTTPError as exc:
        logger.warning("org_tree_libretranslate_failed", target_lang=target_lang, error=str(exc))
        return None


async def build_translated_org_tree(tree: dict, target_lang: OrgLanguage) -> dict | None:
    """Return translated copy of an org tree, or None when unavailable."""
    if target_lang == "ru":
        return copy.deepcopy(tree)
    if target_lang != "en":
        return None

    texts, refs = _collect_tree_texts(tree)
    if not texts:
        return copy.deepcopy(tree)

    translated = (
        await _translate_with_google(texts, target_lang)
        or await _translate_with_libretranslate(texts, target_lang)
    )
    if translated is None:
        return None

    if len(translated) != len(texts):
        logger.warning(
            "org_tree_translation_incomplete",
            expected=len(texts),
            received=len(translated),
        )
        return None

    return _apply_tree_texts(tree, refs, translated)
