"""No background-preparation intermediate state can reach physical submission."""
import pytest

from printer_app.db import Database
from printer_app.print_queue_repository import PrintQueueRepository


@pytest.mark.parametrize('immediate', [False, True])
def test_preparation_must_finish_before_dispatch_even_if_batch_released(tmp_path, immediate):
    db = Database(tmp_path/'queue.db')
    mid = db.execute('''INSERT INTO processed_messages
        (identity,account,mailbox,uidvalidity,uid,message_id,subject,sender,created)
        VALUES ('1','fixture','INBOX','1','1','1','Fixture','fixture@example.test',1)''')
    aid = db.execute('''INSERT INTO attachments(message_id,part,filename,state,created)
        VALUES (?,'1','fixture.pdf','PROCESSING',1)''', (mid,))
    jid = db.create_job(aid, 'pdf', {})
    db.execute("UPDATE jobs SET status='READY' WHERE id=?", (jid,))
    db.execute("INSERT INTO print_queue_releases VALUES (?,2,'Fixture release')", (aid,))
    queue = PrintQueueRepository(db)
    assert not queue.eligible(db.job(jid), immediate)
    assert queue.due_jobs(3, immediate) == []
    db.execute("UPDATE attachments SET state='DONE' WHERE id=?", (aid,))
    assert queue.eligible(db.job(jid), immediate)
    assert [j['id'] for j in queue.due_jobs(3, immediate)] == [jid]
    # A legacy in-flight receipt is reconciled even when preparation was
    # interrupted. Holding it back could lose a durable CUPS acknowledgment.
    db.execute("UPDATE attachments SET state='PROCESSING' WHERE id=?", (aid,))
    db.execute('''INSERT INTO print_attempts(job_id,token,state,created,updated)
        VALUES (?,'fixture-token','HELD',2,2)''', (jid,))
    assert queue.eligible(db.job(jid), immediate)
    assert [j['id'] for j in queue.due_jobs(3, immediate)] == [jid]
