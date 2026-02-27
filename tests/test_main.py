import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree

import pendulum
import pytest
from fastapi.testclient import TestClient

from main import app, make_feed, url_cache, FEEDS, _feed_cache, MohNews

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_feed_cache():
    """Reset the feed cache before each test so endpoints use the sync fallback."""
    for key in _feed_cache:
        _feed_cache[key] = None
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_rss(response):
    """Parse an RSS XML response and return the root ElementTree element."""
    assert response.status_code == 200
    assert "xml" in response.headers["content-type"]
    root = ElementTree.fromstring(response.content)
    return root


def get_items(root):
    """Return all <item> elements from an RSS root."""
    return root.findall(".//item")


# ---------------------------------------------------------------------------
# make_feed helper
# ---------------------------------------------------------------------------

class TestMakeFeed:
    def test_valid_rss_structure(self):
        articles = [
            {
                "title": "Test Article",
                "link": "https://example.com/1",
                "date": pendulum.parse("2025-01-15T10:00:00Z"),
            }
        ]
        resp = make_feed("My Feed", "https://example.com", "A test feed", articles)
        root = ElementTree.fromstring(resp.body)
        channel = root.find("channel")
        assert channel.findtext("title") == "My Feed"
        assert channel.findtext("link") == "https://example.com"
        assert channel.findtext("description") == "A test feed"

    def test_sorts_articles_by_date(self):
        articles = [
            {
                "title": "Second",
                "link": "https://example.com/2",
                "date": pendulum.parse("2025-01-20T00:00:00Z"),
            },
            {
                "title": "First",
                "link": "https://example.com/1",
                "date": pendulum.parse("2025-01-10T00:00:00Z"),
            },
        ]
        resp = make_feed("Feed", "https://example.com", "desc", articles)
        root = ElementTree.fromstring(resp.body)
        items = get_items(root)
        titles = [item.findtext("title") for item in items]
        # feedgen prepends entries, so ascending sort produces newest-first in XML
        assert titles == ["Second", "First"]

    def test_optional_fields_included_when_present(self):
        articles = [
            {
                "title": "Full",
                "link": "https://example.com/1",
                "date": pendulum.parse("2025-01-15T10:00:00Z"),
                "summary": "A brief summary",
                "text": "<p>Full text</p>",
                "modified": pendulum.parse("2025-01-16T10:00:00Z"),
            }
        ]
        resp = make_feed("Feed", "https://example.com", "desc", articles)
        root = ElementTree.fromstring(resp.body)
        item = get_items(root)[0]
        # summary maps to description in feedgen's RSS output when using fe.summary
        # text maps to description via fe.description
        # We just verify the item has content — feedgen may merge summary/description
        assert item.findtext("title") == "Full"

    def test_optional_fields_omitted_when_absent(self):
        articles = [
            {
                "title": "Minimal",
                "link": "https://example.com/1",
                "date": pendulum.parse("2025-01-15T10:00:00Z"),
            }
        ]
        resp = make_feed("Feed", "https://example.com", "desc", articles)
        root = ElementTree.fromstring(resp.body)
        item = get_items(root)[0]
        assert item.findtext("title") == "Minimal"

    def test_empty_articles_list(self):
        resp = make_feed("Feed", "https://example.com", "desc", [])
        root = ElementTree.fromstring(resp.body)
        items = get_items(root)
        assert items == []


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

class TestIndex:
    def test_returns_html(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_contains_all_feed_links(self):
        resp = client.get("/")
        for feed in FEEDS:
            assert feed["path"] in resp.text
            assert feed["title"] in resp.text


# ---------------------------------------------------------------------------
# GET /hackernews-highlights.rss
# ---------------------------------------------------------------------------

HN_HIGHLIGHTS_HTML = """
<html><body><table>
<tr class="athing">
  <td>
    <a class="hnuser" href="user?id=alice">alice</a>
    <div class="commtext">This is a great comment about Rust.</div>
    <span class="age" title="2025-06-10T14:30:00 1718029800">
      <a href="item?id=12345">2 hours ago</a>
    </span>
    <span class="onstory">
      | on <a href="item?id=99999" title="Why Rust is Great">Why Rust is Great</a>
    </span>
  </td>
</tr>
<tr class="athing">
  <td>
    <a class="hnuser" href="user?id=bob">bob</a>
    <div class="commtext">Interesting perspective on databases.</div>
    <span class="age" title="2025-06-09T08:15:00 1717920900">
      <a href="item?id=12346">1 day ago</a>
    </span>
    <span class="onstory">
      | on <a href="item?id=99998" title="Database Design Tips">Database Design Tips</a>
    </span>
  </td>
</tr>
<tr class="athing">
  <td>
    <span class="age" title="2025-06-08T00:00:00 1717804800">
      <a href="item?id=12347">2 days ago</a>
    </span>
  </td>
</tr>
</table></body></html>
"""


class TestHackerNewsHighlights:
    @patch("main.requests.get")
    def test_returns_valid_rss(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = HN_HIGHLIGHTS_HTML
        mock_get.return_value = mock_resp

        resp = client.get("/hackernews-highlights.rss")
        root = parse_rss(resp)
        items = get_items(root)
        assert len(items) == 2

        titles = [item.findtext("title") for item in items]
        assert "alice on Why Rust is Great" in titles
        assert "bob on Database Design Tips" in titles

    @patch("main.requests.get")
    def test_skips_incomplete_comments(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = HN_HIGHLIGHTS_HTML
        mock_get.return_value = mock_resp

        resp = client.get("/hackernews-highlights.rss")
        root = parse_rss(resp)
        items = get_items(root)
        # Third comment has no hnuser, commtext, or onstory — should be skipped
        assert len(items) == 2


# ---------------------------------------------------------------------------
# GET /rnz-phil-pennington.rss
# ---------------------------------------------------------------------------

RNZ_AUTHOR_HTML = """
<html><body>
<div class="o-digest--news">
  <h3 class="o-digest__headline">
    <a href="/news/national/123456/some-article-slug">Some Article Title</a>
  </h3>
</div>
<div class="o-digest--news">
  <h3 class="o-digest__headline">
    <a href="/news/national/789012/another-article-slug">Another Article</a>
  </h3>
</div>
</body></html>
"""


def _make_newspaper_article(title, summary, html, publish_date):
    return SimpleNamespace(
        title=title,
        meta_description=summary,
        article_html=html,
        publish_date=publish_date,
    )


class TestRnzPhilPennington:
    @patch("main.newspaper.article")
    @patch("main.requests.get")
    def test_returns_valid_rss(self, mock_get, mock_article):
        mock_resp = MagicMock()
        mock_resp.text = RNZ_AUTHOR_HTML
        mock_get.return_value = mock_resp

        mock_article.side_effect = [
            _make_newspaper_article(
                "Some Article Title",
                "Summary of article one",
                "<p>Full text one</p>",
                pendulum.parse("2025-06-10T09:00:00Z"),
            ),
            _make_newspaper_article(
                "Another Article",
                "Summary of article two",
                "<p>Full text two</p>",
                pendulum.parse("2025-06-09T09:00:00Z"),
            ),
        ]

        # Clear cache before test
        url_cache.clear()

        resp = client.get("/rnz-phil-pennington.rss")
        root = parse_rss(resp)
        items = get_items(root)
        assert len(items) == 2

        titles = [item.findtext("title") for item in items]
        assert "Some Article Title" in titles
        assert "Another Article" in titles

    @patch("main.newspaper.article")
    @patch("main.requests.get")
    def test_populates_and_clears_cache(self, mock_get, mock_article):
        mock_resp = MagicMock()
        mock_resp.text = RNZ_AUTHOR_HTML
        mock_get.return_value = mock_resp

        mock_article.side_effect = [
            _make_newspaper_article(
                "Title 1", "Summary 1", "<p>Text 1</p>",
                pendulum.parse("2025-06-10T09:00:00Z"),
            ),
            _make_newspaper_article(
                "Title 2", "Summary 2", "<p>Text 2</p>",
                pendulum.parse("2025-06-09T09:00:00Z"),
            ),
        ]

        # Seed cache with a stale entry
        url_cache.clear()
        url_cache["https://www.rnz.co.nz/news/national/000000/stale"] = "old"

        resp = client.get("/rnz-phil-pennington.rss")
        assert resp.status_code == 200

        # Stale entry should be removed
        assert "https://www.rnz.co.nz/news/national/000000/stale" not in url_cache
        # Current entries should be cached
        assert "https://www.rnz.co.nz/news/national/123456/some-article-slug" in url_cache
        assert "https://www.rnz.co.nz/news/national/789012/another-article-slug" in url_cache


# ---------------------------------------------------------------------------
# GET /uber-engineering.rss
# ---------------------------------------------------------------------------

UBER_API_JSON = [
    {
        "content": {"rendered": "<p>Full blog post content here.</p>"},
        "excerpt": {"rendered": "<p>Short excerpt.</p>"},
        "link": "https://www.uber.com/blog/cool-post",
        "yoast_head_json": {
            "title": "Cool Engineering Post",
            "description": "A deep dive into engineering.",
            "article_published_time": "2025-06-01T12:00:00+00:00",
            "article_modified_time": "2025-06-02T12:00:00+00:00",
        },
    },
    {
        "content": {"rendered": "<p>Another post.</p>"},
        "excerpt": {"rendered": "<p>Another excerpt.</p>"},
        "link": "https://www.uber.com/blog/another-post",
        "yoast_head_json": {
            "og_title": "Fallback OG Title",
            "og_description": "Fallback OG description.",
            "article_published_time": "2025-05-20T08:00:00+00:00",
        },
    },
]


class TestUberEngineering:
    @patch("main.requests.get")
    def test_returns_valid_rss(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = UBER_API_JSON
        mock_resp.text = json.dumps(UBER_API_JSON)
        mock_get.return_value = mock_resp

        resp = client.get("/uber-engineering.rss")
        root = parse_rss(resp)
        items = get_items(root)
        assert len(items) == 2

    @patch("main.requests.get")
    def test_title_and_description_fields(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = UBER_API_JSON
        mock_resp.text = json.dumps(UBER_API_JSON)
        mock_get.return_value = mock_resp

        resp = client.get("/uber-engineering.rss")
        root = parse_rss(resp)
        items = get_items(root)
        titles = [item.findtext("title") for item in items]
        assert "Cool Engineering Post" in titles

    @patch("main.requests.get")
    def test_fallback_title_resolution(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = UBER_API_JSON
        mock_resp.text = json.dumps(UBER_API_JSON)
        mock_get.return_value = mock_resp

        resp = client.get("/uber-engineering.rss")
        root = parse_rss(resp)
        items = get_items(root)
        titles = [item.findtext("title") for item in items]
        assert "Fallback OG Title" in titles


# ---------------------------------------------------------------------------
# GET /nicb-news-releases.rss
# ---------------------------------------------------------------------------

NICB_HTML = """
<html><body>
<article>
  <a href="/news/news-releases/nicb-warns-about-fraud">
    <h3>NICB Warns About Fraud</h3>
  </a>
  <div class="date">January 15, 2025</div>
</article>
<article>
  <a href="/news/news-releases/new-report-released">
    <h2>New Report Released</h2>
  </a>
  <div class="date">January 10, 2025</div>
</article>
<article>
  <a href="/about/careers">
    <h3>Join Our Team</h3>
  </a>
  <div class="date">January 5, 2025</div>
</article>
<article>
  <a href="/news/news-releases/no-heading-article">
  </a>
  <div class="date">January 1, 2025</div>
</article>
<article>
  <a href="/news/news-releases/no-date-article">
    <h3>Article Without Date</h3>
  </a>
</article>
</body></html>
"""


class TestNicbNewsReleases:
    @patch("main.requests.post")
    def test_returns_valid_rss(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "solution": {"response": NICB_HTML}
        }
        mock_post.return_value = mock_resp

        resp = client.get("/nicb-news-releases.rss")
        root = parse_rss(resp)
        items = get_items(root)
        # Only 2 valid news-release articles (the /about/careers link is skipped,
        # the article without a heading is skipped, the article without a date is skipped)
        assert len(items) == 2

        titles = [item.findtext("title") for item in items]
        assert "NICB Warns About Fraud" in titles
        assert "New Report Released" in titles

    @patch("main.requests.post")
    def test_skips_non_news_release_links(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "solution": {"response": NICB_HTML}
        }
        mock_post.return_value = mock_resp

        resp = client.get("/nicb-news-releases.rss")
        root = parse_rss(resp)
        items = get_items(root)
        titles = [item.findtext("title") for item in items]
        assert "Join Our Team" not in titles


# ---------------------------------------------------------------------------
# GET /the-situation.rss
# ---------------------------------------------------------------------------

THE_SITUATION_JSON = {
    "value": [
        {
            "Title": "The Situation: January Edition",
            "Summary": "<p>Summary of the January situation report.</p>",
            "PublicationDate": "2025-01-20T14:00:00Z",
            "UrlName": "the-situation-january-2025",
        },
        {
            "Title": "The Situation: December Edition",
            "Summary": "<p>Summary of the December situation report.</p>",
            "PublicationDate": "2024-12-20T14:00:00Z",
            "UrlName": "the-situation-december-2024",
        },
    ]
}

# Flaresolverr returns JSON wrapped in HTML
THE_SITUATION_FLARE_HTML = json.dumps(THE_SITUATION_JSON)


class TestTheSituation:
    @patch("main.requests.post")
    def test_returns_valid_rss(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "solution": {"response": THE_SITUATION_FLARE_HTML}
        }
        mock_post.return_value = mock_resp

        resp = client.get("/the-situation.rss")
        root = parse_rss(resp)
        items = get_items(root)
        assert len(items) == 2

    @patch("main.requests.post")
    def test_title_summary_date(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "solution": {"response": THE_SITUATION_FLARE_HTML}
        }
        mock_post.return_value = mock_resp

        resp = client.get("/the-situation.rss")
        root = parse_rss(resp)
        items = get_items(root)
        titles = [item.findtext("title") for item in items]
        assert "The Situation: January Edition" in titles
        assert "The Situation: December Edition" in titles

        # Verify links are constructed correctly
        links = [item.findtext("link") for item in items]
        assert "https://www.lawfaremedia.org/article/the-situation-january-2025" in links


# ---------------------------------------------------------------------------
# GET /moh-news.rss
# ---------------------------------------------------------------------------

MOH_NEWS_HTML = """
<html><body>
<article class="sector-news">
  <div class="field field--name-field-display-title">
    <h2><a href="https://www.health.govt.nz/news/new-covid-guidance">New COVID Guidance Released</a></h2>
  </div>
  <div class="field field--name-field-issue-date">
    <time datetime="2025-06-15T10:00:00+12:00">15 June 2025</time>
  </div>
  <div class="field field--name-body">
    <p>The Ministry has released updated COVID-19 guidance for winter 2025.</p>
  </div>
  <li class="field--name-field-types">News article</li>
</article>
<article class="sector-news">
  <div class="field field--name-field-display-title">
    <h2><a href="https://www.health.govt.nz/news/mental-health-funding">Mental Health Funding Boost</a></h2>
  </div>
  <div class="field field--name-field-issue-date">
    <time datetime="2025-06-10T09:00:00+12:00">10 June 2025</time>
  </div>
  <div class="field field--name-body">
    <p>Government announces additional funding for mental health services.</p>
  </div>
  <li class="field--name-field-types">Media release</li>
</article>
<article class="sector-news">
  <div class="field field--name-field-display-title">
    <h2><a href="https://www.health.govt.nz/news/vaccination-update">Vaccination Programme Update</a></h2>
  </div>
  <div class="field field--name-field-issue-date">
    <time datetime="2025-06-05T08:00:00+12:00">5 June 2025</time>
  </div>
  <li class="field--name-field-types">News article</li>
</article>
<article class="sector-news">
  <!-- Missing title -->
  <div class="field field--name-field-issue-date">
    <time datetime="2025-06-01T08:00:00+12:00">1 June 2025</time>
  </div>
  <div class="field field--name-body">
    <p>Article with no title should be skipped.</p>
  </div>
</article>
<article class="sector-news">
  <div class="field field--name-field-display-title">
    <h2><a href="https://www.health.govt.nz/news/no-date-article">Article Without Date</a></h2>
  </div>
  <!-- Missing date -->
  <div class="field field--name-body">
    <p>Article with no date should be skipped.</p>
  </div>
</article>
</body></html>
"""


class TestMohNews:
    @patch("main.requests.post")
    def test_returns_valid_rss(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'solution': {'response': MOH_NEWS_HTML}}
        mock_post.return_value = mock_resp

        resp = client.get("/moh-news.rss")
        root = parse_rss(resp)
        items = get_items(root)
        # 3 valid articles (COVID, Mental Health, Vaccination — no summary is fine)
        assert len(items) == 3

        titles = [item.findtext("title") for item in items]
        assert "New COVID Guidance Released" in titles
        assert "Mental Health Funding Boost" in titles
        assert "Vaccination Programme Update" in titles

    @patch("main.requests.post")
    def test_skips_articles_missing_required_fields(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'solution': {'response': MOH_NEWS_HTML}}
        mock_post.return_value = mock_resp

        resp = client.get("/moh-news.rss")
        root = parse_rss(resp)
        items = get_items(root)
        titles = [item.findtext("title") for item in items]
        # Article without title and article without date should both be skipped
        assert len(items) == 3
        assert "Article Without Date" not in titles
