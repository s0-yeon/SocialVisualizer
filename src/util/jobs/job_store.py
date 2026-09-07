# 인덱싱·질의·업데이트 등 모든 비동기 작업의 상태·진행률·로그·결과를 프로세스 메모리에 딕셔너리로 보관하고 스레드 안전하게 등록/갱신/조회한다 (서버 재시작 시 소멸, 영속성 없음).

# Keeps the status, progress, logs, and result of every async job (indexing/query/update) in an in-process dictionary with thread-safe create/update/read access (lost on server restart, no persistence).

import threading
import time

# 모든 작업 상태를 딕셔너리로 관리
_jobs = {}
# 여러 쓰레드가 동시에 _jobs를 수정하는 걸 막기 위한 Lock
_jobs_lock = threading.Lock()


# 새 비동기 작업을 queued 상태로 저장소에 등록한다
def create_job(job_id, job_type="index"):
    with _jobs_lock:                      # lock → 다른 쓰레드 접근 차단
        _jobs[job_id] = {
            "job_id": job_id,             # 작업 고유 ID
            "job_type": job_type,         # 작업 종류, index / query / update 등
            "status": "queued",           # queued / running / done / failed
            "progress": 0,                # 0 ~ 100
            "message": "대기 중",          # 상태 메시지
            "result": None,               # 결과 데이터
            "error": None,
            "logs": [],                   # 로그 저장
            "started_at": time.time(),    # 생성 시각
            "finished_at": None,          # 완료 시각
        }


# 해당 Job의 필드를 kwargs 값으로 갱신한다 (없는 job_id면 경고만 출력)
def update_job(job_id, **kwargs):  # Job 수정
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)    # kwargs로 받은 값들을 기존 job dict에 덮어씀
        else:   # 존재하지 않는 job_id일 경우
            print(f"[JOB_STORE] update_job failed: unknown job_id={job_id}")


# Job 로그에 한 줄을 추가하고 최근 100줄만 유지한다
def append_job_log(job_id, line):  # Job 로그 추가
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["logs"].append(line)
            _jobs[job_id]["logs"] = _jobs[job_id]["logs"][-100:]             # 로그가 너무 많아지는 걸 방지 → 최근 100개만 유지 (메모리 보호)
        else:
            print(f"[JOB_STORE] append_job_log failed: unknown job_id={job_id}")


# job_id로 Job 정보 복사본을 조회한다 (없으면 None)
def get_job(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        return dict(job)    # 복사본(dict(job))을 반환


# 저장소의 모든 Job을 {job_id: 복사본} 형태로 반환한다
def get_all_jobs():
    with _jobs_lock:
        return {job_id: dict(job) for job_id, job in _jobs.items()}
