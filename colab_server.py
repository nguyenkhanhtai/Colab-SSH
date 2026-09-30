"""Local web control plane for Colab SSH sessions."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
from urllib.parse import unquote, urlparse

from colab_ssh import find_colab_cli
import session_manager

HTML = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Colab SSH</title>
<style>:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#09111f;color:#e9f1ff;font:15px system-ui}main{max-width:1050px;margin:auto;padding:40px 20px}header,.row{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}.panel,.card{background:#111d31;border:1px solid #263650;border-radius:16px;padding:18px;margin:20px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:16px}.card{margin:0}input,select,button{padding:10px;border-radius:9px;border:1px solid #365070;background:#0b1628;color:#e9f1ff}button{cursor:pointer;background:#18549a}.danger{background:#722b3b}.ok{color:#8fe4b2}code,p{color:#a9bad4}</style></head>
<body><main><header><div><h1>Colab SSH</h1><p>Multi-session control plane</p></div><button onclick="load()">Refresh</button></header>
<form id="create" class="panel"><div class="row"><input name="session" placeholder="session name (optional)"><select name="gpu"><option>T4</option><option>L4</option><option>G4</option><option>A100</option><option>H100</option></select><input name="repo" placeholder="GitHub URL (optional)"><button>Create</button></div><p id="notice">Create runs in the background.</p></form><section id="list" class="grid"></section></main>
<script>const E=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));async function A(p,o){let r=await fetch(p,o),x=await r.json();if(!r.ok)throw Error(x.error||r.statusText);return x}async function load(){try{let x=await A('/api/sessions'),b=document.querySelector('#list');b.innerHTML=x.sessions.length?x.sessions.map(s=>`<article class="card"><div class="row"><h2>${E(s.name)}</h2><b class="ok">RUNNING</b></div><p>${E(s.gpu)} · ${E(s.shape)}</p><code>${E(s.ssh_command)}</code><p>${s.ssh_configured?'SSH ready':'SSH is being prepared'}</p><div class="row"><button onclick="notebook('${encodeURIComponent(s.name)}')">Notebook</button><button class="danger" onclick="stopS('${encodeURIComponent(s.name)}')">Stop & cleanup</button></div></article>`).join(''):'<div class="panel">No active sessions.</div>'}catch(e){document.querySelector('#list').innerHTML='<div class="panel">'+E(e.message)+'</div>'}}async function stopS(n){if(confirm('Stop runtime and remove SSH state?')){await A('/api/sessions/'+n,{method:'DELETE'});load()}}async function notebook(n){let x=await A('/api/sessions/'+n+'/url');open(x.url,'_blank','noopener')}document.querySelector('#create').onsubmit=async e=>{e.preventDefault();try{let x=await A('/api/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});document.querySelector('#notice').textContent='Started '+x.session;setTimeout(load,1500)}catch(x){document.querySelector('#notice').textContent=x.message}};load();setInterval(load,15000)</script></body></html>'''

class App:
    def __init__(self, cli):
        self.cli = cli
        self.logs = Path.home() / '.config/colab-ssh/logs'
        self.logs.mkdir(parents=True, exist_ok=True)

    def create(self, payload):
        gpu = str(payload.get('gpu') or 'T4').upper()
        if gpu not in {'T4', 'L4', 'G4', 'A100', 'H100'}:
            raise ValueError('Unsupported GPU')
        name = str(payload.get('session') or '').strip()
        if not name:
            from datetime import datetime, timezone
            from uuid import uuid4
            name = 'colab-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:6]
        session_manager.validate_name(name)
        if name in session_manager.active_names():
            raise ValueError('Session already exists')
        cmd = [sys.executable, str(Path(__file__).with_name('colab_ssh.py')), '--session', name, '--gpu', gpu]
        repo = str(payload.get('repo') or '').strip()
        if repo:
            cmd.append(repo)
        log = (self.logs / f'{name}.log').open('ab')
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        log.close()
        return name


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, value, status=200):
            data=json.dumps(value).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
        def body(self):
            return json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))) or b'{}')
        def do_GET(self):
            path=urlparse(self.path).path
            try:
                if path=='/':
                    data=HTML.encode(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
                elif path=='/api/sessions': self.reply({'sessions':session_manager.sessions(cli=app.cli)})
                elif re.fullmatch(r'/api/sessions/[^/]+/url',path): self.reply({'url':session_manager.notebook_url(app.cli,unquote(path.split('/')[3]))})
                else: self.reply({'error':'Not found'},404)
            except Exception as exc: self.reply({'error':str(exc)},400)
        def do_POST(self):
            try:
                if urlparse(self.path).path=='/api/sessions': self.reply({'session':app.create(self.body())},202)
                elif urlparse(self.path).path=='/api/reconcile': self.reply({'removed':[str(p) for p in session_manager.reconcile(cli=app.cli)]})
                else: self.reply({'error':'Not found'},404)
            except Exception as exc: self.reply({'error':str(exc)},400)
        def do_DELETE(self):
            try:
                match=re.fullmatch(r'/api/sessions/([^/]+)',urlparse(self.path).path)
                if not match: return self.reply({'error':'Not found'},404)
                name=unquote(match.group(1)); session_manager.stop(app.cli,name); self.reply({'stopped':name})
            except Exception as exc: self.reply({'error':str(exc)},400)
        def log_message(self, *args): pass
    return Handler


def serve(host='127.0.0.1', port=8765, interval=30):
    cli=find_colab_cli()
    if not cli: raise RuntimeError('Colab CLI missing. Install with: uv tool install -e .')
    server=ThreadingHTTPServer((host,port),handler_for(App(cli)))
    def monitor():
        while True:
            try: session_manager.reconcile(cli=app.cli)
            except Exception: pass
            if threading.Event().wait(interval): return
    threading.Thread(target=monitor,daemon=True).start()
    print(f'Colab SSH dashboard: http://{host}:{port}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--host',default='127.0.0.1'); parser.add_argument('--port',type=int,default=8765); args=parser.parse_args(argv); serve(args.host,args.port)

if __name__=='__main__': main()
