# THIRD_PARTY_NOTICES — image-local

이 저장소의 코드(`app.py`·`worker.py`·`gpu_pick.py`·`ui.html`·`selftest.py`·`setup.sh`)는 DongJu Kim(gggg8657)이 작성했으며 PolyForm Noncommercial 1.0.0 입니다. 제3자 코드·글꼴·아이콘·모델 가중치는 동봉하지 않습니다. 아래는 설치해서 쓰거나, 처음 쓸 때 내려받는 모델, 외부 서비스입니다.

조사 기준: 2026-10-12. 실제 파일(`requirements.txt`, `setup.sh`, `worker.py` 의 모델 id)을 보고, 라이선스는 `venv` 에 설치된 패키지의 dist-info 메타데이터와 Hugging Face 캐시에 받은 모델 카드(README 의 `license:` 필드)에서 확인했습니다. 버전은 이 서버의 `venv` 값입니다(고정 아님 — `requirements.txt` 는 하한만).

## 구성요소

| 이름 | 버전 | 쓰임 | 라이선스 | 링크 | 상업 이용 | 비고 |
|---|---|---|---|---|---|---|
| Qwen/Qwen-Image-2512 | HF 스냅샷 25468b9 | 내려받는 가중치(그리기, 약 58GB, `GEN_MODEL`) | Apache-2.0 (모델 카드 `license: apache-2.0`) | https://huggingface.co/Qwen/Qwen-Image-2512 | 가능 | 저장소에 없음. 생성물의 제3자 권리는 [#1](https://github.com/gggg8657/image-local/issues/1) |
| Qwen/Qwen-Image-Edit-2509 | HF 스냅샷 d3968ef | 내려받는 가중치(고치기, 약 58GB, `EDIT_MODEL`) | Apache-2.0 (모델 카드 `license: apache-2.0`) | https://huggingface.co/Qwen/Qwen-Image-Edit-2509 | 가능 | 위와 같음 |
| diffusers | 0.41.0 | 설치(pip) — `QwenImagePipeline`·`QwenImageEditPlusPipeline` | Apache-2.0 | https://github.com/huggingface/diffusers | 가능 | |
| transformers | 5.19.0 | 설치(pip) | Apache-2.0 | https://github.com/huggingface/transformers | 가능 | |
| accelerate | 1.15.0 | 설치(pip) | Apache-2.0 | https://github.com/huggingface/accelerate | 가능 | |
| safetensors | 0.8.0 | 설치(pip) | Apache-2.0 | https://github.com/huggingface/safetensors | 가능 | |
| Pillow | 12.3.0 | 설치(pip) | MIT-CMU | https://github.com/python-pillow/Pillow | 가능 | |
| PyTorch / torchvision (CUDA 12.x 빌드) | 2.14.1+cu126 / 0.29.1+cu126 | 설치(`setup.sh`, download.pytorch.org) | torch: BSD-3-Clause 계열(Apache-2.0·MIT·BSL-1.0 등 포함) / torchvision: BSD-3-Clause | https://pytorch.org | 가능 | |
| NVIDIA CUDA 런타임 휠 (`nvidia-cublas-cu12` 등) | 12.6.x | 설치(torch 의존성) | NVIDIA 소프트웨어 라이선스(재배포 조건 있음) | https://docs.nvidia.com/cuda/eula/ | 조건부 | 저장소에 넣지 않음. 묶어 재배포할 때만 조건 확인 |
| 프롬프트 다듬기 LLM — Google Gemma 4 `gemma4:31b` (포털 기본) / 단독 실행 기본 `qwen3:8b` | — | 외부 서비스(OpenAI 호환 API·Ollama, 선택) | Gemma 4: Apache-2.0 (Ollama `api/show` 의 license 필드로 확인) / Qwen3: Apache-2.0 | https://ai.google.dev/gemma , https://huggingface.co/Qwen/Qwen3-8B | 가능 | 가중치 동봉 안 함. `LLM_MODEL` 로 바꾸면 그 모델의 라이선스를 따름 |
| Ollama | — | 외부 서비스(LLM 서버) | MIT | https://github.com/ollama/ollama | 가능 | 동봉 안 함 |

README 스크린샷(`docs/img/`)의 그림은 이 도구가 Qwen-Image-2512 로 만든 이미지입니다.

## 확인 필요 (상업 이용 전)

- **Qwen-Image 생성·편집 결과물의 제3자 권리** ([#1](https://github.com/gggg8657/image-local/issues/1)): 모델은 Apache-2.0 이라 상업 이용이 가능하지만, 결과물에는 실존 인물 초상, 상표·로고, 기존 저작물과 비슷한 이미지 문제가 생길 수 있고, 학습 데이터 구성은 확인할 수 없습니다. 지금은 NSFW 부정 프롬프트를 항상 붙이고, 고치기 화면에 동의 경고를 띄웁니다. 대외 자료로 쓸 때는 사내 기준을 확인하세요. 다른 모델은 `GEN_MODEL`·`EDIT_MODEL` 로 바꿀 수 있습니다(그 모델의 라이선스를 따로 확인).

이 문서는 법률 자문이 아니며, 라이선스는 각 원문이 우선합니다.
