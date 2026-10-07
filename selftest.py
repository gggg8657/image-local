#!/usr/bin/env python3
"""GPU·LLM 없이 검증: 프리셋 → 가짜 작업 프로세스로 그리기·고치기 흐름 → 갤러리·지우기 → 화면 저작권 표기.  python3 selftest.py"""
import json, os, shutil, tempfile
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
        open(os.path.join(body["out_dir"], f"img_{i}.png"), "wb").write(PNG); emit({"saved": i})
    return {"paths": []}
app.worker = fake_worker
app.llm = lambda s, u: "A cozy udon shop on a rainy night, sign reads \"우동\""

m = app.generate("비 오는 밤 우동집, 간판 \"우동\"", "photo", "16:9", 2, "fast", 7)
path, body = seen[-1]
assert path == "/generate" and (body["width"], body["height"]) == app.RATIOS["16:9"] and body["steps"] == 20 and body["seed"] == 7
assert "nsfw" in body["negative"] and "Ultra HD" not in body["prompt"], body  # 따옴표 글자 있으면 화질 꼬리말 안 붙임
assert m["images"] == ["img_0.png", "img_1.png"] and m["final_prompt"].startswith("A cozy")
m2 = app.generate("고양이", "illust", "1:1", 1, enhance=False)
assert "digital illustration" in seen[-1][1]["prompt"] and "Ultra HD" in seen[-1][1]["prompt"]

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

shutil.rmtree(app.WS)
print("selftest OK —", len(app.STYLES), "styles,", len(app.RATIOS), "ratios")
