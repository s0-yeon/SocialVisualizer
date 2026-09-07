# src/util/lightrag_backend/lightrag_loop.py

# LightRAG 질의 전용 공유 이벤트 루프 모듈. 
# 백그라운드 스레드에서 절대 닫히지 않는 asyncio 이벤트 루프를 하나 띄워두고, Flask 요청 스레드들은 그 루프에 코루틴만 제출해 결과를 기다린다. 
# 요청마다 새 루프를 만들고 닫는 방식 대신 루프를 계속 재사용해서 LightRAG 내부 상태가 매번 다른 루프에 걸리는 문제를 막는다.

# Shared event loop dedicated to LightRAG queries. 
# Starts a single asyncio event loop on a background thread that never closes; Flask request threads only submit coroutines to it and wait for the result, instead of creating and closing a fresh loop per request.
# Prevents LightRAG's internal state from ending up bound to a different loop on every call.

import asyncio
import threading

_loop: "asyncio.AbstractEventLoop | None" = None
_thread: "threading.Thread | None" = None
_start_lock = threading.Lock()


# 전달받은 이벤트 루프를 현재 스레드에 붙이고 무한 실행한다
def _run_loop_forever(loop: "asyncio.AbstractEventLoop"):
    asyncio.set_event_loop(loop)
    loop.run_forever()


# 공유 질의용 이벤트 루프를 백그라운드 스레드에서 딱 한 번 띄우고 그 루프를 반환한다
def _ensure_loop_started() -> "asyncio.AbstractEventLoop":
    global _loop, _thread
    if _loop is not None:
        return _loop
    with _start_lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            _thread = threading.Thread(
                target=_run_loop_forever, args=(_loop,),
                daemon=True, name="lightrag-query-loop",
            )
            _thread.start()
    return _loop


# 코루틴을 공유 루프에 제출하고 호출한 스레드에서 결과를 기다려 반환한다
def run_coroutine(coro, timeout: "float | None" = None):
    loop = _ensure_loop_started()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)
