import logging

from bs4 import BeautifulSoup
from django.utils import timezone
import newspaper
import requests

from .models import Feed, FeedEntry
from rssdepot.celery import app

logger = logging.getLogger(__name__)

@app.task(bind=True)
def queue_backlog(self):
    backlog = FeedEntry.objects.filter(backfilled=False)
    for item in backlog:
        scan_entry.apply_async(
            kwargs={
                'url': item.url,
            }
        )

@app.task(bind=True)
def scan_entry(self, url):
    entry = FeedEntry.objects.get(url=url)
    article = newspaper.article(url)
    # TODO: Move this to on save functions for model
    title = article.title
    description = article.meta_description
    authors = ' and '.join(article.authors)
    content = article.article_html
    if entry.title == title and entry.description == description and entry.authors == authors and entry.content == content:
        print("Article was exactly the same without change")
        return True
    entry.published_at = article.publish_date
    entry.title = title
    entry.description = description
    entry.authors = authors
    entry.content = content
    entry.backfilled = True
    entry.save()
    print("Saved article")
    return True

@app.task(bind=True)
def scan_rnz_phil_pennington(self, page=1, max_depth=2):
    rnz_base = 'https://www.rnz.co.nz'
    rnz_url = f'https://www.rnz.co.nz/authors/phil-pennington?page={page}'
    
    logger.info(f"Scanning Page {page} of {max_depth} - URL: {rnz_url}")
    
    try:
        r = requests.get(rnz_url)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch page {page}: {str(e)}")
        return False

    soup = BeautifulSoup(r.text, 'html.parser')
    
    try:
        feed = Feed.objects.get(hostname=rnz_base)
    except Feed.DoesNotExist:
        logger.error(f"Feed not found for hostname: {rnz_base}")
        return False

    stories = soup.find_all('div', class_='o-digest')
    next_btn = soup.find('a', rel='next', class_='btn')
    
    entries_created = 0
    for story in stories:
        try:
            url_segment = story.find('h3', class_='o-digest__headline').a.attrs['href']
            url = rnz_base + url_segment
            
            if FeedEntry.objects.filter(url=url).exists() or '/news/chinese/' in url_segment:
                continue
                
            title = story.find('h3', class_='o-digest__headline').text.strip()
            description = story.find('div', class_='o-digest__summary').text.strip()
            
            current_time = timezone.now()
            FeedEntry.objects.create(
                feed=feed,
                title=title,
                authors='Phil Pennington',
                description=description,
                content='',
                url=url,
                in_feed=True,
                backfilled=False,
                created_at=current_time,
                updated_at=current_time,
                modified_at=current_time,
            )
            entries_created += 1
            
        except AttributeError as e:
            logger.warning(f"Failed to parse story: {str(e)}")
            continue

    logger.info(f"Created {entries_created} new entries on page {page}")

    # Schedule next page if we haven't reached max_depth
    if next_btn and page < max_depth:
        next_slug = next_btn.attrs.get('href')
        if next_slug:
            logger.info(f"Scheduling scan of page {page + 1}")
            scan_rnz_phil_pennington.apply_async(
                kwargs={
                    'page': page + 1,
                    'max_depth': max_depth
                },
                countdown=5
            )
            return f"Scheduled page {page + 1}"
    
    return f"Completed scanning page {page}"