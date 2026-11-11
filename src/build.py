"""Kindle Daily: rank public RSS articles, extract readable text, publish EPUB + OPDS."""
from __future__ import annotations
import datetime as dt
import html
import logging
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from collections import Counter
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from ebooklib import epub
import feedparser
import requests
import trafilatura
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'public'
TZ = dt.timezone(dt.timedelta(hours=-3))
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; KindleDaily/0.2; personal news reader)'})
KEYWORDS = {
    'Politica argentina': ['argentina', 'gobierno', 'congreso', 'senado', 'diputados', 'elecciones', 'presidente', 'ley'],
    'Economia argentina': ['economía', 'inflación', 'dólar', 'banco central', 'pbi', 'mercado', 'deuda'],
    'Geografia y clima': ['argentina', 'clima', 'meteorología', 'temperatura', 'lluvias', 'territorio', 'mapa'],
    'Quimica e ingenieria quimica': ['chemistry', 'chemical', 'catalyst', 'synthesis', 'reactor', 'química'],
    'Polimeros y materiales': ['polymer', 'plastic', 'material', 'resin', 'composite', 'polímero'],
    'Impresion 3D': ['3d printing', 'additive manufacturing', 'printer', 'filament', 'impresión 3d'],
    'Inteligencia artificial': ['artificial intelligence', 'machine learning', 'ai model', 'neural', 'inteligencia artificial'],
}

def canonical(url):
    s = urlsplit(url)
    params = [(k, v) for k, v in parse_qsl(s.query) if not k.lower().startswith('utm_') and k not in ('fbclid', 'gclid')]
    return urlunsplit((s.scheme.lower(), s.netloc.lower(), s.path.rstrip('/'), urlencode(params), ''))

def published(item):
    import calendar
    for field in ('published_parsed', 'updated_parsed'):
        t = item.get(field)
        if t:
            return dt.datetime.fromtimestamp(calendar.timegm(t), dt.timezone.utc)
    return None

def candidates(cfg):
    now = dt.datetime.now(dt.timezone.utc)
    pool = []
    seen = set()
    for feed in cfg['feeds']:
        if feed.get('enabled', True) is False:
            continue
        try:
            response = SESSION.get(feed['url'], timeout=22)
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            if not parsed.entries:
                logging.warning('Empty feed: %s', feed['name'])
            for item in parsed.entries[:35]:
                link = item.get('link', '')
                if urlsplit(link).scheme not in ('http', 'https'):
                    continue
                key = canonical(link)
                if key in seen:
                    continue
                seen.add(key)
                date = published(item)
                age = max(0, (now - date).total_seconds() / 3600) if date else None
                if age is not None and age > cfg.get('max_age_hours', 96):
                    continue
                title = re.sub('<[^>]+>', '', item.get('title', 'Sin título')).strip()
                summary = re.sub('<[^>]+>', ' ', item.get('summary', ''))
                keywords = KEYWORDS.get(feed['category'], [])
                content = (title + ' ' + summary).lower()
                match = sum(1 for word in keywords if word in content)
                score = (max(0, 72 - age) / 18 if age is not None else 0.5) + 2 * match
                pool.append(dict(title=title, url=link, category=feed['category'], source=feed['name'], score=score, date=date))
        except Exception as exc:
            logging.warning('Feed failed %s: %s', feed['name'], exc)
    return sorted(pool, key=lambda a: a['score'], reverse=True)

def select_and_extract(cfg, pool):
    quotas = cfg['categories']
    counts, sources = Counter(), Counter()
    chosen, used_titles = [], set()
    # First fill category targets, then use remaining articles from other categories.
    for strict in (True, False):
        for item in pool:
            if len(chosen) >= cfg['max_articles']:
                break
            if item['url'] in {a['url'] for a in chosen}:
                continue
            if strict and counts[item['category']] >= quotas.get(item['category'], 0):
                continue
            if sources[item['source']] >= cfg.get('max_per_source', 4):
                continue
            words = set(re.findall(r'\w+', item['title'].casefold())) - {'de', 'la', 'el', 'the', 'and', 'en', 'a', 'to'}
            if any(len(words & other) / max(1, len(words | other)) > 0.7 for other in used_titles):
                continue
            try:
                resp = SESSION.get(item['url'], timeout=25)
                resp.raise_for_status()
                body = trafilatura.extract(resp.text, url=item['url'], include_comments=False, include_tables=True)
                if not body or len(body.strip()) < cfg.get('min_text_chars', 400):
                    logging.warning('No full text: %s', item['url'])
                    continue
            except Exception as exc:
                logging.warning('Article unavailable %s: %s', item['url'], exc)
                continue
            chosen.append({**item, 'text': body})
            used_titles.add(frozenset(words))
            counts[item['category']] += 1
            sources[item['source']] += 1
        if len(chosen) >= cfg['max_articles']:
            break
    return chosen

def make_epub(cfg, articles, date):
    book = epub.EpubBook()
    book.set_identifier('kindle-daily-' + date)
    book.set_title(f"{cfg['title']} — {date}")
    book.set_language('es')
    book.add_author('Kindle Daily')
    chapters = []
    for i, a in enumerate(articles, 1):
        ch = epub.EpubHtml(title=a['title'], file_name=f'article_{i}.xhtml', lang='es')
        body = ''.join('<p>' + html.escape(part.strip()).replace('\n', '<br/>') + '</p>' for part in re.split(r'\n\s*\n', a['text']) if part.strip())
        ch.content = (f'<h1>{html.escape(a["title"])}</h1><p><em>{html.escape(a["source"])} · {html.escape(a["category"])}</em></p>' + body + f'<p><a href="{html.escape(a["url"], quote=True)}">Fuente original</a></p>')
        book.add_item(ch)
        chapters.append(ch)
    book.toc = tuple(chapters)
    book.spine = ['nav', *chapters]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.add_item(epub.EpubItem(uid='style', file_name='style/main.css', media_type='text/css', content='body{line-height:1.45}h1{font-size:1.4em}p{margin:0 0 .7em}'))
    filename = f'kindle-daily-{date}.epub'
    epub.write_epub(str(OUT / filename), book)
    return filename

def publish(cfg, filename, count, date):
    base = os.getenv('PUBLIC_BASE_URL', '').rstrip('/')
    atom = 'http://www.w3.org/2005/Atom'
    ET.register_namespace('', atom)
    root = ET.Element(f'{{{atom}}}feed')
    ET.SubElement(root, f'{{{atom}}}id').text = (base or 'urn:kindle-daily') + '/catalog.xml'
    ET.SubElement(root, f'{{{atom}}}title').text = cfg['title']
    ET.SubElement(root, f'{{{atom}}}updated').text = dt.datetime.now(dt.timezone.utc).isoformat()
    entry = ET.SubElement(root, f'{{{atom}}}entry')
    ET.SubElement(entry, f'{{{atom}}}id').text = f'urn:kindle-daily:{date}'
    ET.SubElement(entry, f'{{{atom}}}title').text = f'{cfg["title"]} — {date}'
    ET.SubElement(entry, f'{{{atom}}}updated').text = dt.datetime.now(dt.timezone.utc).isoformat()
    ET.SubElement(entry, f'{{{atom}}}summary').text = f'{count} artículos seleccionados por relevancia heurística'
    ET.SubElement(entry, f'{{{atom}}}link', {'rel': 'http://opds-spec.org/acquisition', 'type': 'application/epub+zip', 'href': f'{base}/{filename}' if base else filename})
    ET.ElementTree(root).write(OUT / 'catalog.xml', encoding='utf-8', xml_declaration=True)
    (OUT / 'index.html').write_text(f'<h1>Kindle Daily</h1><p>{date}: {count} artículos</p><a href="catalog.xml">Catálogo OPDS</a><p><a href="{filename}">EPUB</a></p>', encoding='utf8')
    (OUT / '.nojekyll').touch()

def main():
    cfg = yaml.safe_load((ROOT / 'config/feeds.yaml').read_text(encoding='utf8'))
    OUT.mkdir(exist_ok=True)
    pool = candidates(cfg)
    articles = select_and_extract(cfg, pool)
    if not articles:
        raise SystemExit('No readable articles found; publication cancelled')
    date = dt.datetime.now(TZ).date().isoformat()
    filename = make_epub(cfg, articles, date)
    publish(cfg, filename, len(articles), date)
    logging.info('Generated %s with %s articles (target %s)', filename, len(articles), cfg['max_articles'])

if __name__ == '__main__':
    main()
