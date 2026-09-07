# 인덱싱 진행/완료/실패 이벤트를 여러 SSE 구독자에게 실시간으로 전달하기 위한 인메모리 구독·브로드캐스트 큐를 관리한다.

# Manages in-memory subscribe/broadcast queues used to push indexing progress/done/failed events to multiple SSE subscribers in real time.

import threading
import queue
import json

_queues: list[queue.Queue] = []
_lock = threading.Lock()


# 새 SSE 구독 큐를 만들어 구독자 목록에 등록하고 반환한다
def subscribe() -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=30)
    with _lock:
        _queues.append(q)
    return q


# 구독 큐를 구독자 목록에서 제거한다
def unsubscribe(q: queue.Queue) -> None:
    with _lock:
        if q in _queues:
            _queues.remove(q)


# 모든 구독자 큐에 이벤트를 넣고, 큐가 꽉 찬(끊긴) 구독자는 목록에서 제거한다
def broadcast(data: dict) -> None:
    with _lock:
        dead = []
        for q in _queues:
            try:
                q.put_nowait(data)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _queues.remove(q)
