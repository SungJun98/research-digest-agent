from datetime import datetime, timezone


def test_transitive_alias_merge_and_conservative_fallback():
    from research_digest.models import Paper
    from research_digest.identity import merge_papers, canonicalize
    a = Paper(title='A result', arxiv_id='https://arxiv.org/abs/2605.21849v1', sources={'arxiv'})
    b = Paper(title='A result', arxiv_id='2605.21849v2', doi='https://doi.org/10.1234/ABC', sources={'hf'})
    c = Paper(title='Updated title', doi='10.1234/abc', s2_id='abc123', abstract='long abstract', sources={'s2'})
    merged = merge_papers([a, b, c])
    assert len(merged) == 1
    assert merged[0].canonical_id == 'doi:10.1234/abc'
    assert merged[0].sources == {'arxiv', 'hf', 's2'}
    assert merged[0].abstract == 'long abstract'
    assert canonicalize(Paper(title='Same', authors=['Alice'])) != canonicalize(Paper(title='Same', authors=['Bob']))


def test_alias_identity_survives_later_metadata(tmp_path):
    from research_digest.models import Paper
    from research_digest.store import Store
    store = Store(tmp_path / 'state.db')
    a = Paper(title='X', arxiv_id='2609.12345')
    store.upsert_papers([a])
    store.mark_paper_delivered(a.canonical_id, 'markdown', 'digest:x')
    b = Paper(title='X new', arxiv_id='2609.12345v2', doi='10.1/x')
    store.upsert_papers([b])
    assert store.paper_delivered('doi:10.1/x', 'markdown')
    assert len(store.list_papers()) == 1


def test_pending_notification_retries_after_reservation_restart(tmp_path):
    from research_digest.store import Store
    path = tmp_path / 'state.db'
    store = Store(path)
    store.create_notification('digest:x', 'Original', 'Original body', ['email', 'slack'], ['paper:x'])
    assert store.reserve_delivery('digest:x', 'email', now=100)
    store.mark_delivered('digest:x', 'email')
    assert store.reserve_delivery('digest:x', 'slack', now=100)
    reopened = Store(path)
    assert not reopened.reserve_delivery('digest:x', 'slack', now=101)
    assert reopened.reserve_delivery('digest:x', 'slack', now=401)
    reopened.create_notification('digest:x', 'Different', 'Different body', ['email', 'slack'])
    pending = reopened.pending_notifications()[0]
    assert pending.body == 'Original body'
    assert pending.pending_channels == ['slack']


def test_budget_cache_and_latest_explicit_feedback(tmp_path):
    from research_digest.store import Store
    store = Store(tmp_path / 'state.db')
    assert store.reserve_llm_request('2026-09-30', 1)
    assert not store.reserve_llm_request('2026-09-30', 1)
    store.put_cache('embedding', 'k', {'vector': [0.2, 0.8]})
    store.record_feedback('paper:x', 'useful', 'reasoning', datetime.now(timezone.utc))
    store.record_feedback('paper:x', 'not_relevant', 'reasoning', datetime.now(timezone.utc))
    reopened = Store(tmp_path / 'state.db')
    assert reopened.get_cache('embedding', 'k')['vector'] == [0.2, 0.8]
    assert reopened.list_feedback()[0]['kind'] == 'not_relevant'
    assert len(reopened.list_feedback()) == 1


def test_alias_root_merge_preserves_watch_and_latest_feedback(tmp_path):
    from datetime import datetime,timezone,timedelta
    from research_digest.models import Paper
    from research_digest.store import Store
    store=Store(tmp_path/'state.db')
    now=datetime(2026,9,30,tzinfo=timezone.utc)
    store.upsert_papers([Paper(title='A',arxiv_id='2609.12345'),Paper(title='B',s2_id='a'*40)])
    store.mark_watch_item_seen('author:123','s2:'+'a'*40)
    store.record_feedback('arxiv:2609.12345','useful','safety',now)
    store.record_feedback('s2:'+'a'*40,'not_relevant','safety',now+timedelta(seconds=1))
    store.upsert_papers([Paper(title='A',arxiv_id='2609.12345',s2_id='a'*40)])
    root=store.resolve('s2:'+'a'*40)
    assert store.watch_item_seen('author:123',root)
    records=store.list_feedback()
    assert len(records)==1 and records[0]['kind']=='not_relevant' and records[0]['paper_id']==root
