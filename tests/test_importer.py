from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.models import MediaType, Rule
from app.schemas import ImportMode
from app.services.importer import Importer


def test_importer_preview_detects_actions(db_session) -> None:
    fixture_path = Path("tests/fixtures/qb_rules_export.json")
    raw = fixture_path.read_bytes()
    importer = Importer(db_session)

    preview = importer.preview_import_from_bytes(raw, mode=ImportMode.SKIP)

    assert len(preview) == 2
    assert preview[0].action == "create"


def test_importer_apply_maps_supported_fields(db_session) -> None:
    fixture_path = Path("tests/fixtures/qb_rules_export.json")
    raw = fixture_path.read_bytes()
    importer = Importer(db_session)

    result = importer.apply_import_from_bytes(
        raw,
        mode=ImportMode.SKIP,
        source_name=fixture_path.name,
    )

    assert result.imported_count == 2
    rules = db_session.scalars(select(Rule).order_by(Rule.rule_name.asc())).all()
    assert len(rules) == 2
    dune = next(rule for rule in rules if rule.rule_name == "Dune Part Two")
    assert dune.media_type == MediaType.MOVIE
    assert dune.imdb_id == "tt15239678"
    assert dune.normalized_title == "Dune Part Two"
    assert dune.save_path == "Movies/Dune Part Two"
    assert dune.must_contain_override == "Dune Part Two"
    assert dune.feed_urls


def test_importer_preview_preserves_assigned_category_for_custom_prefixes(db_session) -> None:
    raw = (
        b'{"\xd0\x9f\xd0\xb5\xd0\xbb\xd0\xb5\xd0\xb2\xd0\xb8\xd0\xbd":'
        b'{"assignedCategory":"Audiobooks/Victor Pelevin","affectedFeeds":["http://feed.example"],'
        b'"enabled":true,"mustContain":"\xd0\x9f\xd0\xb5\xd0\xbb\xd0\xb5\xd0\xb2\xd0\xb8\xd0\xbd",'
        b'"mustNotContain":"","useRegex":false,"episodeFilter":"","ignoreDays":0,"addPaused":true,"smartFilter":false,"savePath":""}}'
    )
    importer = Importer(db_session)

    preview = importer.preview_import_from_bytes(raw, mode=ImportMode.SKIP)

    assert preview[0].media_type == MediaType.AUDIOBOOK
    assert preview[0].assigned_category == "Audiobooks/Victor Pelevin"
