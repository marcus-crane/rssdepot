from django.contrib import admin

from .models import Feed, FeedEntry

@admin.register(FeedEntry)
class FeedEntryAdmin(admin.ModelAdmin):
    list_display = ['title', 'feed_name', 'published_at', 'in_feed', 'backfilled']
    list_filter = ["feed__title", "in_feed", "backfilled"]
    date_hierarchy = "published_at"
    ordering = ["published_at"]

    def feed_name(self, obj):
        return obj.feed.title

admin.site.register(Feed)