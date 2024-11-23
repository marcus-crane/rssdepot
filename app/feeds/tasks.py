from datetime import datetime
import logging
import time

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
    results = {
        'processed': 0,
        'errors': 0,
        'error_details': [],
        'total': backlog.count()
    }
    for item in backlog:
        # TODO: Capture more detail
        success = scan_entry(item.url)
        if success:
            results['processed'] += 1
        else:
            results['errors'] += 1
            results['error_details'].append({
                'url': item.url
            })
        time.sleep(1)
    return results

def scan_entry(url):
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
def scan_uber_engineering(self, page=1, max_depth=2):
    uber_base = 'https://www.uber.com'
    uber_url = f'https://blogapi.uber.com/wp-json/wp/v2/posts?languages=2257&categories=221148&page={page}'

    logger.info(f"Scanning Page {page} of {max_depth} - URL: {uber_url}")

    try:
        r = requests.get(uber_url)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch page {page}: {str(e)}")
        return False

    try:
        feed = Feed.objects.get(hostname=uber_base)
    except Feed.DoesNotExist:
        logger.error(f"Feed not found for hostname: {uber_base}")
        return False

    stories = r.json()

    if r.status_code == 400 and stories.get('code') == 'rest_post_invalid_page_number':
        logger.info(f"Reached end of available posts. Page {page} doesn't exist.")
        return True

    entries_created = 0
    for story in stories:
        try:
            raw_content = story.get('content', {}).get('rendered', '')
            content = BeautifulSoup(raw_content, 'html.parser').__str__().strip()

            raw_description = story.get('excerpt', {}).get('rendered', '')
            description = BeautifulSoup(raw_description, 'html.parser').text.strip()

            url = story.get('link')

            if FeedEntry.objects.filter(url=url).exists():
                continue

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

            published = article_meta.get('article_published_time')
            modified = article_meta.get('article_modified_time')
            authors = article_meta.get('author')
            if not authors:
                authors = article_meta.get('twitter_misc', {}).get('Written by', 'Unknown')

            published_at = datetime.fromisoformat(published)
            modified_at = published_at
            if modified is not None:
                # Since 2022-07-07 and prior, some articles do not have modified times
                # so we just set published instead
                modified_at = datetime.fromisoformat(modified)

            current_time = timezone.now()
            FeedEntry.objects.create(
                feed=feed,
                title=title,
                authors=authors,
                description=description,
                content=content,
                url=url,
                in_feed=True,
                backfilled=True,
                created_at=current_time,
                updated_at=modified_at,
                published_at=published_at,
            )
            entries_created += 1

        except AttributeError as e:
            logger.warning(f"Failed to parse story: {str(e)}")
            continue

    logger.info(f"Created {entries_created} new entries on page {page}")

    if page < max_depth:
        scan_uber_engineering.apply_async(
            kwargs={
                'page': page + 1,
                'max_depth': max_depth
            },
            countdown=5
        )
        return f"Scheduled page {page + 1}"

    return f"Completed scanning Page {page}"

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
                published_at=current_time,
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