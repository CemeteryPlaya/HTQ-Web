"""Transliterate + slugify a display name into an ascii slug (ru/kz aware)."""

_CYRILLIC_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "қ": "q", "ғ": "g", "ұ": "u", "ү": "u", "һ": "h", "ң": "n", "ө": "o",
    "ә": "a", "і": "i",
}


def slugify(name: str) -> str:
    out: list[str] = []
    for ch in name.strip().lower():
        if ch in _CYRILLIC_MAP:
            out.append(_CYRILLIC_MAP[ch])
        elif ch.isalnum() and ch.isascii():
            out.append(ch)
        elif ch in (" ", "-", "_"):
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "form"
