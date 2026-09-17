"""Language resolution and catalogue translations (ES / EN)."""

import pytest

from modules.core.domain.i18n import (
    TranslatedText,
    UnsupportedLanguage,
    normalise_language,
    parse_accept_language,
    resolve_language,
)


class TestNormalisation:
    @pytest.mark.parametrize(("tag", "expected"), [
        ("es", "es"), ("ES", "es"), ("es-PE", "es"), ("es_PE", "es"),
        ("en-US", "en"), (" en ", "en"),
    ])
    def test_reduces_a_locale_to_its_language(self, tag, expected):
        assert normalise_language(tag) == expected

    @pytest.mark.parametrize("tag", ["pt", "fr-FR", "", None, "xx"])
    def test_unknown_languages_answer_nothing_not_the_default(self, tag):
        # Answering "es" here would swallow the company's configured language.
        assert normalise_language(tag) is None


class TestResolutionChain:
    def test_request_wins_over_everything(self):
        assert resolve_language(requested="en", user_preference="es", company_default="es") == "en"

    def test_falls_back_to_the_user_preference(self):
        assert resolve_language(requested=None, user_preference="en", company_default="es") == "en"

    def test_then_to_the_company_default(self):
        assert resolve_language(company_default="en") == "en"

    def test_and_finally_to_spanish(self):
        assert resolve_language() == "es"

    def test_an_unsupported_request_does_not_break_the_chain(self):
        assert resolve_language(requested="pt", user_preference="en") == "en"


class TestAcceptLanguage:
    def test_reads_the_browser_header(self):
        assert parse_accept_language("es-PE,es;q=0.9,en;q=0.8") == "es"

    def test_skips_languages_the_system_does_not_have(self):
        assert parse_accept_language("pt-BR,pt;q=0.9,en-US;q=0.7") == "en"

    def test_honours_quality_over_order(self):
        assert parse_accept_language("es;q=0.3,en;q=0.9") == "en"

    def test_no_supported_language_answers_nothing(self):
        assert parse_accept_language("pt-BR,fr;q=0.8") is None

    def test_an_empty_header_answers_nothing(self):
        assert parse_accept_language(None) is None


class TestTranslatedText:
    alarm = TranslatedText({"es": "Alarma", "en": "Alarm"})

    def test_returns_the_requested_language(self):
        assert self.alarm.get("en") == "Alarm"
        assert self.alarm.get("es") == "Alarma"

    def test_falls_back_to_the_default_when_a_translation_is_missing(self):
        partial = TranslatedText({"es": "Fuera de servicio"})
        assert partial.get("en") == "Fuera de servicio"

    def test_never_returns_an_empty_label(self):
        # A Spanish label shown to an English user is bad; an empty cell in an
        # ERP grid is worse.
        odd = TranslatedText({"pt": "Parada"})
        assert odd.get("en") == "Parada"

    def test_blank_strings_do_not_count_as_translations(self):
        partial = TranslatedText({"es": "Alarma", "en": "   "})
        assert partial.get("en") == "Alarma"
        assert partial.missing() == ("en",)

    def test_reports_what_is_still_untranslated(self):
        assert self.alarm.missing() == ()
        assert TranslatedText({"en": "Alarm"}).missing() == ("es",)

    def test_adding_a_translation_does_not_mutate_the_original(self):
        updated = self.alarm.with_translation("en", "Warning")
        assert updated.get("en") == "Warning"
        assert self.alarm.get("en") == "Alarm"

    def test_refuses_a_language_the_system_does_not_support(self):
        with pytest.raises(UnsupportedLanguage):
            self.alarm.with_translation("fr", "Alarme")

    def test_accepts_a_plain_string_so_migration_can_be_gradual(self):
        assert TranslatedText.of("Alarma").get("es") == "Alarma"
        assert TranslatedText.of({"en": "Alarm"}).get("en") == "Alarm"
