import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager

from bs4 import BeautifulSoup
from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse
from feedgen.feed import FeedGenerator
from json_repair import repair_json
import newspaper
import pendulum
import requests

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30
FLARESOLVERR_HOST = os.environ.get('FLARESOLVERR_HOST', 'flaresolverr')
REFRESH_INTERVAL = int(os.environ.get('REFRESH_INTERVAL', '900'))

# We fetch some article sources to figure more info but we don't want to fetch for every run
url_cache = {}


def make_feed(title, link, description, articles):
    """Build an RSS feed from a list of article dicts and return a Response."""
    fg = FeedGenerator()
    fg.title(title)
    fg.link(href=link)
    fg.description(description)

    articles.sort(key=lambda x: x['date'])

    for article in articles:
        fe = fg.add_entry()
        fe.id(article['link'])
        fe.title(article['title'])
        fe.pubDate(pubDate=article['date'])
        fe.link(href=article['link'])
        if 'summary' in article:
            fe.summary(summary=article['summary'])
        if 'text' in article:
            fe.description(description=str(article['text']), isSummary=False)
        if 'modified' in article:
            fe.updated(updated=article['modified'])

    rssfeed = fg.rss_str(pretty=True)
    return Response(content=rssfeed, media_type="application/xml")


class FeedSource(ABC):
    path: str
    title: str
    link: str
    description: str
    url: str
    access: str = "direct"

    def fetch_raw(self) -> str:
        if self.access == "direct":
            return requests.get(self.url, timeout=REQUEST_TIMEOUT).text
        elif self.access == "flaresolverr":
            flare_url = f"http://{FLARESOLVERR_HOST}:8191/v1"
            data = {"cmd": "request.get", "url": self.url, "maxTimeout": 60000}
            r = requests.post(flare_url, headers={"Content-Type": "application/json"},
                              json=data, timeout=90)
            return r.json()['solution']['response']
        raise NotImplementedError(f"Access type not implemented: {self.access}")

    @abstractmethod
    def extract_articles(self, raw_text: str) -> list[dict]:
        ...

    def build_feed(self) -> bytes:
        raw = self.fetch_raw()
        articles = self.extract_articles(raw)
        return make_feed(self.title, self.link, self.description, articles).body


class HackerNewsHighlights(FeedSource):
    path = "/hackernews-highlights.rss"
    title = "Hacker News Highlights"
    link = "https://news.ycombinator.com/highlights"
    description = "Interesting comments"
    url = "https://news.ycombinator.com/highlights"
    access = "direct"

    def extract_articles(self, raw_text):
        soup = BeautifulSoup(raw_text, 'html.parser')
        raw_comments = soup.find_all("tr", class_="athing")
        comments = []

        for comment in raw_comments:
            try:
                author_el = comment.find("a", class_="hnuser")
                text_el = comment.find("div", class_="commtext")
                age_el = comment.find("span", class_="age")
                story_el = comment.find("span", class_="onstory")

                if not all([author_el, text_el, age_el, story_el]):
                    continue

                author = author_el.text
                text = text_el
                date_unparsed = age_el.attrs['title']
                date = pendulum.from_format(date_unparsed, 'YYYY-MM-DD[T]HH:mm:SS X')
                link_segment = age_el.a.attrs['href']
                story_title = story_el.a.attrs['title']

                comments.append({
                    'title': f"{author} on {story_title}",
                    'text': text,
                    'date': date,
                    'link': f"https://news.ycombinator.com/{link_segment}"
                })
            except Exception:
                logger.exception("Failed to parse HN highlights comment")
                continue

        return comments


class RnzPhilPennington(FeedSource):
    path = "/rnz-phil-pennington.rss"
    title = "RNZ - Phil Pennington"
    link = "https://www.rnz.co.nz/authors/phil-pennington"
    description = "Articles from Phil Pennington"
    url = "https://www.rnz.co.nz/authors/phil-pennington"
    access = "direct"

    def extract_articles(self, raw_text):
        soup = BeautifulSoup(raw_text, 'html.parser')
        raw_articles = soup.find_all("div", class_="o-digest--news")
        articles = []

        for raw_article in raw_articles:
            link_segment = raw_article.find('h3', class_='o-digest__headline').a.attrs['href']
            link = f"https://www.rnz.co.nz{link_segment}"
            cached = url_cache.get(link, False)
            if not cached:
                cached = newspaper.article(link)
                url_cache[link] = cached

            text = cached.article_html
            title = cached.title
            logger.debug("Parsed RNZ article: %s", title)
            date = cached.publish_date
            summary = cached.meta_description

            articles.append({
                'title': title,
                'summary': summary,
                'text': text,
                'date': date,
                'link': link
            })

        # clear cache with articles that have dropped out of feed
        links = set(a['link'] for a in articles)
        cached_links = set(url_cache.keys())
        for stale_link in cached_links - links:
            del url_cache[stale_link]

        return articles


class UberEngineering(FeedSource):
    path = "/uber-engineering.rss"
    title = "Uber Engineering"
    link = "https://www.uber.com/blog/engineering/"
    description = "Articles from Uber Engineering"
    url = "https://blogapi.uber.com/wp-json/wp/v2/posts?languages=2257&categories=221148&page=1&per_page=25"
    access = "direct"

    def extract_articles(self, raw_text):
        data = json.loads(raw_text)
        articles = []

        for story in data:
            raw_content = story.get('content', {}).get('rendered', '')
            text = BeautifulSoup(raw_content, 'html.parser').__str__().strip()

            raw_description = story.get('excerpt', {}).get('rendered', '')
            description = BeautifulSoup(raw_description, 'html.parser').text.strip()

            link = story.get('link')

            article_meta = story.get('yoast_head_json', {})
            title = article_meta.get('title')
            if title is None:
                title = article_meta.get('og_title')
            if title is None:
                title = article_meta.get('twitter_title')

            description = article_meta.get('description')
            if description is None:
                description = article_meta.get('og_description')
            if description is None:
                description = article_meta.get('twitter_description')
            if description is None:
                description = ""

            published = article_meta.get('article_published_time')
            published_at = pendulum.parse(published)
            modified = article_meta.get('article_modified_time')
            modified_at = published_at
            if modified is not None:
                modified_at = pendulum.parse(modified)

            articles.append({
                'title': title,
                'summary': description,
                'text': text,
                'date': published_at,
                'modified': modified_at,
                'link': link
            })

        return articles


class NicbNewsReleases(FeedSource):
    path = "/nicb-news-releases.rss"
    title = "NICB News Releases"
    link = "https://www.nicb.org/news/news-releases"
    description = "News releases from the National Insurance Crime Bureau"
    url = "https://www.nicb.org/news/news-releases"
    access = "flaresolverr"

    def extract_articles(self, raw_text):
        soup = BeautifulSoup(raw_text, 'html.parser')
        raw_articles = soup.find_all("article")
        articles = []

        for article in raw_articles:
            link_el = article.find('a')
            if not link_el or not link_el.get('href'):
                continue

            link_segment = link_el.get('href')
            if not link_segment.startswith('/news/news-releases/'):
                continue

            link = f"https://www.nicb.org{link_segment}"

            heading = article.find(['h2', 'h3', 'h4'])
            if not heading:
                continue
            title = heading.get_text(strip=True)

            date_el = article.find('div', class_='date')
            if not date_el:
                continue
            date_text = date_el.get_text(strip=True)

            try:
                date = pendulum.parse(date_text, strict=False)
            except Exception:
                continue

            articles.append({
                'title': title,
                'date': date,
                'link': link
            })

        return articles


class TheSituation(FeedSource):
    path = "/the-situation.rss"
    title = "The Situation by Benjamin Wittes"
    link = "https://www.lawfaremedia.org/contributors/bwittes"
    description = "Issues of The Situation"
    url = "https://www.lawfaremedia.org/sfapi/blog-posts/blogposts?$select=Title,Summary,PublicationDate,UrlName,subtopic,toptopics,Tags&$filter=subtopic/any(t:t%20eq%20e0893ae4-5071-430d-a352-616fbf370fd1)&$orderby=PublicationDate%20desc"
    access = "flaresolverr"

    def extract_articles(self, raw_text):
        soup = BeautifulSoup(raw_text, 'html.parser')
        text = repair_json(soup.text)
        data = json.loads(text).get('value', [])
        articles = []

        for story in data:
            soup = BeautifulSoup(story['Summary'], 'html.parser')
            title = story['Title']
            date = pendulum.parse(story['PublicationDate'])
            link = f"https://www.lawfaremedia.org/article/{story['UrlName']}"

            articles.append({
                'title': title,
                'summary': soup.text,
                'date': date,
                'link': link
            })

        return articles


FEEDS_REGISTRY: list[FeedSource] = [
    HackerNewsHighlights(),
    RnzPhilPennington(),
    UberEngineering(),
    NicbNewsReleases(),
    TheSituation(),
]

# Backward compat — tests import this
FEEDS = [{"path": f.path, "title": f.title} for f in FEEDS_REGISTRY]

# path -> RSS XML bytes, None = not yet cached
_feed_cache: dict[str, bytes | None] = {f.path: None for f in FEEDS_REGISTRY}


async def _refresh_all_feeds():
    for feed in FEEDS_REGISTRY:
        try:
            xml_bytes = await asyncio.to_thread(feed.build_feed)
            _feed_cache[feed.path] = xml_bytes
        except Exception:
            logger.exception("Failed to refresh %s", feed.path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async def _loop():
        while True:
            await _refresh_all_feeds()
            await asyncio.sleep(REFRESH_INTERVAL)

    task = asyncio.create_task(_loop())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


def _make_feed_endpoint(feed: FeedSource):
    def endpoint():
        cached = _feed_cache.get(feed.path)
        if cached is not None:
            return Response(content=cached, media_type="application/xml")
        # Cache miss (startup still running or failed) — sync fallback
        try:
            xml_bytes = feed.build_feed()
            _feed_cache[feed.path] = xml_bytes
            return Response(content=xml_bytes, media_type="application/xml")
        except Exception:
            logger.exception("Sync fallback failed for %s", feed.path)
            return Response(status_code=503)
    return endpoint


@app.get("/", response_class=HTMLResponse)
def root():
    items = "".join(
        f'<li><a href="{f.path}">{f.title}</a></li>' for f in FEEDS_REGISTRY
    )
    return f"<html><body><h1>RSS Depot</h1><ul>{items}</ul></body></html>"


for _feed in FEEDS_REGISTRY:
    app.get(_feed.path)(_make_feed_endpoint(_feed))
