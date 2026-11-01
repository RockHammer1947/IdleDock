"""Resource contracts: translations, format arguments, and UI coverage (no app launch)."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = sorted(path.stem for path in (ROOT/'macos/Resources').glob('*.lproj'))


def read_strings(language):
    result = {}
    for line in (ROOT/'macos/Resources'/f'{language}.lproj'/'Localizable.strings').read_text().splitlines():
        if not line.strip() or line.startswith('//'):
            continue
        key, value = line.split(' = ', 1)
        key, value = json.loads(key), json.loads(value.removesuffix(';'))
        if key in result:
            raise AssertionError(f'Duplicate localization key: {key}')
        result[key] = value
    return result


class LocalizationResourcesTests(unittest.TestCase):
    def test_catalogs_have_matching_keys_and_format_arguments(self):
        en = read_strings('en')
        placeholders = re.compile(r'%(?:\d+\$)?[0-9.]*[@df]')
        for language in LANGUAGES:
            translated = read_strings(language)
            self.assertEqual(set(en), set(translated), language)
            for key in en:
                with self.subTest(language=language, key=key):
                    self.assertTrue(en[key].strip() and translated[key].strip())
                    self.assertEqual(placeholders.findall(en[key]), placeholders.findall(translated[key]))
                    if language in ('en', 'es', 'fr', 'de', 'ru', 'pt-BR', 'it') and not key.startswith('language.'):
                        self.assertIsNone(re.search(r'[\u4e00-\u9fff]', translated[key]))

    def test_language_menu_uses_native_names_in_every_catalog(self):
        names = {key: value for key, value in read_strings('en').items()
                 if key.startswith('language.') and key not in ('language.menu', 'language.system')}
        for language in LANGUAGES:
            catalog = read_strings(language)
            for key, name in names.items():
                self.assertEqual(catalog[key], name, f'{language}: {key}')

    def test_all_literal_ui_keys_exist(self):
        catalog = read_strings('en')
        for path in (ROOT/'macos').glob('*.swift'):
            source = path.read_text()
            keys = re.findall(r'\bL\("([^"]+)"|\.localized\("([^"]+)"', source)
            for pair in keys:
                key = next(value for value in pair if value)
                self.assertIn(key, catalog, f'{path.name}: {key}')
        # Legacy wire strings belong in Localization.swift, never in views.
        for name in ('QueueWidget.swift', 'QueueSurface.swift'):
            self.assertIsNone(re.search(r'[\u4e00-\u9fff]', (ROOT/'macos'/name).read_text()), name)

    def test_known_backend_diagnostics_still_match_the_wire_contract(self):
        # These messages are exposed in protection UI. Catch backend wording drift.
        zh = read_strings('zh-Hans')
        safety = (ROOT/'h3queue/safety.py').read_text()
        for key in ('disk', 'memory', 'swap', 'runtime', 'telemetry', 'overheat', 'sensor'):
            self.assertIn(zh['backend.'+key], safety)
