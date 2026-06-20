import threading
from autogis.core.common.qa import QACollector, QARecord


def test_concurrent_add_keeps_every_record():
    qa = QACollector()
    def worker():
        for _ in range(1000):
            qa.add(QARecord(severity="INFO", category="t", message="m"))
    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert len(qa.records) == 8000
