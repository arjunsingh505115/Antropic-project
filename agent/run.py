#!/usr/bin/env python3
"""
OpenYug 2 — Swag/Arjun ka apna agent, ab Arjun Engine ke dimaag ke saath.

Har run (GitHub Actions par, ya phone par `python3 agent/run.py`):
  1. orders.md ke aadesh padhta hai — KOI bhi aadesh (handler na ho to AI se karta hai)
  2. apne banaye sub-agents (agent/agents/*.md) ke aadesh chalata hai
  3. bade kaam ke jobs (agent/jobs/*.json) ka agla step karta hai
  4. dimaag (brain.py) ke khud chune kaam karta hai (seekhna, sujhav)
  5. report likhta hai (agent/reports/)

Aadesh likhne ka tareeka (orders.md mein `- [ ] ...`):
  sudhaar: <kya behtar karna hai>     -> apna code khud sudhaare -> tests -> Pull Request
  banao: <kaisa app>                  -> projects/<naam> mein naya app -> tests -> Pull Request
  kaam: <koi bhi goal>                -> dimaag web/code/tools se kaam kare
  agent banao: <naam> - <uska kaam>   -> naya sub-agent (apne aadesh ke saath)
  bada kaam: <goal>                   -> AI chhote steps ka job banaye, har run ek step
  seekho: <topic>                     -> web + AI se seekh kar knowledge.md mein
  sujhav: <kis baare mein>            -> behtar banane ke idea suggestions.md mein
  Har baar: <...>                     -> har run chalega (kabhi [x] nahi hota)
  koi aur sawaal                      -> AI jawab report mein
  pause / resume                      -> agent rokna / chalana

Suraksha (red line, kabhi nahi hat-ti):
  - code main par seedha kabhi nahi jaata — branch + PR, Merge = owner ki haan
  - kisi aur ka account/credentials nahi; paisa, delete, public post nahi
  - AI kabhi raw shell command nahi chala sakta — sirf neeche ki safe list
"""
import json, os, re, subprocess, sys, time, datetime, urllib.request, importlib.util, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A = os.path.join(ROOT, "agent")
ORDERS = os.path.join(A, "orders.md")
REPORTS = os.path.join(A, "reports")
NOW = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_mod(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(A, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


engine = load_mod("engine")


def jload(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def jsave(path, obj):
    json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


CONFIG = jload(os.path.join(A, "config.json"), {})
OWNER = CONFIG.get("owner", "Swag")
LIMITS = {"heavy_per_run": 1, "ask_per_run": 6, "max_agents": 12, **CONFIG.get("limits", {})}
INBOX = os.path.join(A, "inbox.jsonl")
RESEARCH = os.path.join(A, "research")


def ensure_live():
    """seed/ se pehli baar ki yaad (state, knowledge, orders…) — sirf jo file abhi nahi hai."""
    seed = os.path.join(A, "seed")
    if not os.path.isdir(seed):
        return
    for f in os.listdir(seed):
        dst = os.path.join(A, f)
        if not os.path.exists(dst):
            shutil.copyfile(os.path.join(seed, f), dst)


def sh(cmd, timeout=600):
    try:
        r = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return 1, str(e)


def http_ok(url, timeout=15):
    if engine.offline():
        return False, 0
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "openyug-agent"})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status < 400, int((time.time() - t0) * 1000)
    except Exception:
        return False, 0


def slug(text, n=40):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:n].strip("-") or "kaam")


# ---------------- purane (local) kaam — bina AI ----------------

def job_tests():
    if os.path.exists(os.path.join(ROOT, "tests", "check-all.sh")):
        code, out = sh("bash tests/check-all.sh")
    else:
        code, out = sh(f"node {os.path.join('scripts', 'self-upgrade.cjs')} test", timeout=1200)
    return code == 0, engine.tail(out, 12)


def job_data_age():
    p = os.path.join(ROOT, CONFIG.get("data_file", "data/live.json"))
    if not os.path.exists(p):
        return True, f"{CONFIG.get('data_file')} is repo mein nahi (ye kaam seetal-trader repo ka hai) — chhod diya"
    d = jload(p, {})
    gen, rows = d.get("generated_at"), len(d.get("rows", []))
    if not gen:
        return False, "generated_at nahi hai"
    t = datetime.datetime.fromisoformat(gen.replace("Z", "+00:00"))
    age = int((datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() // 60)
    ok = age <= 45 and rows >= 3
    return ok, f"data {age} min purana, {rows} symbols — {'theek' if ok else 'purana/ kam'}"


def _check(pairs, need):
    lines, okc = [], 0
    for name, url in pairs:
        ok, ms = http_ok(url)
        okc += 1 if ok else 0
        lines.append(f"✅ {name} {ms}ms" if ok else f"❌ {name} (band / nahi mila)")
    return okc >= need(len(pairs)), "\n".join(lines) or "(config.json mein kuch nahi)"


def job_sites():
    return _check(CONFIG.get("sites", []), lambda n: n - 1)


def job_mirrors():
    return _check(CONFIG.get("mirrors", []), lambda n: min(2, n))


def job_cleanup():
    cut, n = time.time() - 7 * 86400, 0
    if os.path.isdir(REPORTS):
        for f in os.listdir(REPORTS):
            p = os.path.join(REPORTS, f)
            if f.endswith(".md") and os.path.isfile(p) and os.path.getmtime(p) < cut:
                os.remove(p)
                n += 1
    return True, f"{n} purani report saaf ki"


LOCAL = [
    (r"\btest|check-all|jaanch", job_tests),
    (r"\bdata\b|purana|umar", job_data_age),
    (r"\bsite|health|platform|check karo", job_sites),
    (r"saaf|cleanup|purani report", job_cleanup),
    (r"mirror|gitlab|codeberg|bitbucket|storage|backup", job_mirrors),
]
KNOWN = {"tests": job_tests, "data": job_data_age, "sites": job_sites, "cleanup": job_cleanup, "mirrors": job_mirrors}


# ---------------- AI wale kaam (Arjun Engine se) ----------------

class Budget:
    def __init__(self):
        self.heavy = int(LIMITS["heavy_per_run"])
        self.ask = int(LIMITS["ask_per_run"])

    def take(self, kind):
        if kind == "heavy":
            if self.heavy <= 0:
                return False
            self.heavy -= 1
            return True
        if self.ask <= 0:
            return False
        self.ask -= 1
        return True


WAIT = "⏳ is run ka AI-budget khatam — agli run mein karunga"


def record_upgrade(text, out):
    st = jload(os.path.join(A, "state.json"), {})
    pr = engine.pr_link(out)
    st.setdefault("upgrades", []).append({"at": NOW, "kaam": text[:200], "pr": pr})
    st["upgrades"] = st["upgrades"][-50:]
    st["version"] = f"2.{len(st['upgrades'])}"
    jsave(os.path.join(A, "state.json"), st)
    return pr


def heavy(kind, text, budget, role=""):
    if not engine.available():
        return False, "AI engine nahi mila (offline) — agli baar", False
    if not budget.take("heavy"):
        return False, WAIT, False
    goal = f"{text}\n(Ye kaam OpenYug ke sub-agent ka hai: {role})" if role else text
    if kind == "khud":
        ok, out = engine.khud(goal)
    elif kind == "banao":
        folder = os.path.join(ROOT, "projects", slug(text))
        os.makedirs(folder, exist_ok=True)
        ok, out = engine.banao(goal, folder)
    else:
        ok, out = engine.kaam(goal)
    pr = record_upgrade(text, out) if kind in ("khud", "banao") and engine.pr_link(out) else engine.pr_link(out)
    msg = engine.tail(out, 10)
    if pr:
        msg += f"\n🔀 Pull Request: {pr} ← dekh kar Merge karo ({OWNER} ki haan)"
    return ok, msg, ok


def light(question, budget, role="", web=False):
    if not engine.available():
        return False, "AI engine nahi mila (offline) — agli baar", False
    if not budget.take("ask"):
        return False, WAIT, False
    q = f"Tum OpenYug ho ({role or OWNER + ' ka agent'}). Simple Hinglish mein chhota, kaam ka jawab do.\n\n{question}"
    ans = engine.ask(q, web=web, query=question[:160])
    return bool(ans), ans or f"AI se jawab nahi aaya — agli baar. Wajah: {engine.LAST_ERROR or 'sab AI busy/limit'}", bool(ans)


def write_suggestions(topic, budget, role=""):
    know = open(os.path.join(A, "knowledge.md"), encoding="utf-8").read()[-1500:] if os.path.exists(os.path.join(A, "knowledge.md")) else ""
    goals = open(os.path.join(A, "goals.md"), encoding="utf-8").read()[:1500] if os.path.exists(os.path.join(A, "goals.md")) else ""
    ok, ans, done = light(f"{OWNER} ke system ko behtar banane ke 3 chhote, safe, kaam ke idea do (har idea 1 line, aur saath mein ek 'sudhaar: ...' aadesh jo use kar sake). Vishay: {topic or 'pura system'}\n\nLakshya:\n{goals}\n\nHaal mein seekha:\n{know}", budget, role)
    if ok:
        with open(os.path.join(A, "suggestions.md"), "a", encoding="utf-8") as f:
            f.write(f"\n## {NOW[:10]} — {topic or 'system'}\n\n{ans}\n")
        st = jload(os.path.join(A, "state.json"), {})
        st["last_sujhav_week"] = datetime.datetime.now(datetime.timezone.utc).strftime("%G-W%V")
        jsave(os.path.join(A, "state.json"), st)
    return ok, ans, done


def inbox_add(kind, title, text, pr=""):
    """📥 Owner ka inbox — phone ka panel yahi dikhata hai (naya upar)."""
    entry = {"at": NOW, "kind": kind, "title": str(title)[:200], "text": str(text)[:6000]}
    if pr:
        entry["pr"] = pr
    try:
        rows = open(INBOX, encoding="utf-8").read().splitlines() if os.path.exists(INBOX) else []
        rows.append(json.dumps(entry, ensure_ascii=False))
        open(INBOX, "w", encoding="utf-8").write("\n".join(rows[-300:]) + "\n")
    except Exception:
        pass


def kind_of(order):
    low = order.lower().strip()
    for pat, k in [(r"^(naya\s+)?agent\s+banao", "agent"), (r"^(sudhaar|sudhar|khud|upgrade|apne aap)", "upgrade"),
                   (r"^(app\s+|website\s+|game\s+)?banao", "banaya"), (r"^kaam", "kaam"), (r"^(bada kaam|job|todo)", "job"),
                   (r"^research", "research"), (r"^(seekho|learn)", "seekha"), (r"^(sujhav|suggest)", "sujhav")]:
        if re.match(pat, low):
            return k
    for pat, _ in LOCAL:
        if re.search(pat, order, re.I):
            return "jaanch"
    return "jawab"


def next_topic():
    topics = CONFIG.get("research_topics") or ["AI agents ke naye free tools"]
    st = jload(os.path.join(A, "state.json"), {})
    return topics[int(st.get("research_index", 0)) % len(topics)]


def research(topic, budget, role=""):
    """Gehri research: AI khud 3 sawaal banata hai -> sabse kaam ka sawaal web se -> sources ke saath file + inbox."""
    if not engine.available():
        return False, "AI engine nahi mila (offline) — research agli baar", False
    auto = not topic
    topic = topic or next_topic()
    if not budget.take("ask"):
        return False, WAIT, False
    raw = engine.ask(f"Tum {OWNER} ke research agent ho. {OWNER} self-evolving AI system, apps, games aur 3D cartoon banata hai, "
                     f"aur sab kuch free/kam kharch mein, phone par bhi chalana chahta hai.\nVishay: {topic}\n"
                     "Is vishay par research ke liye 3 tez, practical sawaal banao jo uske kaam ke liye sabse useful hon. "
                     "Sirf 3 lines, har line ek sawaal, aur kuch nahi.")
    qs = [re.sub(r"^[\s\-*\d.)]+", "", l).strip() for l in (raw or "").splitlines() if len(l.strip()) > 8][:3] or [f"{topic} — aaj sabse kaam ka kya hai?"]
    if not budget.take("ask"):
        return False, WAIT, False
    ans = engine.ask(f"Research karo (web dekh kar, taaza jaankari) aur {OWNER} ke liye gehra par saaf jawab do, simple Hinglish mein.\n"
                     f"Vishay: {topic}\nMukhya sawaal: {qs[0]}\nBaaki sawaal (chhota jawab): {'; '.join(qs[1:])}\n\n"
                     "Format:\n## Saar (3 line)\n## Kya naya hai\n## Kaise use karein (steps, free tools, limits)\n"
                     "## Hamare system mein kya jod sakte hain (ek 'sudhaar: ...' aadesh bhi likho)\n## Sources (links)",
                     web=True, query=f"{topic} {qs[0]}")
    if not ans:
        return False, f"AI se research nahi bani — agli baar. Wajah: {engine.LAST_ERROR or 'pata nahi'}", False
    os.makedirs(RESEARCH, exist_ok=True)
    name = f"{NOW[:10]}-{slug(topic, 50)}.md"
    body = f"# Research: {topic}\n\n_{NOW} · OpenYug_\n\n**Sawaal jo maine khud se poochhe:**\n" + "\n".join(f"- {q}" for q in qs) + f"\n\n{ans}\n"
    open(os.path.join(RESEARCH, name), "w", encoding="utf-8").write(body)
    with open(os.path.join(A, "knowledge.md"), "a", encoding="utf-8") as f:
        f.write(f"\n## {NOW[:10]} — research: {topic}\n\n" + " ".join(ans.split())[:500] + f"\n(poora: agent/research/{name})\n")
    if auto:
        st = jload(os.path.join(A, "state.json"), {})
        st["research_index"] = int(st.get("research_index", 0)) + 1
        st["research_count"] = int(st.get("research_count", 0)) + 1
        jsave(os.path.join(A, "state.json"), st)
    inbox_add("research", topic, "Sawaal:\n" + "\n".join(f"• {q}" for q in qs) + "\n\n" + ans)
    return True, f"🔎 research likhi: agent/research/{name}\n" + engine.tail(ans, 6), True


def dispatch(order, budget, role=""):
    """Ek aadesh -> (ok, nateeja, done?). Prefix wale aadesh pehle, phir purane local kaam, phir AI jawab."""
    o = order.strip()
    low = o.lower()
    rest = re.sub(r"^[^:\-–]+[:\-–]\s*", "", o, count=1) if re.match(r"^[^:\-–]{2,30}[:\-–]", o) else o

    if re.match(r"^(naya\s+)?agent\s+banao", low):
        spawn = load_mod("spawn")
        return spawn.create_agent(rest, ai=lambda q: light(q, budget, role)[1] if engine.available() else "")
    if re.match(r"^(sudhaar|sudhar|khud|upgrade|apne aap)", low):
        return heavy("khud", rest, budget, role)
    if re.match(r"^(app\s+|website\s+|game\s+)?banao\s*[:\-–]", low):
        return heavy("banao", rest, budget, role)
    if re.match(r"^kaam\s*[:\-–]", low):
        return heavy("kaam", rest, budget, role)
    if re.match(r"^(bada kaam|job|todo)\s*[:\-–]", low):
        spawn = load_mod("spawn")
        p = spawn.spawn(rest, ai=(lambda q: light(q, budget, role)[1]) if engine.available() else None)
        return True, f"🧩 job bana: {os.path.basename(p)} — har run ek step", True
    if re.match(r"^research", low):
        return research(rest if rest != o else "", budget, role)
    if re.match(r"^(seekho|learn)", low):
        learn = load_mod("learn")
        topic = rest if rest != o else ""
        ok, msg = learn.learn(topic=topic, ai=(lambda q: engine.ask(q, web=bool(topic))) if engine.available() and budget.take("ask") else None)
        return ok, msg, ok
    if re.match(r"^(sujhav|suggest)", low):
        return write_suggestions(rest if rest != o else "", budget, role)
    if re.match(r"^likho", low):
        return light(rest, budget, role)
    for pat, fn in LOCAL:
        if re.search(pat, o, re.I):
            ok, out = fn()
            return ok, out, ok
    return light(o, budget, role, web=True)


# ---------------- orders / agents / jobs ----------------

def pending(path):
    if not os.path.exists(path):
        return []
    return [m.group(1).strip() for m in (re.match(r"\s*-\s*\[\s\]\s*(.+)", l) for l in open(path, encoding="utf-8")) if m]


def mark_done(path, text):
    try:
        s = open(path, encoding="utf-8").read()
        s = s.replace(f"- [ ] {text}", f"- [x] {text}", 1)
        open(path, "w", encoding="utf-8").write(s)
    except Exception:
        pass


def recurring(text):
    return bool(re.match(r"^har\s*baar", text.strip(), re.I))


def run_orders(path, budget, role="", limit=None):
    lines = []
    for o in pending(path)[:limit]:
        if re.match(r"^(pause|resume)\b", o, re.I):
            continue
        task = re.sub(r"^har\s*baar\s*:\s*", "", o, flags=re.I)
        ok, out, done = dispatch(task, budget, role)
        lines += [f"### {o}", ("✅ " if ok else "❌ ") + str(out).replace("\n", "\n  "), ""]
        if ok and kind_of(task) not in ("research", "jaanch"):  # research khud inbox mein likhti hai
            inbox_add(kind_of(task), (f"[{role.split(':')[0]}] " if role else "") + task, out, engine.pr_link(out))
        if done and not recurring(o):
            mark_done(path, o)
    return lines


def run_agents(budget):
    d = os.path.join(A, "agents")
    if not os.path.isdir(d):
        return []
    out = []
    for f in sorted(os.listdir(d)):
        if not f.endswith(".md") or f == "README.md":
            continue
        path = os.path.join(d, f)
        text = open(path, encoding="utf-8").read()
        m = re.search(r"^kaam:\s*(.+)$", text, re.M)
        role = f"agent {f[:-3]}: {m.group(1).strip() if m else ''}"
        lines = run_orders(path, budget, role=role, limit=1)
        if lines:
            out += [f"## 🤖 Agent {f[:-3]}"] + lines
    return out


def run_jobs(budget):
    jd = os.path.join(A, "jobs")
    if not os.path.isdir(jd):
        return []
    lines = []
    for f in sorted(os.listdir(jd)):
        if not f.endswith(".json"):
            continue
        path = os.path.join(jd, f)
        job = jload(path, None)
        if not job or all(st.get("done") for st in job.get("steps", [])):
            continue
        lines.append(f"### Job {job.get('id')} — {job.get('goal')}")
        for st in job.get("steps", []):
            if st.get("done"):
                continue
            kind, text = st.get("kind"), st.get("text") or st.get("name", "")
            if kind == "known" or (not kind and st.get("name") in KNOWN):
                fn = KNOWN.get(st.get("name") or text)
                ok, out, done = (*fn(), True) if fn else (False, "ye local kaam nahi pehchana", False)
                done = done and ok
            elif kind in ("ask",):
                ok, out, done = light(text, budget)
            elif kind in ("khud", "banao", "kaam"):
                ok, out, done = heavy(kind, text, budget)
            else:  # purane job ki `cmd` — AI ki likhi raw shell kabhi nahi chalti
                ok, out, done = False, "⛔ anjaan step (raw command nahi chalayi jaati)", True
            st["done"] = bool(done)
            lines.append(f"- {'✅' if ok else '❌'} {st.get('name') or kind}: {engine.tail(out, 3)[:400]}")
            if ok:
                inbox_add("job", f"{job.get('goal')} → {st.get('name') or kind}", out, engine.pr_link(out))
            break  # har run har job ka ek step
        jsave(path, job)
        lines.append("")
    return lines


def brain_tasks(budget):
    try:
        b = load_mod("brain")
        tasks, why = b.decide()
        out = ["## Aaj ka faisla (OpenYug ne khud chuna)"] + [f"- {t}" for t in tasks] + ["", "_Wajah: " + "; ".join(why) + "_", ""]
        orders = set(pending(ORDERS))
        did = []
        for t in tasks:
            if t in orders:
                continue  # aadesh upar chal chuke
            ok, res, _ = dispatch(t, budget)
            did.append(t if ok else f"{t} (nahi hua)")
            if ok and kind_of(t) not in ("research", "jaanch"):
                inbox_add(kind_of(t), "khud se: " + t, res)
            out += [f"### {t}", ("✅ " if ok else "⏸️ ") + str(res).replace("\n", "\n  ")[:1500], ""]
        b.record(tasks, why, did)
        return out
    except Exception as e:
        return [f"(dimaag nahi chala: {str(e)[:120]})"]


def clock_line():
    try:
        c = load_mod("clock")
        gap = c.tick("run")
        return c.line() + (f" · pichhli baar se {gap}" if gap else "")
    except Exception:
        return "⏱️ (ghadi nahi chali)"


def main():
    os.makedirs(REPORTS, exist_ok=True)
    ensure_live()
    st = jload(os.path.join(A, "state.json"), {"paused": False})
    raw = open(ORDERS, encoding="utf-8").read() if os.path.exists(ORDERS) else ""
    if re.search(r"^- \[ \]\s*pause", raw, re.M | re.I):
        st["paused"] = True
        jsave(os.path.join(A, "state.json"), st)
        print(f"⏸️ OpenYug paused — {OWNER} ke 'resume' tak kaam band.")
        return
    if re.search(r"^- \[ \]\s*resume", raw, re.M | re.I):
        st["paused"] = False
        jsave(os.path.join(A, "state.json"), st)
        open(ORDERS, "w", encoding="utf-8").write(re.sub(r"^- \[ \]\s*resume", "- [x] resume", raw, flags=re.M | re.I))
        print("▶️ OpenYug resume ho gaya.")
    if st.get("paused"):
        print("⏸️ OpenYug paused hai.")
        return

    budget = Budget()
    ai = "✅ AI juda (Arjun Engine)" if engine.available() else "➖ AI nahi (offline) — sirf local kaam"
    orders = pending(ORDERS)
    lines = [f"# OpenYug report — {NOW}", "", clock_line(), f"🧠 {ai} · version {st.get('version', '2.0')}", ""]
    lines += [f"## Aadesh ({len(orders)})", ""] + (run_orders(ORDERS, budget) or ["Koi naya aadesh nahi.", ""])
    lines += run_agents(budget)
    jobs = run_jobs(budget)
    if jobs:
        lines += ["## Jobs (bade kaam, step by step)"] + jobs
    lines += brain_tasks(budget)
    lines += ["---", f"_OpenYug 2 — AI bachat: bhaari {budget.heavy}, halka {budget.ask}. Code badlav sirf PR se ({OWNER} merge kare)._"]

    name = os.path.join(REPORTS, f"{NOW.replace(':', '').replace('-', '')}.md")
    open(name, "w", encoding="utf-8").write("\n".join(lines))
    job_cleanup()
    print("\n".join(lines))
    print(f"\nReport: {name}")


if __name__ == "__main__":
    main()
