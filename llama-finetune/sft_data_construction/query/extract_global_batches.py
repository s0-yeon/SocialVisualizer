"""
extract_global_batches.py — MAP 배치별 질문 프롬프트 조립

global_context_all.py가 저장해둔 배치 텍스트(도메인당 1회만 계산, 질문과 무관하게 고정)에
파일럿 질문(메일 10 + 메신저 10)을 조합해, MAP 단계에서 실제로 서브에이전트/모델에 넣을
system/user 프롬프트 쌍을 전부 만들어낸다.

MAP: system = global_search_map.txt.format(context_data=배치, max_length=1000), user = 질문
(주의: max_length는 프롬프트 텍스트 어디에서도 실제로 참조되지 않음 — .format()의 미사용
kwarg는 조용히 무시됨. 응답 JSON은 {"points": [{"description", "score"}]} 포맷)

실측: 메일 10문항×17배치 + 메신저 10문항×14배치 = 170+140 = 310건의 MAP 태스크 생성.

## English summary
extract_global_batches.py assembles the per-MAP-batch question prompts.

Combines the batch texts global_context_all.py already saved (computed once per domain, fixed
regardless of question) with the pilot questions (10 mail + 10 messenger) to produce every
system/user prompt pair the MAP stage actually sends to the sub-agent/model.

MAP: system = global_search_map.txt.format(context_data=batch, max_length=1000), user = question
(note: max_length is never actually referenced anywhere in the prompt text — an unused .format()
kwarg is silently ignored. Response JSON format: {"points": [{"description", "score"}]}).

Measured: mail 10 questions x 17 batches + messenger 10 questions x 14 batches = 170+140 = 310
MAP tasks generated.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

MAP_MAX_LENGTH = 1000  # 프롬프트에 넘기지만 실제로는 참조되지 않는 파라미터 (프로덕션 프롬프트 소스 확인)


# 질문 목록 json 파일을 읽어옴
def load_questions(questions_json: Path) -> list[dict]:
    return json.loads(questions_json.read_text(encoding="utf-8"))


# 배치 텍스트 파일들과 질문 목록을 조합해(배치 x 질문) MAP 태스크 딕셔너리 리스트를 만듦
def build_map_tasks(batch_dir: Path, questions: list[dict], map_prompt_template: str, domain: str, room_id: str | None = None) -> list[dict]:
    tasks = []
    batch_files = sorted(batch_dir.glob("batch_*.txt"))
    for batch_file in batch_files:
        batch_text = batch_file.read_text(encoding="utf-8")
        system_prompt = map_prompt_template.format(context_data=batch_text, max_length=MAP_MAX_LENGTH)
        for q in questions:
            tasks.append({
                "domain": domain,
                "room_id": room_id,
                "batch_id": batch_file.stem,
                "question_id": q["id"],
                "question": q["question"],
                "system_prompt": system_prompt,
            })
    return tasks


# CLI 엔트리포인트: 메일/메신저 배치와 파일럿 질문을 조합해 MAP 태스크 jsonl을 만들어 저장함
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--global-batches-dir", type=Path, required=True,
                         help="global_context_all.py가 저장한 배치 텍스트 루트")
    parser.add_argument("--mail-questions", type=Path, required=True)
    parser.add_argument("--messenger-questions", type=Path, required=True)
    parser.add_argument("--global-search-map-prompt", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("map_tasks.jsonl"))
    args = parser.parse_args()

    map_prompt_template = args.global_search_map_prompt.read_text(encoding="utf-8")
    mail_questions = load_questions(args.mail_questions)
    messenger_questions = load_questions(args.messenger_questions)

    all_tasks: list[dict] = []

    mail_batch_dir = args.global_batches_dir / "mail"
    all_tasks += build_map_tasks(mail_batch_dir, mail_questions, map_prompt_template, domain="mail")

    for room_dir in sorted((args.global_batches_dir / "messenger").glob("msg_*")):
        all_tasks += build_map_tasks(
            room_dir, messenger_questions, map_prompt_template,
            domain="messenger", room_id=room_dir.name,
        )

    with args.out.open("w", encoding="utf-8") as f:
        for task in all_tasks:
            f.write(json.dumps(task, ensure_ascii=False) + "\n")

    print(f"MAP 태스크 총 {len(all_tasks)}건 -> {args.out}")
    print("(각 태스크의 system_prompt/question으로 모델을 호출해 "
          "map_results/{domain}_{room_id or ''}_{question_id}_{batch_id}.json 형태로 저장한 뒤 "
          "build_reduce_data.py로 REDUCE 입력을 만드세요.)")


if __name__ == "__main__":
    main()
