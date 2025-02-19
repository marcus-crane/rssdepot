from bs4 import BeautifulSoup
from fastapi import FastAPI, Response
from feedgen.feed import FeedGenerator
import newspaper
import pendulum
import requests

app = FastAPI()

# We fetch some article sources to figure more info but we don't want to fetch for every run
url_cache = {}

@app.get("/")
def root():
    return "Some useful feeds can be found here"

@app.get("/hackernews-highlights.rss")
def serve_highlights():
    r = requests.get("https://news.ycombinator.com/highlights")
    soup = BeautifulSoup(r.text, 'html.parser')
    raw_comments = soup.find_all("tr", class_="athing")

    fg = FeedGenerator()
    fg.title("Hacker News Highlights")
    fg.link(href="https://news.ycombinator.com/highlights")
    fg.description("Interesting comments")

    comments = []

    for comment in raw_comments:
        author = comment.find("a", class_="hnuser").text
        text = comment.find("div", class_="commtext")
        date_unparsed = comment.find("span", class_="age").attrs['title']
        date = pendulum.from_format(date_unparsed, 'YYYY-MM-DD[T]HH:mm:SS X')
        link_segment = comment.find("span", class_="age").a.attrs['href']
        story_title = comment.find("span", class_="onstory").text.replace(" |  on: ", "")

        comments.append({
            'title': f"{author} on {story_title}",
            'text': text,
            'date': date,
            'link': f"https://news.ycombinator.com/{link_segment}"
        })

    comments.sort(key=lambda x: x['date'])

    for comment in comments:
        fe = fg.add_entry()
        fe.id(comment['link'])
        fe.title(comment['title'])
        fe.pubDate(pubDate=comment['date'])
        fe.link(href=comment['link'])
        fe.description(description=str(comment['text']), isSummary=False)

    rssfeed = fg.rss_str(pretty=True)
    return Response(content=rssfeed, media_type="application/xml")

@app.get("/rnz-phil-pennington.rss")
def serve_rnzpp():
    r = requests.get("https://www.rnz.co.nz/authors/phil-pennington")
    soup = BeautifulSoup(r.text, 'html.parser')
    raw_articles = soup.find_all("div", class_="o-digest--news")

    fg = FeedGenerator()
    fg.title("RNZ - Phil Pennington")
    fg.link(href="https://www.rnz.co.nz/authors/phil-pennington")
    fg.description("Articles from Phil Pennington")

    articles = []

    for article in raw_articles:
        link_segment = article.find('h3', class_='o-digest__headline').a.attrs['href']
        link = f"https://www.rnz.co.nz{link_segment}"
        article = url_cache.get(link, False)
        if not article:
            cached_article = newspaper.article(link)
            url_cache[link] = cached_article
            article = cached_article

        text = article.article_html
        title = article.title
        print(title)
        date = article.publish_date
        summary = article.meta_description
        
        articles.append({
            'title': title,
            'summary': summary,
            'text': text,
            'date': date,
            'link': link
        })
    
    articles.sort(key=lambda x: x['date'])

    for article in articles:
        fe = fg.add_entry()
        fe.id(article['link'])
        fe.title(article['title'])
        fe.pubDate(pubDate=article['date'])
        fe.link(href=article['link'])
        fe.summary(summary=article['summary'])
        fe.description(description=str(article['text']), isSummary=False)
    
    # clear cache with articles that have dropped out of feed
    links = set([article['link'] for article in articles])
    cached_links = set(url_cache.keys())
    links_to_remove = cached_links - links
    for link in links_to_remove:
        del url_cache[link]

    rssfeed = fg.rss_str(pretty=True)
    return Response(content=rssfeed, media_type="application/xml")

@app.get("/uber-engineering.rss")
def serve_ubereng():
    r = requests.get("https://blogapi.uber.com/wp-json/wp/v2/posts?languages=2257&categories=221148&page=1&per_page=25")
    data = r.json()

    fg = FeedGenerator()
    fg.title("Uber Engineering")
    fg.link(href="https://www.uber.com/blog/engineering/")
    fg.description("Articles from Uber Engineering")

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
            # Since 2022-07-07 and prior, some articles do not have modified times
            # so we just set published instead
            modified_at = pendulum.parse(modified)

        articles.append({
            'title': title,
            'description': description,
            'text': text,
            'date': published_at,
            'modified': modified_at,
            'link': link
        })
    
    articles.sort(key=lambda x: x['date'])

    for article in articles:
        fe = fg.add_entry()
        fe.id(article['link'])
        fe.title(article['title'])
        fe.pubDate(pubDate=article['date'])
        fe.updated(updated=article['modified'])
        fe.link(href=article['link'])
        fe.summary(summary=article['description'])
        fe.description(description=str(article['text']), isSummary=False)

    rssfeed = fg.rss_str(pretty=True)
    return Response(content=rssfeed, media_type="application/xml")