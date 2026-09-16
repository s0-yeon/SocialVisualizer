# check_messenger_embed_dims.py (v2 - lancedb 기반)
#
# 이전 버전은 entities.parquet 안에 임베딩 컬럼이 있다고 가정했는데, 실제로는
# GraphRAG가 벡터를 entities.parquet이 아니라 <계정폴더>/graphrag/parquet/output/lancedb
# 아래 LanceDB 벡터 스토어에 따로 저장한다(app.py의 재인덱싱 초기화 코드에서 확인).
# 그래서 이번엔 lancedb를 직접 열어서 벡터 컬럼의 차원 수를 확인한다.
#   - 1024차원 -> 로컬 bge-m3로 인덱싱된 것 (OpenAI 전환 시 재임베딩 필요)
#   - 1536차원 -> 이미 OpenAI text-embedding-3-small로 인덱싱된 것
#
# 조회만 하며 아무것도 바꾸지 않음.
#
# MailGrapher 폴더 루트(src/ 옆)에 놓고 실행하세요:
#   python check_messenger_embed_dims.py

import os
import lancedb
import pyarrow as pa

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MESSENGER_ROOT = os.path.join(BASE_DIR, "user_data", "messenger")


def find_vector_dim(lancedb_dir: str):
    db = lancedb.connect(lancedb_dir)
    table_names = db.table_names()
    if not table_names:
        return None, None

    for name in table_names:
        tbl = db.open_table(name)
        schema = tbl.schema
        for field in schema:
            if pa.types.is_fixed_size_list(field.type):
                return name, field.type.list_size
        # fixed_size_list가 아니면(일반 list) 실제 행 하나를 읽어서 길이 확인
        try:
            row = tbl.to_pandas().iloc[0]
            for col in tbl.to_pandas().columns:
                val = row[col]
                if hasattr(val, "__len__") and not isinstance(val, str) and len(val) > 50:
                    return name, len(val)
        except Exception:
            pass
    return table_names[0], None


def main():
    if not os.path.isdir(MESSENGER_ROOT):
        print(f"[중단] {MESSENGER_ROOT} 폴더가 없습니다.")
        return

    room_dirs = sorted(
        d for d in os.listdir(MESSENGER_ROOT)
        if os.path.isdir(os.path.join(MESSENGER_ROOT, d))
    )
    if not room_dirs:
        print("메신저로 인덱싱된 채팅방이 없습니다.")
        return

    print(f"### 메신저 채팅방 {len(room_dirs)}개 확인\n")
    for room_dir in room_dirs:
        lancedb_dir = os.path.join(
            BASE_DIR, "user_data", "messenger", room_dir, "graphrag", "parquet", "output", "lancedb"
        )
        if not os.path.exists(lancedb_dir):
            print(f"  {room_dir}: lancedb 폴더 없음 (인덱싱 안 됨 또는 다른 엔진)")
            continue
        try:
            table_name, dim = find_vector_dim(lancedb_dir)
        except Exception as e:
            print(f"  {room_dir}: 읽기 실패 - {e}")
            continue

        if dim is None:
            print(f"  {room_dir}: 벡터 차원을 못 찾음 (테이블={table_name})")
        elif dim == 1024:
            print(f"  {room_dir}: {dim}차원  <- 로컬(bge-m3)로 인덱싱됨. OpenAI 전환 시 재임베딩 필요")
        elif dim == 1536:
            print(f"  {room_dir}: {dim}차원  <- 이미 OpenAI 임베딩")
        else:
            print(f"  {room_dir}: {dim}차원  <- 알 수 없는 모델")


if __name__ == "__main__":
    main()
