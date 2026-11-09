#!/usr/bin/env python3
"""Build the Arabic gettext catalog from reviewed translation JSON."""

import ast
import json
import os
import re
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CATALOG = ROOT / "locale" / "ar" / "translations.json"
PO_PATH = ROOT / "locale" / "ar" / "LC_MESSAGES" / "django.po"
MO_PATH = ROOT / "locale" / "ar" / "LC_MESSAGES" / "django.mo"


def template_messages():
    messages = set()
    patterns = (
        r'{%\s*translate\s+("(?:\\.|[^"\\])*")\s*%}',
        r'_\(("(?:\\.|[^"\\])*")\)',
    )
    for path in (ROOT / "templates").rglob("*.html"):
        source = path.read_text(encoding="utf-8")
        for pattern in patterns:
            messages.update(ast.literal_eval(item) for item in re.findall(pattern, source))
    return messages


def python_messages():
    messages = set()
    for app in ("accounts", "billing", "integrations", "operations", "portal", "properties"):
        for path in (ROOT / app).rglob("*.py"):
            if ".venv" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "_"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    messages.add(node.args[0].value)
    return messages


def metadata_messages():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.apps import apps
    from django import forms
    from django.forms.utils import pretty_name
    from django.utils.translation import override

    from accounts import forms as account_forms
    from billing import forms as billing_forms
    from integrations import forms as integration_forms
    from operations import forms as operation_forms
    from portal import forms as portal_forms
    from portal import self_forms
    from properties import forms as property_forms

    messages = set()
    with override("en"):
        for model in apps.get_models():
            if model._meta.app_label not in {
                "accounts", "billing", "data_transfer", "integrations",
                "operations", "portal", "properties",
            }:
                continue
            messages.update((str(model._meta.verbose_name), str(model._meta.verbose_name_plural)))
            for field in model._meta.get_fields():
                if getattr(field, "verbose_name", None):
                    messages.add(str(field.verbose_name))
                if getattr(field, "help_text", None):
                    messages.add(str(field.help_text))
                for _, label in getattr(field, "choices", ()) or ():
                    if not isinstance(label, (list, tuple)):
                        messages.add(str(label))
        modules = (
            account_forms, billing_forms, integration_forms, operation_forms,
            portal_forms, self_forms, property_forms,
        )
        for module in modules:
            for candidate in vars(module).values():
                if not isinstance(candidate, type) or not issubclass(candidate, forms.BaseForm):
                    continue
                if candidate.__module__ != module.__name__:
                    continue
                for name, field in candidate.base_fields.items():
                    messages.add(str(field.label or pretty_name(name)))
                    if field.help_text:
                        messages.add(str(field.help_text))
                    if isinstance(field, forms.ChoiceField) and not isinstance(field, forms.ModelChoiceField):
                        messages.update(str(label) for _, label in field.choices)
    return {message for message in messages if message and re.search(r"[A-Za-z]", message)}


def collect_messages():
    return sorted(template_messages() | python_messages() | metadata_messages() | {"English", "Arabic"})


def po_quote(value):
    return json.dumps(value, ensure_ascii=False)


def write_po(translations):
    header = (
        "Project-Id-Version: Oman Skylight PMS\\n"
        "Language: ar\\n"
        "Content-Type: text/plain; charset=UTF-8\\n"
        "Content-Transfer-Encoding: 8bit\\n"
        "Plural-Forms: nplurals=6; plural=n==0 ? 0 : n==1 ? 1 : n==2 ? 2 : "
        "n%100>=3 && n%100<=10 ? 3 : n%100>=11 && n%100<=99 ? 4 : 5;\\n"
    )
    entries = [f'msgid ""\nmsgstr {po_quote(header)}\n']
    for message in sorted(translations):
        entries.append(
            f"msgid {po_quote(message)}\nmsgstr {po_quote(translations[message])}\n"
        )
    PO_PATH.parent.mkdir(parents=True, exist_ok=True)
    PO_PATH.write_text("\n".join(entries), encoding="utf-8")


def write_mo(translations):
    header = (
        "Project-Id-Version: Oman Skylight PMS\n"
        "Language: ar\n"
        "Content-Type: text/plain; charset=UTF-8\n"
        "Content-Transfer-Encoding: 8bit\n"
        "Plural-Forms: nplurals=6; plural=n==0 ? 0 : n==1 ? 1 : n==2 ? 2 : "
        "n%100>=3 && n%100<=10 ? 3 : n%100>=11 && n%100<=99 ? 4 : 5;\n"
    )
    catalog = {"": header, **translations}
    keys = sorted(catalog)
    ids = [key.encode("utf-8") for key in keys]
    strings = [catalog[key].encode("utf-8") for key in keys]
    count = len(keys)
    key_table_offset = 7 * 4
    value_table_offset = key_table_offset + count * 8
    data_offset = value_table_offset + count * 8
    id_blob = b"\x00".join(ids) + b"\x00"
    value_offset = data_offset + len(id_blob)
    key_entries = []
    cursor = data_offset
    for value in ids:
        key_entries.append((len(value), cursor))
        cursor += len(value) + 1
    value_entries = []
    cursor = value_offset
    for value in strings:
        value_entries.append((len(value), cursor))
        cursor += len(value) + 1
    output = [struct.pack("<7I", 0x950412DE, 0, count, key_table_offset, value_table_offset, 0, 0)]
    output.extend(struct.pack("<2I", *entry) for entry in key_entries)
    output.extend(struct.pack("<2I", *entry) for entry in value_entries)
    output.extend((id_blob, b"\x00".join(strings) + b"\x00"))
    MO_PATH.write_bytes(b"".join(output))


def main():
    messages = collect_messages()
    if os.environ.get("LIST_MESSAGES"):
        print(json.dumps(messages, ensure_ascii=False, indent=2))
        return
    translations = json.loads(CATALOG.read_text(encoding="utf-8"))
    missing = sorted(set(messages) - set(translations))
    stale = sorted(set(translations) - set(messages))
    if missing or stale:
        raise SystemExit(
            f"Catalog mismatch: {len(missing)} missing, {len(stale)} stale. "
            "Run with LIST_MESSAGES=1 to inspect current messages."
        )
    if any(not value.strip() for value in translations.values()):
        raise SystemExit("Arabic translations must not be blank.")
    write_po(translations)
    write_mo(translations)
    print(f"Built {len(translations)} Arabic translations.")


if __name__ == "__main__":
    main()
