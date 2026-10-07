#!/usr/bin/env python3
"""image-local — 범용 로컬 이미지 생성·편집. 말로 그리기(Qwen-Image) · 말로 고치기(Qwen-Image-Edit-2509), 전부 이 서버 GPU.
서버는 stdlib, 추론은 venv 의 worker.py(127.0.0.1:WORKER_PORT)가 맡는다(필요할 때 자동으로 띄움).

  bash setup.sh                    # http://localhost:8792
  venv/bin/python app.py --cli "고양이 우주비행사" -o cat.png [--style illust] [--ratio 16:9]

env: PORT(8792) WORKER_PORT(8793) LLM_API·LLM_BASE_URL·LLM_MODEL(프롬프트 다듬기, 없으면 원문 그대로) WORKSPACE"""
import base64, datetime, json, os, re, secrets, shutil, subprocess, sys, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
WS = os.environ.get("WORKSPACE") or os.path.join(ROOT, "_workspace")  # 포털이 AGENT_DATA/<도구> 로 모아 줌
PY = os.path.join(ROOT, "venv", "bin", "python")
PORT = int(os.environ.get("PORT", "8792"))
WORKER = "http://127.0.0.1:" + os.environ.get("WORKER_PORT", "8793")
LLM_API = os.environ.get("LLM_API", "ollama")
LLM_BASE = os.environ.get("LLM_BASE_URL", "http://localhost:8000/v1" if LLM_API == "openai" else "http://localhost:11434").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen3:8b")
RUN_RE = r"\d{4}-\d{2}-\d{2}-[0-9a-f]{6}"

STYLES = {  # 키: (이름, 프롬프트 꼬리, 글자 위주 스타일인가)
    "none": ("그대로", "", False),
    "photo": ("사진", "professional photograph, natural light, sharp focus, realistic detail", False),
    "illust": ("일러스트", "digital illustration, clean shapes, pleasant colors", False),
    "3d": ("3D 렌더", "3D render, soft global illumination, clay-like materials, studio lighting", False),
    "anime": ("애니메", "anime style, cel shading, clean line art, vivid colors", False),
    "watercolor": ("수채화", "watercolor painting, soft washes, paper texture", False),
    "poster": ("포스터·인포그래픽", "clean poster / infographic layout, clear typography, balanced composition", True),
    "logo": ("로고·아이콘", "minimal flat vector logo, simple shapes, plain background", True),
    "product": ("제품 사진", "studio product photography, seamless background, soft shadows, commercial look", False),
}
RATIOS = {"1:1": (1328, 1328), "4:3": (1472, 1104), "3:4": (1104, 1472), "16:9": (1664, 928), "9:16": (928, 1664), "3:2": (1584, 1056), "2:3": (1056, 1584)}
QUALITY = {"fast": ("빠르게", 20), "normal": ("보통", 30), "high": ("고품질", 50)}
SAFE_NEG = "nsfw, nude, nudity, nipples, explicit, gore, child nudity"  # 사내 포털 도구 — 어떤 프롬프트에도 붙는다


def llm(system, user):
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if LLM_API == "openai":
        url, body = LLM_BASE + "/chat/completions", {"model": LLM_MODEL, "messages": msgs, "temperature": 0.4}
    else:
        url, body = LLM_BASE + "/api/chat", {"model": LLM_MODEL, "messages": msgs, "stream": False, "think": False, "options": {"temperature": 0.4}}
    with urllib.request.urlopen(urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=180) as r:
        j = json.load(r)
    out = j["choices"][0]["message"]["content"] if LLM_API == "openai" else j["message"]["content"]
    return re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()


def refine(prompt, style, text_style):
    """한국어·짧은 요청 → 그림 모델용 영어 프롬프트. 따옴표 안 글자(그림에 들어갈 문구)는 원문 그대로 둔다."""
    out = llm("You rewrite a user's image request into one English prompt for a text-to-image model. Output only the prompt, 40-90 words. "
              "Describe subject, composition, setting, lighting, colors. Keep any text that must appear in the image EXACTLY as given, in double quotes, "
              "and say where it appears. Do not add other text, logos or watermarks. Do not depict real, famous people.",
              f"[요청] {prompt}\n[스타일] {STYLES[style][1] or '알아서'}" + ("\n[주의] 글자가 들어가는 디자인 — 문구는 짧고 정확하게" if text_style else ""))
    return out.strip().strip('"')


def worker(path, body, emit=lambda ev: None):
    """GPU 작업 프로세스에 요청(없으면 띄움) → 마지막 결과"""
    try:
        urllib.request.urlopen(WORKER + "/", timeout=2)
    except Exception:
        emit({"stage": "worker", "msg": "GPU 작업 프로세스 시작"})
        wp = subprocess.Popen([PY, os.path.join(ROOT, "worker.py")], cwd=ROOT, env={**os.environ, "PYTHONUNBUFFERED": "1"},
                              stdout=open(os.path.join(ROOT, "worker.log"), "ab"), stderr=subprocess.STDOUT, start_new_session=True)
        open(os.path.join(ROOT, ".worker.pid"), "w").write(str(wp.pid))  # setup.sh stop 이 같이 끈다
        for _ in range(180):
            try:
                urllib.request.urlopen(WORKER + "/", timeout=2); break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("GPU 작업 프로세스가 뜨지 않았습니다 (worker.log 확인)")
    with urllib.request.urlopen(urllib.request.Request(WORKER + path, json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=7200) as r:
        for line in r:
            ev = json.loads(line)
            if "error" in ev: raise RuntimeError(ev["error"])
            if "done" in ev: return ev["done"]
            emit(ev)
    raise RuntimeError("GPU 작업 프로세스 응답이 끊겼습니다")


def new_run():
    rid = f"{datetime.date.today()}-{secrets.token_hex(3)}"
    os.makedirs(os.path.join(WS, rid)); return rid, os.path.join(WS, rid)


def save_meta(d, meta):
    json.dump(meta, open(os.path.join(d, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def generate(prompt, style="none", ratio="1:1", n=1, quality="normal", seed=None, negative="", enhance=True, emit=lambda ev: None):
    if not prompt.strip(): raise ValueError("무엇을 그릴지 써 주세요")
    style = style if style in STYLES else "none"; ratio = ratio if ratio in RATIOS else "1:1"; quality = quality if quality in QUALITY else "normal"
    n = max(1, min(int(n or 1), 4)); seed = int(seed) if str(seed or "").strip().lstrip("-").isdigit() else secrets.randbelow(10 ** 9)
    text_style = STYLES[style][2] or bool(re.search(r"[\"“”'‘’「」]", prompt))
    final = prompt
    if enhance:
        emit({"stage": "prompt", "msg": "요청을 그림 프롬프트로 다듬는 중"})
        try:
            final = refine(prompt, style, text_style)
        except Exception as e:
            emit({"stage": "prompt", "msg": f"다듬기 건너뜀({type(e).__name__}) — 원문 그대로"})
    if STYLES[style][1] and not enhance: final += ", " + STYLES[style][1]
    if not text_style: final += ", Ultra HD, 4K, cinematic composition"  # 글자 디자인엔 붙이지 않음(그림에 글자로 찍힘)
    rid, d = new_run()
    w, h = RATIOS[ratio]
    meta = {"run_id": rid, "kind": "generate", "prompt": prompt, "final_prompt": final, "negative": negative, "style": style, "ratio": ratio,
            "quality": quality, "seed": seed, "n": n, "ts": datetime.datetime.now().isoformat(timespec="seconds")}
    save_meta(d, meta)
    emit({"stage": "draw", "msg": f"그리는 중 ({n}장, {QUALITY[quality][0]})", "run_id": rid, "final_prompt": final})
    try:
        worker("/generate", {"prompt": final, "negative": ", ".join(x for x in (negative, SAFE_NEG) if x), "width": w, "height": h, "n": n,
                             "seed": seed, "steps": QUALITY[quality][1], "out_dir": d}, lambda ev: emit({**ev, "run_id": rid}))
    except Exception:
        shutil.rmtree(d, ignore_errors=True); raise  # 실패한 건 흔적 없이
    meta["images"] = [f"img_{i}.png" for i in range(n)]; save_meta(d, meta)
    return meta


def edit(instruction, sources, n=1, quality="normal", seed=None, negative="", emit=lambda ev: None):
    """sources: 로컬 이미지 경로 1~3개(올린 것 또는 갤러리). 지시는 그대로(편집 모델은 한국어·영어 지시를 읽음)"""
    if not instruction.strip(): raise ValueError("어떻게 고칠지 써 주세요")
    if not sources: raise ValueError("고칠 그림을 올리거나 갤러리에서 고르세요")
    quality = quality if quality in QUALITY else "normal"; n = max(1, min(int(n or 1), 4))
    seed = int(seed) if str(seed or "").strip().lstrip("-").isdigit() else secrets.randbelow(10 ** 9)
    rid, d = new_run()
    srcs = []
    for i, s in enumerate(sources[:3]):
        p = os.path.join(d, f"src_{i}.png"); shutil.copy(s, p); srcs.append(p)
    meta = {"run_id": rid, "kind": "edit", "prompt": instruction, "final_prompt": instruction, "negative": negative, "quality": quality, "seed": seed,
            "n": n, "sources": [os.path.basename(x) for x in srcs], "ts": datetime.datetime.now().isoformat(timespec="seconds")}
    save_meta(d, meta)
    emit({"stage": "draw", "msg": f"고치는 중 ({n}장, {QUALITY[quality][0]})", "run_id": rid})
    try:
        worker("/edit", {"images": srcs, "prompt": instruction, "negative": ", ".join(x for x in (negative, SAFE_NEG) if x), "n": n, "seed": seed,
                         "steps": QUALITY[quality][1], "out_dir": d}, lambda ev: emit({**ev, "run_id": rid}))
    except Exception:
        shutil.rmtree(d, ignore_errors=True); raise
    meta["images"] = [f"img_{i}.png" for i in range(n)]; save_meta(d, meta)
    return meta


def list_runs():
    out = []
    for n in sorted(os.listdir(WS), key=lambda n: os.path.getmtime(os.path.join(WS, n)), reverse=True)[:80] if os.path.isdir(WS) else []:
        p = os.path.join(WS, n, "meta.json")
        if re.fullmatch(RUN_RE, n) and os.path.exists(p):
            m = json.load(open(p, encoding="utf-8"))
            if m.get("images"): out.append(m)  # 끝난 것만
    return out


def delete(run_id):
    """휴지통(.trash)으로 옮김 — 실수로 지워도 폴더째 되살릴 수 있게"""
    if not re.fullmatch(RUN_RE, run_id or ""): raise ValueError("잘못된 ID")
    src = os.path.join(WS, run_id)
    if not os.path.isdir(src): raise ValueError("없는 그림")
    t = os.path.join(WS, ".trash"); os.makedirs(t, exist_ok=True); shutil.move(src, os.path.join(t, run_id))
    return {"ok": True}


def resolve(ref):
    """'run_id/img_0.png' → 로컬 경로 (갤러리 그림을 편집 원본으로)"""
    m = re.fullmatch(rf"({RUN_RE})/((?:img|src)_\d\.png)", ref or "")
    if not m: raise ValueError("잘못된 그림 경로")
    p = os.path.join(WS, m.group(1), m.group(2))
    if not os.path.exists(p): raise ValueError("없는 그림")
    return p


def status():
    try:
        w = json.load(urllib.request.urlopen(WORKER + "/", timeout=2))
    except Exception:
        w = None
    return {"worker": w, "styles": {k: v[0] for k, v in STYLES.items()}, "ratios": list(RATIOS), "quality": {k: v[0] for k, v in QUALITY.items()}}


# ── 저작권 표기 (LICENSE·NOTICE 참고) ─────────────────────────────────────
_SIG = __import__("base64").b64decode("wqkgMjAyNiBnZ2dnODY1NyDCtyBkb25nanVraW0uZGV2QGdtYWlsLmNvbQ==").decode()
_SIG_A = __import__("base64").b64decode("Z2dnZzg2NTcgPGRvbmdqdWtpbS5kZXZAZ21haWwuY29tPg==").decode()


def signed(html):
    """화면에 저작권 표기를 붙인다. ui.html 에서 지워져도 서버가 내보낼 때 다시 붙는다."""
    name, mail = _SIG.split(" · ")
    if 'name="author"' not in html:
        meta = f'<meta name="author" content="{name[7:]} <{mail}>">'
        html = html.replace("<head>", "<head>" + meta, 1) if "<head>" in html else meta + html
    if "data-sig" not in html:
        tag = (f'<!-- {_SIG} --><div data-sig title="{mail}" style="text-align:center;font-size:11px;color:#9aa0a6;'
               f'opacity:.55;margin:28px 0 8px">{name}</div>')
        html = html.replace("</body>", tag + "</body>", 1) if "</body>" in html else html + tag
    return html


HTML = open(os.path.join(ROOT, "ui.html"), encoding="utf-8").read() if os.path.exists(os.path.join(ROOT, "ui.html")) else "ui.html 없음"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, body, ctype="application/json", code=200, name=None):
        b = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("X-Author", _SIG_A); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        if name: self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.request.quote(name))
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        p, _, q = self.path.partition("?")
        if p == "/api/status": return self._send(status())
        if p == "/api/runs": return self._send(list_runs())
        m = re.fullmatch(rf"/api/runs/({RUN_RE})/((?:img|src)_\d\.png)", p)
        if m:
            f = os.path.join(WS, m.group(1), m.group(2))
            if os.path.exists(f):
                return self._send(open(f, "rb").read(), "image/png", name=f"{m.group(1)}_{m.group(2)}" if "download" in q else None)
            return self._send({"error": "없음"}, code=404)
        self._send(signed(HTML).encode(), "text/html; charset=utf-8")

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/api/delete":
            try: return self._send(delete(req.get("run_id")))
            except ValueError as e: return self._send({"error": str(e)}, code=400)
        if self.path not in ("/api/generate", "/api/edit"):
            return self._send({"error": "not found"}, code=404)
        self.send_response(200); self.send_header("Content-Type", "text/event-stream; charset=utf-8"); self.send_header("Cache-Control", "no-cache"); self.end_headers()

        def emit(ev):
            self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode()); self.wfile.flush()
        ups = []
        try:
            if self.path == "/api/generate":
                r = generate(req.get("prompt") or "", req.get("style"), req.get("ratio"), req.get("n"), req.get("quality"), req.get("seed"),
                             req.get("negative") or "", req.get("enhance", True), emit)
            else:
                srcs = [resolve(x) for x in req.get("refs") or []]
                up = os.path.join(WS, "_upload"); os.makedirs(up, exist_ok=True)
                for f in req.get("uploads") or []:
                    if not re.search(r"\.(png|jpe?g|webp)$", f.get("name", ""), re.I): raise ValueError("그림 파일(png·jpg·webp)만")
                    p = os.path.join(up, secrets.token_hex(4) + "_" + re.sub(r"[^\w.\-]", "_", os.path.basename(f["name"])))
                    open(p, "wb").write(base64.b64decode(f["b64"])); ups.append(p); srcs.append(p)
                r = edit(req.get("instruction") or "", srcs, req.get("n"), req.get("quality"), req.get("seed"), req.get("negative") or "", emit)
            emit({"done": r})
        except Exception as e:
            emit({"error": f"{type(e).__name__}: {e}"})
        finally:
            for p in ups:
                if os.path.exists(p): os.remove(p)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        a = sys.argv[2:]; get = lambda k, d=None: a[a.index(k) + 1] if k in a else d
        prompt = a[0]
        m = generate(prompt, get("--style", "none"), get("--ratio", "1:1"), 1, get("--quality", "normal"),
                     emit=lambda ev: print(ev.get("msg") or "", file=sys.stderr) if ev.get("msg") else None)
        shutil.copy(os.path.join(WS, m["run_id"], "img_0.png"), get("-o", "out.png")); print(get("-o", "out.png")); sys.exit(0)
    print(f"image-local → http://localhost:{PORT}  (worker {WORKER}, llm={LLM_API} {LLM_BASE} {LLM_MODEL})  {_SIG}")
    ThreadingHTTPServer(("", PORT), H).serve_forever()
