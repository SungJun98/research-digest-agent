from __future__ import annotations
import re
from urllib.parse import urlparse,quote
from bs4 import BeautifulSoup


def escape(text):
    soup=BeautifulSoup(str(text),'html.parser')
    for node in soup.select('script,style'):node.decompose()
    clean=' '.join(soup.get_text(' ',strip=True).split())
    return re.sub(r'([\\`*_{}\[\]<>#!|])',r'\\\1',clean)


def safe_url(url):
    if not isinstance(url,str) or len(url)>2048 or re.search(r'[\x00-\x20\x7f]',url):return ''
    parsed=urlparse(url)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password:return ''
    return quote(url,safe=':/?#&=%+@~-._')


def _line(label,text,budget):
    text=escape(text)
    # One concise thought per line, keeping source numbers intact.
    text=re.split(r'(?<=[.!?。])\s+',text,maxsplit=1)[0]
    value=f'{label}: {text}'
    return value if len(value)<=budget else value[:max(0,budget-1)]+'…'


def render_paper(item,label,language='ko',max_chars=400):
    ev,paper=item.evaluation,item.paper
    ko=language.lower().startswith('ko')
    coverage=('본문 일부 확인' if ev.coverage=='partial_html' else '초록 기반') if ko else ('Partial HTML checked' if ev.coverage=='partial_html' else 'Abstract only')
    attention=item.attention_label.replace('attention unknown','관심 미확인') if ko else item.attention_label
    labels=['문제','기여·근거','관심 주제','관심·한계','읽을 질문'] if ko else ['Problem','Contribution/evidence','Topic fit','Attention/limits','Reading question']
    quote_text=ev.evidence_spans[0].text if ev.evidence_spans else ''
    texts=[ev.reason,ev.contribution+' '+quote_text,ev.fit_reason,attention+'; '+ev.limitation,ev.reading_question]
    lines=[_line(name,text,max_chars//5) for name,text in zip(labels,texts)]
    links=[]
    for name,url in [('원문' if ko else 'Paper',paper.url)]+[('근거' if ko else 'Evidence',s.url) for s in ev.evidence_spans]:
        url=safe_url(url)
        if url and url not in [u for _,u in links]:links.append((name,url))
    return '\n'.join([f'### {label}: {escape(paper.title)}',*lines,
        f'{coverage} · {item.score:.2f}/5 · `{escape(paper.canonical_id)}`',
        ' · '.join(f'[{name}]({url})' for name,url in links)])


def render_digest(result,queued_events,language='ko',max_chars=400):
    ko=language.lower().startswith('ko')
    chunks=['# 오늘의 읽을 논문' if ko else '# Papers to read today']
    if not result.selected:chunks.append('오늘은 추천 기준을 충족하는 새 논문이 없습니다.' if ko else 'No new papers meet the selection criteria today.')
    for index,item in enumerate(result.selected):
        label=('정독 후보' if index==0 else '빠르게 훑어볼 후보') if ko else ('Read closely' if index==0 else 'Quick scan')
        chunks.append(render_paper(item,label,language,max_chars))
    if queued_events:
        chunks.append('## 팔로우 업데이트' if ko else '## Follow-up updates')
        chunks.extend(render_event(event,language,max_chars) for event in queued_events)
    return '\n\n'.join(chunks)+'\n'


def render_event(event,language='ko',max_chars=400):
    from .selection import ScoredPaper
    label=('새 연구' if event.kind=='author_paper' else '실질적 후속 연구') if language.startswith('ko') else ('New author paper' if event.kind=='author_paper' else 'Substantive follow-up')
    if event.evaluation:
        item=ScoredPaper(event.paper,event.evaluation,0,'attention unknown')
        return render_paper(item,label,language,max_chars)
    url=safe_url(event.paper.url)
    return f'### {label}: {escape(event.paper.title)}\n'+(f'[원문]({url})' if url else '')
