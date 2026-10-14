import pytest

from radar.filter.keywords import parse_keywords

SAMPLE = """
# comment
[GLOBAL_FILTER]
/\\bhiring\\b/
for sale

[Checkout]
checkout extensibility
/checkout\\.liquid/
thank you page => Trang cảm ơn
!job

[Hiệu năng]
/\\blighthouse\\b/
+shopify
@5

speed
pagespeed => PageSpeed
"""


def test_global_filter_blocks_everywhere():
    cfg = parse_keywords(SAMPLE)
    assert cfg.match("We are hiring a Shopify checkout extensibility dev") == []
    assert cfg.is_blocked("Theme FOR SALE cheap")


def test_groups_and_aliases():
    cfg = parse_keywords(SAMPLE)
    assert [g.name for g in cfg.groups] == ["Checkout", "Hiệu năng", "speed / PageSpeed"]
    assert cfg.match("Migrating off checkout.liquid this year") == ["Checkout"]
    assert cfg.match("New THANK YOU PAGE rules") == ["Checkout"]


def test_exclude_only_affects_its_group():
    cfg = parse_keywords(SAMPLE)
    assert cfg.match("checkout extensibility job board") == []
    assert cfg.match("checkout extensibility job board and speed") == ["speed / PageSpeed"]


def test_required_words():
    cfg = parse_keywords(SAMPLE)
    assert cfg.match("Lighthouse score dropped") == []
    assert cfg.match("Shopify Lighthouse score dropped") == ["Hiệu năng"]
    assert cfg.limits() == {"Hiệu năng": 5}


def test_group_alias_without_word_groups_marker_ends_global_filter():
    cfg = parse_keywords("[GLOBAL_FILTER]\nspam\n[Theme]\ntheme store\n")
    assert len(cfg.global_filter) == 1
    assert cfg.match("theme store news") == ["Theme"]


def test_empty_file_means_no_filter():
    cfg = parse_keywords("# nothing\n")
    assert cfg.empty
    assert cfg.match("anything") == []


def test_invalid_regex_has_readable_error():
    with pytest.raises(ValueError, match="Regex không hợp lệ"):
        parse_keywords("[G]\n/(unclosed/\n")


def test_repo_keywords_file_parses():
    from pathlib import Path

    cfg = parse_keywords((Path(__file__).parent.parent / "config" / "keywords.txt").read_text(encoding="utf-8"))
    assert len(cfg.groups) >= 5
    assert "Nhu cầu merchant" in cfg.match("Looking for a Shopify theme with quick add")
    assert cfg.match("Shopify is hiring theme developers") == []
