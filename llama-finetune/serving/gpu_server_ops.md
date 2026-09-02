# GPU 서버 서비스 운영 치트시트

SocialVisualizer 개발 과정에서 사용한 GPU 서버의 모델 서비스 구성과 재기동, 로그 확인 방법을 정리한 문서다.

> **주의:** 이 문서는 프로젝트의 개발 GPU 서버 환경을 기준으로 작성됐다.
> GPU 번호, 서버 경로, 가상환경 경로, 포트 및 tmux 세션 이름은 다른 환경에서 그대로 사용할 수 없으며 필요에 따라 수정해야 한다.

---

## 서비스 목록

| tmux 세션 | 실제 모델 | GPU | 포트 | 용도 |
|---|---|---|---:|---|
| `socialvisualizer-v5-serve` | `socialvisualizer-llama-index` (merged) | GPU2 | 8002 | 인덱싱용 파인튜닝 모델 서빙 |
| `vllm-embed` | `BAAI/bge-m3` | GPU3 | 8001 | 임베딩 서버 |
| `vllm-llama` | `Qwen2.5-7B-Instruct` | GPU3 | 8003 | 서브태스크용 서빙 |
| `socialvisualizer-query-serve` | `socialvisualizer-llama-query` (merged) | GPU3 | 8004 | 질의(`local_search`/`global_search`)용 서빙 |
| `flux-server` | `FLUX.1-schnell` | GPU3 | - | 이미지/아바타 생성 |

---

## Python 가상환경

개발 GPU 서버에서는 서비스별로 별도의 Python 가상환경을 사용한다. Llama(vLLM) 서빙용 venv와
FLUX 이미지 생성용 venv는 서로 다른 의존성(각각 vLLM / torch+diffusers)을 요구하므로 반드시
구분해서 활성화해야 한다.

| 서비스 | 가상환경 경로 |
|---|---|
| Llama 서빙 (Index/Query/Qwen/BGE-M3) | `/workspace/socialvisualizer-llama-venv` |
| FLUX 이미지 생성 | `/workspace/flux-venv` |

새 환경에서 가상환경을 생성하는 예시는 다음과 같다.

```bash
# Llama 서빙용
python3 -m venv /workspace/socialvisualizer-llama-venv
source /workspace/socialvisualizer-llama-venv/bin/activate
pip install vllm

# FLUX 이미지 생성용 (별도 venv — torch/diffusers는 여기에만 설치한다)
python3 -m venv /workspace/flux-venv
source /workspace/flux-venv/bin/activate
pip install torch diffusers
```

가상환경을 생성한 후 프로젝트에서 사용하는 Python 및 모델 서빙 의존성을 설치한다.
정확한 라이브러리 버전은 상위 프로젝트의 SBOM 문서를 참고한다.

> Qwen2.5-7B-Instruct, BAAI/bge-m3는 Llama Index/Query 모델과 달리 별도로 준비해둘 로컬
> 모델 파일이 없다 — `vllm serve` 명령에 허깅페이스 repo id를 그대로 넘기면 처음 실행할 때
> 자동으로 가중치를 다운로드한다.

---

## 재기동 명령

### 1. Index 모델

GPU2에서 인덱싱용 파인튜닝 모델을 실행한다.

```bash
tmux new -s socialvisualizer-v5-serve
source /workspace/socialvisualizer-llama-venv/bin/activate

CUDA_VISIBLE_DEVICES=2 vllm serve /workspace/models/socialvisualizer-llama-v5-merged \
  --served-model-name socialvisualizer-llama-index \
  --port 8002 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.85
```

- GPU: `2`
- Port: `8002`
- Model: `socialvisualizer-llama-index`
- 용도: `extract_graph`, `community_reports`

### 2. BGE-M3 임베딩 서버

GPU3에서 임베딩 모델을 실행한다.

```bash
tmux new -s vllm-embed
source /workspace/socialvisualizer-llama-venv/bin/activate

CUDA_VISIBLE_DEVICES=3 vllm serve BAAI/bge-m3 \
  --convert embed \
  --port 8001 \
  --gpu-memory-utilization 0.1
```

- GPU: `3`
- Port: `8001`
- Model: `BAAI/bge-m3`
- 용도: 텍스트 임베딩

### 3. Qwen2.5-7B-Instruct

GPU3에서 서브태스크용 모델을 실행한다.

```bash
tmux new -s vllm-llama
source /workspace/socialvisualizer-llama-venv/bin/activate

CUDA_VISIBLE_DEVICES=3 vllm serve Qwen/Qwen2.5-7B-Instruct \
  --port 8003 \
  --gpu-memory-utilization 0.5
```

- GPU: `3`
- Port: `8003`
- Model: `Qwen2.5-7B-Instruct`
- 용도: 서브태스크용 서빙

### 4. FLUX 이미지 생성 서버

GPU3에서 이미지/아바타 생성 서버를 실행한다. Llama 서빙용 venv가 아니라
FLUX 전용 venv(`flux-venv`)를 활성화해야 한다 — torch/diffusers는 여기에만 설치돼 있다.

```bash
tmux new -s flux-server
source /workspace/flux-venv/bin/activate
cd /workspace

CUDA_VISIBLE_DEVICES=3 python flux_server.py
```

- GPU: `3`
- venv: `/workspace/flux-venv` (Llama 서빙용과 별도)
- 용도: 이미지/아바타 생성

### 5. Query 모델

GPU3에서 질의응답용 파인튜닝 모델을 실행한다.

```bash
tmux new -s socialvisualizer-query-serve
source /workspace/socialvisualizer-llama-venv/bin/activate

CUDA_VISIBLE_DEVICES=3 vllm serve /workspace/models/socialvisualizer-llama-query-merged \
  --served-model-name socialvisualizer-llama-query \
  --port 8004 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.3
```

- GPU: `3`
- Port: `8004`
- Model: `socialvisualizer-llama-query`
- 용도: `local_search`, `global_search`

---

## 모델명과 SocialVisualizer 설정

`--served-model-name`은 SocialVisualizer에서 사용하는 모델명과 일치하도록 설정했다.

```text
socialvisualizer-llama-index
socialvisualizer-llama-query
```

SocialVisualizer의 `.env`에서는 다음과 같이 지정한다.

```env
INDEXING_CHAT_MODEL=socialvisualizer-llama-index
RAG_CHAT_MODEL=socialvisualizer-llama-query
```

모델 서버의 주소나 포트를 변경한 경우 애플리케이션의 endpoint 설정도 함께 확인해야 한다.

---

## 로그 확인

### tmux 세션 접속

실행 중인 서비스의 터미널에 접속하려면 다음 명령을 사용한다.

```bash
tmux attach -t <세션명>
```

예:

```bash
tmux attach -t socialvisualizer-v5-serve
```

tmux에서 빠져나올 때는 서비스를 종료하지 않고 다음 키 조합을 사용한다.

```text
Ctrl+B → D
```

---

### 최근 로그 확인

세션에 직접 접속하지 않고 최근 로그를 확인하려면:

```bash
tmux capture-pane -t <세션명> -p -S -200
```

예:

```bash
tmux capture-pane -t socialvisualizer-v5-serve -p -S -200
```

`-S -200`은 최근 200줄을 확인하는 설정이다.

---

## 서비스 확인

현재 실행 중인 tmux 세션을 확인한다.

```bash
tmux ls
```

GPU 사용 현황은 다음 명령으로 확인할 수 있다.

```bash
nvidia-smi
```

서비스가 정상적으로 실행되지 않는 경우 다음 항목을 확인한다.

1. 해당 GPU의 메모리가 충분한지 확인
2. 포트가 다른 프로세스에서 사용 중인지 확인
3. 모델 경로가 올바른지 확인
4. Python 가상환경이 올바르게 활성화되었는지 확인
5. `CUDA_VISIBLE_DEVICES`가 올바른 GPU를 가리키는지 확인
6. `--gpu-memory-utilization` 및 `--max-model-len` 설정을 확인

---

## 환경에 맞게 수정해야 하는 항목

이 문서의 명령을 다른 GPU 서버에서 사용하는 경우 다음 항목을 수정해야 한다.

| 항목 | 개발 서버 설정 | 다른 환경에서 |
|---|---|---|
| GPU 번호 | GPU2 / GPU3 | 사용 가능한 GPU로 변경 |
| Python 환경 (Llama 서빙) | `/workspace/socialvisualizer-llama-venv` | 자신의 가상환경 경로로 변경 |
| Python 환경 (FLUX) | `/workspace/flux-venv` | 자신의 가상환경 경로로 변경 |
| Index 모델 경로 | `/workspace/models/socialvisualizer-llama-v5-merged` | 실제 모델 경로로 변경 |
| Query 모델 경로 | `/workspace/models/socialvisualizer-llama-query-merged` | 실제 모델 경로로 변경 |
| FLUX 서버 경로 | `/workspace/flux_server.py` | 실제 파일 위치로 변경 |
| 포트 | 8001~8004 | 사용 가능한 포트로 변경 |
| tmux 세션 | 문서의 세션명 | 필요에 따라 변경 |

> 본 문서는 개발 환경의 운영 기록을 보존하기 위한 문서다.
> 일반적인 모델 설치 및 서빙 방법은 상위 디렉터리의 [`EXECUTE.md`](../../docs/EXECUTE.md)를 참고한다.