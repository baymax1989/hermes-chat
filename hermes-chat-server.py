#!/usr/bin/env python3
"""Hermes Chat 本地服务器 — CORS + 技能 + Memory + 数字员工"""
import http.server
import urllib.request
import urllib.parse
import json
import os
import glob
import shutil
import sqlite3
import threading
import time
import uuid

API_URL = os.environ.get("HERMES_API_URL", "http://127.0.0.1:8642")
API_KEY = os.environ.get("HERMES_API_KEY", "")
PORT = int(os.environ.get("PORT", "8080"))
HTML_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hermes-chat.html")
SKILLS_DIRS = [
    os.path.expanduser("~/.hermes/skills"),
    os.path.expanduser("~/.hermes/hermes-agent/skills"),
    os.path.expanduser("~/.hermes/hermes-agent/optional-skills"),
]
MEMORY_DB = os.path.expanduser("~/.hermes/memory_store.db")
AGENTS_FILE = os.path.expanduser("~/.hermes/hermes_agents.json")

TOOLSETS = [
    {"name":"web","desc":"网页搜索和内容提取"},
    {"name":"browser","desc":"浏览器自动化"},
    {"name":"terminal","desc":"终端命令执行"},
    {"name":"file","desc":"文件读写操作"},
    {"name":"vision","desc":"图像识别分析"},
    {"name":"tts","desc":"文本转语音"},
    {"name":"skills","desc":"技能浏览管理"},
    {"name":"memory","desc":"跨会话记忆"},
    {"name":"session_search","desc":"历史会话搜索"},
    {"name":"delegation","desc":"子代理任务委派"},
    {"name":"cronjob","desc":"定时任务调度"},
    {"name":"clarify","desc":"向用户提问澄清"},
]

# ===== Storage Helpers =====
def load_json(path, default=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return default if default is not None else {}

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ===== Agent/Task Storage =====
def load_agents():
    return load_json(AGENTS_FILE, {"agents": {}, "tasks": {}, "next_id": 1, "next_task_id": 1})

def save_agents(data):
    save_json(AGENTS_FILE, data)

# ===== Skills =====
def parse_skill_meta(path):
    try:
        with open(path, "r") as f:
            content = f.read()
        meta = {"name": os.path.basename(os.path.dirname(path)), "path": path}
        if content.startswith("---"):
            end = content.find("---", 3)
            if end > 0:
                for line in content[3:end].strip().split("\n"):
                    if ":" in line:
                        k, v = line.split(":", 1)
                        meta[k.strip()] = v.strip()
        meta["size"] = len(content)
        return meta
    except:
        return None

def list_skills():
    skills, seen = [], set()
    for base in SKILLS_DIRS:
        if not os.path.isdir(base): continue
        for root, dirs, files in os.walk(base):
            if "SKILL.md" in files:
                md = os.path.join(root, "SKILL.md")
                meta = parse_skill_meta(md)
                if meta and meta["name"] not in seen:
                    seen.add(meta["name"]); skills.append(meta)
    return skills

def read_skill(name):
    for base in SKILLS_DIRS:
        for root, dirs, files in os.walk(base):
            if os.sep + name in root and "SKILL.md" in files:
                full = os.path.join(root, "SKILL.md")
                with open(full, "r") as f:
                    return {"name": name, "content": f.read(), "path": full}
    return None

def save_skill(name, content):
    for base in SKILLS_DIRS:
        for root, dirs, files in os.walk(base):
            if os.sep + name in root and "SKILL.md" in files:
                with open(os.path.join(root, "SKILL.md"), "w") as f:
                    f.write(content)
                return True
    return False

def delete_skill(name):
    for base in SKILLS_DIRS:
        for root, dirs, files in os.walk(base):
            if os.sep + name in root and os.path.isdir(root) and root != base:
                shutil.rmtree(root); return True
    return False

# ===== Memory =====
def list_memory():
    try:
        conn = sqlite3.connect(MEMORY_DB); conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT fact_id, content, category, tags, trust_score, created_at FROM facts ORDER BY created_at DESC LIMIT 200").fetchall()
        conn.close(); return [dict(r) for r in rows]
    except: return []

def update_memory(fact_id, content):
    try:
        conn = sqlite3.connect(MEMORY_DB)
        conn.execute("UPDATE facts SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE fact_id = ?", (content, fact_id))
        conn.commit(); conn.close(); return True
    except: return False

def delete_memory(fact_id):
    try:
        conn = sqlite3.connect(MEMORY_DB)
        conn.execute("DELETE FROM facts WHERE fact_id = ?", (fact_id,))
        conn.commit(); conn.close(); return True
    except: return False

# ===== Direct Actions (no LLM) =====
def direct_search(query):
    """Search via Hermes API with tool_choice forced to web_search"""
    body = json.dumps({
        "model": "hermes",
        "messages": [{"role": "user", "content": f"搜索：{query}"}],
        "tools": [{"type": "function", "function": {
            "name": "web_search",
            "description": "Search the web",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
        }}],
        "tool_choice": {"type": "function", "function": {"name": "web_search"}},
        "max_tokens": 2000
    }).encode()
    req = urllib.request.Request(f"{API_URL}/v1/chat/completions", data=body, method="POST")
    req.add_header("Authorization", f"Bearer {API_KEY}")
    req.add_header("Content-Type", "application/json")
    resp = urllib.request.urlopen(req, timeout=120)
    data = json.loads(resp.read())
    msg = data.get("choices", [{}])[0].get("message", {})
    # Prefer tool call result, fall back to content
    tc = msg.get("tool_calls")
    if tc:
        return json.dumps(tc[0].get("function", {}), ensure_ascii=False)
    return msg.get("content", "(无结果)")

def direct_extract(url):
    """Extract web content via Hermes API"""
    body = json.dumps({
        "model": "hermes",
        "messages": [{"role": "user", "content": f"提取网页内容：{url}"}],
        "tools": [{"type": "function", "function": {
            "name": "web_extract",
            "description": "Extract web page content",
            "parameters": {"type": "object", "properties": {"urls": {"type": "array", "items": {"type": "string"}}}, "required": ["urls"]}
        }}],
        "tool_choice": {"type": "function", "function": {"name": "web_extract"}},
        "max_tokens": 3000
    }).encode()
    req = urllib.request.Request(f"{API_URL}/v1/chat/completions", data=body, method="POST")
    req.add_header("Authorization", f"Bearer {API_KEY}")
    req.add_header("Content-Type", "application/json")
    resp = urllib.request.urlopen(req, timeout=120)
    data = json.loads(resp.read())
    msg = data.get("choices", [{}])[0].get("message", {})
    tc = msg.get("tool_calls")
    if tc:
        return json.dumps(tc[0].get("function", {}), ensure_ascii=False)
    return msg.get("content", "(无结果)")

# ===== Workflow Engine =====
def execute_workflow(wf_nodes, wf_conns):
    """Execute a workflow's nodes in topological order."""
    if not wf_nodes: return []
    # Topological sort
    in_deg, adj = {}, {}
    for n in wf_nodes: nid = n["id"]; in_deg[nid] = 0; adj[nid] = []
    for c in wf_conns: adj[c["from"]].append(c["to"]); in_deg[c["to"]] = in_deg.get(c["to"], 0) + 1
    q = [n["id"] for n in wf_nodes if in_deg.get(n["id"], 0) == 0]
    order = []
    while q:
        u = q.pop(0); order.append(u)
        for v in adj.get(u, []):
            in_deg[v] -= 1
            if in_deg[v] == 0: q.append(v)

    results = []
    context = ""
    for nid in order:
        node = next((n for n in wf_nodes if n["id"] == nid), None)
        if not node: continue
        
        action = node.get("action", "skill")
        params = node.get("params", {})
        custom_prompt = node.get("prompt", "")
        desc = node.get("desc", "")
        
        # Build prompt based on action type
        if action == "custom" and custom_prompt:
            prompt = custom_prompt.replace("{{input}}", context)
        elif action == "search":
            q = params.get("query") or desc or context or "最新新闻"
            prompt = f"请使用 web_search 工具搜索：{q}"
        elif action == "extract":
            url = params.get("url") or (context.strip() if context else "")
            prompt = f"请使用 web_extract 工具提取以下URL的网页内容：{url}"
        elif action == "write":
            fp = params.get("filepath", "~/hermes_output.txt")
            fp = os.path.expanduser(fp)
            prompt = f"请使用 write_file 工具将以下内容写入文件 {fp}：\n\n{context}"
        elif action == "terminal":
            cmd = params.get("command", "echo {{input}}").replace("{{input}}", context)
            prompt = f"请在终端执行命令并返回结果：{cmd}"
        elif action == "analyze":
            prompt = f"{desc}\n\n{context}" if desc else f"请分析以下内容并给出总结：\n\n{context}"
        elif action == "skill":
            skill_name = node.get("skill") or node.get("name", "skill")
            prompt = f"使用技能 {skill_name}，执行以下任务。{desc}" + (f"\n\n上下文：{context}" if context else "")
            if not desc:
                prompt = f"使用技能 {skill_name}，基于以下上下文继续处理:\n\n{context}" if context else f"使用技能 {skill_name} 完成任务"
        else:
            prompt = f"{desc}" + (f"\n\n上下文：{context}" if context else "") if desc else (context or "处理任务")
        
        # Execute based on action type
        try:
            if action == "search":
                q = params.get("query") or desc or context or "最新新闻"
                output = direct_search(q)
            elif action == "extract":
                url = params.get("url") or (context.strip() if context else "")
                output = direct_extract(url) if url else "(无URL)"
            elif action == "write":
                fp = os.path.expanduser(params.get("filepath", "~/hermes_output.txt"))
                os.makedirs(os.path.dirname(fp) or ".", exist_ok=True)
                with open(fp, "w") as f:
                    f.write(context)
                output = f"已写入文件：{fp}（{len(context)} 字符）"
            elif action == "terminal":
                cmd = params.get("command", "echo {{input}}").replace("{{input}}", context)
                import subprocess
                r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, cwd=os.path.expanduser("~"))
                output = r.stdout + ("\n" + r.stderr if r.stderr else "")
            else:
                # analyze / skill / custom → use Hermes
                body = json.dumps({
                    "model": "hermes",
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "temperature": node.get("temp", 0.7),
                    "max_tokens": node.get("maxTokens", 1000)
                }).encode()
                req = urllib.request.Request(f"{API_URL}/v1/chat/completions", data=body, method="POST")
                req.add_header("Authorization", f"Bearer {API_KEY}")
                req.add_header("Content-Type", "application/json")
                resp = urllib.request.urlopen(req, timeout=180)
                data = json.loads(resp.read())
                output = data.get("choices", [{}])[0].get("message", {}).get("content", "(无输出)")
            
            context = output
            results.append({"name": node["name"], "output": output, "error": None})
        except Exception as e:
            results.append({"name": node["name"], "output": None, "error": str(e)})
    return results

# ===== Scheduler =====
def scheduler_loop():
    while True:
        try:
            data = load_agents()
            now = time.time()
            for aid, agent in data.get("agents", {}).items():
                if agent.get("schedule_type") != "cron": continue
                interval = int(agent.get("schedule_interval", 3600))
                last_run = agent.get("last_run", 0)
                if agent.get("status") == "active" and now - last_run >= interval:
                    print(f"⏰ Agent {agent['name']} 定时触发")
                    run_agent(aid)
            time.sleep(30)
        except Exception as e:
            print(f"Scheduler error: {e}")
            time.sleep(30)

def run_agent(agent_id):
    data = load_agents()
    agent = data["agents"].get(agent_id)
    if not agent: return None
    wf = agent.get("workflow", {})
    nodes = wf.get("nodes", [])
    conns = wf.get("conns", [])
    if not nodes: return None

    task_id = str(data["next_task_id"])
    data["next_task_id"] += 1
    task = {
        "id": task_id, "agent_id": agent_id, "agent_name": agent["name"],
        "status": "running", "started_at": time.time(), "finished_at": None,
        "results": [], "review": None
    }
    data["tasks"][task_id] = task
    data["agents"][agent_id]["last_run"] = time.time()
    data["agents"][agent_id]["last_task_id"] = task_id
    save_agents(data)

    try:
        results = execute_workflow(nodes, conns)
        data = load_agents()
        if task_id in data["tasks"]:
            data["tasks"][task_id]["status"] = "pending_review"
            data["tasks"][task_id]["finished_at"] = time.time()
            data["tasks"][task_id]["results"] = results
            save_agents(data)
        return task_id
    except Exception as e:
        data = load_agents()
        if task_id in data["tasks"]:
            data["tasks"][task_id]["status"] = "error"
            data["tasks"][task_id]["finished_at"] = time.time()
            data["tasks"][task_id]["results"] = [{"name": "system", "output": None, "error": str(e)}]
            save_agents(data)
        return None


# ===== Persona =====
SOUL_FILE = os.path.expanduser("~/.hermes/SOUL.md")

def read_persona():
    try:
        with open(SOUL_FILE, "r") as f:
            return {"content": f.read(), "path": SOUL_FILE}
    except:
        return {"content": "", "path": SOUL_FILE}

def save_persona(content):
    try:
        with open(SOUL_FILE, "w") as f:
            f.write(content)
        return True
    except:
        return False

class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            return self._serve_html()
        elif self.path.startswith("/v1/") or self.path == "/health":
            return self._proxy("GET", self.path)
        elif self.path.startswith("/api/skills"):
            qs = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(qs)
            name = params.get("name", [None])[0]
            if name:
                skill = read_skill(name)
                self._json(200, skill) if skill else self._json(404, {"error": "not found"})
            else:
                self._json(200, {"skills": list_skills()})
        elif self.path.startswith("/api/memory"):
            self._json(200, {"facts": list_memory()})
        elif self.path.startswith("/api/persona"):
            self._json(200, read_persona())
        elif self.path.startswith("/api/tools"):
            self._json(200, {"toolsets": TOOLSETS})
        elif self.path.startswith("/api/agents"):
            data = load_agents()
            self._json(200, data)
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith("/v1/"):
            return self._proxy("POST", self.path)
        elif self.path == "/api/agents/create":
            body = json.loads(self._read_body())
            data = load_agents()
            aid = str(data["next_id"]); data["next_id"] += 1
            data["agents"][aid] = {
                "id": aid, "name": body.get("name", "新员工"),
                "role": body.get("role", "worker"),
                "workflow": body.get("workflow", {}),
                "schedule_type": body.get("schedule_type", "manual"),
                "schedule_interval": int(body.get("schedule_interval", 3600)),
                "status": "active", "created_at": time.time(),
                "last_run": 0, "last_task_id": None
            }
            save_agents(data)
            self._json(200, {"ok": True, "agent": data["agents"][aid]})
        elif self.path == "/api/agents/update":
            body = json.loads(self._read_body())
            data = load_agents()
            aid = body.get("id")
            if aid and aid in data["agents"]:
                for k in ["name","role","workflow","schedule_type","schedule_interval","status"]:
                    if k in body: data["agents"][aid][k] = body[k]
                save_agents(data)
                self._json(200, {"ok": True})
            else:
                self._json(404, {"error": "not found"})
        elif self.path == "/api/agents/delete":
            body = json.loads(self._read_body())
            data = load_agents()
            aid = body.get("id")
            if aid and aid in data["agents"]:
                del data["agents"][aid]
                # Also delete related tasks
                data["tasks"] = {k:v for k,v in data["tasks"].items() if v.get("agent_id") != aid}
                save_agents(data)
                self._json(200, {"ok": True})
            else:
                self._json(404, {"error": "not found"})
        elif self.path == "/api/agents/run":
            body = json.loads(self._read_body())
            aid = body.get("id")
            if aid:
                task_id = run_agent(aid)
                self._json(200, {"ok": True, "task_id": task_id} if task_id else {"ok": False, "error": "execution failed"})
            else:
                self._json(400, {"error": "id required"})
        elif self.path == "/api/tasks/review":
            body = json.loads(self._read_body())
            data = load_agents()
            tid = body.get("id")
            if tid and tid in data["tasks"]:
                data["tasks"][tid]["status"] = body.get("approved") and "archived" or "rejected"
                data["tasks"][tid]["review"] = {
                    "reviewed_by": body.get("reviewer", "admin"),
                    "approved": body.get("approved", False),
                    "note": body.get("note", ""),
                    "reviewed_at": time.time()
                }
                save_agents(data)
                self._json(200, {"ok": True})
            else:
                self._json(404, {"error": "not found"})
        elif self.path.startswith("/api/skills"):
            body = self._read_body()
            data = json.loads(body)
            name = data.get("name"); content = data.get("content")
            if name and content:
                self._json(200 if save_skill(name, content) else 404, {"ok": True})
            else:
                self._json(400, {"error": "name and content required"})
        elif self.path.startswith("/api/memory"):
            body = self._read_body()
            data = json.loads(body)
            fid = data.get("fact_id"); content = data.get("content")
            if fid is not None and content is not None:
                self._json(200 if update_memory(int(fid), content) else 404, {"ok": True})
            else:
                self._json(400, {"error": "fact_id and content required"})
        elif self.path.startswith("/api/persona"):
            body = self._read_body()
            data = json.loads(body)
            content = data.get("content", "")
            self._json(200 if save_persona(content) else 500, {"ok": True})
        elif self.path == "/api/test-conn":
            body = self._read_body()
            data = json.loads(body)
            url = data.get("url", API_URL); key = data.get("key", API_KEY)
            try:
                req = urllib.request.Request(f"{url}/health")
                if key: req.add_header("Authorization", f"Bearer {key}")
                urllib.request.urlopen(req, timeout=5)
                self._json(200, {"ok": True})
            except Exception as e:
                self._json(200, {"ok": False, "error": str(e)})
        elif self.path == "/api/wf-execute":
            body = self._read_body()
            data = json.loads(body)
            action = data.get("action", "")
            params = data.get("params", {})
            context = data.get("context", "")
            try:
                if action == "search":
                    q = params.get("query") or context.strip() or "最新新闻"
                    output = direct_search(q)
                elif action == "extract":
                    url = params.get("url") or context.strip()
                    output = direct_extract(url) if url else "(无URL)"
                elif action == "write":
                    fp = os.path.expanduser(params.get("filepath", "~/hermes_output.txt"))
                    os.makedirs(os.path.dirname(fp) or ".", exist_ok=True)
                    with open(fp, "w") as f:
                        f.write(context)
                    output = f"已写入文件：{fp}（{len(context)} 字符）"
                elif action == "terminal":
                    import subprocess
                    cmd = params.get("command", "echo {{input}}").replace("{{input}}", context)
                    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, cwd=os.path.expanduser("~"))
                    output = r.stdout + ("\n" + r.stderr if r.stderr else "")
                else:
                    output = f"(未知动作类型: {action})"
                self._json(200, {"ok": True, "output": output})
            except Exception as e:
                self._json(200, {"ok": False, "error": str(e)})
        elif self.path == "/api/upload":
            content_type = self.headers.get('Content-Type', '')
            if 'multipart/form-data' not in content_type:
                self._json(400, {"ok": False, "error": "multipart required"})
                return
            import cgi, tempfile, io
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={'REQUEST_METHOD': 'POST', 'CONTENT_TYPE': content_type})
            item = form['file']
            if not item or not item.filename:
                self._json(400, {"ok": False, "error": "no file"})
                return
            upload_dir = os.path.expanduser("~/hermes_uploads")
            os.makedirs(upload_dir, exist_ok=True)
            fpath = os.path.join(upload_dir, item.filename)
            with open(fpath, 'wb') as f:
                f.write(item.file.read())
            self._json(200, {"ok": True, "path": fpath, "name": item.filename})
        else:
            self._json(404, {})

    def do_DELETE(self):
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        if self.path.startswith("/api/skills"):
            name = params.get("name", [None])[0]
            self._json(200 if name and delete_skill(name) else 404, {"ok": bool(name)})
        elif self.path.startswith("/api/memory"):
            fid = params.get("id", [None])[0]
            self._json(200 if fid and delete_memory(int(fid)) else 404, {"ok": bool(fid)})
        else:
            self._json(404, {})

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def _serve_html(self):
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
        with open(HTML_FILE, "rb") as f: self.wfile.write(f.read())

    def _json(self, code, data):
        self.send_response(code); self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length > 0 else "{}"

    def _proxy(self, method, path):
        try:
            body = None
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len > 0: body = self.rfile.read(content_len)
            url = f"{API_URL}{path}"
            req = urllib.request.Request(url, data=body, method=method)
            req.add_header("Authorization", f"Bearer {API_KEY}")
            req.add_header("Content-Type", self.headers.get("Content-Type", "application/json"))
            resp = urllib.request.urlopen(req)
            self.send_response(resp.status)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
            if resp.headers.get("Transfer-Encoding"): self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while True:
                chunk = resp.read(8192)
                if not chunk: break
                self.wfile.write(chunk); self.wfile.flush()
        except Exception as e:
            self.send_response(502)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

if __name__ == "__main__":
    # Start scheduler thread
    sched = threading.Thread(target=scheduler_loop, daemon=True)
    sched.start()
    server = http.server.HTTPServer(("127.0.0.1", PORT), ProxyHandler)
    print(f"🐱 Hermes Chat → http://localhost:{PORT}")
    print(f"   代理 → {API_URL} | 数字员工引擎已启动")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 已退出")
