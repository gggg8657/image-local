#!/usr/bin/env python3
"""image-local GPU 작업 프로세스 — app.py 가 필요할 때 venv 파이썬으로 띄우고 127.0.0.1 에서만 받는다.
그리기 Qwen-Image-2512 / 고치기 Qwen-Image-Edit-2509 (둘 다 Apache-2.0). 모델은 한 번에 하나만 올리고,
기본은 GPU 에 통째로(장당 약 25초), 다른 도구가 GPU 를 쓰고 있어 모자라면 CPU 오프로드(필요한 부분만 GPU 로, 약 40GB·장당 약 65초)로 자동 전환.
IDLE_MIN 분 동안 안 쓰면 모델을 내려 GPU 를 비운다. 응답은 줄마다 JSON(NDJSON), 마지막 줄이 {"done"} 또는 {"error"}.

  POST /generate {prompt, negative, width, height, n, seed, steps, cfg, out_dir} → out_dir/img_<i>.png
  POST /edit     {images[], prompt, negative, n, seed, steps, cfg, out_dir}     → out_dir/img_<i>.png

GPU 는 고정하지 않는다: 모델을 올릴 때마다 그 순간 여유 메모리가 가장 큰 GPU 를 고른다(gpu_pick.py).
env: WORKER_PORT(8793) IMAGE_DEVICE(비우면 자동, cuda:1 처럼 주면 고정) GPU_POOL GPU_IDLE_UNLOAD_S(600) OFFLOAD(auto/1/0)
     GEN_MODEL(Qwen/Qwen-Image-2512) EDIT_MODEL(Qwen/Qwen-Image-Edit-2509)"""
import gc, json, os, threading, time, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from gpu_pick import IDLE_S, free_cuda, gpus, label, pick, release, torch_device  # torch 보다 먼저 (CUDA_DEVICE_ORDER)
import torch
from PIL import Image

PORT = int(os.environ.get("WORKER_PORT", "8793"))
DEV = os.environ.get("IMAGE_DEVICE", "")  # 비우면 모델 올릴 때마다 자동
NEED_GPU, NEED_OFFLOAD = 62000, 24000  # MiB — 통째로 올릴 때 / 오프로드로 돌릴 때 필요한 여유(대략)
GEN_MODEL = os.environ.get("GEN_MODEL", "Qwen/Qwen-Image-2512")
EDIT_MODEL = os.environ.get("EDIT_MODEL", "Qwen/Qwen-Image-Edit-2509")
OFFLOAD = os.environ.get("OFFLOAD", "auto")  # auto: GPU 에 올려 보고 모자라면 오프로드 / 1: 항상 오프로드 / 0: 항상 GPU
LOCK = threading.Lock()
_cur = {"name": None, "pipe": None, "used": 0.0, "mode": None, "where": "아직 안 올림"}


def unload():
    _cur.update(name=None, pipe=None, mode=None, where="아직 안 올림"); gc.collect(); free_cuda()


def pipe(name):
    if _cur["name"] == name:
        return _cur["pipe"]
    unload()
    if name == "generate":
        from diffusers import QwenImagePipeline
        p = QwenImagePipeline.from_pretrained(GEN_MODEL, torch_dtype=torch.bfloat16)
    else:
        from diffusers import QwenImageEditPlusPipeline
        p = QwenImageEditPlusPipeline.from_pretrained(EDIT_MODEL, torch_dtype=torch.bfloat16)
    mode, where, g = "gpu", DEV or "CPU", None
    if DEV:
        dev = DEV
    elif torch.cuda.is_available():
        g = pick(NEED_GPU) if OFFLOAD != "1" else None
        if not g and OFFLOAD != "0":
            g = pick(NEED_OFFLOAD); mode = "offload"
        if not g:
            best = max((x["free"] for x in gpus()), default=0)
            raise RuntimeError(f"GPU 여유 메모리 부족 — 약 {NEED_OFFLOAD // 1024}GB 이상 필요, 가장 넉넉한 GPU 가 {best // 1024}GB. 잠시 뒤 다시 해 보세요")
        dev, where = torch_device(g), label(g)
    else:
        dev = "cpu"
    try:
        if dev.startswith("cuda") and (mode == "offload" or OFFLOAD == "1"):
            p.enable_model_cpu_offload(device=dev); mode = "offload"
        else:
            try:
                p.to(dev)
            except torch.cuda.OutOfMemoryError:
                if OFFLOAD == "0" or not dev.startswith("cuda"): raise
                p.to("cpu"); free_cuda()
                p.enable_model_cpu_offload(device=dev); mode = "offload"
    finally:
        release(g)
    print(f"loaded {name} on {where} ({mode})", flush=True)
    _cur.update(name=name, pipe=p, mode=mode, where=f"{where} · {'오프로드' if mode == 'offload' else '통째로'}")
    return p


def janitor():  # GPU_IDLE_UNLOAD_S 동안 안 쓰면 모델을 내려 GPU 를 다른 도구에 돌려준다
    while IDLE_S > 0:
        time.sleep(30)
        if _cur["pipe"] is not None and time.time() - _cur["used"] > IDLE_S and LOCK.acquire(blocking=False):
            try: unload(); print("idle → unloaded", flush=True)
            finally: LOCK.release()


def run(kind, q, emit):
    emit({"stage": "load", "msg": "모델 준비 (처음엔 1~2분)" if _cur["name"] != kind else "그리는 중"})
    p = pipe(kind)
    os.makedirs(q["out_dir"], exist_ok=True)
    steps = int(q.get("steps", 30)); n = int(q.get("n", 1))
    paths = []
    for i in range(n):
        g = torch.Generator("cpu").manual_seed(int(q.get("seed", 0)) + i)

        def cb(pp, s, t, kw, i=i):
            emit({"step": s + 1, "total": steps, "image": i}); return kw
        kw = dict(prompt=q["prompt"], negative_prompt=q.get("negative") or " ", num_inference_steps=steps,
                  true_cfg_scale=float(q.get("cfg", 4.0)), generator=g, callback_on_step_end=cb)
        if kind == "generate":
            im = p(width=int(q["width"]), height=int(q["height"]), **kw).images[0]
        else:
            im = p(image=[Image.open(x).convert("RGB") for x in q["images"]], **kw).images[0]
        path = os.path.join(q["out_dir"], f"img_{i}.png"); im.save(path); paths.append(path)
        emit({"saved": i, "path": path})
    return {"paths": paths}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        b = json.dumps({"ok": True, "device": _cur["where"], "loaded": _cur["name"], "mode": _cur["mode"]}, ensure_ascii=False).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_POST(self):
        q = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        kind = {"/generate": "generate", "/edit": "edit"}.get(self.path)
        self.send_response(200 if kind else 404); self.send_header("Content-Type", "application/x-ndjson"); self.end_headers()

        def emit(ev):
            self.wfile.write((json.dumps(ev, ensure_ascii=False) + "\n").encode()); self.wfile.flush()
        if not kind:
            return emit({"error": "not found"})
        with LOCK:  # GPU 작업은 한 번에 하나
            try:
                emit({"done": run(kind, q, emit)})
            except torch.cuda.OutOfMemoryError:
                unload(); emit({"error": "GPU 메모리가 모자랍니다 — 다른 도구(아바타 스튜디오 등)가 GPU 를 쓰는 중일 수 있어요. 잠시 뒤 다시 시도하세요."})
            except Exception as e:
                traceback.print_exc(); emit({"error": f"{type(e).__name__}: {e}"[:600]})
            finally:
                _cur["used"] = time.time()


if __name__ == "__main__":
    threading.Thread(target=janitor, daemon=True).start()
    print(f"image worker → 127.0.0.1:{PORT} device={DEV or '자동(올릴 때마다 여유 많은 GPU)'} offload={OFFLOAD}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
