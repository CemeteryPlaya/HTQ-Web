import os
import json
import re

frontend_dir = r"d:\site\frontend"
src_dir = os.path.join(frontend_dir, "src")
locales_dir = os.path.join(frontend_dir, "public", "locales")

def flatten_dict(d, parent_key='', sep='.'):
    items = []
    for k, v in d.items():
        new_key = parent_key + sep + k if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)

def load_locale(lang):
    path = os.path.join(locales_dir, lang, "translation.json")
    with open(path, "r", encoding="utf-8") as f:
        return flatten_dict(json.load(f))

ru_keys = load_locale("ru")
en_keys = load_locale("en")

used_keys = set()
key_pattern = re.compile(r"t\(\s*['\"`]([^'\"`]+)['\"`]")
i18n_key_pattern = re.compile(r"i18nKey\s*=\s*['\"`]([^'\"`]+)['\"`]")

for root, _, files in os.walk(src_dir):
    for file in files:
        if file.endswith((".tsx", ".ts", ".jsx", ".js")):
            path = os.path.join(root, file)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                for match in key_pattern.finditer(content):
                    used_keys.add(match.group(1).replace(':', '.'))
                for match in i18n_key_pattern.finditer(content):
                    used_keys.add(match.group(1).replace(':', '.'))

missing_ru = []
missing_en = []

for key in used_keys:
    if "${" in key or "{{" in key:
        continue
    if key not in ru_keys:
        missing_ru.append(key)
    if key not in en_keys:
        missing_en.append(key)

print(f"Missing in RU ({len(missing_ru)}):")
for key in missing_ru:
    print(key)

print(f"\nMissing in EN ({len(missing_en)}):")
for key in missing_en:
    print(key)
