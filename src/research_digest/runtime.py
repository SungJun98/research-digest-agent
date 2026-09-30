"""Composition for the CLI; adapters themselves remain injectable for offline tests."""
from datetime import datetime,timedelta,timezone
import imaplib
import os
from .store import Store
from .runner import Runner
from .llm import Evaluator
from .embeddings import Embedder
from .retrieval import Retriever
from .sources.arxiv import ArxivSource
from .sources.huggingface import HuggingFaceSource
from .sources.scholar_mail import ScholarMailSource
from .sources.semantic_scholar import SemanticScholarSource
from .sources.fulltext import FulltextSource
from .delivery import Dispatcher,MarkdownTransport,SmtpTransport,SlackWebhookTransport,DiscordWebhookTransport
from .watch import WatchService


class Discovery:
    def __init__(self,name,fetcher):self.name,self.fetcher=name,fetcher
    def fetch(self,since,preview=False):return self.fetcher(since,preview)


def build_runner(config,client):
    store=Store(config.state_path)
    sources=[]
    if config.sources.arxiv.enabled:
        cfg=config.sources.arxiv
        source=ArxivSource(client,max_results=cfg.max_results)
        category='('+' OR '.join('cat:'+c for c in cfg.categories)+')'
        queries=cfg.queries or ([category] if cfg.categories else [])
        if not cfg.queries:
            for topic in config.profile.topics:
                terms=[word.replace('"','') for word in topic.include]
                if terms:queries.append(category+' AND ('+' OR '.join(f'all:"{word}"' for word in terms)+')')
        sources.append(Discovery('arxiv',lambda since,preview:source.fetch(queries,since)))
    if config.sources.huggingface.enabled:
        hf=HuggingFaceSource(client,config.sources.huggingface.limit)
        def hf_fetch(since,preview):
            today=datetime.now(timezone.utc).date()
            dates=[since.date()+timedelta(days=i) for i in range((today-since.date()).days+1)]
            return hf.fetch(dates)
        sources.append(Discovery('huggingface',hf_fetch))
    if config.sources.scholar_mail.enabled:
        cfg=config.sources.scholar_mail
        def imap_factory():
            connection=imaplib.IMAP4_SSL(cfg.host,cfg.port,timeout=30)
            connection.login(os.environ[cfg.username_env],os.environ[cfg.password_env])
            return connection
        mail=ScholarMailSource(imap_factory,store,cfg.mailbox,cfg.max_messages,account=cfg.host+':'+os.environ.get(cfg.username_env,''))
        sources.append(Discovery('scholar_mail',lambda since,preview:mail.fetch(since,set(cfg.allowed_senders),mark_fetched=not preview)))
    llm=config.llm
    evaluator=Evaluator(client,llm.base_url,llm.model,os.environ.get(llm.api_key_env) if llm.enabled else None,store,llm.max_requests_per_day,
        lenses=config.profile.lenses,exclude=config.profile.exclude,language=config.profile.summary_language,max_output_tokens=llm.max_output_tokens,json_mode=llm.json_mode)
    embeddings=Embedder(client,config.retrieval,store) if config.retrieval.embeddings_enabled else None
    s2cfg=config.sources.semantic_scholar
    semantic=SemanticScholarSource(client,os.environ.get(s2cfg.api_key_env),s2cfg.max_pages) if s2cfg.enabled else None
    watch=WatchService(semantic,store,evaluator,config.profile.topics) if semantic and (config.watchlist.authors or config.watchlist.papers) else None
    transports={}
    notify=config.notifications
    if notify.markdown.enabled:transports['markdown']=MarkdownTransport(notify.markdown.directory)
    if notify.email.enabled:transports['email']=SmtpTransport(notify.email)
    if notify.slack.enabled:transports['slack']=SlackWebhookTransport(client,os.environ.get(notify.slack.url_env,''))
    if notify.discord.enabled:transports['discord']=DiscordWebhookTransport(client,os.environ.get(notify.discord.url_env,''))
    return Runner(config,store,sources,evaluator,Dispatcher(store,transports),retriever=Retriever(config.retrieval,embeddings),
        fulltext=FulltextSource(client,store) if config.retrieval.fulltext_enabled else None,watch=watch,semantic_source=semantic)
