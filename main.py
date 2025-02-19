from fastapi import FastAPI, Response

from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
import pendulum
import requests

app = FastAPI()

# We fetch some article sources to figure more info but we don't want to fetch for every run
url_time_cache = {}

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
        text = article.find('div', class_='o-digest__summary').text
        date_unparsed = article.find('span', class_='o-kicker__time').text
        link_segment = article.find('h3', class_='o-digest__headline').a.attrs['href']
        link = f"https://www.rnz.co.nz{link_segment}"
        title = article.find('h3', class_='o-digest__headline').text

        # if 'today' not in date_unparsed:
        #     
        # else:
        if 'today' in date_unparsed:
            today = pendulum.today(tz='Pacific/Auckland')
            date_unparsed_tweaked = date_unparsed.replace(" today", "").replace("am", "AM").replace("pm", "PM")
            parsed_time = pendulum.from_format(date_unparsed_tweaked, "h:mm A", tz='Pacific/Auckland')
            date = today.set(hour=parsed_time.hour, minute=parsed_time.minute, second=0)

        if 'today' not in date_unparsed:
            # 2:14 pm on 18 February 2025
            cached_date = url_time_cache.get(link, False)
            if not cached_date:
                # fetch page to get timestamp and cache result
                r = requests.get(link)
                soup2 = BeautifulSoup(r.text, 'html.parser')
                # One article had a case of double whitespace one time
                # https://www.rnz.co.nz/news/political/541208/trump-gaza-plan-not-proposal-but-threat-says-federation-of-islamic-associations
                raw_date = soup2.find('span', class_='updated').text.strip().replace("am", "AM").replace("pm", "PM").replace("  ", " ")
                print(raw_date, link)
                date = pendulum.from_format(raw_date, "h:mm A [on] D MMMM YYYY", tz="Pacific/Auckland")
                url_time_cache[link] = date
            else:
                date = cached_date
        
        articles.append({
            'title': title,
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
        fe.description(description=str(article['text']), isSummary=False)
    
    # clear cache with articles that have dropped out of feed
    links = set([article['link'] for article in articles])
    cached_links = set(url_time_cache.keys())
    links_to_remove = cached_links - links
    for link in links_to_remove:
        del url_time_cache[link]

    rssfeed = fg.rss_str(pretty=True)
    return Response(content=rssfeed, media_type="application/xml")