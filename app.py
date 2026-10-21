#!/usr/bin/env python3
"""image-local — 범용 로컬 이미지 생성·편집. 말로 그리기(Qwen-Image) · 말로 고치기(Qwen-Image-Edit-2509), 전부 이 서버 GPU.
서버는 stdlib, 추론은 venv 의 worker.py(127.0.0.1:WORKER_PORT)가 맡는다(필요할 때 자동으로 띄움).

  bash setup.sh                    # http://localhost:8792
  venv/bin/python app.py --cli "고양이 우주비행사" -o cat.png [--style illust] [--ratio 16:9]

env: PORT(8792) WORKER_PORT(8793) LLM_API·LLM_BASE_URL·LLM_MODEL(프롬프트 다듬기, 없으면 원문 그대로) WORKSPACE"""
import base64, datetime, json, os, re, secrets, shutil, subprocess, sys, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from gpu_pick import pool_env  # 작업자 GPU 후보 좁히기
import portal_jobs  # 포털 작업 알림(🔔) — 포털 밖이면 아무 일도 안 함
import portal_auth  # 포털 서명 확인 관문·오류 문장 정리(원본 agent-page-portal/sdk/portal_auth.py)

ROOT = os.path.dirname(os.path.abspath(__file__))
WS = os.environ.get("WORKSPACE") or os.path.join(ROOT, "_workspace")  # 포털이 AGENT_DATA/<도구> 로 모아 줌
PY = os.path.join(ROOT, "venv", "bin", "python")
PORT = int(os.environ.get("PORT", "8792"))
WORKER = "http://127.0.0.1:" + os.environ.get("WORKER_PORT", "8793")
LLM_API = os.environ.get("LLM_API", "ollama")
LLM_KEY = os.environ.get("LLM_API_KEY", "")
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


def llm(system, user, temperature=0.4, as_json=False):
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if LLM_API == "openai":
        url, body = LLM_BASE + "/chat/completions", {"model": LLM_MODEL, "messages": msgs, "temperature": temperature}
        if as_json: body["response_format"] = {"type": "json_object"}
    else:
        url, body = LLM_BASE + "/api/chat", {"model": LLM_MODEL, "messages": msgs, "stream": False, "think": False, "options": {"temperature": temperature}}
        if as_json: body["format"] = "json"
    with urllib.request.urlopen(urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **({"Authorization": "Bearer " + LLM_KEY} if LLM_KEY else {})}), timeout=300) as r:   # vLLM 대기열 고려
        j = json.load(r)
    out = (j["choices"][0]["message"] if LLM_API == "openai" else j["message"]).get("content") or ""   # vLLM 은 빈 응답에 null
    return re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()


# ── 프롬프트 다듬기 ─────────────────────────────────────────────────────
# 1) 요청 → 장면 계획(JSON 칸) 2) 계획 → 영어 한 문단(40~80단어) 3) 서버가 검사: 지어낸 따옴표 문구·상투어·길이 → 한 번 다시, 그래도 남으면 잘라냄
MAGIC = "Ultra HD, 4K, cinematic composition"  # Qwen-Image 공식 positive magic — 다듬기 없이 그대로/사진일 때만, 이미 비슷한 말이 있으면 안 붙임
MAGIC_STYLES = ("none", "photo")
STYLE_CUES = {  # 스타일이 문단의 매체·표현을 정하게: (문단에 꼭 있어야 할 말, 없으면 앞에 붙일 말, 작성 지시)
    "none": (None, "", "Pick the medium the request implies; if it implies none, describe it as a natural, realistic photograph. Do not call it a film still."),
    "photo": (r"photo", "Photograph.", "It is a photograph: name a plausible lens (e.g. 35mm, 50mm, 85mm), the real light source and its direction, depth of field, and color rendering (e.g. neutral digital, Kodak Portra-like film)."),
    "illust": (r"illustrat", "Digital illustration.", "It is a digital illustration: describe line quality, shape language, flat or textured fills and a limited palette by naming the colors."),
    "3d": (r"3d|render", "3D render.", "It is a 3D render: name the materials (clay, matte plastic, glass, wood), the lighting setup (soft global illumination, area lights), and the backdrop."),
    "anime": (r"anime", "Anime illustration.", "It is a 2D anime illustration: cel shading, crisp line art, character design details (hair, clothing), background art style."),
    "watercolor": (r"watercolou?r", "Watercolor painting.", "It is a watercolor painting: wet-on-wet washes, pigment blooms, soft edges, white paper left as highlights, visible cold-press paper grain."),
    "poster": (r"poster|infographic", "Flat graphic poster.", "It is a flat graphic poster or infographic: describe the layout grid, visual hierarchy, where each text element sits, simple icons or chart shapes, two or three named colors."),
    "logo": (r"logo", "Flat vector logo.", "It is a flat vector logo mark: geometry, negative space, one to three named colors, plain background, centered, nothing else around it."),
    "product": (r"product", "Studio product photograph.", "It is a studio product photograph: backdrop, softbox or light placement, reflections and contact shadow, camera angle, lens."),
}
OVERUSED = ["cinematic", "moody", "high-contrast", "high contrast", "ultra hd", "ultra-detailed", "highly detailed", "4k", "8k", "masterpiece", "breathtaking",
            "stunning", "epic", "hyper-realistic", "hyperrealistic", "photorealistic", "award-winning", "dramatic lighting", "best quality", "trending on artstation"]
OVERUSED_KO = {"cinematic": ("영화", "시네마"), "moody": ("무드",), "high-contrast": ("대비",), "high contrast": ("대비",), "4k": ("4k",), "8k": ("8k",),
               "hyper-realistic": ("극사실", "하이퍼"), "hyperrealistic": ("극사실", "하이퍼"), "photorealistic": ("실사", "사실적"), "epic": ("웅장", "장엄"),
               "dramatic lighting": ("극적",), "ultra hd": ("고화질",), "highly detailed": ("디테일",), "ultra-detailed": ("디테일",)}
ADDED_KO = {"setting": "장소 디테일", "time_light": "시간·조명", "composition": "구도", "mood": "분위기", "medium": "표현 방식"}
_Q_OUT = r'"([^"\n]{1,80})"|“([^”\n]{1,80})”|‘([^’\n]{1,80})’|「([^」\n]{1,80})」|『([^』\n]{1,80})』'
_Q_USER = _Q_OUT + r"|'([^'\n]{1,80})'"  # 사용자 문장의 '…' 도 문구로 본다(영어 출력의 ' 는 아포스트로피라 뺌)


def quotes(text, user=False):
    """따옴표 안 문구들(그림에 들어갈 글자)"""
    return [next(g for g in m.groups() if g is not None).strip() for m in re.finditer(_Q_USER if user else _Q_OUT, text or "")]


def _norm(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()


def invented_quotes(out, request):
    """다듬은 문장 속 따옴표 문구 중 사용자가 따옴표로 주지 않은 것(요청 속 낱말이라도 따옴표가 없으면 그림 글자로 안 넣음)"""
    given = [_norm(q) for q in quotes(request, user=True)]
    return [q for q in quotes(out) if q and not any(_norm(q) in g for g in given)]


def overused(out, request, style):
    """사용자·스타일이 부르지 않은 상투어"""
    req, low = _norm(request), out.lower()
    allowed = _norm(STYLES[style][1] + " " + STYLE_CUES[style][2])
    return [w for w in OVERUSED if re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", low) and w not in req and w not in allowed
            and not any(k in req for k in OVERUSED_KO.get(w, ()))]


def tidy(text):
    """빈칸·쉼표·마침표 정리: '., ,' · ' ,' · ',,' · '..' 같은 것"""
    t = re.sub(r"\s+", " ", text or "").strip()
    if len(t) > 1 and t[0] == t[-1] == '"' and t.count('"') == 2: t = t[1:-1].strip()  # LLM 이 답 전체를 따옴표로 감싼 경우만
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    t = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", t)
    t = re.sub(r"\.(?:\s*[,.;:])+", ".", t)
    t = re.sub(r",\s*\.", ".", t)
    t = re.sub(r"([,;])(?=[^\s\d,.;:!?\"”’)])", r"\1 ", t)
    return t.strip(" ,;:")


def with_tail(text, terms):
    """꼬리말 붙이기 — 이미 들어 있는 말은 빼고, 문장 끝 구두점은 깔끔하게"""
    low = (text or "").lower()
    add = [t.strip() for t in terms.split(",")] if isinstance(terms, str) else list(terms)
    add = [t for t in add if t and t.lower() not in low]
    if not add: return tidy(text)
    t = tidy(text)
    return tidy(t + (" " if t.endswith((".", "!", "?")) else ", ") + ", ".join(add))


def plain(prompt, style, text_style):
    """다듬기 없이 보낼 문장: 원문 + 스타일 꼬리 + (그대로·사진이고 글자 디자인이 아니면) magic — 겹치지 않게"""
    out = with_tail(prompt, STYLES[style][1])
    if style in MAGIC_STYLES and not text_style and not re.search(r"cinematic|ultra ?hd|\b[48]k\b", out, re.I):
        out = with_tail(out, MAGIC)
    return out


def _strip_quotes(text, bad):
    """지어낸 문구가 든 문장을 통째로 뺀다(문장이 하나뿐이면 문구만 뺀다)"""
    sents = re.split(r"(?<=[.!?])\s+", text)
    keep = [s for s in sents if not any(q in s for q in bad)]
    if keep: return " ".join(keep)
    for q in bad: text = re.sub(r'(?:the (?:text|words?)\s*)?["“‘「『]' + re.escape(q) + r'["”’」』]', "", text)
    return text


def _strip_overused(text, words):
    for w in words:
        text = re.sub(rf"(?<![\w-]){re.escape(w)}(?![\w-])(?:\s*,)?", "", text, flags=re.I)
    return re.sub(r"\b(a|an)\s+(?=[,.]|and\b)", "", tidy(text))


def _trim(text, limit=90):
    """너무 길면 문장 단위로 자름"""
    if len(text.split()) <= limit: return text
    out = []
    for s in re.split(r"(?<=[.!?])\s+", text):
        if out and len(" ".join(out + [s]).split()) > limit: break
        out.append(s)
    return " ".join(out)


def _plan(prompt, style):
    """요청 → 장면 계획 칸(JSON). 실패하면 빈 계획(요청만으로 문단을 씀)"""
    sys_p = ("You plan a picture from a user's request (usually Korean) for a text-to-image model. Return only a JSON object with these English string keys: "
             '"subject" (who/what and the action), "setting" (place with concrete, specific visual details), "time_light" (time of day, season, light source), '
             '"composition" (framing, camera angle or viewpoint), "mood" (one or two plain words), "medium" (style/medium the user asked for, or ""), '
             '"avoid" (list of short English things to keep out of the image), and "added_ko" (list of short Korean nouns naming which aspects you added that the user did not state, e.g. "장소 디테일", "조명", "구도", "색감").\n'
             "Rules: Stay faithful: keep every element the user named and do not add people, objects, symbols or events that change the meaning. "
             "When the request names a country, region, era or event, fill \"setting\" with recognisable details typical of that place and time (architecture, vehicles, uniforms, clothing, street furniture, vegetation, weather) from general knowledge, not a generic city. "
             "A request written in Korean that names no place is set in South Korea (Korean school uniforms, streets, homes, food) unless its content points elsewhere. "
             "Keep the user's facts exactly as given, even if they look wrong; do not correct dates, names or places. Dates and names are context, never visible text. "
             "Never include real, identifiable people (politicians, celebrities); use anonymous people. "
             "Use plain, specific words, not hype words such as cinematic, epic, stunning, moody, masterpiece, 4K.")
    try:
        raw = llm(sys_p, f"[요청] {prompt}\n[스타일] {STYLES[style][0]}", temperature=0.3, as_json=True)
        j = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        return j if isinstance(j, dict) else {}
    except Exception:
        return {}


def _compose(prompt, plan, style, user_q, text_style, note=""):
    cue = STYLE_CUES[style][2]
    if user_q:
        txt = ("Text in the image: include exactly these strings, each in double quotes, unchanged and untranslated, and say where each one appears: "
               + ", ".join(f'"{q}"' for q in user_q) + ". No other words, letters or numbers anywhere in the image.")
    else:
        txt = ("The image has no written words: no readable signs, captions, dates, labels, logos or watermarks. Do not use quotation marks at all."
               + (" Use icons, shapes and chart forms instead of words." if text_style else ""))
    sys_p = ("You write one prompt for the Qwen-Image text-to-image model from a user's request and a scene plan. Output only the prompt: one natural English paragraph of 40-80 words, "
             "plain declarative sentences, concrete nouns and specific details rather than adjectives. Begin with the medium and the main subject, then the setting details, light and time, composition, and mood in plain words.\n"
             f"- Medium: {cue}\n- {txt}\n"
             "- Stay faithful to the request; do not add elements that change its meaning, and do not correct the user's facts.\n"
             "- No real, identifiable people; anonymous figures only.\n"
             "- Do not use these over-used words unless the request itself asks for them: " + ", ".join(OVERUSED) + ".")
    usr = f"[요청] {prompt}\n[장면 계획] {json.dumps({k: v for k, v in plan.items() if k != 'added_ko'}, ensure_ascii=False) if plan else '(없음 — 요청만 보고 쓰기)'}"
    if note: usr += f"\n[고칠 점] {note}"
    return tidy(llm(sys_p, usr, temperature=0.3))


def refine(prompt, style, text_style):
    """한국어·짧은 요청 → 그림 모델용 영어 프롬프트 + 무엇을 보탰는지 한 줄 + 빼야 할 것.
    따옴표 안 글자(그림에 들어갈 문구)는 원문 그대로, 사용자가 따옴표로 준 것만 그림에 넣는다."""
    user_q = quotes(prompt, user=True)
    plan = _plan(prompt, style)
    out = _compose(prompt, plan, style, user_q, text_style)
    if not out: return {"final_prompt": plain(prompt, style, text_style), "summary_ko": "다듬기 결과가 비어 원문 그대로 씁니다", "avoid": []}
    bad, hype, n = invented_quotes(out, prompt), overused(out, prompt, style), len(out.split())
    if bad or hype or not 30 <= n <= 100:
        note = " ".join(x for x in (
            f"Remove the quoted text {', '.join(repr(q) for q in bad)}: the user did not ask for it, so the image must not contain it." if bad else "",
            f"Do not use the words: {', '.join(hype)}; describe what is actually seen instead." if hype else "",
            f"It was {n} words; write 40-80 words." if not 30 <= n <= 100 else "") if x)
        try:
            again = _compose(prompt, plan, style, user_q, text_style, note)
            out = again or out
        except Exception:
            pass
    bad = invented_quotes(out, prompt)
    if bad: out = _strip_quotes(out, bad)
    hype = overused(out, prompt, style)
    if hype: out = _strip_overused(out, hype)
    out = _trim(tidy(out))
    key, lead, _ = STYLE_CUES[style]
    if key and not re.search(key, out, re.I): out = lead + " " + out  # 스타일이 그림 모델까지 꼭 가게
    added = [x for x in (plan.get("added_ko") or []) if isinstance(x, str) and x.strip()][:5] or \
            [v for k, v in ADDED_KO.items() if str(plan.get(k) or "").strip()]
    avoid = plan.get("avoid") or []
    avoid = [x.strip() for x in (avoid.split(",") if isinstance(avoid, str) else avoid) if isinstance(x, str) and x.strip()][:6]  # 문자열로 오기도 함
    if user_q or text_style:  # 글자를 넣는 그림이면 네거티브에 글자 관련 말을 넣지 않음(제목까지 지워짐)
        avoid = [a for a in avoid if not re.search(r"text|letter|word|typograph|font|caption|label|title", a, re.I)]
    elif not any("text" in a.lower() for a in avoid): avoid.append("text, watermark")
    return {"final_prompt": tidy(out), "summary_ko": "추가한 것: " + ("·".join(added) if added else "영어로 옮기기"), "avoid": avoid}


def worker_env(env=None, smi_ids=None):
    """작업자 프로세스 환경 — CUDA_VISIBLE_DEVICES 를 부모 후보(CUDA_VISIBLE_DEVICES ∩ GPU_POOL − GPU_RESERVED)로 좁힘(운영 vLLM GPU 는 안 보임)"""
    return pool_env({**(os.environ if env is None else env), "PYTHONUNBUFFERED": "1"}, smi_ids)


def worker(path, body, emit=lambda ev: None):
    """GPU 작업 프로세스에 요청(없으면 띄움) → 마지막 결과"""
    try:
        urllib.request.urlopen(WORKER + "/", timeout=2)
    except Exception:
        emit({"stage": "worker", "msg": "GPU 작업 프로세스 시작"})
        wp = subprocess.Popen([PY, os.path.join(ROOT, "worker.py")], cwd=ROOT, env=worker_env(),
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


def _scrub(ev):
    """GPU 작업 프로세스 이벤트에서 서버 절대 경로를 빼고 파일 이름만 남긴다"""
    ev = dict(ev)
    if isinstance(ev.get("path"), str):
        ev["path"] = os.path.basename(ev["path"])
    if isinstance(ev.get("paths"), list):
        ev["paths"] = [os.path.basename(str(x)) for x in ev["paths"]]
    return ev


def _hide_paths(msg):
    """오류 문구 속 서버 폴더 경로를 지운다"""
    for base in sorted({os.path.realpath(WS), WS, ROOT, os.path.realpath(ROOT)}, key=len, reverse=True):
        msg = msg.replace(base + os.sep, "").replace(base, "")
    return msg


def user_ws(h):
    """포털이 넘긴 사용자별 작업 폴더. owner(서버 주인)·헤더 없음(단독 실행) = 예전 WORKSPACE 그대로"""
    u = (h.headers.get("X-Agent-User") or "owner").strip()
    if u == "owner":
        return WS
    d = os.path.join(WS, "u", re.sub(r"[^A-Za-z0-9_.-]", "_", u)[:64] or "_")
    os.makedirs(d, exist_ok=True)
    return d


def new_run(ws=WS):
    rid = f"{datetime.date.today()}-{secrets.token_hex(3)}"
    os.makedirs(os.path.join(ws, rid)); return rid, os.path.join(ws, rid)


def save_meta(d, meta):
    json.dump(meta, open(os.path.join(d, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def generate(prompt, style="none", ratio="1:1", n=1, quality="normal", seed=None, negative="", enhance=True, emit=lambda ev: None, ws=WS, exact=False):
    """exact=True: 받은 문장을 꼬리말 없이 그대로 보냄('다듬기만 보기'에서 고친 문장으로 그릴 때)"""
    if not prompt.strip(): raise ValueError("무엇을 그릴지 써 주세요")
    style = style if style in STYLES else "none"; ratio = ratio if ratio in RATIOS else "1:1"; quality = quality if quality in QUALITY else "normal"
    n = max(1, min(int(n or 1), 4)); seed = int(seed) if str(seed or "").strip().lstrip("-").isdigit() else secrets.randbelow(10 ** 9)
    text_style = STYLES[style][2] or bool(quotes(prompt, user=True))
    final, auto_neg = (prompt.strip() if exact else plain(prompt, style, text_style)), []
    if enhance and not exact:
        emit({"stage": "prompt", "msg": "요청을 그림 프롬프트로 다듬는 중"})
        try:
            r = refine(prompt, style, text_style)
            final, auto_neg = r["final_prompt"], r["avoid"]
        except Exception as e:
            emit({"stage": "prompt", "msg": f"다듬기 건너뜀({type(e).__name__}) — 원문 그대로"})
    rid, d = new_run(ws)
    w, h = RATIOS[ratio]
    meta = {"run_id": rid, "kind": "generate", "prompt": prompt, "final_prompt": final, "negative": negative, "style": style, "ratio": ratio,
            **({"auto_negative": ", ".join(auto_neg)} if auto_neg else {}),
            "quality": quality, "seed": seed, "n": n, "ts": datetime.datetime.now().isoformat(timespec="seconds")}
    save_meta(d, meta)
    emit({"stage": "draw", "msg": f"그리는 중 ({n}장, {QUALITY[quality][0]})", "run_id": rid, "final_prompt": final})
    try:
        worker("/generate", {"prompt": final, "negative": ", ".join(x for x in (negative, *auto_neg, SAFE_NEG) if x), "width": w, "height": h, "n": n,
                             "seed": seed, "steps": QUALITY[quality][1], "out_dir": d}, lambda ev: emit({**_scrub(ev), "run_id": rid}))
    except Exception:
        shutil.rmtree(d, ignore_errors=True); raise  # 실패한 건 흔적 없이
    meta["images"] = [f"img_{i}.png" for i in range(n)]; save_meta(d, meta)
    return meta


def edit(instruction, sources, n=1, quality="normal", seed=None, negative="", emit=lambda ev: None, ws=WS):
    """sources: 로컬 이미지 경로 1~3개(올린 것 또는 갤러리). 지시는 그대로(편집 모델은 한국어·영어 지시를 읽음)"""
    if not instruction.strip(): raise ValueError("어떻게 고칠지 써 주세요")
    if not sources: raise ValueError("고칠 그림을 올리거나 갤러리에서 고르세요")
    quality = quality if quality in QUALITY else "normal"; n = max(1, min(int(n or 1), 4))
    seed = int(seed) if str(seed or "").strip().lstrip("-").isdigit() else secrets.randbelow(10 ** 9)
    rid, d = new_run(ws)
    srcs = []
    for i, s in enumerate(sources[:3]):
        p = os.path.join(d, f"src_{i}.png"); shutil.copy(s, p); srcs.append(p)
    meta = {"run_id": rid, "kind": "edit", "prompt": instruction, "final_prompt": instruction, "negative": negative, "quality": quality, "seed": seed,
            "n": n, "sources": [os.path.basename(x) for x in srcs], "ts": datetime.datetime.now().isoformat(timespec="seconds")}
    save_meta(d, meta)
    emit({"stage": "draw", "msg": f"고치는 중 ({n}장, {QUALITY[quality][0]})", "run_id": rid})
    try:
        worker("/edit", {"images": srcs, "prompt": instruction, "negative": ", ".join(x for x in (negative, SAFE_NEG) if x), "n": n, "seed": seed,
                         "steps": QUALITY[quality][1], "out_dir": d}, lambda ev: emit({**_scrub(ev), "run_id": rid}))
    except Exception:
        shutil.rmtree(d, ignore_errors=True); raise
    meta["images"] = [f"img_{i}.png" for i in range(n)]; save_meta(d, meta)
    return meta


def list_runs(ws=WS):
    out = []
    for n in sorted(os.listdir(ws), key=lambda n: os.path.getmtime(os.path.join(ws, n)), reverse=True)[:80] if os.path.isdir(ws) else []:
        p = os.path.join(ws, n, "meta.json")
        if re.fullmatch(RUN_RE, n) and os.path.exists(p):
            m = json.load(open(p, encoding="utf-8"))
            if m.get("images"): out.append(m)  # 끝난 것만
    return out


def delete(run_id, ws=WS):
    """휴지통(.trash)으로 옮김 — 실수로 지워도 폴더째 되살릴 수 있게"""
    if not re.fullmatch(RUN_RE, run_id or ""): raise ValueError("잘못된 ID")
    src = os.path.join(ws, run_id)
    if not os.path.isdir(src): raise ValueError("없는 그림")
    t = os.path.join(ws, ".trash"); os.makedirs(t, exist_ok=True); shutil.move(src, os.path.join(t, run_id))
    return {"ok": True}


def resolve(ref, ws=WS):
    """'run_id/img_0.png' → 로컬 경로 (갤러리 그림을 편집 원본으로)"""
    m = re.fullmatch(rf"({RUN_RE})/((?:img|src)_\d\.png)", ref or "")
    if not m: raise ValueError("잘못된 그림 경로")
    p = os.path.join(ws, m.group(1), m.group(2))
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


def safe_emit(wfile):
    """SSE 한 줄 쓰기. 브라우저가 떠나 연결이 끊기면(포털도 도구 쪽 연결을 닫음) 그 뒤 쓰기는 조용히 버린다 —
    끊김은 취소가 아니라서 작업은 끝까지 하고 결과는 갤러리에 남고 🔔 알림은 완료로 간다"""
    gone = []

    def emit(ev):
        if gone: return
        b = f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode()
        try:
            wfile.write(b); wfile.flush()
        except OSError:  # BrokenPipe·ConnectionReset·ConnectionAborted·닫힌 소켓
            gone.append(1); print("클라이언트 연결 끊김 — 작업은 계속", file=sys.stderr, flush=True)
    return emit


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
        if p == "/api/runs": return self._send(list_runs(user_ws(self)))
        m = re.fullmatch(rf"/api/runs/({RUN_RE})/((?:img|src)_\d\.png)", p)
        if m:
            f = os.path.join(user_ws(self), m.group(1), m.group(2))
            if os.path.exists(f):
                return self._send(open(f, "rb").read(), "image/png", name=f"{m.group(1)}_{m.group(2)}" if "download" in q else None)
            return self._send({"error": "없음"}, code=404)
        if self.path.split("?")[0].startswith("/api/"):   # 없는 API 경로는 화면 대신 JSON 404
            return self._send({"error": "not found"}, code=404)
        self._send(signed(HTML).encode(), "text/html; charset=utf-8")

    def do_POST(self):
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self._send({"error": "잘못된 요청"}, code=400)
        if not isinstance(req, dict):
            return self._send({"error": "잘못된 요청"}, code=400)
        ws = user_ws(self)  # 경로는 요청 시점에 정해 GPU 워커로 out_dir 로 넘긴다
        if self.path == "/api/delete":
            try: return self._send(delete(req.get("run_id"), ws))
            except ValueError as e: return self._send({"error": str(e)}, code=400)
        if self.path == "/api/refine":  # 다듬기만 보기: 그리지 않고 다듬은 문장·한 줄 설명만
            prompt, style = str(req.get("prompt") or "").strip(), req.get("style") if req.get("style") in STYLES else "none"
            if not prompt: return self._send({"error": "무엇을 그릴지 써 주세요"}, code=400)
            ts = STYLES[style][2] or bool(quotes(prompt, user=True))
            try:
                r = refine(prompt, style, ts)
                return self._send({"final_prompt": r["final_prompt"], "summary_ko": r["summary_ko"], "negative": ", ".join(r["avoid"])})
            except Exception as e:
                return self._send({"final_prompt": plain(prompt, style, ts), "summary_ko": f"다듬기를 못 했습니다({type(e).__name__}) — 원문에 스타일 꼬리말만 붙였어요", "negative": "", "fallback": True})
        if self.path not in ("/api/generate", "/api/edit"):
            return self._send({"error": "not found"}, code=404)
        self.send_response(200); self.send_header("Content-Type", "text/event-stream; charset=utf-8"); self.send_header("Cache-Control", "no-cache"); self.end_headers()
        emit = safe_emit(self.wfile)
        ups = []
        user, jid, kind = self.headers.get("X-Agent-User"), secrets.token_hex(6), "그림 생성" if self.path == "/api/generate" else "그림 고치기"
        title = f"{kind} · {(req.get('prompt') if self.path == '/api/generate' else req.get('instruction')) or ''}"[:60]
        portal_jobs.notify(user, "running", id=jid, title=title, link="/")
        noted = False
        try:
            if self.path == "/api/generate":
                r = generate(req.get("prompt") or "", req.get("style"), req.get("ratio"), req.get("n"), req.get("quality"), req.get("seed"),
                             req.get("negative") or "", req.get("enhance", True), emit, ws, bool(req.get("exact")))
            else:
                srcs = [resolve(x, ws) for x in req.get("refs") or []]
                up = os.path.join(ws, "_upload"); os.makedirs(up, exist_ok=True)
                for f in req.get("uploads") or []:
                    if not re.search(r"\.(png|jpe?g|webp)$", f.get("name", ""), re.I): raise ValueError("그림 파일(png·jpg·webp)만")
                    p = os.path.join(up, secrets.token_hex(4) + "_" + re.sub(r"[^\w.\-]", "_", os.path.basename(f["name"])))
                    open(p, "wb").write(base64.b64decode(f["b64"])); ups.append(p); srcs.append(p)
                r = edit(req.get("instruction") or "", srcs, req.get("n"), req.get("quality"), req.get("seed"), req.get("negative") or "", emit, ws)
            portal_jobs.notify(user, "done", id=jid, title=title, link=f"/?run={r['run_id']}", message=f"{len(r['images'])}장"); noted = True
            emit({"done": r})
        except Exception as e:
            if not noted:
                portal_jobs.notify(user, "failed", id=jid, title=title, link="/", message=_hide_paths(f"{type(e).__name__}: {e}")[:200])
            emit({"error": _hide_paths(f"{type(e).__name__}: {e}")})
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
    ThreadingHTTPServer((os.environ.get("BIND", "127.0.0.1"), PORT), portal_auth.install(H, "image-local")).serve_forever()
