import datetime as dt
import html
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

import ebooklib
from ebooklib import epub
import feedparser
import requests
import trafilatura
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output'
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')


def main():
    cfg = yaml.safe_load((ROOT / 'config' / 'feeds.yaml').read_text(encoding='utf-8'))
    OUT.mkdir(exist_ok=True)
    articles = []
    seen = set()
    for feed in cfg['feeds']:
        try:
            parsed = feedparser.parse(feed['url'], request_headers={'User-Agent': 'KindleDaily/0.1'})
            if parsed.bozo:
                logging.warning('Feed warning %s: %s', feed['name'], parsed.bozo_exception)
            for entry in parsed.entries[:20]:
                url = entry.get('link', '')
                if not url or url in seen:
                    continue
                seen.add(url)
                articles.append({'title': entry.get('title', 'Untitled'), 'url': url, 'source': feed['name'], 'summary': entry.get('summary', '')})
        except Exception as exc:
            logging.warning('Feed failed %s: %s', feed['name'], exc)
    # Round-robin across sources for basic diversity.
    grouped = {feed['name']: [a for a in articles if a['source'] == feed['name']] for feed in cfg['feeds']}
    chosen = []
    while len(chosen) < cfg.get('max_articles', 10) and any(grouped.values()):
        for name in grouped:
            if grouped[name] and len(chosen) < cfg.get('max_articles', 10):
                chosen.append(grouped[name].pop(0))
    if not chosen:
        raise RuntimeError('No articles found; refusing to publish an empty edition')
    book = epub.EpubBook()
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    book.set_identifier(f'kindle-daily-{today}')
    book.set_title(f"{cfg.get('title', 'Kindle Daily')} — {today}")
    book.set_language('en')  # Individual articles may be in Spanish or English.
    book.add_author('Kindle Daily')
    chapters = []
    for i, item in enumerate(chosen, 1):
        body = None
        try:
            response = requests.get(item['url'], timeout=20, headers={'User-Agent': 'Mozilla/5.0 (compatible; KindleDaily/0.1)'})
            response.raise_for_status()
            body = trafilatura.extract(response.text, output_format='html', include_comments=False, include_tables=True, include_images=False)
        except Exception as exc:
            logging.warning('Article extraction failed %s: %s', item['url'], exc)
        if not body:
            body = '<p>Full text unavailable. Read at the original source.</p>'
        title = html.escape(item['title'])
        url = html.escape(item['url'], quote=True)
        source = html.escape(item['source'])
        chapter = epub.EpubHtml(title=item['title'], file_name=f'article_{i}.xhtml', lang='en')
        chapter.content = f'<h1>{title}</h1><p><em>{source}</em></p>{body}<p><a href="{url}">Original article</a></p>'
        book.add_item(chapter)
        chapters.append(chapter)
    book.toc = tuple(chapters)
    book.spine = ['nav', *chapters]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    name = f'kindle-daily-{today}.epub'
    epub.write_epub(str(OUT / name), book)
    # Static OPDS 1.2 catalog, suitable for publishing alongside the EPUB.
    from xml.etree.ElementTree import Element, SubElement, ElementTree
    atom = 'http://www.w3.org/2005/Atom'
    opds = 'http://opds-spec.org/2010/catalog'
    root = Element('feed', {'xmlns': atom, 'xmlns:opds': opds})
    SubElement(root, 'id').text = 'urn:kindle-daily:catalog'
    SubElement(root, 'title').text = 'Kindle Daily'
    SubElement(root, 'updated').text = dt.datetime.now(dt.timezone.utc).isoformat()
    entry = SubElement(root, 'entry')
    SubElement(entry, 'id').text = f'urn:kindle-daily:{today}'
    SubElement(entry, 'title').text = f'Kindle Daily — {today}'
    SubElement(entry, 'updated').text = dt.datetime.now(dt.timezone.utc).isoformat()
    SubElement(entry, 'link', {'rel': 'http://opds-spec.org/acquisition', 'type': 'application/epub+zip', 'href': name})
    ElementTree(root).write(OUT / 'catalog.xml', encoding='utf-8', xml_declaration=True)
    logging.info('Generated %s with %d articles', name, len(chapters))

if __name__ == '__main__':
    main()
