from django.urls import path

from . import feeds
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("<slug:slug>.atom", feeds.AtomFeed()),
    path("<slug:slug>.xml", feeds.RSSFeed()),
    path("<slug:slug>.rss", feeds.RSSFeed()),
]