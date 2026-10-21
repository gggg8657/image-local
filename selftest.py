#!/usr/bin/env python3
"""GPU·LLM 없이 검증: 프리셋 → 가짜 작업 프로세스로 그리기·고치기 흐름 → 갤러리·지우기 → 화면 저작권 표기.  python3 selftest.py"""
import json, os, shutil, tempfile
for _k in ("PORTAL_JOBS_URL", "PORTAL_JOBS_TOKEN", "PORTAL_JOBS_TOOL"): os.environ.pop(_k, None)   # setup.sh 가 포털 환경에서 돌려도 시험 작업을 진짜 🔔 로 보내지 않게
os.environ["WORKSPACE"] = tempfile.mkdtemp(prefix="image-local-test-")
import app

# 1) 프리셋: 비율은 16 의 배수, 글자 스타일 표시
for k, (w, h) in app.RATIOS.items():
    assert w % 16 == 0 and h % 16 == 0, k
assert app.STYLES["poster"][2] and app.STYLES["logo"][2] and not app.STYLES["photo"][2]

# 2) 가짜 작업 프로세스: 받은 요청을 기록하고 빈 png 를 쓴다
seen = []
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000" "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")
def fake_worker(path, body, emit=lambda ev: None):
    seen.append((path, body))
    for i in range(int(body["n"])):
        p = os.path.join(body["out_dir"], f"img_{i}.png"); open(p, "wb").write(PNG); emit({"saved": i, "path": p})
    return {"paths": []}
app.worker = fake_worker
app.llm = lambda s, u, temperature=0.4, as_json=False: "{}" if as_json else "A cozy udon shop on a rainy night, sign reads \"우동\""

m = app.generate("비 오는 밤 우동집, 간판 \"우동\"", "photo", "16:9", 2, "fast", 7)
path, body = seen[-1]
assert path == "/generate" and (body["width"], body["height"]) == app.RATIOS["16:9"] and body["steps"] == 20 and body["seed"] == 7
assert "nsfw" in body["negative"] and "Ultra HD" not in body["prompt"], body  # 따옴표 글자 있으면 화질 꼬리말 안 붙임
assert m["images"] == ["img_0.png", "img_1.png"] and '"우동"' in m["final_prompt"] and m["final_prompt"].startswith("Photograph. A cozy"), m["final_prompt"]
evs = []
m2 = app.generate("고양이", "illust", "1:1", 1, enhance=False, emit=evs.append)
assert [e["path"] for e in evs if "saved" in e] == ["img_0.png"], evs  # 진행 이벤트에 서버 절대 경로가 새지 않음
assert app._hide_paths(f"FileNotFoundError: {app.WS}/x/img_0.png") == "FileNotFoundError: x/img_0.png"
assert seen[-1][1]["prompt"] == "고양이, digital illustration, clean shapes, pleasant colors", seen[-1][1]["prompt"]  # magic 꼬리는 그대로·사진에만

# 2-1) 꼬리말·구두점: 겹치지 않고 '., ,' 같은 것 없음, 스타일 따라 붙음
assert app.plain("고양이", "none", False) == "고양이, Ultra HD, 4K, cinematic composition"
assert app.plain("A cat on a sofa.", "photo", False) == "A cat on a sofa. professional photograph, natural light, sharp focus, realistic detail, Ultra HD, 4K, cinematic composition"
assert app.plain("A cinematic shot of a cat.", "none", False) == "A cinematic shot of a cat."  # 이미 비슷한 말이 있으면 magic 안 붙임
assert app.plain("고양이, 4K", "photo", False).count("4K") == 1 and "Ultra HD" not in app.plain("고양이, 4K", "photo", False)
assert "Ultra HD" not in app.plain('포스터, 제목 "안전"', "poster", True) and "Ultra HD" not in app.plain("산", "watercolor", False)
assert app.with_tail("a watercolor painting, soft washes", "watercolor painting, soft washes, paper texture") == "a watercolor painting, soft washes, paper texture"
assert app.tidy('"Dark street ,  shadows., , Ultra HD,, 4K ."') == "Dark street, shadows. Ultra HD, 4K."
for st in app.STYLES:
    t = app.plain("A dog.", st, app.STYLES[st][2])
    assert ".," not in t and ",," not in t and " ," not in t and t.lower().count("ultra hd") <= 1, (st, t)
assert set(app.STYLE_CUES) == set(app.STYLES)

# 2-2) 따옴표 문구: 사용자가 준 것만, 지어낸 건 한 번 다시 쓰게 하고 그래도 남으면 그 문장째 뺌
REQ = "2026년 12월 3일 대한민국에서 일어난 비상계엄 상황을 그려줘"
assert app.quotes('제목 "책 읽는 가을", 부제 \'함께\' 「가」', user=True) == ["책 읽는 가을", "함께", "가"]
assert app.quotes("the kitten's fur and the dog's tail") == []  # 아포스트로피는 문구 아님
assert app.invented_quotes('A billboard reads "2026년 12월 3일 비상계엄". Soldiers stand.', REQ) == ["2026년 12월 3일 비상계엄"]
assert app.invented_quotes('A poster titled "책 읽는 가을".', '가을 포스터, 제목 "책 읽는 가을"') == []
assert app.invented_quotes('A sign reads "비상계엄".', REQ) == ["비상계엄"]  # 요청 속 낱말이라도 따옴표로 준 게 아니면 지어낸 것
PLAN = json.dumps({"subject": "soldiers at a barricade", "setting": "Seoul street with police buses", "avoid": "text, logos", "added_ko": ["장소 디테일", "조명"]})
BODY = "Soldiers in winter uniforms stand at a barricade on a wide Seoul avenue lined with police buses and bare ginkgo trees, citizens holding phones behind them, street lamps casting sodium orange light on wet asphalt, eye-level view from the sidewalk across six lanes of traffic."
def fake_llm(replies):
    calls = []
    def f(system, user, temperature=0.4, as_json=False):
        calls.append((system, user, temperature, as_json))
        return PLAN if as_json else replies[min(len([c for c in calls if not c[3]]) - 1, len(replies) - 1)]
    f.calls = calls; return f
app.llm = fake_llm([BODY + ' A billboard displays "2026년 12월 3일 비상계엄" in white letters.', BODY])
r = app.refine(REQ, "none", False)
assert r["final_prompt"].startswith("Soldiers") and '"' not in r["final_prompt"], r
comp = [c for c in app.llm.calls if not c[3]]
assert len(comp) == 2 and "Remove the quoted text" in comp[1][1] and all(c[2] == 0.3 for c in app.llm.calls), comp
assert r["summary_ko"] == "추가한 것: 장소 디테일·조명" and r["avoid"][:2] == ["text", "logos"], r
app.llm = fake_llm([BODY + ' A billboard displays "비상계엄" in white letters. Cold night air.'])  # 다시 써도 남으면 그 문장만 뺌
r = app.refine(REQ, "none", False)
assert "비상계엄" not in r["final_prompt"] and "billboard" not in r["final_prompt"] and r["final_prompt"].endswith("Cold night air."), r
app.llm = fake_llm(['A poster with the title "책 읽는 가을" at the top, ' + BODY])
r = app.refine('가을 포스터, 제목 "책 읽는 가을"', "poster", True)
assert '"책 읽는 가을"' in r["final_prompt"] and len([c for c in app.llm.calls if not c[3]]) == 1, r  # 사용자 문구는 그대로, 다시 안 씀
assert '"책 읽는 가을"' in app.llm.calls[1][0] and "No other words" in app.llm.calls[1][0]  # 시스템 지시에 문구를 정확히 넘김
assert r["avoid"] == ["logos"], r  # 글자 넣는 그림이면 네거티브에서 text 류는 뺌
app.llm = fake_llm([BODY])
r = app.refine(REQ, "none", False)
assert "no written words" in app.llm.calls[1][0] and "text, logos" in ", ".join(r["avoid"])

# 2-3) 상투어: 사용자가 부르지 않았으면 다시 쓰게, 그래도 남으면 지움 / 영화 같은 걸 원하면 그대로
HYPE = "A cinematic, moody shot. " + BODY + " Epic atmosphere, 4K."
app.llm = fake_llm([HYPE])
r = app.refine(REQ, "none", False)
low = r["final_prompt"].lower()
assert not any(w in low for w in ("cinematic", "moody", "epic", "4k")) and ".," not in low and " ," not in low and "  " not in low, r
assert "Do not use the words" in [c for c in app.llm.calls if not c[3]][1][1]
app.llm = fake_llm(["A cinematic wide shot. " + BODY])
assert "cinematic" in app.refine("영화 같은 서울 밤거리", "none", False)["final_prompt"]

# 2-4) 스타일이 그림 모델까지 감: 작성 지시에 매체 단서, 결과에 매체 말이 없으면 앞에 붙임, 다듬기엔 magic 안 붙음
app.llm = fake_llm([BODY])
r = app.refine("안개 낀 지리산", "watercolor", False)
assert r["final_prompt"].startswith("Watercolor painting. Soldiers") and "wet-on-wet" in app.llm.calls[1][0], r
app.llm = fake_llm(["A watercolor painting of misty ridges. " + BODY])
assert app.refine("안개 낀 지리산", "watercolor", False)["final_prompt"].startswith("A watercolor painting")
app.llm = fake_llm([BODY]); app.worker = fake_worker
g = app.generate("벚꽃길 자전거 소녀", "anime", "1:1", 1, "fast", 1)
assert seen[-1][1]["prompt"].startswith("Anime illustration. ") and "Ultra HD" not in seen[-1][1]["prompt"] and "cel shading" not in seen[-1][1]["prompt"]
assert "text, logos" in seen[-1][1]["negative"] and "nsfw" in seen[-1][1]["negative"] and g["auto_negative"].startswith("text, logos")
# 고친 문장으로 그리기(exact): 꼬리말 없이 그대로
g = app.generate("A quiet street at dawn.", "photo", "1:1", 1, "fast", 1, enhance=False, exact=True)
assert seen[-1][1]["prompt"] == "A quiet street at dawn." and g["final_prompt"] == "A quiet street at dawn."
# LLM 이 죽으면 원문 + 꼬리(다듬기 없을 때와 같음)
def dead(*a, **k): raise OSError("LLM 꺼짐")
app.llm = dead
g = app.generate("고양이", "photo", "1:1", 1, "fast", 1)
assert seen[-1][1]["prompt"] == app.plain("고양이", "photo", False)
for x in (g,): app.delete(x["run_id"]); shutil.rmtree(os.path.join(app.WS, ".trash", x["run_id"]))
for rid in [x["run_id"] for x in app.list_runs() if x["run_id"] not in (m["run_id"], m2["run_id"])]:
    shutil.rmtree(os.path.join(app.WS, rid))

# 3) 고치기: 갤러리 그림을 원본으로
src = app.resolve(f"{m['run_id']}/img_0.png")
e = app.edit("눈 내리는 밤으로", [src], 1)
assert seen[-1][0] == "/edit" and len(seen[-1][1]["images"]) == 1 and e["sources"] == ["src_0.png"]
for bad in ("../etc/passwd", f"{m['run_id']}/../../x.png", "2026-01-01-zzzzzz/img_0.png"):
    try: app.resolve(bad); assert False, bad
    except ValueError: pass

# 4) 실패하면 흔적 없음
def boom(*a, **k): raise RuntimeError("GPU 없음")
app.worker = boom
n0 = len(os.listdir(app.WS))
try: app.generate("실패", enhance=False); assert False
except RuntimeError: pass
assert len(os.listdir(app.WS)) == n0

# 5) 갤러리·지우기(휴지통으로)
ids = [x["run_id"] for x in app.list_runs()]
assert set(ids) == {m["run_id"], m2["run_id"], e["run_id"]}, ids
app.delete(m2["run_id"]); assert m2["run_id"] not in [x["run_id"] for x in app.list_runs()]
assert os.path.isdir(os.path.join(app.WS, ".trash", m2["run_id"]))

# 저작권 표기: 서버가 화면에 붙이는 코드가 있어야 한다 (LICENSE·NOTICE)
_src = open(os.path.join(app.ROOT, "app.py"), encoding="utf-8").read()
assert "wqkgMjAyNiBnZ2dnODY1NyDCtyBkb25nanVraW0uZGV2QGdtYWlsLmNvbQ==" in _src and "signed(" in _src and "X-Author" in _src, "저작권 표기 누락"
assert "data-sig" in app.signed(app.HTML)

# 6) 포털 작업 알림(🔔): 환경변수 없으면 notify 는 False 이고 그리기는 그대로 / 가짜 포털에 running → done 이 토큰 헤더와 함께 간다
import threading, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import portal_jobs
for k in ("PORTAL_JOBS_URL", "PORTAL_JOBS_TOKEN", "PORTAL_JOBS_TOOL"): os.environ.pop(k, None)
app.worker = fake_worker
assert portal_jobs.notify("alice", "running", id="x") is False
GOT = []
class FakePortal(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        GOT.append((self.headers.get("X-Portal-Jobs-Token"), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
        self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"{}")
portal = ThreadingHTTPServer(("127.0.0.1", 0), FakePortal); threading.Thread(target=portal.serve_forever, daemon=True).start()
tool = ThreadingHTTPServer(("127.0.0.1", 0), app.H); threading.Thread(target=tool.serve_forever, daemon=True).start()
def sse(path, body, user="alice"):
    r = urllib.request.Request(f"http://127.0.0.1:{tool.server_address[1]}{path}", json.dumps(body).encode(), {"Content-Type": "application/json", "X-Agent-User": user})
    return [json.loads(l[6:]) for l in urllib.request.urlopen(r).read().decode().split("\n\n") if l.startswith("data: ")]
assert "done" in sse("/api/generate", {"prompt": "알림 없이", "enhance": False})[-1] and GOT == []  # 꺼져 있어도 도구는 그대로
os.environ.update(PORTAL_JOBS_URL=f"http://127.0.0.1:{portal.server_address[1]}/api/internal/jobs", PORTAL_JOBS_TOKEN="tok-test", PORTAL_JOBS_TOOL="image-local")
assert portal_jobs.notify("alice", "queued", id="j1", title="t", link="/?run=x", message="m", progress=150) and portal_jobs.flush()
assert GOT[-1] == ("tok-test", {"tool": "image-local", "user": "alice", "status": "queued", "title": "t", "link": "/?run=x", "message": "m", "id": "j1", "progress": 100}), GOT
d = sse("/api/generate", {"prompt": "알림 고양이", "enhance": False, "n": 2})[-1]["done"]; portal_jobs.flush()
st = [g[1] for g in GOT[1:]]
assert [x["status"] for x in st] == ["running", "done"] and st[0]["id"] == st[1]["id"] and st[1]["link"] == f"/?run={d['run_id']}", st
assert st[1]["user"] == "alice" and st[1]["title"].startswith("그림 생성") and st[1]["message"] == "2장" and all(g[0] == "tok-test" for g in GOT)
app.worker = boom; del GOT[:]
assert "error" in sse("/api/edit", {"instruction": "실패", "refs": [f"{e['run_id']}/img_0.png"]})[-1]; portal_jobs.flush()
assert [g[1]["status"] for g in GOT] == ["running", "failed"] and app.WS not in GOT[-1][1]["message"] and GOT[-1][1]["title"].startswith("그림 고치기"), GOT
# 다듬기만 보기 API: 그리지 않고 문장·한 줄 설명 / LLM 이 죽으면 fallback
app.llm = fake_llm([BODY])
def post(path, body):
    r = urllib.request.Request(f"http://127.0.0.1:{tool.server_address[1]}{path}", json.dumps(body).encode(), {"Content-Type": "application/json"})
    try: return json.load(urllib.request.urlopen(r))
    except urllib.error.HTTPError as x: return {"code": x.code, **json.load(x)}
j = post("/api/refine", {"prompt": REQ, "style": "photo"})
assert j["final_prompt"].startswith("Photograph. Soldiers") and j["summary_ko"].startswith("추가한 것:") and "text" in j["negative"], j
app.llm = dead
j = post("/api/refine", {"prompt": "고양이", "style": "illust"})
assert j["fallback"] and j["final_prompt"] == app.plain("고양이", "illust", False), j
assert post("/api/refine", {"prompt": " "})["code"] == 400
tool.shutdown(); portal.shutdown()
for k in ("PORTAL_JOBS_URL", "PORTAL_JOBS_TOKEN", "PORTAL_JOBS_TOOL"): os.environ.pop(k, None)

shutil.rmtree(app.WS)
print("selftest OK —", len(app.STYLES), "styles,", len(app.RATIOS), "ratios")

# GPU 후보: 부모 후보가 0,1,2 면 3(운영 vLLM 전용)을 절대 고르지 않음 — nvidia-smi 출력은 가짜, 예약 장부는 임시 폴더
import gpu_pick as _gp, os as _os, tempfile as _tf, shutil as _sh
_smi0, _dir0, _env0 = _gp._smi, _gp.RES_DIR, dict(_os.environ)
try:
    _gp._smi = lambda: "0, 1000, 90\n1, 2000, 90\n2, 3000, 90\n3, 90000, 0\n"  # 3 이 가장 한가해 보이게
    _gp.RES_DIR = _tf.mkdtemp()
    for _k in ("GPU_POOL", "GPU_RESERVED", "VLLM_GPUS"): _os.environ.pop(_k, None)
    for _res in ("none", "3"):
        _os.environ.update(CUDA_VISIBLE_DEVICES="0,1,2", GPU_RESERVED=_res)
        assert [g["index"] for g in _gp.gpus()] == ["0", "1", "2"]
        assert _gp.pick(0, hold_s=0)["index"] == "2" and _gp.torch_device(_gp.pick(0, hold_s=0)) == "cuda:2"
        assert _gp.pool_env(_os.environ)["CUDA_VISIBLE_DEVICES"] == "0,1,2" == _gp.env_for(None, _os.environ)["CUDA_VISIBLE_DEVICES"]
    # 셸(~/.zshrc)에서 2,3 을 물려받아도 예약된 3 은 빼고 2 만 — 보이는 번호는 cuda:0
    _os.environ.update(CUDA_VISIBLE_DEVICES="2,3", GPU_RESERVED="3")
    assert _gp.pick(0, hold_s=0)["index"] == "2" and _gp.torch_device(_gp.pick(0, hold_s=0)) == "cuda:0"
    assert _gp.pool_env(_os.environ)["CUDA_VISIBLE_DEVICES"] == "2"
    _os.environ.pop("GPU_RESERVED"); _os.environ["VLLM_GPUS"] = "3"  # GPU_RESERVED 없으면 VLLM_GPUS
    assert _gp.pick(0, hold_s=0)["index"] == "2"
    _os.environ["GPU_POOL"] = "0,1"  # 교집합이 비면 GPU 를 하나도 안 보임(CPU)
    assert _gp.pick(0, hold_s=0) is None and _gp.pool_env(_os.environ)["CUDA_VISIBLE_DEVICES"] == ""
    if hasattr(app, "worker_env"):  # 작업자(그림·영상) 프로세스 환경
        assert app.worker_env({"CUDA_VISIBLE_DEVICES": "0,1,2", "GPU_RESERVED": "none"}, ["0", "1", "2", "3"])["CUDA_VISIBLE_DEVICES"] == "0,1,2"
        assert app.worker_env({"CUDA_VISIBLE_DEVICES": "2,3", "GPU_RESERVED": "3"}, ["0", "1", "2", "3"])["CUDA_VISIBLE_DEVICES"] == "2"
        assert app.worker_env({"GPU_POOL": "0,1,2,3", "VLLM_GPUS": "3"}, ["0", "1", "2", "3"])["CUDA_VISIBLE_DEVICES"] == "0,1,2"
finally:
    _sh.rmtree(_gp.RES_DIR, ignore_errors=True); _gp._smi, _gp.RES_DIR = _smi0, _dir0; _os.environ.clear(); _os.environ.update(_env0)
print("selftest GPU 후보 OK — 0,1,2 에서 3 안 고름")
