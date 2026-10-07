# image-local — 말로 그리기 · 말로 고치기 (폐쇄망 로컬)

글로 설명하면 그림을 그리고(**Qwen-Image-2512**), 있는 그림을 말로 고칩니다(**Qwen-Image-Edit-2509**). 모델·LLM 모두 이 서버에서 돌고 밖으로 나가는 요청은 없습니다(처음 한 번 모델 다운로드 제외).

- **그리기**: 스타일 9종(사진·일러스트·3D·애니메·수채화·포스터/인포그래픽·로고·제품 …), 비율 7종(1:1 1328², 16:9 1664×928 …), 1~4장, 품질 20/30/50 단계, 번호(seed)
- **한글 글자**: 따옴표 안 문구를 그림에 씀(짧은 제목·간판 수준). 글자 스타일엔 "Ultra HD, 4K" 같은 꼬리말을 붙이지 않음(그림에 글자로 찍혀 나옴)
- **프롬프트 다듬기**: 로컬 LLM(gemma4:31b)이 한국어 요청을 자세한 영어 프롬프트로 — 따옴표 문구는 그대로
- **고치기**: 그림 1~3장 + 지시("배경을 겨울로", "2번 옷을 1번 사람에게") → 결과 약 1MP
- **갤러리**: 끝난 것만, 받기·이걸로 고치기·같은 설정으로 다시·지우기(`.trash/` 로 이동)

## 실행
```bash
bash setup.sh          # venv(torch는 드라이버에 맞는 CUDA 빌드) → selftest → http://localhost:8792
bash setup.sh stop
venv/bin/python app.py --cli "비 오는 밤 우동집, 간판 \"우동\"" -o udon.png --style photo --ratio 16:9
```
포털(agent-page-portal)에서는 `그림 생성` 으로 켜고 끕니다.

## 구조
- `app.py` — stdlib 서버(SSE). 프리셋·LLM 다듬기·실행 기록(`WORKSPACE/<날짜-id>/meta.json, img_N.png`)
- `worker.py` — venv 의 GPU 작업 프로세스(127.0.0.1:8793, NDJSON). 필요할 때 app 이 띄움. 모델은 한 번에 하나만 올림,
  올릴 때마다 여유 메모리가 가장 큰 GPU 를 고름(`gpu_pick.py`), 모자라면 CPU 오프로드로 자동 전환, `GPU_IDLE_UNLOAD_S`(600초) 안 쓰면 내림
- 측정(H100, bf16, 통째로 GPU): 1664×928 30단계 **약 24초/장**, 첫 로드 +30초. GPU 메모리 약 60GB. 오프로드 모드는 약 65초/장
- 모델 캐시: Qwen-Image-2512 약 58GB(아바타 스튜디오와 같은 캐시) + Qwen-Image-Edit-2509 약 58GB (`~/.cache/huggingface`)

env: `PORT`(8792) `WORKER_PORT`(8793) `IMAGE_DEVICE`(고정하려면 cuda:N) `GPU_POOL` `OFFLOAD`(auto/1/0) `GEN_MODEL` `EDIT_MODEL` `LLM_API` `LLM_BASE_URL` `LLM_MODEL` `WORKSPACE`

## 주의
실존 인물·유명인, 동의 없는 실제 사람 사진 편집, 사칭, 선정적인 그림은 만들지 마세요. 서버는 모든 요청에 NSFW 네거티브 프롬프트를 붙입니다.

라이선스 MIT · 모델 Apache-2.0 — `NOTICE` 참고. © 2026 gggg8657
