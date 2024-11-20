from django.db import models


class Feed(models.Model):
    hostname = models.URLField()
    slug = models.CharField(max_length=100)
    url = models.URLField()
    title = models.CharField(max_length=200)
    backfilled = models.BooleanField(default=False)

    created_at = models.DateTimeField("date created", auto_created=True)
    updated_at = models.DateTimeField("date updated", auto_now=True)
    modified_at = models.DateTimeField("date modified")

    def __str__(self):
        return f"{self.title} <{self.url}>"

class FeedEntry(models.Model):
    feed = models.ForeignKey(Feed, related_name="entries", on_delete=models.CASCADE)
    title = models.CharField(max_length=500)
    authors = models.CharField(max_length=200)
    description = models.CharField(max_length=500)
    content = models.TextField()
    url = models.URLField()
    in_feed = models.BooleanField(default=True)
    backfilled = models.BooleanField(default=False)
    
    created_at = models.DateTimeField("date created", auto_created=True)
    updated_at = models.DateTimeField("date updated", auto_now=True)
    published_at = models.DateTimeField("date published")

    class Meta:
        verbose_name_plural = "entries"

    def __str__(self):
        return f"{self.title} <{self.feed.title}>"