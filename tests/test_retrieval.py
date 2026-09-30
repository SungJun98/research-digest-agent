import httpx
import pytest


def test_fallback_coverage_uniqueness_extras_and_cap():
    from research_digest.config import RetrievalConfig, Topic
    from research_digest.models import Paper
    from research_digest.retrieval import Retriever
    papers = [Paper(title=f'Safety alignment {i}',arxiv_id=f's{i}',signals={'hf_upvotes':i}) for i in range(40)]
    papers += [Paper(title=f'Reasoning verification {i}',arxiv_id=f'r{i}') for i in range(40)]
    papers += [papers[0]]
    topics = [Topic(id='safety',description='Safety alignment'),Topic(id='reasoning',description='Reasoning verification')]
    batch = Retriever(RetrievalConfig(),None).shortlist(papers,topics)
    assert batch.retrieval_mode == 'source_queries_and_categories'
    assert len(batch.papers) <= 50 and batch.truncated
    assert any(p.arxiv_id.startswith('s') for p in batch.papers)
    assert any(p.arxiv_id.startswith('r') for p in batch.papers)
    assert len({p.canonical_id for p in batch.papers}) == len(batch.papers)
    assert 's39' in {p.arxiv_id for p in batch.papers}


def test_embeddings_cache_content_model_and_failure(tmp_path,monkeypatch):
    from research_digest.config import RetrievalConfig,Topic
    from research_digest.models import Paper
    from research_digest.store import Store
    from research_digest.embeddings import Embedder,EmbeddingError
    from research_digest.retrieval import Retriever
    monkeypatch.setenv('EMBED_KEY','secret')
    calls=[]
    def respond(request):
        import json
        calls.append(request)
        inputs=json.loads(request.content)['input']
        return httpx.Response(200,json={'data':[{'index':i,'embedding':[1.0,0.0]} for i,_ in enumerate(inputs)]})
    cfg=RetrievalConfig(embeddings_enabled=True,embedding_base_url='https://example.com/v1',embedding_model='m',embedding_key_env='EMBED_KEY')
    store=Store(tmp_path/'state.db')
    client=httpx.Client(transport=httpx.MockTransport(respond))
    embedder=Embedder(client,cfg,store)
    assert embedder.embed(['x']) == embedder.embed(['x']) and len(calls)==1
    embedder.embed(['y'])
    Embedder(client,cfg.model_copy(update={'embedding_model':'m2'}),store).embed(['x'])
    assert len(calls)==3
    bad=Embedder(httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(503))),cfg,store)
    with pytest.raises(EmbeddingError): bad.embed(['uncached'])
    batch=Retriever(cfg,bad).shortlist([Paper(title='Safety')],[Topic(id='s',description='safety')])
    assert batch.retrieval_mode == 'source_queries_and_categories:embedding_failed'


def test_semantic_ranking_many_topics_obeys_evaluation_cap():
    from research_digest.config import RetrievalConfig, Topic
    from research_digest.models import Paper
    from research_digest.retrieval import Retriever
    class Vectors:
        def embed(self,texts):
            return [[1,0] if 'safety' in text else [0,1] for text in texts]
    cfg=RetrievalConfig(embeddings_enabled=True,embedding_base_url='https://example.org',embedding_model='m')
    papers=[Paper(title=f'Unrelated {i}',arxiv_id=f'{i}') for i in range(100)]
    papers.append(Paper(title='safety oversight',arxiv_id='special'))
    topics=[Topic(id=f't{i}',description='safety') for i in range(60)]
    batch=Retriever(cfg,Vectors()).shortlist(papers,topics)
    assert batch.retrieval_mode == 'semantic_embeddings'
    assert len(batch.papers) == 50
    assert 'special' in {p.arxiv_id for p in batch.papers}
