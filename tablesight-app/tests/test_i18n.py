from tablesight import i18n


def test_all_catalogs_have_all_keys_and_placeholders_match():
    en = i18n.load("en")
    for lang in ("ar", "es", "de", "fr"):
        cat = i18n.load(lang)
        assert set(cat) == set(en), lang
        for k, v in en.items():
            for ph in ("{table}", "{minutes}", "{n}", "{tables}"):
                assert (ph in v) == (ph in cat[k]), (lang, k, ph)


def test_rtl_and_fallback_and_tz():
    assert i18n.direction("ar") == "rtl" and i18n.direction("ar-EG") == "rtl" and i18n.direction("en") == "ltr"
    assert i18n.t("xx", "state.empty") == "Empty"
    assert i18n.local_time(0, "Asia/Dubai").hour == 4
