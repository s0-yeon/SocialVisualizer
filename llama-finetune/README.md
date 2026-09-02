# Llama 파인튜닝 및 서빙 파이프라인

SocialVisualizer의 그래프 인덱싱 및 질의응답에 사용되는 Llama 기반 모델의 파인튜닝, 평가, 서빙 관련 코드를 제공한다.

본 프로젝트에서는 `meta-llama/Llama-3.1-8B-Instruct`를 기반 모델로 사용하고, LoRA(Low-Rank Adaptation)를 적용하여 두 개의 어댑터를 독립적으로 학습했다.

- `index` adapter: 그래프 인덱싱을 위한 구조화된 정보 추출
- `query` adapter: 그래프 기반 질의응답

두 어댑터는 동일한 Base Model에서 각각 독립적으로 학습되며, 필요에 따라 개별적으로 서빙할 수 있다.

---

## 📌 1. 모델 구성

| Adapter | 담당 태스크 | 서빙 모델명 | 기본 포트 |
|---|---|---|---:|
| `index` | `extract_graph`, `community_reports` | `socialvisualizer-llama-index` | 8002 |
| `query` | `local_search`, `global_search` | `socialvisualizer-llama-query` | 8004 |

### ▸ 두 개의 LoRA Adapter를 사용하는 이유

인덱싱과 질의응답은 요구되는 출력 형태가 다르다.

- `extract_graph`, `community_reports`
  - 그래프의 엔티티·관계·커뮤니티 정보를 생성
  - 구조화된 형식의 출력이 중요
- `local_search`, `global_search`
  - 검색된 정보를 바탕으로 사용자 질문에 답변
  - 자연어 기반의 서술형 출력이 중요

따라서 두 태스크를 하나의 LoRA Adapter로 학습하기보다 각각 독립적인 Adapter로 학습하여 태스크 간 출력 분포의 간섭을 줄였다.

---

## 📌 2. 학습 데이터

모델 학습에는 실제 사용자의 이메일이나 메신저 데이터를 사용하지 않았다.

모든 SFT 학습 데이터는 오프라인 단계에서 자체 생성한 합성(가상) 데이터로 구성했다.

### ▸ 데이터 구성

| Adapter | 태스크 | 데이터 규모 |
|---|---|---:|
| `index` | `extract_graph` | 1,775건 |
| `index` | `community_reports` | 950건 |
| `index` | 합계 | 2,725건 |
| `query` | `local_search` | 143건 |
| `query` | `global_search` | 330건 |
| `query` | 합계 | 473건 |

### ▸ 데이터 도메인

- 메일 도메인
  - 세미나
  - 동아리
  - 졸업
  - 실험실
  - 장학금 등 대학원생의 일상을 소재로 한 가상 메일 데이터
- 메신저 도메인
  - 캡스톤 프로젝트 등의 가상 팀 대화 데이터 (총 13개 채팅방)

합성 데이터 생성 단계에서는 Claude/GPT 계열 LLM을 활용했다.

원천 데이터는 실존 인물이 아닌 가상의 인물·메일함·채팅방으로 생성했으며, 실제 개인 데이터는 포함하지 않았다.

### ▸ 데이터 가공

GraphRAG 프로덕션에서 실제 사용하는 프롬프트 템플릿을 재사용하여 각 태스크의 instruction-output 쌍을 구성한 뒤, LLaMA-Factory 학습을 위한 ShareGPT 3-turn 형식으로 변환했다.

`extract_graph` 데이터에는 원문 텍스트가 응답에 그대로 노출되는 사례를 제거하기 위한 근거 검증 필터를 적용했다.

`community_reports` 데이터는 토큰 예산을 초과하는 커뮤니티에 대해 트리밍된 컨텍스트 기반의 gold 데이터를 구성하고, citation을 원문 근거와 대조하여 검증했다.

`query` 데이터는 `local_search`와 `global_search`의 실제 프로덕션 처리 방식을 기반으로 구성했다.

---

## 📌 3. 공개 모델 가중치

파인튜닝 결과물은 LoRA Adapter 형태로 공개한다.

### ▸ Base Model

`meta-llama/Llama-3.1-8B-Instruct`

Base Model은 Meta의 Llama 라이선스 및 Hugging Face 접근 정책에 따라 별도로 준비해야 한다.

### ▸ LoRA Adapters

| Adapter | Hugging Face Repository |
|---|---|
| `index` | [Golden-Olive/llama-3.1-8b-socialvisualizer-index-lora](https://huggingface.co/Golden-Olive/llama-3.1-8b-socialvisualizer-index-lora) |
| `query` | [Golden-Olive/llama-3.1-8b-socialvisualizer-query-lora](https://huggingface.co/Golden-Olive/llama-3.1-8b-socialvisualizer-query-lora) |

각 Adapter는 LoRA 방식으로 학습되었으며, LoRA 설정은 `r=32`, `alpha=64`이다.

Adapter 하나의 용량은 약 335.6MB이다.

공개 저장소에는 `adapter_model.safetensors`, `adapter_config.json` 및 tokenizer 관련 파일 등 LoRA Adapter에 필요한 파일을 제공한다.

Base Model과 LoRA Adapter를 결합하여 사용할 수 있으며, 본 프로젝트에서는 병합된 모델을 vLLM을 통해 OpenAI-compatible API 형태로 서빙한다.

---

## 📌 4. 요구 환경

파인튜닝 및 모델 서빙에는 NVIDIA GPU 환경을 권장한다.

### ▸ 주요 소프트웨어

본 프로젝트의 모델 학습 및 서빙 개발 환경에서는 다음 버전을 사용했다.

| 소프트웨어 | 버전 |
|---|---|
| PyTorch | 2.13.0 (+cu130) |
| Transformers | 5.6.0 |
| PEFT | 0.18.1 |
| Datasets | 4.0.0 |
| Tokenizers | 0.22.2 |
| LLaMA-Factory | 0.9.5 |
| vLLM | 0.26.0 |

Python 버전을 포함해 전체 의존성의 버전 및 라이선스 정보는 프로젝트의 SBOM 문서를 참고.

### ▸ GPU

Llama 3.1 8B 모델의 파인튜닝 및 서빙에는 충분한 GPU VRAM이 필요하다

실제 GPU 메모리 사용량은 다음 설정에 따라 달라질 수 있다.

- GPU 종류 및 VRAM
- `max_model_len`
- `gpu_memory_utilization`
- batch size
- 파인튜닝 설정

따라서 본 프로젝트의 개발 환경과 다른 GPU 환경에서는 관련 설정을 조정해야 할 수 있다.

---

## 📌 5. 빠른 시작

공개된 LoRA Adapter를 이용하여 모델을 사용하는 경우 다음 순서로 진행한다.

### Step 1. Base Model 준비

[`meta-llama/Llama-3.1-8B-Instruct`](https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct)를 준비.

Llama 모델은 별도의 접근 권한 및 라이선스 조건이 적용될 수 있으므로 Hugging Face의 모델 페이지 안내를 먼저 확인.

### Step 2. LoRA Adapter 준비

사용 목적에 따라 Adapter를 선택.

- 그래프 인덱싱: `index`
- 질의응답: `query`

각 Adapter는 다음 Hugging Face 저장소에서 받을 수 있다.

- [Index Adapter](https://huggingface.co/Golden-Olive/llama-3.1-8b-socialvisualizer-index-lora)
- [Query Adapter](https://huggingface.co/Golden-Olive/llama-3.1-8b-socialvisualizer-query-lora)

### Step 3. Base Model + LoRA Adapter 구성

다운로드한 Base Model에 해당 LoRA Adapter를 적용.

필요한 경우 `training_configs/`에 제공된 merge 설정과 LLaMA-Factory의 merge/export 기능을 이용하여 Adapter가 적용된 모델을 별도의 모델 디렉터리로 export할 수 있다.

- `training_configs/index_merge.yaml`
- `training_configs/query_merge.yaml`

### Step 4. vLLM으로 모델 서빙

구성된 모델을 vLLM으로 실행.

GPU 번호와 모델 경로는 사용하는 환경에 맞게 변경.

#### Index Model

```bash
CUDA_VISIBLE_DEVICES=<GPU_ID> vllm serve <MODEL_PATH> \
  --served-model-name socialvisualizer-llama-index \
  --port 8002 \
  --max-model-len 32768
```

#### Query Model

```bash
CUDA_VISIBLE_DEVICES=<GPU_ID> vllm serve <MODEL_PATH> \
  --served-model-name socialvisualizer-llama-query \
  --port 8004 \
  --max-model-len 32768
```

> GPU 번호, 모델 경로, 포트 및 GPU 메모리 사용량 관련 설정은 사용자의 실행 환경에 맞게 변경해야 한다.

---

## 📌 6. SocialVisualizer 연결

SocialVisualizer에서는 그래프 인덱싱과 질의응답에 서로 다른 모델을 사용.

예시 환경 변수:

```env
INDEXING_CHAT_MODEL=socialvisualizer-llama-index
RAG_CHAT_MODEL=socialvisualizer-llama-query
```

vLLM은 OpenAI-compatible API를 제공하므로 SocialVisualizer에서는 각 모델 서버의 API endpoint를 통해 모델을 호출한다.

전체적인 구성은 다음과 같다.

```text
                         SocialVisualizer
                                │
              ┌─────────────────┴─────────────────┐
              │                                   │
       Graph Indexing                         User Query
              │                                   │
     ┌────────┴────────┐                 ┌────────┴────────┐
     │                 │                 │                 │
extract_graph   community_reports   local_search    global_search
     │                 │                 │                 │
     └────────┬────────┘                 └────────┬────────┘
              │                                   │
        Index LoRA Adapter                   Query LoRA Adapter
              │                                   │
         vLLM : 8002                         vLLM : 8004
```

임베딩 모델이나 기타 모델 서버를 함께 사용하는 경우 해당 endpoint도 별도로 설정해야 한다.

---

## 📌 7. 직접 파인튜닝하기

공개된 Adapter를 사용하는 대신 새로운 데이터로 모델을 다시 학습하려는 경우 다음 과정을 수행할 수 있다.

### ▸ Index Adapter

```text
학습 데이터
    ↓
GraphRAG 처리 결과
    ↓
SFT 데이터 구축
    ↓
ShareGPT JSONL 변환
    ↓
LLaMA-Factory
    ↓
LoRA Fine-tuning
    ↓
Merge / Export
    ↓
vLLM Serving
```

관련 스크립트:

```text
sft_data_construction/indexing/
training_configs/index_lora.yaml
training_configs/index_merge.yaml
```

### ▸ Query Adapter

```text
원본 데이터 및 GraphRAG 결과
    ↓
Query Context 구축
    ↓
SFT 데이터 생성
    ↓
LLaMA-Factory
    ↓
LoRA Fine-tuning
    ↓
Merge / Export
    ↓
vLLM Serving
```

관련 스크립트:

```text
sft_data_construction/query/
training_configs/query_lora.yaml
training_configs/query_merge.yaml
```

---

## 📌 8. 데이터 구축 전제조건

SFT 데이터 구축 스크립트를 실행하기 전에 GraphRAG 파이프라인을 통해 필요한 중간 산출물을 준비해야 한다.

이 디렉터리는 전체 데이터 처리 과정 중 다음 단계를 담당한다.

```text
원본 데이터
   ↓
GraphRAG Indexing
   ↓
GraphRAG 산출물
   ↓
SFT 데이터 구축
   ↓
LoRA Fine-tuning
   ↓
Model Serving
```

GraphRAG Indexing 단계에서 생성되는 주요 산출물은 다음과 같다.

```text
entities.parquet
relationships.parquet
communities.parquet
community_reports.parquet
```

SFT 데이터 구축 스크립트는 이러한 GraphRAG 산출물이 이미 존재하는 것을 전제로 동작한다.

---

## 📌 9. 디렉터리 구조

```text
llama-finetune/
├── README.md
├── LIMITATIONS.md
│
├── sft_data_construction/
│   ├── indexing/
│   │   ├── README.md
│   │   ├── build_context.py
│   │   ├── survey.py
│   │   ├── build_pairs.py
│   │   ├── compose_oversized.py
│   │   ├── finalize_pairs.py
│   │   ├── convert_to_sharegpt.py
│   │   ├── global_build_context.py
│   │   └── extract_graph_matching/
│   │
│   └── query/
│       ├── README.md
│       ├── room_names.py
│       ├── rebuild_lancedb.py
│       ├── local_build_context.py
│       ├── build_local_sft.py
│       ├── global_context_all.py
│       ├── extract_global_batches.py
│       ├── build_reduce_data.py
│       └── assemble_global_sft.py
│
├── training_configs/
│   ├── index_lora.yaml
│   ├── index_merge.yaml
│   ├── query_lora.yaml
│   └── query_merge.yaml
│
├── eval/
│   ├── Llama_mail_QA.xlsx
│   └── Llama_messenger_QA.xlsx
│
└── serving/
    └── gpu_server_ops.md
```

---

## 📌 10. QA 데이터 세트

`eval/` 디렉터리에는 합성 데이터를 기반으로 작성한 QA 세트를 제공한다.

```text
eval/
├── Llama_mail_QA.xlsx
└── Llama_messenger_QA.xlsx
```

이 QA 세트는 `query` adapter의 `local_search` SFT 학습 데이터를 만드는 데 사용한 원본으로(`sft_data_construction/query/build_local_sft.py` 참고), 143문항 전체가 train(129)/val(14)로 분할되어 학습 과정에 직접 사용됐다. 따라서 완전히 분리된 held-out 평가셋은 아니며, 질문·정답 형식과 프로덕션 응답 스타일을 확인하는 참고 자료로 제공한다.

---

## 📌 11. 제한사항 및 재현성

본 프로젝트의 모든 데이터 구축 및 학습 과정을 모든 환경에서 완전히 동일하게 재현할 수 없는 일부 제한사항이 존재한다.

자세한 내용은 [`LIMITATIONS.md`](./LIMITATIONS.md)를 참고.

주요 내용은 다음과 같다.

- Query SFT 데이터 구축 스크립트 일부는 연구 기록을 기반으로 재구성된 코드이다.
- 메신저 도메인의 일부 데이터 매칭은 근사 매칭 방식을 사용한다.
- 원본 합성 데이터 및 일부 중간 산출물은 저장소에 포함하지 않는다.
- GPU 및 라이브러리 버전에 따라 학습 및 서빙 결과가 달라질 수 있다.

---

## 📌 12. 서빙 운영 문서

본 프로젝트의 개발 GPU 서버에서 사용했던 구체적인 tmux 세션, GPU 번호, 디렉터리 경로 등의 운영 명령은 [`serving/gpu_server_ops.md`](./serving/gpu_server_ops.md)에 정리되어 있다.

해당 문서는 특정 개발 서버 환경에 종속되어 있으므로 다른 환경에서는 다음 항목을 자신의 환경에 맞게 수정해야 한다.

- GPU 번호
- 모델 경로
- 가상환경 경로
- 포트
- tmux 세션 이름

---

## 📌 13. 라이선스

본 프로젝트에서 사용하는 모델 및 소프트웨어의 라이선스는 각각의 원본 라이선스를 따른다.

### ▸ 주요 모델 및 라이브러리

| 구성 요소 | 버전 | 라이선스 |
|---|---|---|
| Llama 3.1 | - | Meta Llama License |
| LLaMA-Factory | 0.9.5 | Apache-2.0 |
| vLLM | 0.26.0 | Apache-2.0 |
| Transformers | 5.6.0 | Apache-2.0 |
| PEFT | 0.18.1 | Apache-2.0 |
| Datasets | 4.0.0 | Apache-2.0 |
| Tokenizers | 0.22.2 | Apache-2.0 |
| PyTorch | 2.13.0 (+cu130) | BSD 계열 |

위 항목 외에도 프로젝트 실행 환경에는 다양한 오픈소스 의존성이 포함되어 있다.

전체 라이브러리의 버전, 라이선스 및 공식 저장소 정보는 프로젝트의 SBOM 문서를 참고.

Llama 3.1 Base Model의 사용 및 재배포 조건은 Meta Llama License를 따라야 하며, 본 프로젝트에서는 Base Model 자체를 저장소에 포함하지 않고 LoRA Adapter만 공개한다.