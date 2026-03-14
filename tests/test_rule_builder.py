from __future__ import annotations

import re

from app.models import AppSettings, MediaType, QualityProfile, Rule
from app.services.rule_builder import (
    RuleBuilder,
    build_title_regex_fragment,
    extract_imdb_id_from_category,
    infer_media_type_from_category,
    parse_additional_include_groups,
)


def build_rule(**overrides) -> Rule:
    rule = Rule(
        rule_name="3 Body Problem",
        content_name="3 Body Problem",
        normalized_title="3 Body Problem",
        imdb_id="tt13016388",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.UHD_2160P_HDR,
        release_year="",
        include_release_year=False,
        additional_includes="",
        quality_include_tokens=[],
        quality_exclude_tokens=[],
        use_regex=True,
        feed_urls=["http://feed.example"],
        assigned_category="",
        save_path="",
    )
    for key, value in overrides.items():
        setattr(rule, key, value)
    return rule


def test_build_generated_pattern_for_2160p_hdr() -> None:
    builder = RuleBuilder(settings=None)
    pattern = builder.build_generated_pattern(
        build_rule(
            quality_include_tokens=["ultra_hd", "uhd", "4k", "2160p", "hdr"],
            quality_exclude_tokens=["1080p", "720p", "480p", "sd"],
        )
    )
    assert "2160p" in pattern
    assert "hdr" in pattern.lower()
    assert "1080p" in pattern


def test_render_category_uses_defaults() -> None:
    settings = AppSettings()
    builder = RuleBuilder(settings=settings)
    category = builder.render_category(build_rule())
    assert category == "Series/3 Body Problem [imdbid-tt13016388]"


def test_category_helpers_extract_metadata() -> None:
    category = "Movies/Dune Part Two [imdbid-tt15239678]"
    assert infer_media_type_from_category(category) == MediaType.MOVIE
    assert extract_imdb_id_from_category(category) == "tt15239678"


def test_category_helpers_keep_non_standard_category_as_other() -> None:
    category = "Audiobooks/Victor Pelevin"
    assert infer_media_type_from_category(category) == MediaType.AUDIOBOOK
    assert extract_imdb_id_from_category(category) is None


def test_category_helpers_detect_music() -> None:
    category = "Music/Pink Floyd"
    assert infer_media_type_from_category(category) == MediaType.MUSIC


def test_category_helpers_detect_root_music_category() -> None:
    category = "Music"
    assert infer_media_type_from_category(category) == MediaType.MUSIC


def test_render_category_for_audiobook_uses_audiobooks_prefix() -> None:
    builder = RuleBuilder(settings=AppSettings())
    category = builder.render_category(
        build_rule(
            media_type=MediaType.AUDIOBOOK,
            assigned_category="",
            imdb_id=None,
            normalized_title="Victor Pelevin",
            content_name="Victor Pelevin",
        )
    )
    assert category == "Audiobooks/Victor Pelevin"


def test_build_generated_pattern_for_plain_regex() -> None:
    builder = RuleBuilder(settings=None)
    pattern = builder.build_generated_pattern(
        build_rule(
            quality_profile=QualityProfile.PLAIN,
            use_regex=True,
            normalized_title="A Man on the Inside",
            content_name="A Man on the Inside",
        )
    )
    assert pattern == r"(?i)(?=.*a[\s._-]*man[\s._-]*on[\s._-]*the[\s._-]*inside)"


def test_build_generated_pattern_uses_custom_quality_year_and_keywords() -> None:
    builder = RuleBuilder(settings=None)
    pattern = builder.build_generated_pattern(
        build_rule(
            quality_profile=QualityProfile.CUSTOM,
            use_regex=False,
            normalized_title="Anaconda",
            content_name="Anaconda",
            release_year="2024",
            include_release_year=True,
            additional_includes="Director's Cut, remux",
            quality_include_tokens=["ultra_hd", "uhd", "4k", "2160p", "hdr"],
            quality_exclude_tokens=["1080p", "720p", "480p", "sd"],
        )
    )
    assert pattern.startswith("(?i)")
    assert "(?=.*anaconda)" in pattern
    assert "(?=.*2024)" in pattern
    assert r"(?=.*director[\s._-]*s[\s._-]*cut)" in pattern
    assert "(?=.*remux)" in pattern
    assert "(?=.*(?:ultra[\\s._-]*hd|uhd|4k|2160p))" in pattern
    assert "(?=.*(?:hdr10\\+?|hdr))" in pattern
    assert pattern.endswith(r"(?!.*(?:1080p|720p|480p|sd))")


def test_parse_additional_include_groups_supports_pipe_alternatives() -> None:
    groups = parse_additional_include_groups("aaa, bbb|ccc, ddd|eee")
    assert groups == [["aaa"], ["bbb", "ccc"], ["ddd", "eee"]]


def test_build_generated_pattern_supports_pipe_alternatives_in_extra_includes() -> None:
    builder = RuleBuilder(settings=None)
    pattern = builder.build_generated_pattern(
        build_rule(
            quality_profile=QualityProfile.PLAIN,
            use_regex=False,
            normalized_title="Anaconda",
            content_name="Anaconda",
            additional_includes="aaa, bbb|ccc, ddd",
        )
    )
    assert "(?=.*anaconda)" in pattern
    assert "(?=.*aaa)" in pattern
    assert "(?=.*(?:bbb|ccc))" in pattern
    assert "(?=.*ddd)" in pattern


def test_build_qb_rule_enables_regex_when_generated_conditions_are_present() -> None:
    builder = RuleBuilder(settings=None)
    qb_rule = builder.build_qb_rule(
        build_rule(
            quality_profile=QualityProfile.PLAIN,
            use_regex=False,
            normalized_title="Anaconda",
            content_name="Anaconda",
            additional_includes="remux",
        )
    )
    assert qb_rule["useRegex"] is True
    assert qb_rule["mustContain"] == r"(?i)(?=.*anaconda)(?=.*remux)"


def test_build_generated_pattern_appends_manual_must_contain_fragments() -> None:
    builder = RuleBuilder(settings=None)
    pattern = builder.build_generated_pattern(
        build_rule(
            quality_profile=QualityProfile.PLAIN,
            use_regex=False,
            normalized_title="Anaconda",
            content_name="Anaconda",
            must_contain_override="Proper\nx265|hevc",
        )
    )
    assert pattern.startswith("(?i)")
    assert "(?=.*anaconda)" in pattern
    assert "(?=.*proper)" in pattern
    assert "(?=.*(?:x265|hevc))" in pattern


def test_build_generated_pattern_preserves_legacy_full_override() -> None:
    builder = RuleBuilder(settings=None)
    pattern = builder.build_generated_pattern(
        build_rule(
            quality_profile=QualityProfile.PLAIN,
            use_regex=False,
            normalized_title="Dune Part Two",
            content_name="Dune Part Two",
            must_contain_override=r"(?i)(?=.*dune)(?!.*cam)",
        )
    )
    assert pattern == r"(?i)(?=.*dune)(?!.*cam)"


def test_build_generated_pattern_allows_empty_quality_selection() -> None:
    builder = RuleBuilder(settings=AppSettings())
    pattern = builder.build_generated_pattern(
        build_rule(
            normalized_title="Anaconda",
            content_name="Anaconda",
            quality_profile=QualityProfile.UHD_2160P_HDR,
            quality_include_tokens=[],
            quality_exclude_tokens=[],
            use_regex=False,
        )
    )
    assert pattern == "Anaconda"


def test_build_generated_pattern_supports_start_season_episode_floor() -> None:
    builder = RuleBuilder(settings=None)
    pattern = builder.build_generated_pattern(
        build_rule(
            quality_profile=QualityProfile.PLAIN,
            use_regex=True,
            normalized_title="Shrinking",
            content_name="Shrinking",
            start_season=3,
            start_episode=7,
        )
    )
    compiled = re.compile(pattern)

    assert compiled.search("Shrinking S03E07 1080p")
    assert compiled.search("Shrinking S3E7 1080p")
    assert compiled.search("Shrinking S03E01-07 1080p")
    assert compiled.search("Shrinking S03E1-7 1080p")
    assert compiled.search("Shrinking S03 1080p season pack")
    assert compiled.search("Shrinking Season 03 1080p season pack")
    assert compiled.search("Shrinking Season: 3 1080p season pack")
    assert compiled.search("Shrinking S04E01 1080p")
    assert compiled.search("Shrinking S04 Complete 1080p season pack")
    assert not compiled.search("Shrinking S03E06 1080p")
    assert not compiled.search("Shrinking S03E01-06 1080p")
    assert not compiled.search("Shrinking S02E99 1080p")


def test_build_generated_pattern_requires_all_selected_quality_groups() -> None:
    builder = RuleBuilder(settings=None)
    pattern = builder.build_generated_pattern(
        build_rule(
            quality_profile=QualityProfile.CUSTOM,
            use_regex=True,
            normalized_title="3 Body Problem",
            content_name="3 Body Problem",
            quality_include_tokens=["4k", "hdr"],
        )
    )
    compiled = re.compile(pattern)

    assert compiled.search("3 Body Problem S01 4K HDR WEBDL")
    assert not compiled.search("3 Body Problem S01 4K SDR WEBDL")


def test_build_title_regex_fragment_normalizes_case_and_separators() -> None:
    assert build_title_regex_fragment("3 Body Problem") == r"3[\s._-]*body[\s._-]*problem"
