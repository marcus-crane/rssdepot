from fastapi import FastAPI, Response

from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
import pendulum
import requests

app = FastAPI()

@app.get("/")
def root():
    return "Some useful feeds can be found here"

@app.get("/hacker_news/highlights.rss")
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
