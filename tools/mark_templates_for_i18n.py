#!/usr/bin/env python3
"""Mark literal interface copy in Django templates for translation."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = ROOT / "templates"
DJANGO_OPENERS = {"{{": "}}", "{%": "%}", "{#": "#}"}
TRANSLATABLE_ATTRIBUTES = ("aria-label", "placeholder", "title")


def quote(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def mark_text(value):
    if not re.search(r"[A-Za-z]", value):
        return value
    leading = value[: len(value) - len(value.lstrip())]
    trailing = value[len(value.rstrip()) :]
    message = value.strip()
    if not message:
        return value
    return f"{leading}{{% translate {quote(message)} %}}{trailing}"


def mark_attributes(tag):
    for attribute in TRANSLATABLE_ATTRIBUTES:
        pattern = re.compile(rf'({re.escape(attribute)}\s*=\s*)"([^"{{}}]*[A-Za-z][^"{{}}]*)"')
        tag = pattern.sub(
            lambda match: f'{match.group(1)}"{{% translate {quote(match.group(2))} %}}"',
            tag,
        )
    return tag


def tokenize(source):
    tokens = []
    start = 0
    index = 0
    while index < len(source):
        opener = source[index : index + 2]
        if opener in DJANGO_OPENERS:
            if start < index:
                tokens.append(("plain", source[start:index]))
            closer = DJANGO_OPENERS[opener]
            end = source.find(closer, index + 2)
            if end < 0:
                raise ValueError(f"Unclosed Django token at character {index}")
            end += 2
            tokens.append(("django", source[index:end]))
            index = end
            start = end
            continue
        if source[index] == "<":
            if start < index:
                tokens.append(("plain", source[start:index]))
            end = index + 1
            quote_char = None
            while end < len(source):
                nested_opener = source[end : end + 2]
                if nested_opener in DJANGO_OPENERS:
                    nested_end = source.find(DJANGO_OPENERS[nested_opener], end + 2)
                    if nested_end < 0:
                        raise ValueError(f"Unclosed Django token at character {end}")
                    end = nested_end + 2
                    continue
                char = source[end]
                if quote_char:
                    if char == quote_char:
                        quote_char = None
                elif char in "\"'":
                    quote_char = char
                elif char == ">":
                    end += 1
                    break
                end += 1
            tokens.append(("html", source[index:end]))
            index = end
            start = end
            continue
        index += 1
    if start < len(source):
        tokens.append(("plain", source[start:]))
    return tokens


def mark_filter_literals(source):
    pattern = re.compile(r"\|(default|default_if_none|yesno):(['\"])(.*?)(?<!\\)\2")
    return pattern.sub(
        lambda match: f'|{match.group(1)}:_({quote(match.group(3))})'
        if re.search(r"[A-Za-z]", match.group(3))
        else match.group(0),
        source,
    )


def add_i18n_load(source):
    if re.search(r"{%\s*load\s+[^%]*\bi18n\b", source):
        return source
    extends = re.match(r"(\s*{%\s*extends\s+.*?%})", source, flags=re.DOTALL)
    if extends:
        return source[: extends.end()] + "{% load i18n %}" + source[extends.end() :]
    return "{% load i18n %}" + source


def transform(source):
    scripts = []

    def preserve_script(match):
        scripts.append(match.group(0))
        return f"\ue000{len(scripts) - 1}\ue001"

    source = re.sub(r"<script\b.*?</script>", preserve_script, source, flags=re.DOTALL | re.IGNORECASE)
    rendered = []
    for kind, value in tokenize(source):
        if kind == "plain":
            rendered.append(mark_text(value))
        elif kind == "html":
            rendered.append(mark_attributes(value))
        else:
            rendered.append(value)
    output = add_i18n_load(mark_filter_literals("".join(rendered)))
    for index, script in enumerate(scripts):
        output = output.replace(f"\ue000{index}\ue001", script)
    return output


def main():
    changed = 0
    for path in sorted(TEMPLATE_ROOT.rglob("*.html")):
        source = path.read_text(encoding="utf-8")
        updated = transform(source)
        if updated != source:
            path.write_text(updated, encoding="utf-8")
            changed += 1
    print(f"Marked {changed} templates for translation.")


if __name__ == "__main__":
    main()
