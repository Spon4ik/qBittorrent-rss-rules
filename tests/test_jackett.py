from __future__ import annotations

import httpx
import pytest

from app.models import MediaType, QualityProfile, Rule
from app.schemas import JackettSearchRequest, SearchSourceKind
from app.services.jackett import (
    JackettClient,
    JackettClientError,
    build_reduced_search_request_from_rule,
    build_search_request_from_rule,
    clamp_search_query_text,
)


def test_jackett_client_expands_optional_keywords_and_deduplicates_results() -> None:
    seen_queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["t"] == "movie"
        assert request.url.params["cat"] == "2000"
        assert request.url.params["imdbid"] == "tt13016388"
        assert request.url.params["year"] == "2024"
        seen_queries.append(request.url.params["q"])
        return httpx.Response(
            200,
            text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Dune Part Two Remux 2160p</title>
      <guid>guid-1</guid>
      <link>magnet:?xt=urn:btih:ABC123</link>
      <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
      <torznab:attr name="size" value="1073741824" />
      <torznab:attr name="infohash" value="ABC123" />
      <torznab:attr name="jackettindexer" value="rutracker" />
    </item>
  </channel>
</rss>
""",
        )

    client = JackettClient(
        "http://jackett:9117",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.search(
        JackettSearchRequest(
            query="Dune Part Two",
            media_type="movie",
            imdb_id="tt13016388",
            release_year="2024",
            keywords_all=["remux"],
            keywords_any=["4k", "2160p"],
            keywords_not=["cam"],
        )
    )

    assert seen_queries == ["Dune Part Two remux 4k", "Dune Part Two remux 2160p"]
    assert result.query_variants == ["Dune Part Two remux 4k", "Dune Part Two remux 2160p"]
    assert len(result.results) == 1
    assert result.results[0].indexer == "rutracker"
    assert result.results[0].size_label == "1.0 GB"
    assert result.results[0].source_kind == SearchSourceKind.JACKETT_ACTIVE_SEARCH


def test_jackett_client_connection_test_calls_caps_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v2.0/indexers/all/results/torznab/api"
        assert request.url.params["t"] == "caps"
        assert request.url.params["apikey"] == "secret"
        return httpx.Response(200, text="<caps />")

    client = JackettClient(
        "http://jackett:9117",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    client.test_connection()


def test_jackett_client_retries_timeout_before_success() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        assert request.url.params["t"] == "search"
        assert request.url.params["cat"] == "5000"
        if attempts < 3:
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(200, text="<rss><channel /></rss>")

    client = JackettClient(
        "http://jackett:9117",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.search(JackettSearchRequest(query="Example"))

    assert attempts == 3
    assert result.query_variants == ["Example"]
    assert result.results == []


def test_jackett_client_timeout_error_includes_request_context() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = JackettClient(
        "http://jackett:9117",
        "secret",
        transport=httpx.MockTransport(handler),
        timeout=0.01,
    )

    with pytest.raises(JackettClientError) as exc_info:
        client.search(
            JackettSearchRequest(
                query="American Classic",
                media_type="series",
                imdb_id="tt17676654",
                imdb_id_only=True,
            )
        )

    message = str(exc_info.value)
    assert "Jackett request failed after 3 timeout attempts for" in message
    assert 't=tvsearch q="American Classic" imdbid=tt17676654 cat=5000' in message


def test_jackett_client_drops_year_after_timeout_for_same_variant() -> None:
    seen_requests: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = {key: value for key, value in request.url.params.multi_items()}
        seen_requests.append(params)

        if params == {
            "apikey": "secret",
            "t": "tvsearch",
            "q": "American Classic uhd",
            "cat": "5000",
            "year": "2025",
        }:
            raise httpx.ReadTimeout("timed out", request=request)

        if params == {
            "apikey": "secret",
            "t": "tvsearch",
            "q": "American Classic uhd",
            "cat": "5000",
        }:
            return httpx.Response(200, text="<rss><channel /></rss>")

        raise AssertionError(f"Unexpected request params: {params}")

    client = JackettClient(
        "http://jackett:9117",
        "secret",
        transport=httpx.MockTransport(handler),
        timeout=0.01,
    )

    result = client.search(
        JackettSearchRequest(
            query="American Classic",
            media_type="series",
            release_year="2025",
            keywords_any=["uhd"],
        )
    )

    assert seen_requests[:3] == [
        {
            "apikey": "secret",
            "t": "tvsearch",
            "q": "American Classic uhd",
            "cat": "5000",
            "year": "2025",
        }
    ] * 3
    assert seen_requests[3:] == [
        {
            "apikey": "secret",
            "t": "tvsearch",
            "q": "American Classic uhd",
            "cat": "5000",
        },
    ]
    assert result.request_variants == ['t=tvsearch q="American Classic uhd" cat=5000']
    assert result.warning_messages == [
        'Jackett request failed after 3 timeout attempts for t=tvsearch q="American Classic uhd" year=2025 cat=5000: timed out'
    ]
    assert result.results == []


def test_jackett_client_skips_timed_out_variant_when_another_variant_succeeds() -> None:
    seen_requests: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = {key: value for key, value in request.url.params.multi_items()}
        seen_requests.append(params)

        if params == {
            "apikey": "secret",
            "t": "search",
            "q": "American Classic uhd",
            "cat": "5000",
        }:
            raise httpx.ReadTimeout("timed out", request=request)

        if params == {
            "apikey": "secret",
            "t": "search",
            "q": "American Classic 1080p",
            "cat": "5000",
        }:
            return httpx.Response(
                200,
                text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>American Classic S01E01 1080p</title>
      <guid>classic-guid</guid>
      <link>magnet:?xt=urn:btih:CLASSIC123</link>
    </item>
  </channel>
</rss>
""",
            )

        raise AssertionError(f"Unexpected request params: {params}")

    client = JackettClient(
        "http://jackett:9117",
        "secret",
        transport=httpx.MockTransport(handler),
        timeout=0.01,
    )

    result = client.search(
        JackettSearchRequest(
            query="American Classic",
            media_type="series",
            keywords_any=["uhd", "1080p"],
        )
    )

    assert seen_requests[:3] == [
        {
            "apikey": "secret",
            "t": "search",
            "q": "American Classic uhd",
            "cat": "5000",
        }
    ] * 3
    assert seen_requests[3:] == [
        {
            "apikey": "secret",
            "t": "search",
            "q": "American Classic 1080p",
            "cat": "5000",
        },
    ]
    assert result.request_variants == ['t=search q="American Classic 1080p" cat=5000']
    assert result.warning_messages == [
        'Jackett request failed after 3 timeout attempts for t=search q="American Classic uhd" cat=5000: timed out'
    ]
    assert [item.title for item in result.results] == ["American Classic S01E01 1080p"]


def test_jackett_client_retries_bad_request_before_dropping_imdb_id() -> None:
    seen_requests: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = {key: value for key, value in request.url.params.multi_items()}
        seen_requests.append(params)

        if params == {
            "apikey": "secret",
            "t": "tvsearch",
            "q": "American Classic",
            "cat": "5000",
            "imdbid": "tt17676654",
            "year": "2025",
        }:
            return httpx.Response(400, text="Bad Request")

        if params == {
            "apikey": "secret",
            "t": "tvsearch",
            "q": "American Classic",
            "cat": "5000",
            "imdbid": "tt17676654",
        }:
            return httpx.Response(200, text="<rss><channel /></rss>")

        raise AssertionError(f"Unexpected request params: {params}")

    client = JackettClient(
        "http://jackett:9117",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.search(
        JackettSearchRequest(
            query="American Classic",
            media_type="series",
            imdb_id="tt17676654",
            release_year="2025",
        )
    )

    assert seen_requests == [
        {
            "apikey": "secret",
            "t": "tvsearch",
            "q": "American Classic",
            "cat": "5000",
            "imdbid": "tt17676654",
            "year": "2025",
        },
        {
            "apikey": "secret",
            "t": "tvsearch",
            "q": "American Classic",
            "cat": "5000",
            "imdbid": "tt17676654",
        },
    ]
    assert result.query_variants == ["American Classic"]
    assert result.request_variants == [
        't=tvsearch q="American Classic" imdbid=tt17676654 cat=5000'
    ]
    assert result.results == []


def test_jackett_client_can_force_imdb_id_only_request() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        assert request.url.params["t"] == "tvsearch"
        assert request.url.params["cat"] == "5000"
        assert request.url.params["imdbid"] == "tt11379026"
        assert "q" not in request.url.params
        assert "year" not in request.url.params
        return httpx.Response(
            200,
            text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Ghosts S03E01 1080p</title>
      <guid>ghosts-guid</guid>
      <link>magnet:?xt=urn:btih:GHOSTS123</link>
    </item>
  </channel>
</rss>
""",
        )

    client = JackettClient(
        "http://jackett:9117",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.search(
        JackettSearchRequest(
            query="Ghosts",
            media_type="series",
            imdb_id="tt11379026",
            imdb_id_only=True,
            release_year="2025",
            keywords_any=["full hd", "1080p"],
        )
    )

    assert request_count == 1
    assert result.query_variants == ["Ghosts"]
    assert result.request_variants == ["t=tvsearch imdbid=tt11379026 cat=5000"]
    assert [item.title for item in result.results] == ["Ghosts S03E01 1080p"]


def test_jackett_client_retries_imdb_only_with_q_when_strict_match_is_empty() -> None:
    seen_requests: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = {key: value for key, value in request.url.params.multi_items()}
        seen_requests.append(params)

        if params == {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "imdbid": "tt11379026",
        }:
            return httpx.Response(200, text="<rss><channel /></rss>")

        if params == {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "imdbid": "tt11379026",
            "q": "Ghosts",
        }:
            return httpx.Response(
                200,
                text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Ghosts S03E01 1080p</title>
      <guid>ghosts-guid</guid>
      <link>magnet:?xt=urn:btih:GHOSTS123</link>
    </item>
  </channel>
</rss>
""",
            )

        raise AssertionError(f"Unexpected request params: {params}")

    client = JackettClient(
        "http://jackett:9117",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.search(
        JackettSearchRequest(
            query="Ghosts",
            media_type="series",
            imdb_id="tt11379026",
            imdb_id_only=True,
        )
    )

    assert seen_requests == [
        {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "imdbid": "tt11379026",
        },
        {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "imdbid": "tt11379026",
            "q": "Ghosts",
        },
    ]
    assert result.request_variants == [
        "t=tvsearch imdbid=tt11379026 cat=5000",
        't=tvsearch q="Ghosts" imdbid=tt11379026 cat=5000'
    ]
    assert [item.title for item in result.results] == ["Ghosts S03E01 1080p"]
    assert result.fallback_request_variants == []


def test_jackett_client_retries_series_imdb_only_with_title_after_bad_request() -> None:
    seen_requests: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = {key: value for key, value in request.url.params.multi_items()}
        seen_requests.append(params)

        if params == {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "imdbid": "tt39781131",
        }:
            return httpx.Response(400, text="Bad Request")

        if params == {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "imdbid": "tt39781131",
            "q": "Common Title",
        }:
            return httpx.Response(200, text="<rss><channel /></rss>")

        if params == {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "q": "Common Title",
        }:
            return httpx.Response(200, text="<rss><channel /></rss>")

        raise AssertionError(f"Unexpected request params: {params}")

    client = JackettClient(
        "http://jackett:9117",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.search(
        JackettSearchRequest(
            query="Common Title",
            media_type="series",
            imdb_id="tt39781131",
            imdb_id_only=True,
        )
    )

    assert seen_requests == [
        {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "imdbid": "tt39781131",
        },
        {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "imdbid": "tt39781131",
            "q": "Common Title",
        },
        {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "q": "Common Title",
        },
    ]
    assert result.request_variants == [
        "t=tvsearch imdbid=tt39781131 cat=5000",
        't=tvsearch q="Common Title" imdbid=tt39781131 cat=5000'
    ]
    assert result.results == []
    assert result.fallback_request_variants == [
        't=tvsearch q="Common Title" cat=5000'
    ]
    assert result.fallback_results == []


def test_jackett_client_uses_direct_indexers_when_all_rejects_imdb_enforced_series_search() -> None:
    seen_requests: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = {key: value for key, value in request.url.params.multi_items()}
        seen_requests.append((path, params))

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "imdbid": "tt17676654",
        }:
            return httpx.Response(400, text="Bad Request")

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "imdbid": "tt17676654",
            "q": "American Classic",
        }:
            return httpx.Response(400, text="Bad Request")

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "indexers",
            "configured": "true",
        }:
            return httpx.Response(
                200,
                text="""
<indexers>
  <indexer id="rutracker">
    <caps>
      <searching>
        <tv-search available="yes" supportedParams="q,imdbid,season,ep" />
      </searching>
    </caps>
  </indexer>
  <indexer id="plaintext">
    <caps>
      <searching>
        <tv-search available="yes" supportedParams="q,season,ep" />
      </searching>
    </caps>
  </indexer>
</indexers>
""",
            )

        if path == "/api/v2.0/indexers/rutracker/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "imdbid": "tt17676654",
            "q": "American Classic",
        }:
            return httpx.Response(
                200,
                text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>American Classic S01E01 1080p</title>
      <guid>american-classic-guid</guid>
      <link>magnet:?xt=urn:btih:AMERICAN1</link>
      <torznab:attr name="jackettindexer" value="rutracker" />
    </item>
  </channel>
</rss>
""",
            )

        raise AssertionError(f"Unexpected request: {path} {params}")

    client = JackettClient(
        "http://jackett:9117",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.search(
        JackettSearchRequest(
            query="American Classic",
            media_type="series",
            imdb_id="tt17676654",
            imdb_id_only=True,
        )
    )

    assert seen_requests == [
        (
            "/api/v2.0/indexers/all/results/torznab/api",
            {
                "apikey": "secret",
                "t": "tvsearch",
                "cat": "5000",
                "imdbid": "tt17676654",
            },
        ),
        (
            "/api/v2.0/indexers/all/results/torznab/api",
            {
                "apikey": "secret",
                "t": "tvsearch",
                "cat": "5000",
                "imdbid": "tt17676654",
                "q": "American Classic",
            },
        ),
        (
            "/api/v2.0/indexers/all/results/torznab/api",
            {
                "apikey": "secret",
                "t": "indexers",
                "configured": "true",
            },
        ),
        (
            "/api/v2.0/indexers/rutracker/results/torznab/api",
            {
                "apikey": "secret",
                "t": "tvsearch",
                "cat": "5000",
                "imdbid": "tt17676654",
                "q": "American Classic",
            },
        ),
    ]
    assert result.request_variants == [
        "t=tvsearch imdbid=tt17676654 cat=5000",
        't=tvsearch q="American Classic" imdbid=tt17676654 cat=5000'
    ]
    assert [item.title for item in result.results] == ["American Classic S01E01 1080p"]
    assert result.fallback_request_variants == []
    assert result.fallback_results == []


def test_jackett_client_falls_back_to_broad_title_search_when_tv_indexers_do_not_support_input_imdb() -> None:
    seen_requests: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = {key: value for key, value in request.url.params.multi_items()}
        seen_requests.append((path, params))

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "imdbid": "tt17676654",
        }:
            return httpx.Response(
                200,
                text=(
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<error code="203" description="Function Not Available: imdbid is not supported for TV search by this indexer" />'
                ),
            )

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "imdbid": "tt17676654",
            "q": "American Classic",
        }:
            return httpx.Response(
                200,
                text=(
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<error code="203" description="Function Not Available: imdbid is not supported for TV search by this indexer" />'
                ),
            )

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "indexers",
            "configured": "true",
        }:
            return httpx.Response(
                200,
                text="""
<indexers>
  <indexer id="fuzer">
    <caps>
      <searching>
        <tv-search available="yes" supportedParams="q,season,ep" />
      </searching>
    </caps>
  </indexer>
</indexers>
""",
            )

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "tvsearch",
            "q": "American Classic",
            "cat": "5000",
        }:
            return httpx.Response(
                200,
                text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>American Classic S01E01 1080p</title>
      <guid>match-guid</guid>
      <link>magnet:?xt=urn:btih:MATCH123</link>
      <torznab:attr name="jackettindexer" value="fuzer" />
    </item>
  </channel>
</rss>
""",
            )

        raise AssertionError(f"Unexpected request: {path} {params}")

    client = JackettClient(
        "http://jackett:9117",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.search(
        JackettSearchRequest(
            query="American Classic",
            media_type="series",
            imdb_id="tt17676654",
            imdb_id_only=True,
        )
    )

    assert seen_requests == [
        (
            "/api/v2.0/indexers/all/results/torznab/api",
            {
                "apikey": "secret",
                "t": "tvsearch",
                "cat": "5000",
                "imdbid": "tt17676654",
            },
        ),
        (
            "/api/v2.0/indexers/all/results/torznab/api",
            {
                "apikey": "secret",
                "t": "tvsearch",
                "cat": "5000",
                "imdbid": "tt17676654",
                "q": "American Classic",
            },
        ),
        (
            "/api/v2.0/indexers/all/results/torznab/api",
            {
                "apikey": "secret",
                "t": "indexers",
                "configured": "true",
            },
        ),
        (
            "/api/v2.0/indexers/all/results/torznab/api",
            {
                "apikey": "secret",
                "t": "tvsearch",
                "q": "American Classic",
                "cat": "5000",
            },
        ),
    ]
    assert result.request_variants == [
        "t=tvsearch imdbid=tt17676654 cat=5000",
        't=tvsearch q="American Classic" imdbid=tt17676654 cat=5000'
    ]
    assert result.results == []
    assert result.fallback_request_variants == [
        't=tvsearch q="American Classic" cat=5000'
    ]
    assert [item.title for item in result.fallback_results] == ["American Classic S01E01 1080p"]


def test_jackett_client_expands_multiple_optional_groups() -> None:
    seen_queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_queries.append(request.url.params["q"])
        return httpx.Response(200, text="<rss><channel /></rss>")

    client = JackettClient(
        "http://jackett:9117",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    client.search(
        JackettSearchRequest(
            query="Example",
            keywords_any_groups=[["mp3", "flac"], ["2025", "2026"]],
        )
    )

    assert seen_queries == [
        "Example mp3 2025",
        "Example mp3 2026",
        "Example flac 2025",
        "Example flac 2026",
    ]


def test_build_search_request_from_rule_uses_structured_terms_not_raw_regex() -> None:
    rule = Rule(
        rule_name="Andrew Michael Blues Band",
        content_name="Andrew Michael Blues Band",
        normalized_title="Andrew Michael Blues Band",
        imdb_id="tt7654321",
        media_type=MediaType.MUSIC,
        quality_profile=QualityProfile.CUSTOM,
        release_year="2026",
        additional_includes="2026",
        quality_include_tokens=["mp3"],
        quality_exclude_tokens=["flac"],
        must_contain_override=r"(?i)(?=.*andrew[\s._-]*michael)(?=.*mp3)",
    )

    payload, ignored_full_regex = build_search_request_from_rule(rule)

    assert payload.query == "Andrew Michael Blues Band"
    assert payload.media_type == MediaType.MUSIC
    assert payload.imdb_id == "tt7654321"
    assert payload.release_year == "2026"
    assert payload.keywords_all == ["2026"]
    assert payload.keywords_any == ["mp3"]
    assert "flac" in payload.keywords_not
    assert payload.keywords_any_groups == [["mp3"]]
    assert ignored_full_regex is True


def test_build_search_request_from_generated_regex_extracts_title_and_groups() -> None:
    rule = Rule(
        rule_name="The Chair Company",
        content_name="",
        normalized_title="",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.CUSTOM,
        must_contain_override=(
            r"(?i)"
            r"(?=.*the[\s._-]*chair[\s._-]*company)"
            r"(?=.*(?:full[\s._-]*hd|1080p|ultra[\s._-]*hd|uhd|2160p|4k))"
            r"(?!.*(?:sd|720p|cam))"
        ),
    )

    payload, ignored_full_regex = build_search_request_from_rule(rule)

    assert payload.query == "The Chair Company"
    assert payload.keywords_all == []
    assert payload.keywords_any_groups == [["full hd", "1080p", "ultra hd", "uhd", "2160p", "4k"]]
    assert payload.keywords_not == ["sd", "720p", "cam"]
    assert ignored_full_regex is True


def test_build_search_request_from_rule_clamps_overlong_title() -> None:
    long_title = "Long Search Title " * 20
    rule = Rule(
        rule_name=long_title,
        content_name=long_title,
        normalized_title=long_title,
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
    )

    payload, ignored_full_regex = build_search_request_from_rule(rule)

    assert payload.query == clamp_search_query_text(long_title)
    assert len(payload.query) <= 255
    assert ignored_full_regex is False


def test_build_reduced_search_request_from_rule_trims_but_keeps_keywords() -> None:
    rule = Rule(
        rule_name="Many Terms",
        content_name="Many Terms",
        normalized_title="Many Terms",
        media_type=MediaType.MUSIC,
        quality_profile=QualityProfile.CUSTOM,
        additional_includes=", ".join(f"year{index}" for index in range(30)),
        quality_include_tokens=[f"codec{index}" for index in range(10)],
        quality_exclude_tokens=[f"bad{index}" for index in range(60)],
    )

    payload, ignored_full_regex = build_reduced_search_request_from_rule(rule)

    assert payload.query == "Many Terms"
    assert len(payload.keywords_all) == 24
    assert len(payload.keywords_not) == 48
    assert payload.keywords_any_groups == [["codec0", "codec1", "codec2", "codec3", "codec4", "codec5", "codec6", "codec7", "codec8", "codec9"]]
    assert ignored_full_regex is False
