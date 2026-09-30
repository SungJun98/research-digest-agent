"""Explicit synthetic fixtures; never an alternative live scoring implementation."""
import json
from importlib.resources import files
from .models import Paper,Evaluation,FulltextContext,EvidenceSpan
from .runner import Runner
from .store import Store
from .delivery import Dispatcher
from .retrieval import Retriever,concepts


def offline_runner(config,state_path):
    data=json.loads(files('research_digest').joinpath('demo/papers.json').read_text())
    papers=[Paper.model_validate(item) for item in data]
    evaluations={key:Evaluation.model_validate(value) for key,value in json.loads(files('research_digest').joinpath('demo/evaluations.json').read_text()).items()}
    class Source:
        name='offline_synthetic_fixtures'
        def fetch(self,since,preview=False):return papers
    class FixtureEvaluator:
        def evaluate(self,paper,topics):
            result=evaluations[paper.canonical_id]
            if result.topic_id not in {t.id for t in topics}:
                text=concepts(paper.title+' '+paper.abstract)
                topic=max(topics,key=lambda t:len(text&concepts(t.description)))
                result=result.model_copy(update={'topic_id':topic.id})
            return result
        def reassess(self,paper,evaluation,context):
            return evaluation.model_copy(update={'coverage':'partial_html','evidence_spans':[EvidenceSpan(text='Only one task was tested.',source='partial_html',url=context.url)]})
    class FixtureHTML:
        def fetch(self,paper,max_chars):
            from bs4 import BeautifulSoup
            from .sources.fulltext import extract_relevant_sections
            text=extract_relevant_sections(BeautifulSoup(files('research_digest').joinpath('demo/sample.html').read_text(),'html.parser'))
            return FulltextContext(text=text[:max_chars],url='demo://sample.html')
    cfg=config.model_copy(deep=True)
    cfg.retrieval.embeddings_enabled=False
    store=Store(state_path)
    return Runner(cfg,store,[Source()],FixtureEvaluator(),Dispatcher(store,{}),retriever=Retriever(cfg.retrieval),fulltext=FixtureHTML() if cfg.retrieval.fulltext_enabled else None)
