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


def test_jackett_client_fetches_broad_query_and_filters_locally() -> None:
    seen_queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["t"] == "search"
        assert request.url.params["cat"] == "2000"
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
      <torznab:attr name="year" value="2024" />
      <torznab:attr name="category" value="2000" />
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

    assert seen_queries == ["Dune Part Two"]
    assert result.query_variants == ["Dune Part Two"]
    assert result.request_variants == ['t=search q="Dune Part Two" cat=2000']
    assert len(result.raw_results) == 1
    assert len(result.results) == 1
    assert result.results[0].indexer == "rutracker"
    assert result.results[0].size_label == "1.0 GB"
    assert result.results[0].year == "2024"
    assert result.results[0].category_ids == ["2000"]
    assert result.results[0].category_labels == ["Movies"]
    assert result.results[0].source_kind == SearchSourceKind.JACKETT_ACTIVE_SEARCH


def test_jackett_client_parses_indexer_tag_and_infers_peers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["t"] == "search"
        return httpx.Response(
            200,
            text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Example Show S01E01</title>
      <guid>example-guid</guid>
      <link>magnet:?xt=urn:btih:EXAMPLE123</link>
      <indexer>xmltracker</indexer>
      <torznab:attr name="seeders" value="8" />
      <torznab:attr name="leechers" value="2" />
      <torznab:attr name="downloads" value="16" />
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
            query="Example Show",
            media_type="series",
        )
    )

    assert len(result.results) == 1
    assert result.results[0].indexer == "xmltracker"
    assert result.results[0].seeders == 8
    assert result.results[0].leechers == 2
    assert result.results[0].peers == 10
    assert result.results[0].grabs == 16


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
        assert request.url.params["q"] == "Example"
        if attempts < 3:
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(200, text="<rss><channel /></rss>")

    client = JackettClient(
        "http://jackett:9117",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.search(JackettSearchRequest(query="Example"))

    assert attempts == 4
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
    assert "t=tvsearch imdbid=tt17676654" in message


def test_jackett_client_reports_timeout_for_single_broad_variant() -> None:
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
                release_year="2025",
                keywords_any=["uhd"],
            )
        )

    message = str(exc_info.value)
    assert "Jackett request failed after 3 timeout attempts for" in message
    assert 't=search q="American Classic"' in message


def test_jackett_client_applies_local_metadata_filters_to_cached_results() -> None:
    seen_requests: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = {key: value for key, value in request.url.params.multi_items()}
        seen_requests.append(params)
        assert params == {
            "apikey": "secret",
            "t": "search",
            "q": "American Classic",
        }
        return httpx.Response(
            200,
            text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>American Classic S01E01 1080p</title>
      <guid>classic-guid</guid>
      <link>magnet:?xt=urn:btih:CLASSIC123</link>
      <torznab:attr name="size" value="2147483648" />
      <torznab:attr name="year" value="2025" />
      <torznab:attr name="jackettindexer" value="rutracker" />
      <torznab:attr name="category" value="5000" />
    </item>
    <item>
      <title>American Classic S01E01 720p</title>
      <guid>classic-guid-2</guid>
      <link>magnet:?xt=urn:btih:CLASSIC222</link>
      <torznab:attr name="size" value="734003200" />
      <torznab:attr name="year" value="2024" />
      <torznab:attr name="jackettindexer" value="otherindexer" />
      <torznab:attr name="category" value="7000" />
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
            query="American Classic",
            media_type="series",
            keywords_any=["1080p"],
            release_year="2025",
            size_min_mb=1000,
            filter_indexers=["rutracker"],
            filter_category_ids=["5000"],
        )
    )

    assert seen_requests == [
        {
            "apikey": "secret",
            "t": "search",
            "q": "American Classic",
        }
    ]
    assert result.query_variants == ["American Classic"]
    assert result.request_variants == ['t=search q="American Classic"']
    assert [item.title for item in result.raw_results] == [
        "American Classic S01E01 1080p",
        "American Classic S01E01 720p",
    ]
    assert [item.title for item in result.results] == ["American Classic S01E01 1080p"]


def test_jackett_client_scopes_standard_remote_fetch_to_filter_indexers() -> None:
    seen_requests: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = {key: value for key, value in request.url.params.multi_items()}
        seen_requests.append((path, params))

        if path == "/api/v2.0/indexers/all/results/torznab/api":
            assert params == {
                "apikey": "secret",
                "t": "search",
                "q": "American Classic",
            }
            return httpx.Response(
                200,
                text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>American Classic S01E01 1080p</title>
      <guid>classic-guid-1</guid>
      <link>magnet:?xt=urn:btih:CLASSIC111</link>
      <torznab:attr name="jackettindexer" value="rutracker" />
      <torznab:attr name="category" value="5000" />
    </item>
    <item>
      <title>American Classic S01E01 WEB</title>
      <guid>classic-guid-2</guid>
      <link>magnet:?xt=urn:btih:CLASSIC222</link>
      <torznab:attr name="jackettindexer" value="kinozal" />
      <torznab:attr name="category" value="5000" />
    </item>
    <item>
      <title>American Classic S01E01 720p</title>
      <guid>classic-guid-3</guid>
      <link>magnet:?xt=urn:btih:CLASSIC333</link>
      <torznab:attr name="jackettindexer" value="othertacker" />
      <torznab:attr name="category" value="5000" />
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
            filter_indexers=["rutracker", "kinozal"],
        )
    )

    assert seen_requests == [
        (
            "/api/v2.0/indexers/all/results/torznab/api",
            {
                "apikey": "secret",
                "t": "search",
                "q": "American Classic",
            },
        ),
    ]
    assert {item.title for item in result.raw_results} == {
        "American Classic S01E01 1080p",
        "American Classic S01E01 WEB",
        "American Classic S01E01 720p",
    }
    assert {item.indexer for item in result.results} == {"rutracker", "kinozal"}


def test_jackett_client_omits_default_media_cat_for_scoped_movie_indexers_without_caps_map() -> (
    None
):
    seen_requests: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = {key: value for key, value in request.url.params.multi_items()}
        seen_requests.append((path, params))
        if path == "/api/v2.0/indexers/all/results/torznab/api":
            assert params == {
                "apikey": "secret",
                "t": "search",
                "q": "The Housemaid",
            }
            return httpx.Response(200, text="<rss><channel /></rss>")
        raise AssertionError(f"Unexpected request: {path} {params}")

    client = JackettClient(
        "http://jackett:9117",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.search(
        JackettSearchRequest(
            query="The Housemaid",
            media_type="movie",
            filter_indexers=["rutracker"],
        )
    )

    assert seen_requests == [
        (
            "/api/v2.0/indexers/all/results/torznab/api",
            {
                "apikey": "secret",
                "t": "search",
                "q": "The Housemaid",
            },
        ),
    ]
    assert result.request_variants == ['t=search q="The Housemaid"']


def test_jackett_client_falls_back_to_all_when_filter_indexer_is_not_slug() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        assert request.url.path == "/api/v2.0/indexers/all/results/torznab/api"
        assert dict(request.url.params.multi_items()) in (
            {
                "apikey": "secret",
                "t": "search",
                "q": "American Classic",
                "cat": "5000",
            },
            {
                "apikey": "secret",
                "t": "search",
                "q": "American Classic",
            },
        )
        return httpx.Response(200, text="<rss><channel /></rss>")

    client = JackettClient(
        "http://jackett:9117",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.search(
        JackettSearchRequest(
            query="American Classic",
            media_type="series",
            filter_indexers=["The Pirate Bay"],
        )
    )

    assert all(path == "/api/v2.0/indexers/all/results/torznab/api" for path in seen_paths)
    assert len(seen_paths) >= 1
    assert result.results == []


def test_jackett_client_scoped_standard_search_continues_after_indexer_timeout() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen_paths.append(path)
        if path == "/api/v2.0/indexers/all/results/torznab/api":
            raise httpx.ReadTimeout("timed out", request=request)
        if path == "/api/v2.0/indexers/rutracker/results/torznab/api":
            raise httpx.ReadTimeout("timed out", request=request)
        if path == "/api/v2.0/indexers/kinozal/results/torznab/api":
            return httpx.Response(
                200,
                text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>American Classic S01E01 WEB</title>
      <guid>classic-guid-2</guid>
      <link>magnet:?xt=urn:btih:CLASSIC222</link>
      <torznab:attr name="jackettindexer" value="kinozal" />
      <torznab:attr name="category" value="5000" />
    </item>
  </channel>
</rss>
""",
            )
        raise AssertionError(f"Unexpected request path: {path}")

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
            filter_indexers=["rutracker", "kinozal"],
        )
    )

    assert seen_paths.count("/api/v2.0/indexers/all/results/torznab/api") == 3
    assert seen_paths.count("/api/v2.0/indexers/rutracker/results/torznab/api") == 3
    assert seen_paths.count("/api/v2.0/indexers/kinozal/results/torznab/api") == 1
    assert [item.title for item in result.results] == ["American Classic S01E01 WEB"]
    assert any('t=search q="American Classic"' in item for item in result.warning_messages)


def test_jackett_client_can_filter_by_category_label_across_indexers() -> None:
    seen_requests: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = {key: value for key, value in request.url.params.multi_items()}
        seen_requests.append((path, params))

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "search",
            "q": "Classic Audio",
            "cat": "3030",
        }:
            return httpx.Response(
                200,
                text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Classic Audio Collection RU</title>
      <guid>audio-ru-guid</guid>
      <link>magnet:?xt=urn:btih:AUDIO111</link>
      <torznab:attr name="jackettindexer" value="rutracker" />
      <torznab:attr name="category" value="101279" />
    </item>
    <item>
      <title>Classic Audio Collection EN</title>
      <guid>audio-en-guid</guid>
      <link>magnet:?xt=urn:btih:AUDIO222</link>
      <torznab:attr name="jackettindexer" value="booktracker" />
      <torznab:attr name="category" value="22222" />
    </item>
    <item>
      <title>Classic Audio Collection Misc</title>
      <guid>audio-misc-guid</guid>
      <link>magnet:?xt=urn:btih:AUDIO333</link>
      <torznab:attr name="jackettindexer" value="booktracker" />
      <torznab:attr name="category" value="90999" />
    </item>
  </channel>
</rss>
""",
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
  <indexer id="rutracker">
    <caps>
      <categories>
        <category id="100000" name="Audio">
          <subcat id="101279" name="Audiobooks" />
        </category>
      </categories>
    </caps>
  </indexer>
  <indexer id="booktracker">
    <caps>
      <categories>
        <category id="22000" name="Books">
          <subcat id="22222" name="Audiobooks" />
          <subcat id="90999" name="Misc" />
        </category>
      </categories>
    </caps>
  </indexer>
</indexers>
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
            query="Classic Audio",
            media_type="audiobook",
            filter_category_ids=["audiobooks"],
        )
    )

    assert seen_requests == [
        (
            "/api/v2.0/indexers/all/results/torznab/api",
            {
                "apikey": "secret",
                "t": "search",
                "q": "Classic Audio",
                "cat": "3030",
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
    ]
    assert [item.title for item in result.results] == [
        "Classic Audio Collection EN",
        "Classic Audio Collection RU",
    ]
    labels_by_title = {item.title: set(item.category_labels) for item in result.results}
    assert labels_by_title["Classic Audio Collection RU"] == {"Audiobooks", "Audio/Audiobooks"}
    assert labels_by_title["Classic Audio Collection EN"] == {"Audiobooks", "Books/Audiobooks"}


def test_jackett_client_can_enrich_result_category_labels_without_label_filter() -> None:
    seen_requests: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = {key: value for key, value in request.url.params.multi_items()}
        seen_requests.append((path, params))

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "search",
            "q": "Classic Audio",
            "cat": "3030",
        }:
            return httpx.Response(
                200,
                text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Classic Audio Collection RU</title>
      <guid>audio-ru-guid</guid>
      <link>magnet:?xt=urn:btih:AUDIO111</link>
      <torznab:attr name="jackettindexer" value="rutracker" />
      <torznab:attr name="category" value="101279" />
    </item>
  </channel>
</rss>
""",
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
  <indexer id="rutracker">
    <caps>
      <categories>
        <category id="100000" name="Audio">
          <subcat id="101279" name="Audiobooks" />
        </category>
      </categories>
    </caps>
  </indexer>
</indexers>
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
            query="Classic Audio",
            media_type="audiobook",
        )
    )
    assert result.results[0].category_labels == []

    client.enrich_result_category_labels([*result.raw_results, *result.results])

    assert set(result.results[0].category_labels) == {"Audiobooks", "Audio/Audiobooks"}
    assert seen_requests == [
        (
            "/api/v2.0/indexers/all/results/torznab/api",
            {
                "apikey": "secret",
                "t": "search",
                "q": "Classic Audio",
                "cat": "3030",
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
    ]


def test_jackett_client_matches_release_year_from_title_when_attr_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "The Rip"
        assert request.url.params["cat"] == "2000"
        return httpx.Response(
            200,
            text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>The Rip (2026) 4K HDR10</title>
      <guid>rip-guid-1</guid>
      <link>magnet:?xt=urn:btih:RIP111</link>
    </item>
    <item>
      <title>The Rip (2025) 4K HDR10</title>
      <guid>rip-guid-2</guid>
      <link>magnet:?xt=urn:btih:RIP222</link>
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
            query="The Rip",
            media_type="movie",
            release_year="2026",
            keywords_any_groups=[["uhd", "4k", "ultra hd"], ["hdr", "hdr10"]],
        )
    )

    assert [item.title for item in result.results] == ["The Rip (2026) 4K HDR10"]
    assert result.results[0].year == "2026"


def test_jackett_client_local_filters_require_title_to_match_query() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "The Rip"
        assert request.url.params["cat"] == "2000"
        return httpx.Response(
            200,
            text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Красота / The Beauty (2026) 4K WEB-DL AVC</title>
      <guid>beauty-guid-1</guid>
      <link>magnet:?xt=urn:btih:BEAUTY111</link>
    </item>
    <item>
      <title>The Rip (2026) 4K WEB-DL AVC</title>
      <guid>rip-guid-3</guid>
      <link>magnet:?xt=urn:btih:RIP333</link>
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
            query="The Rip",
            media_type="movie",
            release_year="2026",
            keywords_any_groups=[["ultra hd", "uhd", "2160p", "4k", "hdr", "dolby vision"]],
            keywords_not=["sd", "720p", "cam"],
        )
    )

    assert [item.title for item in result.results] == ["The Rip (2026) 4K WEB-DL AVC"]


def test_jackett_client_short_included_terms_require_token_match() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "The Rip"
        return httpx.Response(
            200,
            text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>The Rip 2026 2160P WEB H265-POKE</title>
      <guid>rip-short-include-1</guid>
      <link>magnet:?xt=urn:btih:RIP555</link>
      <torznab:attr name="description" value="HDRezka Studio encode" />
    </item>
    <item>
      <title>The Rip 2026 HDR 2160P WEB H265-ALT</title>
      <guid>rip-short-include-2</guid>
      <link>magnet:?xt=urn:btih:RIP666</link>
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
            query="The Rip",
            media_type="movie",
            keywords_any=["hdr"],
        )
    )

    assert [item.title for item in result.results] == ["The Rip 2026 HDR 2160P WEB H265-ALT"]


def test_jackett_client_non_latin_query_still_filters_by_title() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "Пелевин"
        assert request.url.params["cat"] == "3030"
        return httpx.Response(
            200,
            text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Pelevin 2006 MP3</title>
      <guid>pelevin-latin-guid</guid>
      <link>magnet:?xt=urn:btih:PEL111</link>
    </item>
    <item>
      <title>Пелевин 2006 MP3</title>
      <guid>pelevin-cyrillic-guid</guid>
      <link>magnet:?xt=urn:btih:PEL222</link>
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
            query="Пелевин",
            media_type="audiobook",
            keywords_any=["mp3"],
        )
    )

    assert [item.title for item in result.results] == ["Пелевин 2006 MP3"]


def test_jackett_client_required_keyword_s3_matches_s03_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "Ghosts"
        assert request.url.params["cat"] == "5000"
        return httpx.Response(
            200,
            text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Ghosts S03E01 1080p</title>
      <guid>ghosts-s03-guid</guid>
      <link>magnet:?xt=urn:btih:GHOSTS301</link>
    </item>
    <item>
      <title>Ghosts S02E08 1080p</title>
      <guid>ghosts-s02-guid</guid>
      <link>magnet:?xt=urn:btih:GHOSTS208</link>
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
            keywords_all=["s3"],
            keywords_any=["1080p"],
        )
    )

    assert [item.title for item in result.results] == ["Ghosts S03E01 1080p"]


def test_jackett_client_required_keyword_e7_matches_sxxexx_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "Ghosts"
        assert request.url.params["cat"] == "5000"
        return httpx.Response(
            200,
            text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Ghosts S03E07 1080p</title>
      <guid>ghosts-s03e07-guid</guid>
      <link>magnet:?xt=urn:btih:GHOSTS307</link>
    </item>
    <item>
      <title>Ghosts S03E08 1080p</title>
      <guid>ghosts-s03e08-guid</guid>
      <link>magnet:?xt=urn:btih:GHOSTS308</link>
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
            keywords_all=["e7"],
            keywords_any=["1080p"],
        )
    )

    assert [item.title for item in result.results] == ["Ghosts S03E07 1080p"]


def test_jackett_client_short_excluded_terms_require_token_match() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "The Rip"
        return httpx.Response(
            200,
            text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>The Rip 2026 HDR 2160P WEB H265-POKE</title>
      <guid>rip-short-exclude-1</guid>
      <link>magnet:?xt=urn:btih:RIP333</link>
      <torznab:attr name="description" value="HDR SDR transfer" />
    </item>
    <item>
      <title>The Rip 2026 HDR 2160P WEB H265-ALT</title>
      <guid>rip-short-exclude-2</guid>
      <link>magnet:?xt=urn:btih:RIP444</link>
      <torznab:attr name="description" value="HDR SD transfer" />
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
            query="The Rip",
            media_type="movie",
            keywords_any=["hdr"],
            keywords_not=["sd"],
        )
    )

    assert [item.title for item in result.results] == ["The Rip 2026 HDR 2160P WEB H265-POKE"]


def test_jackett_client_uses_broad_remote_query_when_local_filters_include_imdb_and_year() -> None:
    seen_requests: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = {key: value for key, value in request.url.params.multi_items()}
        seen_requests.append(params)
        assert params in (
            {
                "apikey": "secret",
                "t": "search",
                "q": "American Classic",
                "cat": "5000",
            },
            {
                "apikey": "secret",
                "t": "search",
                "q": "American Classic",
            },
        )
        return httpx.Response(200, text="<rss><channel /></rss>")

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

    assert seen_requests
    assert all(
        request in (
            {
                "apikey": "secret",
                "t": "search",
                "q": "American Classic",
                "cat": "5000",
            },
            {
                "apikey": "secret",
                "t": "search",
                "q": "American Classic",
            },
        )
        for request in seen_requests
    )
    assert result.query_variants == ["American Classic"]
    assert any('t=search q="American Classic"' in item for item in result.request_variants)
    assert result.results == []


def test_jackett_client_can_force_imdb_id_only_request() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        params = {key: value for key, value in request.url.params.multi_items()}
        if params == {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "imdbid": "tt11379026",
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
      <torznab:attr name="year" value="2025" />
    </item>
  </channel>
</rss>
""",
            )
        if params == {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
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
      <torznab:attr name="year" value="2025" />
    </item>
  </channel>
</rss>
""",
            )
        return httpx.Response(
            400,
            text="Unexpected request params",
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

    assert request_count == 2
    assert result.query_variants == ["Ghosts"]
    assert result.request_variants == [
        "t=tvsearch imdbid=tt11379026 cat=5000",
        't=tvsearch q="Ghosts" cat=5000',
    ]
    assert [item.title for item in result.results] == ["Ghosts S03E01 1080p"]
    assert result.fallback_request_variants == []
    assert result.fallback_results == []


def test_jackett_client_uses_series_episode_precision_before_broad_fallback() -> None:
    seen_requests: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = {key: value for key, value in request.url.params.multi_items()}
        seen_requests.append(params)

        if params.get("apikey") == "secret" and params.get("t") == "tvsearch" and params.get("imdbid") == "tt11379026" and params.get("season") == "3" and params.get("ep") == "7":
            return httpx.Response(200, text="<rss><channel /></rss>")

        if params.get("apikey") == "secret" and params.get("t") == "tvsearch" and params.get("imdbid") == "tt11379026" and params.get("season") == "3" and "ep" not in params:
            return httpx.Response(
                200,
                text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Ghosts S03 1080p Season Pack</title>
      <guid>ghosts-season-pack</guid>
      <link>magnet:?xt=urn:btih:GHOSTSPACK</link>
      <torznab:attr name="imdbid" value="tt11379026" />
    </item>
  </channel>
</rss>
""",
            )

        if params.get("apikey") == "secret" and params.get("t") == "tvsearch" and params.get("q") == "Ghosts" and params.get("season") == "3" and params.get("ep") == "7":
            return httpx.Response(200, text="<rss><channel /></rss>")

        if params.get("apikey") == "secret" and params.get("t") == "tvsearch" and params.get("q") == "Ghosts" and params.get("season") == "3" and "ep" not in params:
            return httpx.Response(200, text="<rss><channel /></rss>")

        if params.get("apikey") == "secret" and params.get("t") == "tvsearch" and params.get("q") == "Ghosts" and "season" not in params:
            return httpx.Response(200, text="<rss><channel /></rss>")

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
            season_number=3,
            episode_number=7,
        )
    )

    assert any(
        params.get("t") == "tvsearch"
        and params.get("imdbid") == "tt11379026"
        and params.get("season") == "3"
        and params.get("ep") == "7"
        for params in seen_requests
    )
    assert any(
        params.get("t") == "tvsearch"
        and params.get("imdbid") == "tt11379026"
        and params.get("season") == "3"
        and "ep" not in params
        for params in seen_requests
    )
    assert any('t=tvsearch q="Ghosts"' in item for item in result.request_variants)
    assert [item.title for item in result.results] == ["Ghosts S03 1080p Season Pack"]
    assert result.fallback_request_variants == []
    assert result.fallback_results == []


def test_jackett_client_precise_movie_quality_exclude_bluray_keeps_bdrip_result() -> None:
    seen_requests: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = {key: value for key, value in request.url.params.multi_items()}
        seen_requests.append(params)
        assert request.url.path == "/api/v2.0/indexers/all/results/torznab/api"
        if params == {
            "apikey": "secret",
            "t": "movie",
            "cat": "2000",
            "imdbid": "tt0161081",
        }:
            return httpx.Response(
                200,
                text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>What Lies Beneath 2000 DUB, MVO, AVO, Sub 4K, HEVC, HDR, Dolby Vision P8 BDRip 2160p - RUSSIAN</title>
      <guid>what-lies-beneath-guid</guid>
      <link>magnet:?xt=urn:btih:WLB123</link>
      <torznab:attr name="imdbid" value="tt0161081" />
      <torznab:attr name="jackettindexer" value="kinozal" />
      <torznab:attr name="size" value="42949672960" />
      <torznab:attr name="category" value="2000" />
      <torznab:attr name="year" value="2000" />
    </item>
  </channel>
</rss>
""",
            )
        if params in (
            {
                "apikey": "secret",
                "t": "movie",
                "cat": "2000",
                "q": "What Lies Beneath",
            },
            {
                "apikey": "secret",
                "t": "movie",
                "q": "What Lies Beneath",
            },
            {
                "apikey": "secret",
                "t": "search",
                "cat": "2000",
                "q": "What Lies Beneath",
            },
            {
                "apikey": "secret",
                "t": "search",
                "q": "What Lies Beneath",
            },
        ):
            return httpx.Response(200, text="<rss><channel /></rss>")
        raise AssertionError(f"Unexpected request params: {params}")

    client = JackettClient(
        "http://jackett:9117",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.search(
        JackettSearchRequest(
            query="What Lies Beneath",
            media_type="movie",
            imdb_id="tt0161081",
            imdb_id_only=True,
            keywords_any=[
                "ultra hd",
                "uhd",
                "2160p",
                "4k",
                "hdr",
                "hdr10",
                "dolby vision",
                "dv",
            ],
            keywords_any_groups=[
                ["ultra hd", "uhd", "2160p", "4k"],
                ["hdr", "hdr10"],
                ["dolby vision", "dv"],
            ],
            keywords_not=["bdremux", "bluray"],
        )
    )

    assert seen_requests[0] == {
        "apikey": "secret",
        "t": "movie",
        "cat": "2000",
        "imdbid": "tt0161081",
    }
    assert any(
        params.get("q") == "What Lies Beneath"
        and params.get("cat") == "2000"
        for params in seen_requests[1:]
    )
    assert result.request_variants[0] == "t=movie imdbid=tt0161081 cat=2000"
    assert any('q="What Lies Beneath"' in item for item in result.request_variants)
    assert [item.title for item in result.results] == [
        "What Lies Beneath 2000 DUB, MVO, AVO, Sub 4K, HEVC, HDR, Dolby Vision P8 BDRip 2160p - RUSSIAN"
    ]
    assert result.fallback_request_variants == []
    assert result.fallback_results == []


def test_jackett_client_keeps_imdb_match_when_title_text_differs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        params = {key: value for key, value in request.url.params.multi_items()}
        if params == {
            "apikey": "secret",
            "t": "movie",
            "cat": "2000",
            "imdbid": "tt0068646",
        }:
            return httpx.Response(
                200,
                text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Крёстный отец 1972 UHD</title>
      <guid>godfather-ru-guid</guid>
      <link>magnet:?xt=urn:btih:GODFATHER1</link>
      <torznab:attr name="imdbid" value="tt0068646" />
    </item>
  </channel>
</rss>
""",
            )
        if params in (
            {
                "apikey": "secret",
                "t": "movie",
                "cat": "2000",
                "q": "The Godfather",
            },
            {
                "apikey": "secret",
                "t": "movie",
                "q": "The Godfather",
            },
            {
                "apikey": "secret",
                "t": "search",
                "cat": "2000",
                "q": "The Godfather",
            },
            {
                "apikey": "secret",
                "t": "search",
                "q": "The Godfather",
            },
        ):
            return httpx.Response(200, text="<rss><channel /></rss>")
        raise AssertionError(f"Unexpected request params: {params}")

    client = JackettClient(
        "http://jackett:9117",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.search(
        JackettSearchRequest(
            query="The Godfather",
            media_type="movie",
            imdb_id="tt0068646",
            imdb_id_only=True,
            keywords_any=["uhd"],
        )
    )

    assert [item.title for item in result.results] == ["Крёстный отец 1972 UHD"]


def test_jackett_client_uses_title_fallback_when_strict_imdb_match_is_empty() -> None:
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
            "imdbid": "tt11379026",
        }:
            return httpx.Response(200, text="<rss><channel /></rss>")

        if params == {
            "apikey": "secret",
            "t": "indexers",
            "configured": "true",
        }:
            return httpx.Response(
                200,
                text="""
<indexers>
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

        if params in (
            {
                "apikey": "secret",
                "t": "tvsearch",
                "cat": "5000",
                "q": "Ghosts",
            },
            {
                "apikey": "secret",
                "t": "tvsearch",
                "q": "Ghosts",
            },
        ):
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

    assert seen_requests[0] == {
        "apikey": "secret",
        "t": "tvsearch",
        "cat": "5000",
        "imdbid": "tt11379026",
    }
    assert {
        "apikey": "secret",
        "t": "indexers",
        "configured": "true",
    } in seen_requests
    assert any(
        params.get("q") == "Ghosts" and params.get("t") == "tvsearch"
        for params in seen_requests
    )
    assert result.request_variants[0] == "t=tvsearch imdbid=tt11379026 cat=5000"
    assert any('t=tvsearch q="Ghosts"' in item for item in result.request_variants)
    assert [item.title for item in result.results] == ["Ghosts S03E01 1080p"]
    assert result.fallback_request_variants == []
    assert result.fallback_results == []


def test_jackett_client_drops_fallback_rows_with_conflicting_imdb_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        params = {key: value for key, value in request.url.params.multi_items()}

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
            "imdbid": "tt11379026",
        }:
            return httpx.Response(200, text="<rss><channel /></rss>")

        if params == {
            "apikey": "secret",
            "t": "indexers",
            "configured": "true",
        }:
            return httpx.Response(200, text="<indexers />")

        if params in (
            {
                "apikey": "secret",
                "t": "tvsearch",
                "cat": "5000",
                "q": "Ghosts",
            },
            {
                "apikey": "secret",
                "t": "tvsearch",
                "q": "Ghosts",
            },
            {
                "apikey": "secret",
                "t": "search",
                "cat": "5000",
                "q": "Ghosts",
            },
            {
                "apikey": "secret",
                "t": "search",
                "q": "Ghosts",
            },
        ):
            return httpx.Response(
                200,
                text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Ghosts S03E01 1080p</title>
      <guid>ghosts-us-guid</guid>
      <link>magnet:?xt=urn:btih:GHOSTSUS</link>
      <torznab:attr name="imdbid" value="tt8594324" />
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

    assert result.results == []
    assert result.fallback_results == []


def test_jackett_client_imdb_title_fallback_uses_scoped_indexers_after_all_timeout() -> None:
    seen_requests: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = {key: value for key, value in request.url.params.multi_items()}
        seen_requests.append((path, params))

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "tvsearch",
            "imdbid": "tt17676654",
        }:
            return httpx.Response(200, text="<rss><channel /></rss>")

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
        <tv-search available="yes" supportedParams="q,imdbid" />
      </searching>
    </caps>
  </indexer>
  <indexer id="kinozal">
    <caps>
      <searching>
        <tv-search available="yes" supportedParams="q,imdbid" />
      </searching>
    </caps>
  </indexer>
</indexers>
""",
            )

        if path in {
            "/api/v2.0/indexers/rutracker/results/torznab/api",
            "/api/v2.0/indexers/kinozal/results/torznab/api",
        } and params == {
            "apikey": "secret",
            "t": "tvsearch",
            "imdbid": "tt17676654",
        }:
            return httpx.Response(200, text="<rss><channel /></rss>")

        if path == "/api/v2.0/indexers/all/results/torznab/api" and (
            params
            == {
                "apikey": "secret",
                "t": "tvsearch",
                "q": "American Classic",
            }
            or params
            == {
                "apikey": "secret",
                "t": "search",
                "q": "American Classic",
            }
        ):
            raise httpx.ReadTimeout("timed out", request=request)

        if path == "/api/v2.0/indexers/rutracker/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "tvsearch",
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

        if path == "/api/v2.0/indexers/kinozal/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "tvsearch",
            "q": "American Classic",
        }:
            return httpx.Response(200, text="<rss><channel /></rss>")

        if path in {
            "/api/v2.0/indexers/rutracker/results/torznab/api",
            "/api/v2.0/indexers/kinozal/results/torznab/api",
        } and params == {
            "apikey": "secret",
            "t": "search",
            "q": "American Classic",
        }:
            return httpx.Response(200, text="<rss><channel /></rss>")

        raise AssertionError(f"Unexpected request: {path} {params}")

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
            imdb_id="tt17676654",
            imdb_id_only=True,
            filter_indexers=["rutracker", "kinozal"],
        )
    )

    assert any(
        path == "/api/v2.0/indexers/all/results/torznab/api"
        and params.get("t") == "tvsearch"
        and params.get("q") == "American Classic"
        for path, params in seen_requests
    )
    assert any(
        path == "/api/v2.0/indexers/rutracker/results/torznab/api"
        and params.get("t") == "tvsearch"
        and params.get("q") == "American Classic"
        for path, params in seen_requests
    )
    assert [item.title for item in result.results] == ["American Classic S01E01 1080p"]
    assert result.fallback_results == []
    assert result.warning_messages == [] or any(
        "American Classic" in item for item in result.warning_messages
    )


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
            "imdbid": "tt39781131",
        }:
            return httpx.Response(400, text="Bad Request")

        if params == {
            "apikey": "secret",
            "t": "indexers",
            "configured": "true",
        }:
            return httpx.Response(
                200,
                text="""
<indexers>
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

        if params == {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "q": "Common Title",
        }:
            return httpx.Response(200, text="<rss><channel /></rss>")

        if params == {
            "apikey": "secret",
            "t": "tvsearch",
            "q": "Common Title",
        }:
            return httpx.Response(200, text="<rss><channel /></rss>")

        if params == {
            "apikey": "secret",
            "t": "search",
            "cat": "5000",
            "q": "Common Title",
        }:
            return httpx.Response(200, text="<rss><channel /></rss>")

        if params == {
            "apikey": "secret",
            "t": "search",
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

    assert seen_requests[0] == {
        "apikey": "secret",
        "t": "tvsearch",
        "cat": "5000",
        "imdbid": "tt39781131",
    }
    assert {
        "apikey": "secret",
        "t": "indexers",
        "configured": "true",
    } in seen_requests
    assert seen_requests.count(
        {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "q": "Common Title",
        }
    ) >= 1
    assert result.request_variants[0] == "t=tvsearch imdbid=tt39781131 cat=5000"
    assert any('q="Common Title"' in item for item in result.request_variants)
    assert result.results == []
    assert any('q="Common Title"' in item for item in result.fallback_request_variants)
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
            "imdbid": "tt17676654",
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
        if path == "/api/v2.0/indexers/all/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
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

    assert seen_requests[0] == (
        "/api/v2.0/indexers/all/results/torznab/api",
        {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "imdbid": "tt17676654",
        },
    )
    assert (
        "/api/v2.0/indexers/all/results/torznab/api",
        {
            "apikey": "secret",
            "t": "tvsearch",
            "imdbid": "tt17676654",
        },
    ) in seen_requests
    assert (
        "/api/v2.0/indexers/all/results/torznab/api",
        {
            "apikey": "secret",
            "t": "indexers",
            "configured": "true",
        },
    ) in seen_requests
    assert (
        "/api/v2.0/indexers/rutracker/results/torznab/api",
        {
            "apikey": "secret",
            "t": "tvsearch",
            "imdbid": "tt17676654",
        },
    ) in seen_requests
    assert any(
        path == "/api/v2.0/indexers/all/results/torznab/api"
        and params.get("q") == "American Classic"
        for path, params in seen_requests
    )
    assert result.request_variants[0] == "t=tvsearch imdbid=tt17676654 cat=5000"
    assert "t=tvsearch imdbid=tt17676654" in result.request_variants
    assert any('q="American Classic"' in item for item in result.request_variants)
    assert [item.title for item in result.results] == ["American Classic S01E01 1080p"]
    assert result.fallback_request_variants == []
    assert result.fallback_results == []


def test_jackett_client_uses_direct_indexers_when_all_imdb_search_returns_empty() -> None:
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
            return httpx.Response(200, text="<rss><channel /></rss>")

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "tvsearch",
            "imdbid": "tt17676654",
        }:
            return httpx.Response(200, text="<rss><channel /></rss>")

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
</indexers>
""",
            )

        if path == "/api/v2.0/indexers/rutracker/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "tvsearch",
            "imdbid": "tt17676654",
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
      <torznab:attr name="imdbid" value="tt17676654" />
      <torznab:attr name="jackettindexer" value="rutracker" />
    </item>
  </channel>
</rss>
""",
            )

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "q": "American Classic",
        }:
            return httpx.Response(200, text="<rss><channel /></rss>")

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "tvsearch",
            "q": "American Classic",
        }:
            return httpx.Response(200, text="<rss><channel /></rss>")

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "search",
            "cat": "5000",
            "q": "American Classic",
        }:
            return httpx.Response(200, text="<rss><channel /></rss>")

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "search",
            "q": "American Classic",
        }:
            return httpx.Response(200, text="<rss><channel /></rss>")

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

    assert (
        "/api/v2.0/indexers/all/results/torznab/api",
        {
            "apikey": "secret",
            "t": "tvsearch",
            "cat": "5000",
            "imdbid": "tt17676654",
        },
    ) in seen_requests
    assert (
        "/api/v2.0/indexers/all/results/torznab/api",
        {
            "apikey": "secret",
            "t": "tvsearch",
            "imdbid": "tt17676654",
        },
    ) in seen_requests
    assert (
        "/api/v2.0/indexers/rutracker/results/torznab/api",
        {
            "apikey": "secret",
            "t": "tvsearch",
            "imdbid": "tt17676654",
        },
    ) in seen_requests
    assert result.request_variants[0] == "t=tvsearch imdbid=tt17676654 cat=5000"
    assert "t=tvsearch imdbid=tt17676654" in result.request_variants
    assert any('q="American Classic"' in item for item in result.request_variants)
    assert [item.title for item in result.results] == ["American Classic S01E01 1080p"]


def test_jackett_client_groups_same_hash_duplicates_in_one_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = {key: value for key, value in request.url.params.multi_items()}
        if path == "/api/v2.0/indexers/all/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "search",
            "q": "Dune Part Two",
            "cat": "2000",
        }:
            return httpx.Response(
                200,
                text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Dune Part Two 2160p HDR</title>
      <guid>dune-1</guid>
      <link>magnet:?xt=urn:btih:ABCDEF1234567890ABCDEF1234567890ABCDEF12&amp;tr=https://tracker.one/announce</link>
      <torznab:attr name="infohash" value="ABCDEF1234567890ABCDEF1234567890ABCDEF12" />
      <torznab:attr name="jackettindexer" value="rutracker" />
      <torznab:attr name="seeders" value="5" />
    </item>
    <item>
      <title>Dune Part Two 2160p HDR Proper</title>
      <guid>dune-2</guid>
      <link>magnet:?xt=urn:btih:ABCDEF1234567890ABCDEF1234567890ABCDEF12&amp;tr=https://tracker.two/announce</link>
      <torznab:attr name="infohash" value="ABCDEF1234567890ABCDEF1234567890ABCDEF12" />
      <torznab:attr name="jackettindexer" value="kinozal" />
      <torznab:attr name="seeders" value="12" />
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
            query="Dune Part Two",
            media_type=MediaType.MOVIE,
        )
    )

    assert len(result.raw_results) == 1
    merged = result.raw_results[0]
    assert merged.duplicate_count == 2
    assert merged.seeders == 12
    assert merged.grouped_indexers == ["rutracker", "kinozal"]
    assert merged.grouped_trackers == [
        "https://tracker.one/announce",
        "https://tracker.two/announce",
    ]
    assert len(merged.grouped_links) == 2


def test_jackett_client_prefers_structured_music_search_before_generic_query() -> None:
    seen_requests: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = {key: value for key, value in request.url.params.multi_items()}
        seen_requests.append((path, params))

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "indexers",
            "configured": "true",
        }:
            return httpx.Response(
                200,
                text="""
<indexers>
  <indexer id="musictracker">
    <caps>
      <searching>
        <music-search available="yes" supportedParams="q,artist,album,year" />
      </searching>
    </caps>
  </indexer>
</indexers>
""",
            )

        if path == "/api/v2.0/indexers/musictracker/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "music",
            "q": "Andrew Michael Blues Band",
            "cat": "3000",
            "artist": "Andrew Michael",
            "album": "Blues Band",
            "year": "2026",
        }:
            return httpx.Response(
                200,
                text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Andrew Michael Blues Band 2026 FLAC</title>
      <guid>music-guid</guid>
      <link>magnet:?xt=urn:btih:MUSIC111</link>
      <torznab:attr name="jackettindexer" value="musictracker" />
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
            query="Andrew Michael Blues Band",
            media_type=MediaType.MUSIC,
            artist="Andrew Michael",
            album="Blues Band",
            release_year="2026",
        )
    )

    assert [item.title for item in result.results] == ["Andrew Michael Blues Band 2026 FLAC"]
    assert seen_requests == [
        (
            "/api/v2.0/indexers/all/results/torznab/api",
            {
                "apikey": "secret",
                "t": "indexers",
                "configured": "true",
            },
        ),
        (
            "/api/v2.0/indexers/musictracker/results/torznab/api",
            {
                "apikey": "secret",
                "t": "music",
                "q": "Andrew Michael Blues Band",
                "cat": "3000",
                "artist": "Andrew Michael",
                "album": "Blues Band",
                "year": "2026",
            },
        ),
    ]
    assert result.fallback_request_variants == []
    assert result.fallback_results == []


def test_jackett_client_precise_title_primary_keeps_non_exact_title_rows_available_for_fallback() -> (
    None
):
    seen_requests: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = {key: value for key, value in request.url.params.multi_items()}
        seen_requests.append((path, params))

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params.get(
            "apikey"
        ) == "secret" and params.get("t") == "tvsearch" and params.get("imdbid") == "tt8599532":
            return httpx.Response(200, text="<rss><channel /></rss>")

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "indexers",
            "configured": "true",
        }:
            return httpx.Response(
                200,
                text="""
<indexers>
  <indexer id="alpha">
    <caps>
      <searching>
        <tv-search available="yes" supportedParams="q,imdbid" />
      </searching>
    </caps>
  </indexer>
</indexers>
""",
            )

        if path == "/api/v2.0/indexers/alpha/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "tvsearch",
            "imdbid": "tt8599532",
        }:
            return httpx.Response(
                200,
                text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Young Sherlock S01E01 2160p HDR10 WEB-DL</title>
      <guid>young-sherlock-primary-guid</guid>
      <link>magnet:?xt=urn:btih:YOUNG111</link>
      <torznab:attr name="jackettindexer" value="alpha" />
      <torznab:attr name="category" value="5000" />
    </item>
  </channel>
</rss>
""",
            )

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params.get(
            "apikey"
        ) == "secret" and params.get("t") in {"tvsearch", "search"} and params.get("q") == "Young Sherlock":
            return httpx.Response(
                200,
                text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Young Sherlock S01E02 2160p HDR WEB-DL</title>
      <guid>young-sherlock-exact-guid</guid>
      <link>magnet:?xt=urn:btih:YOUNG222</link>
      <torznab:attr name="jackettindexer" value="beta" />
      <torznab:attr name="category" value="5000" />
    </item>
    <item>
      <title>Young Sherlock Test Cut 2160p HDR10 WEB-DL</title>
      <guid>young-sherlock-fallback-guid</guid>
      <link>magnet:?xt=urn:btih:YOUNG333</link>
      <torznab:attr name="jackettindexer" value="gamma" />
      <torznab:attr name="category" value="5000" />
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
            query="Young Sherlock",
            media_type="series",
            imdb_id="tt8599532",
            imdb_id_only=True,
            keywords_all=["test cut"],
            keywords_any=["2160p", "hdr", "hdr10"],
            keywords_any_groups=[["2160p"], ["hdr", "hdr10"]],
            primary_keywords_any=["2160p", "hdr", "hdr10"],
            primary_keywords_any_groups=[["2160p"], ["hdr", "hdr10"]],
        )
    )

    assert (
        "/api/v2.0/indexers/all/results/torznab/api",
        {
            "apikey": "secret",
            "t": "indexers",
            "configured": "true",
        },
    ) in seen_requests
    assert (
        "/api/v2.0/indexers/alpha/results/torznab/api",
        {
            "apikey": "secret",
            "t": "tvsearch",
            "imdbid": "tt8599532",
        },
    ) in seen_requests
    assert [item.title for item in result.results] == [
        "Young Sherlock S01E01 2160p HDR10 WEB-DL",
        "Young Sherlock S01E02 2160p HDR WEB-DL",
    ]
    assert any('q="Young Sherlock"' in item for item in result.fallback_request_variants)
    assert [item.title for item in result.fallback_results] == [
        "Young Sherlock Test Cut 2160p HDR10 WEB-DL"
    ]


def test_jackett_client_falls_back_to_broad_title_search_when_tv_indexers_do_not_support_input_imdb() -> (
    None
):
    seen_requests: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = {key: value for key, value in request.url.params.multi_items()}
        seen_requests.append((path, params))

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params.get(
            "apikey"
        ) == "secret" and params.get("t") == "tvsearch" and params.get("imdbid") == "tt17676654":
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

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params.get(
            "apikey"
        ) == "secret" and params.get("t") in {"tvsearch", "search"} and params.get("q") == "American Classic":
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

    assert (
        "/api/v2.0/indexers/all/results/torznab/api",
        {
            "apikey": "secret",
            "t": "indexers",
            "configured": "true",
        },
    ) in seen_requests
    assert result.request_variants[0].startswith("t=tvsearch imdbid=tt17676654")
    assert any('q="American Classic"' in item for item in result.request_variants)
    assert [item.title for item in result.results] == ["American Classic S01E01 1080p"]
    assert result.fallback_request_variants == []
    assert result.fallback_results == []


def test_jackett_client_uses_broad_title_fallback_when_imdb_first_returns_no_results_for_subtitle_title() -> (
    None
):
    seen_requests: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = {key: value for key, value in request.url.params.multi_items()}
        seen_requests.append((path, params))

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params.get(
            "apikey"
        ) == "secret" and params.get("t") == "tvsearch" and params.get("imdbid") == "tt22074164":
            return httpx.Response(200, text="<rss><channel /></rss>")

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params == {
            "apikey": "secret",
            "t": "indexers",
            "configured": "true",
        }:
            return httpx.Response(200, text="<indexers />")

        empty_query_variants = {"Jury Duty Presents: Company Retreat", "Jury Duty Presents Company Retreat", "Jury Duty Presents"}
        if path == "/api/v2.0/indexers/all/results/torznab/api" and params.get("apikey") == "secret" and params.get("t") in {"tvsearch", "search"} and params.get("q") in empty_query_variants:
            return httpx.Response(200, text="<rss><channel /></rss>")

        if path == "/api/v2.0/indexers/all/results/torznab/api" and params.get(
            "apikey"
        ) == "secret" and params.get("t") in {"tvsearch", "search"} and params.get("q") == "Company Retreat":
            return httpx.Response(
                200,
                text="""
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Jury Duty Presents Company Retreat S01E01 1080p</title>
      <guid>jury-duty-guid</guid>
      <link>magnet:?xt=urn:btih:JURYDUTY123</link>
      <torznab:attr name="jackettindexer" value="rutracker" />
      <torznab:attr name="category" value="5000" />
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
            query="Jury Duty Presents: Company Retreat",
            media_type="series",
            imdb_id="tt22074164",
            imdb_id_only=True,
        )
    )

    assert any(
        params.get("q") == "Company Retreat"
        for path, params in seen_requests
        if path == "/api/v2.0/indexers/all/results/torznab/api"
    )
    assert [item.title for item in result.results] == [
        "Jury Duty Presents Company Retreat S01E01 1080p"
    ]
    assert result.fallback_results == []
    assert any('q="Company Retreat"' in item for item in result.request_variants)


def test_jackett_client_uses_single_remote_query_when_optional_groups_are_present() -> None:
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

    assert seen_queries
    assert set(seen_queries) == {"Example"}


def test_build_search_request_from_rule_uses_structured_terms_not_raw_regex() -> None:
    rule = Rule(
        rule_name="Andrew Michael Blues Band",
        content_name="Andrew Michael Blues Band",
        normalized_title="Andrew Michael Blues Band",
        imdb_id="tt7654321",
        media_type=MediaType.MUSIC,
        quality_profile=QualityProfile.CUSTOM,
        include_release_year=True,
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


def test_build_search_request_from_rule_carries_series_episode_floor() -> None:
    rule = Rule(
        rule_name="Shrinking",
        content_name="Shrinking",
        normalized_title="Shrinking",
        imdb_id="tt15677150",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        start_season=3,
        start_episode=7,
    )

    payload, ignored_full_regex = build_search_request_from_rule(rule)

    assert payload.query == "Shrinking"
    assert payload.imdb_id == "tt15677150"
    assert payload.season_number == 3
    assert payload.episode_number == 7
    assert ignored_full_regex is False


def test_build_search_request_from_rule_uses_watched_progress_for_keep_searching_existing() -> None:
    rule = Rule(
        rule_name="The Miniature Wife",
        content_name="The Miniature Wife",
        normalized_title="The Miniature Wife",
        imdb_id="tt31909098",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        start_season=1,
        start_episode=11,
        jellyfin_search_existing_unseen=True,
        jellyfin_watched_episode_numbers=["S01E01", "S01E02"],
        jellyfin_existing_episode_numbers=[
            "S01E03",
            "S01E04",
            "S01E05",
            "S01E06",
            "S01E07",
            "S01E08",
            "S01E09",
            "S01E10",
        ],
    )

    payload, ignored_full_regex = build_search_request_from_rule(rule)

    assert payload.query == "The Miniature Wife"
    assert payload.imdb_id == "tt31909098"
    assert payload.season_number == 1
    assert payload.episode_number == 2
    assert ignored_full_regex is False


def test_build_search_request_from_rule_maps_pipe_alternatives_to_any_groups() -> None:
    rule = Rule(
        rule_name="Pipe Terms",
        content_name="Pipe Terms",
        normalized_title="Pipe Terms",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.CUSTOM,
        additional_includes="aaa, bbb|ccc, ddd|eee",
    )

    payload, ignored_full_regex = build_search_request_from_rule(rule)

    assert payload.query == "Pipe Terms"
    assert payload.keywords_all == ["aaa"]
    assert payload.keywords_any_groups == [["bbb", "ccc"], ["ddd", "eee"]]
    assert ignored_full_regex is False


def test_build_search_request_from_rule_skips_release_year_when_not_enabled() -> None:
    rule = Rule(
        rule_name="Ghosts",
        content_name="Ghosts",
        normalized_title="Ghosts",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.HD_1080P,
        include_release_year=False,
        release_year="2025",
    )

    payload, ignored_full_regex = build_search_request_from_rule(rule)

    assert payload.query == "Ghosts"
    assert payload.release_year is None
    assert ignored_full_regex is False


def test_build_search_request_from_rule_ignores_legacy_none_override() -> None:
    rule = Rule(
        rule_name="Ghosts GB",
        content_name="Ghosts",
        normalized_title="Ghosts",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.HD_1080P,
        quality_include_tokens=["1080p"],
        must_contain_override="None",
    )

    payload, ignored_full_regex = build_search_request_from_rule(rule)

    assert payload.query == "Ghosts"
    assert payload.keywords_all == []
    assert payload.keywords_any_groups == [["1080p"]]
    assert ignored_full_regex is False


def test_build_search_request_from_rule_groups_quality_terms_by_taxonomy_group() -> None:
    rule = Rule(
        rule_name="3 Body Problem",
        content_name="3 Body Problem",
        normalized_title="3 Body Problem",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.CUSTOM,
        quality_include_tokens=["ultra_hd", "uhd", "2160p", "4k", "hdr"],
    )

    payload, ignored_full_regex = build_search_request_from_rule(rule)

    assert payload.query == "3 Body Problem"
    assert payload.keywords_any_groups == [["ultra hd", "uhd", "2160p", "4k"], ["hdr", "hdr10"]]
    assert payload.keywords_any == ["ultra hd", "uhd", "2160p", "4k", "hdr", "hdr10"]
    assert ignored_full_regex is False


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
    assert payload.keywords_any_groups == [
        [
            "codec0",
            "codec1",
            "codec2",
            "codec3",
            "codec4",
            "codec5",
            "codec6",
            "codec7",
            "codec8",
            "codec9",
        ]
    ]
    assert ignored_full_regex is False
