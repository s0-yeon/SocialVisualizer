# 파일명을 안전하게 정규화하고, 오래된 업데이트 결과·증분 업로드 파일을 정리하며, JSON 파일을 읽어온다.

# Sanitizes filenames, cleans up stale update-result and incremental upload files, and reads JSON files from disk.

import os
import re
import shutil
import datetime
import json

# 파일명에서 경로 구분자와 위험 문자를 제거해 안전한 파일명으로 정규화한다
def _sanitize_filename(name: str) -> str:
    name = os.path.basename(name or "attachment.bin").strip()
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name or "attachment.bin"

# 업데이트 결과 폴더(update_output) 중 가장 최근 것만 남기고 이전 폴더들을 삭제한다
def _delete_old_update_files(paths):
    update_output_dir = paths.UPDATE_DIR
    if not os.path.exists(update_output_dir):
        return

    folders = sorted([
        f for f in os.listdir(update_output_dir)
        if os.path.isdir(os.path.join(update_output_dir, f))
    ])

    for folder in folders[:-1]:
        folder_path = os.path.join(update_output_dir, folder)
        try:
            shutil.rmtree(folder_path)
            print(f"[CLEANUP] 삭제: {folder_path}")
        except Exception as e:
            print(f"[CLEANUP] 삭제 실패 (무시): {e}")

# input 폴더에서 증분 메일 파일(inc_*.txt/csv)과 attachment_latest.txt를 삭제한다
def _delete_incremental_files(paths):
    os.makedirs(paths.MAIL_DIR, exist_ok=True)

    for name in os.listdir(paths.MAIL_DIR):
        is_inc_txt = name.startswith("inc_") and name.endswith(".txt")
        is_inc_csv = name.startswith("inc_") and name.endswith(".csv")
        is_att_txt = name == "attachment_latest.txt"

        if is_inc_txt or is_inc_csv or is_att_txt:
            path = os.path.join(paths.MAIL_DIR, name)
            try:
                os.remove(path)
            except Exception as e:
                print(f"[UPLOAD] failed to remove incremental file: {path} / {e}")

# 증분 업로드 파일을 저장할 경로를 만든다 (inc_ 접두사가 없으면 타임스탬프 이름으로 새로 생성)
def _build_incremental_path(filename: str, paths) -> str:
    safe_name = _sanitize_filename(filename or "")
    if not safe_name.startswith("inc_"):
        safe_name = f"inc_{datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')}.txt"
    return os.path.join(paths.MAIL_DIR, safe_name)

# JSON 파일을 읽어 dict로 파싱해 반환한다
def _read_json_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
