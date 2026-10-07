#!/usr/bin/env bash
# image-local — 원샷 설치·실행 (Linux + NVIDIA GPU). bash setup.sh | bash setup.sh stop
# env: PORT(8792) WORKER_PORT(8793) LLM_API·LLM_BASE_URL·LLM_MODEL(프롬프트 다듬기) — 모델(약 112GB)은 처음 쓸 때 HF 에서 받음
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8792}"
ok(){ printf '  ✔ %s\n' "$*"; }; die(){ printf '  ✘ %s\n' "$*" >&2; exit 1; }
if [ "${1:-}" = stop ]; then [ -f .worker.pid ] && kill "$(cat .worker.pid)" 2>/dev/null; rm -f .worker.pid  # GPU 작업 프로세스
  [ -f .server.pid ] && kill "$(cat .server.pid)" 2>/dev/null && rm -f .server.pid && ok "서버 종료" || echo "  실행 중 아님"; exit 0; fi
PY=""; for c in python3.11 python3.12 python3.10 python3; do command -v $c >/dev/null && $c -c 'import sys;sys.exit(0 if (3,10)<=sys.version_info<(3,13) else 1)' 2>/dev/null && { PY=$c; break; }; done
[ -n "$PY" ] || { command -v uv >/dev/null && PY=3.11 || die "Python 3.10~3.12 필요"; }
if [ ! -x venv/bin/python ]; then if command -v uv >/dev/null; then uv venv --python "$PY" venv -q; else $PY -m venv venv; fi; fi
ok "$(venv/bin/python --version)"
# GPU 드라이버에 맞는 torch — PyPI 기본 torch 는 CUDA 13 빌드라 드라이버가 CUDA 12.x 면 GPU 를 못 쓴다(드라이버 570 = 12.8)
TORCH_CU=""; TORCH_ARGS=()
if command -v nvidia-smi >/dev/null 2>&1; then
  _cu=$(nvidia-smi 2>/dev/null | sed -n 's/.*CUDA Version: \([0-9]*\)\.\([0-9]*\).*/\1\2/p' | head -1)
  if [ -n "$_cu" ] && [ "$_cu" -lt 130 ]; then TORCH_CU=cu121; [ "$_cu" -ge 124 ] && TORCH_CU=cu124; [ "$_cu" -ge 126 ] && TORCH_CU=cu126
    if command -v uv >/dev/null; then TORCH_ARGS=(--torch-backend "$TORCH_CU"); else TORCH_ARGS=(--extra-index-url "https://download.pytorch.org/whl/$TORCH_CU"); fi; fi
fi
venv/bin/python -c "import torch, torchvision, diffusers, transformers, accelerate" 2>/dev/null || {
  echo "  · 의존성 설치 (torch 포함, 수 분)"
  if command -v uv >/dev/null; then VIRTUAL_ENV=$PWD/venv uv pip install -q "${TORCH_ARGS[@]}" torch torchvision -r requirements.txt
  else venv/bin/pip install -q "${TORCH_ARGS[@]}" torch torchvision -r requirements.txt; fi
}
venv/bin/python -c "import torch,sys;sys.exit(0 if torch.cuda.is_available() else 1)" && ok "venv 준비 (GPU 사용 가능)" || echo "  ! GPU 를 못 잡음 — CPU 로는 너무 느려 실사용 불가"
env -u WORKSPACE python3 selftest.py >/dev/null && ok "selftest 통과" || die "selftest 실패"
[ -f .server.pid ] && kill "$(cat .server.pid)" 2>/dev/null || true
PORT=$PORT nohup python3 app.py > server.log 2>&1 & echo $! > .server.pid
for _ in $(seq 1 30); do curl -fsS "http://localhost:$PORT/api/status" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS "http://localhost:$PORT/api/status" >/dev/null || { cat server.log; die "서버 기동 실패"; }
ok "http://localhost:$PORT  (종료: bash setup.sh stop) — 그림 모델은 처음 그릴 때 받음/올림"
