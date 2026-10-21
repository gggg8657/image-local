# image-local — 말로 그리기 · 말로 고치기 (폐쇄망 로컬)

말로 그리고 말로 고치는 범용 그림 도구입니다 — 글로 설명하면 그림을 그리고(**Qwen-Image-2512**), 있는 그림을 말로 고칩니다(**Qwen-Image-Edit-2509**). 한글 글자·사진/일러스트/포스터/로고. 포트 `8792`.

> ⚠️ 연구·내부 시험용 프로토타입입니다(배포·상업 서비스용 아님). 제3자 구성요소의 라이선스는 THIRD_PARTY_NOTICES.md 를 확인하세요.

![그리기 화면 — 요청·스타일 → 품질·그리기 → 결과(받기·이걸로 고치기)](docs/img/gen.png)

## 무엇을 하나

모델·LLM 모두 이 서버에서 돌고 밖으로 나가는 요청은 없습니다(처음 한 번 모델 다운로드 제외).

- **그리기**: 스타일 9종(그대로·사진·일러스트·3D 렌더·애니메·수채화·포스터/인포그래픽·로고/아이콘·제품 사진), 비율 7종(1:1 1328², 16:9 1664×928 …), 1~4장, 품질 빠르게 20 / 보통 30 / 고품질 50 단계, 번호(seed)
- **한글 글자**: 따옴표 안 문구만 그림에 씀(짧은 제목·간판 수준). 따옴표로 주지 않은 글자(날짜·이름 등)는 그림에 넣지 않음
- **프롬프트 다듬기**: 로컬 LLM(포털 기본 `gemma4:31b`)이 한국어 요청을 영어 한 문단(40~80단어)으로 — 아래 "프롬프트 다듬기" 참고
- **다듬기만 보기**: 그리지 않고 다듬은 문장과 "추가한 것: 장소 디테일·조명·구도" 같은 한 줄 설명을 보여 줌. 문장을 고친 뒤 **이 문장 그대로 그리기**로 다듬기 없이 그대로 보냄
- **고치기**: 그림 1~3장 + 지시("배경을 겨울로", "2번 옷을 1번 사람에게") → 결과 약 1MP
- **갤러리**: 끝난 것만, 받기·이걸로 고치기·같은 설정으로 다시·지우기(`.trash/` 로 이동)

## 사용 방법

**그리기** (위 화면, 빨간 상자가 누를 곳)

1. **요청**을 한국어로 편하게 씁니다. 그림 안에 넣을 글자는 따옴표로 감쌉니다 — 예) 포스터, 제목 "안전이 먼저입니다".
2. **스타일**과 **비율**을 고릅니다.
3. **장수·품질·번호(#)·프롬프트 다듬기(LLM)**를 정합니다. 같은 번호면 같은 그림이 나오고, 비우면 매번 새로 그립니다. 빼고 싶은 것(네거티브)은 그 아래 접힌 칸에 적습니다.
4. **그리기**를 누르면 진행률이 보이고 결과가 바로 아래에 뜹니다. 보통 품질 1장 약 25초, 처음 한 번은 모델을 GPU 에 올리느라 1~2분 더 걸립니다.
5. **갤러리**의 그림을 누르면 크게 보기 창이 열립니다.

![크게 보기 — 받기 · 이걸로 고치기 · 같은 설정으로 다시 · 지우기](docs/img/view.png)

6. 크게 보기 창에서 받기·이걸로 고치기·같은 설정으로 다시·지우기를 하고, 아래에서 원래 요청·그림 모델에 실제로 보낸 프롬프트·설정을 확인합니다.

**고치기**

![고치기 화면 — ① 그림 올리기 ② 고칠 그림 ③ 지시 ④ 고치기](docs/img/edit.png)

1. 그림을 끌어다 놓거나 눌러서 고릅니다(①, 1~3장 · png/jpg/webp). 갤러리에서 **이걸로 고치기**를 누르면 그 그림이 바로 들어옵니다.
2. 올라간 그림(②)을 확인합니다. ✕ 로 뺄 수 있고, 여러 장이면 "1번 사람에게 2번 옷을 입혀 줘" 처럼 합칠 수 있습니다.
3. **어떻게 고칠지**(③)를 씁니다 — "배경을 눈 내리는 겨울 숲으로", "수채화 느낌으로", 간판 글자 바꾸기 등.
4. **고치기**(④)를 누릅니다. 처음엔 고치기 모델을 올리느라 1~2분 더 걸립니다.

## 프롬프트 다듬기

1. **장면 계획**(JSON): 주제·동작 / 장소(구체적인 모습) / 시간·빛 / 구도 / 분위기 / 스타일 / 빼야 할 것 / 보탠 것(한국어). 나라·시대·사건이 나오면 그곳 그때의 모습(건물·차량·제복·옷차림·거리)을 채우고, 사용자가 쓴 날짜·이름은 고치지도 글자로 넣지도 않습니다. 실존 인물은 그리지 않습니다.
2. **문단 쓰기**: 계획으로 영어 한 문단(40~80단어). 스타일이 매체를 정합니다 — 사진은 렌즈·빛의 방향·색 표현, 수채화는 번짐·종이 결, 애니메는 셀 셰이딩·선, 3D 는 재질·조명, 포스터·로고는 배치·색 수.
3. **서버 검사**(LLM 온도 0.3): 사용자가 따옴표로 주지 않은 문구가 따옴표로 들어가면, 상투어(cinematic·moody·high-contrast·4K·masterpiece·stunning·epic·hyper-realistic …, 사용자가 원하면 허용)가 있으면, 길이가 크게 벗어나면 한 번 다시 쓰게 하고, 그래도 남으면 그 문장·낱말을 지웁니다. 문단에 스타일 매체 말이 없으면 앞에 붙입니다(예: `Watercolor painting.`).
4. **빼야 할 것**은 네거티브 프롬프트에 더합니다(글자를 넣는 그림이 아니면 `text, watermark` 도). 실행 기록의 `auto_negative` 에 남습니다.

꼬리말: 다듬기를 끄면 원문 + 스타일 꼬리(예: `digital illustration, clean shapes, pleasant colors`). Qwen-Image 공식 꼬리말 `Ultra HD, 4K, cinematic composition` 은 스타일 **그대로·사진**이고 글자 디자인이 아닐 때만, 이미 비슷한 말이 없을 때만 붙입니다. 다듬기를 켜면 붙이지 않습니다. 이미 들어 있는 말은 다시 붙이지 않고 `., ,` 같은 구두점은 정리합니다. LLM 이 실패하면 다듬기를 끈 것과 같은 문장으로 그립니다.

API: `POST api/refine {prompt, style}` → `{final_prompt, summary_ko, negative}`(실패하면 `fallback: true` 와 다듬기 없는 문장). `POST api/generate` 에 `exact: true` 를 주면 받은 문장을 꼬리말 없이 그대로 그립니다.

## 예시

포털 경유로 실제 실행한 결과입니다(2026-10-12, 실행 `2026-10-12-c14ee5`, 위 화면의 그림).

- **입력**: "연구실 책상 위 작은 화분, 옆에 "gggg8657" 이라고 적힌 나무 팻말, 창가의 따뜻한 오후 햇살" · 스타일 일러스트 · 4:3 · 빠르게(20단계) · 1장 · 프롬프트 다듬기 켬
- **다듬어진 프롬프트**(LLM): "A clean digital illustration of a small potted plant sitting on a tidy research laboratory desk. Beside the plant is a small wooden sign with the text "gggg8657" clearly engraved on it. Warm afternoon sunlight streams through a nearby window … bright, airy lighting scheme."
- **출력**: 1472×1104 PNG 1장 · 번호 #851036815 (같은 번호·설정이면 같은 그림) · 팻말에 따옴표 문구 "gggg8657" 이 그대로 들어감

## 설치·실행
```bash
bash setup.sh          # venv(torch는 드라이버에 맞는 CUDA 빌드) → selftest → http://localhost:8792
bash setup.sh stop
venv/bin/python app.py --cli "비 오는 밤 우동집, 간판 \"우동\"" -o udon.png --style photo --ratio 16:9 [--quality fast|normal|high]
```
포털(agent-page-portal)에서는 `그림 생성` 으로 켜고 끕니다.
포털이 띄우면(`PORTAL_JOBS_*` 환경변수) 그리기·고치기의 시작·완료·실패를 포털 작업 알림(🔔)에 알리고(`portal_jobs.py`, 실패해도 도구 동작엔 영향 없음), 알림을 누르면 `/?run=<ID>` 로 그 그림이 크게 열립니다. 단독 실행에서는 아무것도 보내지 않습니다.

## 구조
- `app.py` — stdlib 서버(SSE). 프리셋·LLM 다듬기·실행 기록(`WORKSPACE/<날짜-id>/meta.json, img_N.png`)
- `worker.py` — venv 의 GPU 작업 프로세스(127.0.0.1:8793, NDJSON). 필요할 때 app 이 띄움. 모델은 한 번에 하나만 올림,
  올릴 때마다 여유 메모리가 가장 큰 GPU 를 고름(`gpu_pick.py`), 모자라면 CPU 오프로드로 자동 전환, `GPU_IDLE_UNLOAD_S`(600초) 안 쓰면 내림
- 측정(H100, bf16, 통째로 GPU): 1664×928 30단계 **약 24초/장**, 첫 로드 +30초. GPU 메모리 약 60GB. 오프로드 모드는 약 65초/장
- 모델 캐시: Qwen-Image-2512 약 58GB(아바타 스튜디오와 같은 캐시) + Qwen-Image-Edit-2509 약 58GB (`~/.cache/huggingface`)

env: `PORT`(8792) `WORKER_PORT`(8793) `IMAGE_DEVICE`(비우면 자동, 고정하려면 cuda:N) `GPU_POOL` `GPU_IDLE_UNLOAD_S`(600) `GPU_PICK_HOLD_S`(600) `OFFLOAD`(auto/1/0) `GEN_MODEL` `EDIT_MODEL` `LLM_API`(ollama/openai) `LLM_BASE_URL` `LLM_MODEL`(기본 `qwen3:8b`, 포털로 띄우면 `gemma4:31b`) `WORKSPACE`(기본 `./_workspace`)

포털 접속자 기준으로 그림·갤러리·휴지통·올린 원본은 사용자별로 따로 저장합니다(`WORKSPACE/u/<사용자>/`, 포털이 넘기는 `X-Agent-User` 헤더). 서버 주인(owner)·단독 실행은 예전처럼 `WORKSPACE` 바로 아래를 쓰므로 예전 기록이 그대로 보입니다. 포털이 `BIND=127.0.0.1` 을 주면 포털을 거쳐서만 열립니다. GPU 작업 프로세스에는 요청 때 그 사용자 폴더를 `out_dir` 로 넘깁니다.

## 주의
실존 인물·유명인, 동의 없는 실제 사람 사진 편집, 사칭, 선정적인 그림은 만들지 마세요. 서버는 모든 요청에 NSFW 네거티브 프롬프트를 붙입니다.

## 출처·감사 (Credits)

- 그리기 모델 [Qwen/Qwen-Image-2512](https://huggingface.co/Qwen/Qwen-Image-2512), 고치기 모델 [Qwen/Qwen-Image-Edit-2509](https://huggingface.co/Qwen/Qwen-Image-Edit-2509) — Alibaba Qwen 팀, Apache-2.0 (가중치는 동봉하지 않음, 처음 쓸 때 Hugging Face 에서 받음)
- 실행: [PyTorch](https://github.com/pytorch/pytorch) (BSD-3), [diffusers](https://github.com/huggingface/diffusers)·[transformers](https://github.com/huggingface/transformers)·[accelerate](https://github.com/huggingface/accelerate)·safetensors (Apache-2.0), [Pillow](https://github.com/python-pillow/Pillow) (MIT-CMU), NVIDIA CUDA 런타임 휠(NVIDIA 라이선스, torch 와 함께 설치)
- **프롬프트 다듬기 LLM** — 기본 배포는 [Ollama](https://github.com/ollama/ollama) (MIT) 위의 Google [Gemma 4](https://ai.google.dev/gemma) `gemma4:31b` (Apache-2.0). 단독 실행 기본값은 `qwen3:8b` (Apache-2.0).
- 생성·편집 결과물을 대외 자료로 쓸 때는 초상·상표·기존 저작물 유사성을 확인하세요([#1](https://github.com/gggg8657/image-local/issues/1)). 다른 모델은 `GEN_MODEL`·`EDIT_MODEL` 로 바꿀 수 있습니다(그 모델의 라이선스를 따로 확인).
- 이 도구는 [agent-page-portal](https://github.com/gggg8657/agent-page-portal) 에 연결해 쓰도록 만들었습니다(단독 실행도 됨).

전체 목록·라이선스·상업 이용 확인 항목은 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md), 저작권 표기는 `NOTICE` 를 보세요.

## 라이선스

[PolyForm Noncommercial License 1.0.0](LICENSE) — Copyright 2026 DongJu Kim (gggg8657). 모델 가중치는 각 배포처의 라이선스(Apache-2.0)를 따릅니다.

- 비상업 목적(개인 연구·학습·시험, 교육기관·공공 연구기관·정부기관·비영리 단체 등)이면 쓰고 고치고 다시 배포할 수 있습니다. 다시 배포할 때는 `LICENSE` 와 `Required Notice:` 줄을 함께 주세요.
- 상업적 이용은 저작자의 별도 허락이 필요합니다.
- 2026-10-13 이전 버전(커밋 `7cdb5fb` 까지)을 MIT 로 받아 간 사본에는 MIT 가 계속 적용됩니다. 이 변경은 이후 버전에만 적용됩니다.
- 제3자 구성요소는 각자의 원래 라이선스를 따르며 이 라이선스로 바뀌지 않습니다(`THIRD_PARTY_NOTICES.md`, `NOTICE`).

## 만든 사람

DongJu Kim (gggg8657) — 설계·구현
