from django.contrib.syndication.views import Feed as DjangoFeed
from django.utils.feedgenerator import Atom1Feed

from .models import Feed, FeedEntry


class RSSFeed(DjangoFeed):
    description = "TBA"

    def get_object(self, request, slug):
        return Feed.objects.get(slug=slug)

    def title(self, obj):
        return obj.title
    
    def link(self, obj):
        return obj.url

    def items(self, obj):
        return FeedEntry.objects.filter(feed=obj).order_by("-published_at")[:100]
    
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

class AtomFeed(RSSFeed):
    feed_type = Atom1Feed
    subtitle = RSSFeed.description