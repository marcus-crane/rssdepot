from fastapi import FastAPI, Response

from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
import requests

app = FastAPI()

@app.get("/")
def root():
    return "Some useful feeds can be found here"

@app.get("/hacker_news/highlights.rss")
def serve_highlights():
    r = requests.get("https://news.ycombinator.com/highlights")
    soup = BeautifulSoup(r.text, 'html.parser')
    comments = soup.find_all("tr", class_="athing")

    fg = FeedGenerator()
    fg.title("Hacker News Highlights")
    fg.link(href="https://news.ycombinator.com/highlights")
    fg.description("Interesting comments")

    for comment in comments:
        author = comment.find("a", class_="hnuser").text
        text = comment.find("div", class_="commtext")
        link_segment = comment.find("span", class_="age").a.attrs['href']
        story_title = comment.find("span", class_="onstory").text.replace(" |  on: ", "")

        title = f"{author} on {story_title}"

        link = f"https://news.ycombinator.com/{link_segment}"

        fe = fg.add_entry()
        fe.id(link)
        fe.title(title)
        fe.link(href=link)
        fe.description(description=str(text), isSummary=False)

    rssfeed = fg.rss_str(pretty=True)
    return Response(content=rssfeed, media_type="application/xml")
