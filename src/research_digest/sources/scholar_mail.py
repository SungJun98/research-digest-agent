from __future__ import annotations
import re
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup

from ..models import Paper
from . import SourceError


def paper_url(href):
    parsed = urlparse(href)
    if parsed.hostname and (parsed.hostname == 'scholar.google.com' or parsed.hostname.startswith('scholar.google.')):
        query = parse_qs(parsed.query)
        href = (query.get('url') or query.get('q') or [''])[0]
        parsed = urlparse(href)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password:
        return None
    if parsed.hostname.endswith('google.com') or '/unsubscribe' in parsed.path:
        return None
    return href


def parse_scholar_message(raw: bytes, received_at: datetime) -> list[Paper]:
    if len(raw) > 2_000_000:
        return []
    message = BytesParser(policy=policy.default).parsebytes(raw)
    body = message.get_body(preferencelist=('html','plain')) if message.is_multipart() else message
    try:
        text = body.get_content() if body else ''
    except (LookupError, UnicodeError, AttributeError):
        return []
    candidates = []
    if body and body.get_content_type() == 'text/html':
        soup = BeautifulSoup(text, 'html.parser')
        for a in soup.find_all('a',href=True)[:500]:
            title = a.get_text(' ',strip=True)
            url = paper_url(a['href'])
            if not url or len(title) < 8 or title.casefold() in {'unsubscribe','view all','create alert','알림 취소'}:
                continue
            # Scholar titles live in headings. The adjacent snippet is abstract-level context.
            heading = a.find_parent(['h3','h2'])
            if not heading:
                continue
            snippet = heading.find_next_sibling(class_='gse_alrt_sni')
            candidates.append((title,url,snippet.get_text(' ',strip=True) if snippet else ''))
    else:
        lines = str(text).splitlines()
        for index,line in enumerate(lines):
            match = re.fullmatch(r'\s*(https?://\S+)\s*',line)
            if match and index > 0:
                title = lines[index-1].strip()
                url = paper_url(match[1])
                if url and len(title) >= 8:
                    candidates.append((title,url,''))
    result, seen = [], set()
    for title,url,abstract in candidates:
        if url in seen: continue
        seen.add(url)
        parsed = urlparse(url)
        result.append(Paper(title=title,abstract=abstract,url=url,first_seen_at=received_at,sources={'scholar_mail'},
            arxiv_id=url if parsed.hostname in {'arxiv.org','www.arxiv.org'} else None,
            doi=url if parsed.hostname in {'doi.org','dx.doi.org'} else None,
            metadata={'scholar_subject': str(message['subject'] or '')}))
    return result


class ScholarMailSource:
    def __init__(self, imap_factory, store=None, mailbox='INBOX', max_messages=100, account='default'):
        self.imap_factory, self.store = imap_factory, store
        self.mailbox, self.max_messages, self.account = mailbox, max_messages, account

    def fetch(self, since, allowed_senders: set[str], mark_fetched=True):
        connection = None
        try:
            connection = self.imap_factory()
            status,_ = connection.select(self.mailbox,readonly=True)
            if status != 'OK': raise ValueError()
            _, validity = connection.response('UIDVALIDITY')
            validity = (validity or [b'unknown'])[0].decode()
            status,data = connection.uid('search',None,'SINCE',since.strftime('%d-%b-%Y'))
            if status != 'OK': raise ValueError()
            result = []
            for uid in (data[0] or b'').split()[-self.max_messages:]:
                key = f'imap:{self.account}:{self.mailbox}:{validity}:{uid.decode()}'
                if self.store and self.store.seen(key): continue
                status,data = connection.uid('fetch',uid,'(BODY.PEEK[] INTERNALDATE)')
                if status != 'OK': continue
                for row in data:
                    if not isinstance(row,tuple): continue
                    match = re.search(rb'INTERNALDATE "([^"]+)"',row[0])
                    if not match: continue
                    received = datetime.strptime(match[1].decode(),'%d-%b-%Y %H:%M:%S %z').astimezone(timezone.utc)
                    message = BytesParser(policy=policy.default).parsebytes(row[1])
                    sender = parseaddr(message['from'] or '')[1].lower()
                    if received >= since and sender in {s.lower() for s in allowed_senders}:
                        result.extend(parse_scholar_message(row[1],received))
                    if mark_fetched and self.store:
                        self.store.mark_seen(key)
            return result
        except Exception as error:
            if isinstance(error,SourceError): raise
            raise SourceError('Scholar mail: IMAP read failed') from None
        finally:
            if connection:
                try: connection.logout()
                except Exception: pass
