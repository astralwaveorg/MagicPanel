#!/usr/bin/env python3
"""Search a small index and read bounded excerpts of official documentation."""

import argparse
import hashlib
import json
import re
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / 'docs' / 'reference' / 'official-docs-index.json'
CACHE = ROOT / '.cache' / 'official-docs'
HOSTS = {'wiki.metacubex.one', 'stash.wiki'}
EXTRACTOR_VERSION = 1


class ArticleText(HTMLParser):
    """Extract article text, retaining headings and code indentation."""

    def __init__(self, url):
        super().__init__()
        host = urlsplit(url).hostname
        self.url = url
        self.root_tag = 'main' if host == 'stash.wiki' else 'article'
        self.active = False
        self.parts = []
        self.pre = False
        self.code = False
        self.ignored = 0
        self.heading = False
        self.anchors = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == self.root_tag:
            self.active = True
        if not self.active:
            return
        classes = attrs.get('class', '').split()
        if self.ignored:
            if tag not in {'br', 'hr', 'img', 'input', 'meta', 'link', 'wbr', 'source'}:
                self.ignored += 1
            return
        if (tag in {'script', 'style', 'nav'} or
                set(classes) & {'linenos', 'headerlink', 'md-content__button'}):
            self.ignored = 1
            return
        if re.fullmatch(r'h[1-6]', tag):
            self.heading = True
            self.parts.append('\n\n' + '#' * int(tag[1]) + ' ')
        elif tag == 'pre':
            self.parts.append('\n\n```\n')
            self.pre = True
        elif tag == 'code' and not self.pre:
            self.parts.append('`')
            self.code = True
        elif tag == 'a' and not self.pre:
            href = attrs.get('href') if not self.heading else None
            self.anchors.append(urljoin(self.url, href) if href else None)
            if href:
                self.parts.append('[')
        elif tag in {'p', 'div', 'ul', 'ol', 'table', 'tr', 'blockquote'} and not self.pre:
            self.parts.append('\n')
        elif tag == 'li':
            self.parts.append('\n- ')
        elif tag == 'br':
            self.parts.append('\n')
        elif tag in {'td', 'th'}:
            self.parts.append(' | ')

    def handle_endtag(self, tag):
        if not self.active:
            return
        if self.ignored:
            self.ignored -= 1
            return
        if tag == self.root_tag:
            self.active = False
        elif tag == 'pre':
            self.pre = False
            self.parts.append('\n```\n\n')
        elif tag == 'code' and self.code:
            self.parts.append('`')
            self.code = False
        elif tag == 'a' and not self.pre and self.anchors:
            href = self.anchors.pop()
            if href:
                self.parts.append(f']({href})')
        elif re.fullmatch(r'h[1-6]', tag):
            self.heading = False
            self.parts.append('\n\n')
        elif tag in {'p', 'li', 'tr', 'blockquote'} and not self.pre:
            self.parts.append('\n')

    def handle_data(self, data):
        if self.active and not self.ignored:
            if not self.pre:
                data = re.sub(r'\s+', ' ', data)
                if not data.strip():
                    data = ''
            self.parts.append(data)

    def result(self):
        return re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+', '\n\n', ''.join(self.parts)).strip()


def extract_text(html, url):
    parser = ArticleText(url)
    parser.feed(html)
    text = parser.result()
    if not text:
        raise ValueError('No article extracted; inspect the official page in a browser.')
    return text


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def checked_url(url):
    url = urldefrag(url)[0]
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in HOSTS or parts.username or parts.password:
        raise ValueError('Use an HTTPS URL on an indexed official documentation host.')
    return url


def save_cache(record):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / (hashlib.sha256(record['url'].encode()).hexdigest() + '.json')
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=CACHE, delete=False) as out:
        json.dump(record, out, ensure_ascii=False, indent=2)
        tmp = Path(out.name)
    tmp.replace(path)


def load_page(url, offline=False):
    url = checked_url(url)
    path = CACHE / (hashlib.sha256(url.encode()).hexdigest() + '.json')
    cached = json.loads(path.read_text()) if path.exists() else None
    if offline:
        if not cached:
            raise ValueError('No cached page. Read it online first.')
        return cached, 'OFFLINE: no freshness check in this invocation'
    headers = {'User-Agent': 'MagicHub-docs-lookup/1.0'}
    if cached and cached.get('extractor_version') == EXTRACTOR_VERSION:
        if cached.get('etag'):
            headers['If-None-Match'] = cached['etag']
        if cached.get('last_modified'):
            headers['If-Modified-Since'] = cached['last_modified']
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            final = checked_url(response.url)
            body = response.read(4_000_001)
            if len(body) > 4_000_000:
                raise ValueError('Page exceeds 4 MB; use a browser.')
            charset = response.headers.get_content_charset() or 'utf-8'
            text = extract_text(body.decode(charset), final)
            record = {
                'url': url, 'final_url': final, 'checked_at': now(),
                'extractor_version': EXTRACTOR_VERSION,
                'etag': response.headers.get('ETag'),
                'last_modified': response.headers.get('Last-Modified'),
                'sha256': hashlib.sha256(text.encode()).hexdigest(), 'text': text,
            }
    except urllib.error.HTTPError as error:
        if error.code != 304 or not cached:
            raise
        record = dict(cached, checked_at=now())
        save_cache(record)
        return record, 'ONLINE 304: cached body revalidated'
    save_cache(record)
    return record, 'ONLINE 200: downloaded official body'


def search(args):
    index = json.loads(INDEX.read_text())
    terms = args.query.casefold().split()
    matches = []
    for entry in index['pages']:
        if args.product and entry['product'] != args.product:
            continue
        title = entry['title'].casefold()
        keywords = [s.casefold() for s in entry.get('terms', [])]
        haystack = ' '.join([entry['url'].casefold(), title, *keywords])
        if not all(term in haystack for term in terms):
            continue
        score = sum(20 * (term in keywords) + 10 * (term in title) for term in terms)
        matches.append((-score, entry['url'], entry))
    for _, _, entry in sorted(matches)[:args.limit]:
        print(f"[{entry['product']}] {entry['title']}\n  {entry['url']}")
    if not matches:
        print('No matches. Try a field name or the product navigation; the index may need updating.')
        return 1
    print(f'{min(len(matches), args.limit)}/{len(matches)} matches; index checked {index["checked_on"]}')
    return 0


def page_headings(lines):
    headings = []
    in_code = False
    for i, line in enumerate(lines):
        if line.startswith('```'):
            in_code = not in_code
        match = re.match(r'^(#{1,6}) (.+)$', line) if not in_code else None
        if match:
            headings.append((i, len(match[1]), match[2]))
    return headings


def excerpt(text, args):
    lines = text.splitlines()
    headings = page_headings(lines)
    if args.outline:
        for i, level, title in headings[:args.max_lines]:
            print(f'{i + 1:04d} {"#" * level} {title}')
        if len(headings) > args.max_lines:
            print('… outline truncated; increase --max-lines to see remaining headings.')
        return
    start = args.start_line - 1
    end = len(lines)
    if args.section:
        candidates = [h for h in headings if args.section.casefold() == h[2].casefold()]
        if not candidates:
            candidates = [h for h in headings if args.section.casefold() in h[2].casefold()]
        if len(candidates) != 1:
            raise ValueError(f'Section must match one heading; found {len(candidates)}. Use a more specific heading.')
        first, level, _ = candidates[0]
        start = first + args.start_line - 1
        end = next((i for i, depth, _ in headings if i > first and depth <= level), end)
    if args.find:
        found = next((i for i in range(start, end) if args.find.casefold() in lines[i].casefold()), None)
        if found is None:
            raise ValueError('Text not found in the selected range.')
        start = max(start, found - 6)
    if start >= end:
        raise ValueError('Start line is outside the selected page/section.')
    stop = min(end, start + args.max_lines)
    print(f'Lines {start + 1}-{stop}/{len(lines)} (selected range ends at {end})')
    for i in range(start, stop):
        line = lines[i]
        if len(line) > 1800:
            line = line[:1800] + ' … [long line clipped; inspect original page]'
        print(f'{i + 1:04d} {line}')
    if stop < end:
        print('… excerpt truncated; read further before editing if constraints or examples are incomplete.')


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('Use a positive integer.')
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    finder = commands.add_parser('search', help='Search titles and field names locally; no network.')
    finder.add_argument('query')
    finder.add_argument('--product', choices=['mihomo', 'stash'])
    finder.add_argument('--limit', type=positive, default=5)
    reader = commands.add_parser('read', help='Fetch/revalidate an official page and show a bounded excerpt.')
    reader.add_argument('url')
    reader.add_argument('--section')
    reader.add_argument('--outline', action='store_true', help='Show only section headings and their line numbers.')
    reader.add_argument('--find')
    reader.add_argument('--start-line', type=positive, default=1)
    reader.add_argument('--max-lines', type=positive, default=80)
    reader.add_argument('--offline', action='store_true', help='Reuse a local copy without checking freshness.')
    args = parser.parse_args()
    if args.command == 'read' and args.outline and (args.section or args.find or args.start_line != 1):
        parser.error('--outline cannot be combined with --section, --find, or --start-line.')
    try:
        if args.command == 'search':
            return search(args)
        record, status = load_page(args.url, args.offline)
        print(f'Source: {record["url"]}\nChecked (UTC): {record["checked_at"]}\n{status}\nSHA256: {record["sha256"]}')
        excerpt(record['text'], args)
        return 0
    except (OSError, ValueError, urllib.error.URLError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
