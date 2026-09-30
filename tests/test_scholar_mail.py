from pathlib import Path
from datetime import datetime, timezone

NOW = datetime(2026,9,30,tzinfo=timezone.utc)
RAW = Path('tests/fixtures/scholar_alert.eml').read_bytes()


class FakeIMAP:
    def __init__(self, raw=RAW, received='30-Sep-2026 00:00:00 +0000'):
        self.raw, self.received, self.calls = raw, received, []
    def select(self, mailbox, readonly):
        assert readonly
        return 'OK', [b'1']
    def response(self, kind):
        return 'UIDVALIDITY', [b'42']
    def uid(self, command, *args):
        self.calls.append((command,args))
        if command == 'search': return 'OK',[b'101']
        assert args[-1] == '(BODY.PEEK[] INTERNALDATE)'
        return 'OK',[(f'1 (UID 101 INTERNALDATE "{self.received}")'.encode(),self.raw)]
    def logout(self): pass


def test_multipart_redirect_and_plain_text():
    from research_digest.sources.scholar_mail import parse_scholar_message
    papers = parse_scholar_message(RAW,NOW)
    assert len(papers) == 2
    assert papers[0].arxiv_id == '2609.12345'
    assert papers[0].abstract == 'Reasoning with reliable verification.'
    assert papers[0].metadata['scholar_subject'] == 'New research in reasoning'
    plain = b'From: scholaralerts-noreply@google.com\nContent-Type: text/plain\n\nReliable reasoning systems\nhttps://arxiv.org/abs/2609.12345'
    assert len(parse_scholar_message(plain,NOW)) == 1
    assert parse_scholar_message(b'broken',NOW) == []


def test_old_untrusted_uid_and_preview(tmp_path):
    from research_digest.sources.scholar_mail import ScholarMailSource
    from research_digest.store import Store
    store = Store(tmp_path/'state.db')
    allowed = {'scholaralerts-noreply@google.com'}
    source = ScholarMailSource(lambda:FakeIMAP(),store)
    assert len(source.fetch(NOW,allowed,mark_fetched=False)) == 2
    assert len(source.fetch(NOW,allowed)) == 2
    assert source.fetch(NOW,allowed) == []
    stale = ScholarMailSource(lambda:FakeIMAP(received='01-Sep-2026 00:00:00 +0000'))
    assert stale.fetch(NOW,allowed) == []
    spoof = ScholarMailSource(lambda:FakeIMAP(raw=RAW.replace(b'scholaralerts-noreply@google.com',b'other@example.com')))
    assert spoof.fetch(NOW,allowed) == []
