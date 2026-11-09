# Arabic localization

Oman Skylight supports English (`en`) and Arabic (`ar`) on the same URLs. The
language control is available on public listings, authentication pages, the
staff application, and the resident portal. Django stores the selection in a
secure, HTTP-only language cookie for one year. For signed-in users, the same
selection is saved to `UserProfile.preferred_language` and becomes the fallback
when the cookie is absent.

Arabic pages render with `lang="ar"` and `dir="rtl"`. RTL rules mirror the
sidebar, navigation affordances, tables, form alignment, status layouts, and
mobile drawer while keeping email addresses, telephone numbers, URLs, codes,
and identifiers left-to-right.

The catalog source is `locale/ar/translations.json`; standard gettext artifacts
are generated at `locale/ar/LC_MESSAGES/django.po` and `django.mo`. After adding
new interface copy, mark it with Django's translation helpers, update the JSON
catalog, and rebuild it with:

```bash
DJANGO_ENV=test .venv/bin/python tools/build_ar_locale.py
```

The test suite checks that every marked template/Python message and generated
form/model label has a non-empty Arabic translation. `tools/arabic_smoke.mjs`
checks the language switch, RTL public page, Arabic login and dashboard, and a
mobile viewport.
