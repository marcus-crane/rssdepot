from typing import Any
from django.contrib.syndication.views import Feed as DjangoFeed
from django.utils.feedgenerator import Atom1Feed, Rss201rev2Feed
from django.utils.http import urlencode
from urllib.parse import urlencode, parse_qs, urlparse, urlunparse

from .models import Feed, FeedEntry


class PaginatedFeedGenerator(Rss201rev2Feed):
    def root_attributes(self):
        attrs = super().root_attributes()
        attrs['xmlns:atom'] = 'http://www.w3.org/2005/Atom'
        return attrs

    def add_root_elements(self, handler):
        super().add_root_elements(handler)
    
        if self.feed.get('next_page_url'):
            handler.startElement('atom:link', {
                'rel': 'next',
                'href': self.feed['next_page_url'],
                'type': 'application/rss+xml'
            })
            handler.endElement('atom:link')

        if self.feed.get('prev_page_url'):
            handler.startElement('atom:link', {
                'rel': 'prev',
                'href': self.feed['prev_page_url'],
                'type': 'application/rss+xml'
            })
            handler.endElement('atom:link')

class PaginatedAtomGenerator(Atom1Feed):
    def add_root_elements(self, handler):
        super().add_root_elements(handler)

        if self.feed.get('next_page_url'):
            handler.startElement('atom:link', {
                'rel': 'next',
                'href': self.feed['next_page_url'],
                'type': 'application/atom+xml'
            })
            handler.endElement('atom:link')

        if self.feed.get('prev_page_url'):
            handler.startElement('atom:link', {
                'rel': 'prev',
                'href': self.feed['prev_page_url'],
                'type': 'application/atom+xml'
            })
            handler.endElement('link')

class RSSFeed(DjangoFeed):
    feed_type = PaginatedFeedGenerator
    description = "TBA"
    default_limit = 25

    def __init__(self):
        super().__init__()
        self.page_num = 1
        self.total_items = 0

    def get_object(self, request, slug):
        feed = Feed.objects.get(slug=slug)
        self.request = request

        # ?page=X is generic and supported by Newsblur
        # Wordpress installs support ?paged=X but we opt to use paged from RFC 5005 https://datatracker.ietf.org/doc/html/rfc5005#section-3
        # https://forum.newsblur.com/t/newsblur-premium-archive-subscription-keeps-all-of-your-stories-searchable-shareable-and-unread-forever/9402
        page_param = request.GET.get('page')
        if page_param and page_param.isdigit():
            self.page_num = max(1, int(page_param))
        
        self.total_items = FeedEntry.objects.filter(feed=feed).count()
        total_pages = (self.total_items + self.default_limit - 1) // self.default_limit
        if total_pages > 0:
            self.page_num = min(self.page_num, max(1, total_pages))

        return feed

    def title(self, obj):
        return obj.title
    
    def link(self, obj):
        return obj.url

    def feed_url(self, obj):
        return self.request.build_absolute_uri()

    def items(self, obj):
        offset = (self.page_num - 1) * self.default_limit
        limit = offset + self.default_limit
        return FeedEntry.objects.filter(feed=obj).order_by("-published_at")[offset:limit]
    
    def item_title(self, item):
        return item.title

    def item_description(self, item):
        return item.content

    def item_author_name(self, item):
        return item.authors

    def item_link(self, item):
        return item.url

    def item_pubdate(self, item):
        return item.published_at

    def item_updateddate(self, item):
        return item.updated_at

    def _get_page_url(self, obj, page_num=None):
        url_parts = list(urlparse(self.request.build_absolute_uri()))
        # We know we have query params already but we don't want to lose any other params that may exist
        query_params = parse_qs(url_parts[4])
        if page_num is not None:
            query_params['page'] = [str(page_num)]
        else:
            query_params.pop('page', None)
        url_parts[4] = urlencode(query_params, doseq=True)
        return urlunparse(url_parts)

    def feed_extra_kwargs(self, obj):
        total_pages = (self.total_items + self.default_limit - 1) // self.default_limit
        next_page_url = None
        prev_page_url = None

        # We only want to surface the next page if there are actually more items to go
        if self.page_num < total_pages:
            next_page_url = self._get_page_url(obj, self.page_num + 1)

        # You can't have an earlier page than the first one
        if self.page_num > 1:
            prev_page_url = self._get_page_url(obj, self.page_num - 1)

        return {
            'next_page_url': next_page_url,
            'prev_page_url': prev_page_url
        }

class AtomFeed(RSSFeed):
    feed_type = PaginatedAtomGenerator
    subtitle = RSSFeed.description