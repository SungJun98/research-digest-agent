from __future__ import annotations
import re
from urllib.parse import urlparse, urljoin
import httpx
from bs4 import BeautifulSoup
from ..models import FulltextContext
from . import ARXIV_LIMITER

ARXIV_ID = re.compile(r'^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?$')
MATCH = re.compile(r'introduction|results|discussion|limitations|conclusion',re.I)


def extract_relevant_sections(soup):
    for node in soup.select('script, style, nav, .ltx_bibliography'):
        node.decompose()
    chunks=[]
    for heading in soup.find_all(['h1','h2','h3','h4']):
        if not MATCH.search(heading.get_text()): continue
        lines=[heading.get_text(' ',strip=True)]
        level=int(heading.name[1])
        for sibling in heading.next_siblings:
            if not getattr(sibling,'name',None): continue
            if sibling.name in {'h1','h2','h3','h4'} and int(sibling.name[1])<=level: break
            if sibling.name in {'section'}: break
            lines.append(sibling.get_text(' ',strip=True))
        chunks.append('\n'.join(lines))
    return '\n\n'.join(chunks)


class FulltextSource:
    def __init__(self,client,store,limiter=None):
        self.client,self.store,self.limiter=client,store,limiter or ARXIV_LIMITER

    def _download(self,url):
        limiter=self.limiter
        with limiter.lock:
            if limiter.last is not None:
                limiter.sleep(max(0,limiter.interval-(limiter.clock()-limiter.last)))
            limiter.last=limiter.clock()
            with self.client.stream('GET',url,timeout=20,follow_redirects=False) as response:
                if response.is_redirect:
                    target=urljoin(url,response.headers.get('location',''))
                    if urlparse(target).hostname != 'arxiv.org' or urlparse(target).scheme!='https': return None,None
                    return None,target
                if not response.is_success: return None,None
                length=response.headers.get('content-length','')
                if length.isdigit() and int(length)>2*1024*1024: return None,None
                chunks,total=[],0
                for chunk in response.iter_bytes():
                    total+=len(chunk)
                    if total>2*1024*1024: return None,None
                    chunks.append(chunk)
                return b''.join(chunks),None

    def fetch(self,paper,max_chars=8000):
        identity=paper.arxiv_id or ''
        if not ARXIV_ID.fullmatch(identity): return None
        version=re.search(r'(?:abs|html|pdf)/([^?#]+)',paper.url)
        version=version[1].removesuffix('.pdf') if version and ARXIV_ID.fullmatch(version[1].removesuffix('.pdf')) else identity
        cache_key=version+':'+str(paper.metadata.get('updated_at',''))
        cached=self.store.get_cache('fulltext',cache_key)
        if cached: return FulltextContext(**(cached|{'text':cached['text'][:max_chars]}))
        url='https://arxiv.org/html/'+version
        try:
            content=None
            for _ in range(3):
                content,target=self._download(url)
                if target: url=target
                else: break
            if not content: return None
            text=extract_relevant_sections(BeautifulSoup(content,'html.parser'))[:32000]
            if not text.strip(): return None
            result=FulltextContext(text=text,url=url)
            self.store.put_cache('fulltext',cache_key,result.model_dump())
            return result.model_copy(update={'text':text[:max_chars]})
        except (httpx.HTTPError,ValueError):
            return None
