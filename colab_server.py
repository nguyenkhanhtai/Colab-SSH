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
from setup_ssh import alias_for
import session_manager
import backup_manager

HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Colab SSH Dashboard</title>
<style>
:root{color-scheme:dark;--bg:#070b14;--surface:#0e1524;--raised:#141d2f;--line:#243049;--text:#f2f5fb;--muted:#8c9ab3;--brand:#7c6cff;--brand2:#4f8cff;--green:#42d392;--red:#ff657a}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(900px 500px at 15% -10%,#25205b55,transparent),var(--bg);color:var(--text);font:14px Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}button,input,select{font:inherit}.shell{max-width:1180px;margin:auto;padding:32px 24px 70px}.topbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:38px}.brand{display:flex;align-items:center;gap:12px}.logo{display:grid;place-items:center;width:40px;height:40px;border-radius:12px;background:linear-gradient(135deg,var(--brand),var(--brand2));font-weight:800;box-shadow:0 10px 30px #6558ff44}.brand h1{font-size:17px;margin:0}.brand p{margin:3px 0 0;color:var(--muted);font-size:12px}.icon-button,.button{border:1px solid var(--line);color:var(--text);background:var(--surface);border-radius:11px;padding:10px 14px;cursor:pointer;transition:.18s ease}.icon-button:hover,.button:hover{border-color:#465574;transform:translateY(-1px)}.hero{display:flex;align-items:end;justify-content:space-between;gap:20px;margin-bottom:24px}.eyebrow{color:#9488ff;text-transform:uppercase;letter-spacing:.14em;font-size:11px;font-weight:700}.hero h2{font-size:34px;letter-spacing:-.04em;margin:8px 0}.hero p{color:var(--muted);margin:0}.create-button{display:flex;align-items:center;gap:9px;background:linear-gradient(135deg,var(--brand),#5b81ff);border:0;padding:12px 17px;box-shadow:0 12px 28px #665dff33;font-weight:700}.plus{font-size:22px;line-height:14px}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:25px 0 36px}.stat{background:#0d1422aa;border:1px solid var(--line);border-radius:15px;padding:17px}.stat span{color:var(--muted);font-size:12px}.stat strong{display:block;font-size:25px;margin-top:7px}.section-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}.section-head h3{font-size:16px;margin:0}.sync{color:var(--muted);font-size:12px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(315px,1fr));gap:16px}.card{position:relative;overflow:hidden;background:linear-gradient(145deg,#111a2b,#0c1320);border:1px solid var(--line);border-radius:17px;padding:20px;box-shadow:0 18px 50px #0003}.card:before{content:"";position:absolute;inset:0 0 auto;height:2px;background:linear-gradient(90deg,var(--brand),transparent)}.card-top,.actions,.meta{display:flex;align-items:center;justify-content:space-between;gap:10px}.card h4{font-size:17px;margin:0}.status{display:flex;align-items:center;gap:7px;color:#79e4b2;font-size:11px;font-weight:700;letter-spacing:.05em}.dot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 10px var(--green)}.meta{justify-content:flex-start;color:var(--muted);margin:18px 0}.chip{background:#172137;border:1px solid #2a3855;border-radius:8px;padding:5px 8px;font-size:12px}.ssh{display:block;background:#090f1a;border:1px solid #1d293f;border-radius:10px;padding:11px;color:#b8c8e7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:10px}.ready{color:var(--muted);font-size:12px;margin:0 0 10px}.progress{height:6px;background:#202b40;border-radius:20px;overflow:hidden;margin:0 0 18px}.progress i{display:block;height:100%;background:linear-gradient(90deg,var(--brand),var(--brand2));border-radius:20px;transition:width .35s}.status.failed{color:#ff92a0}.status.provisioning{color:#a9c4ff}.status.awaiting_authorization{color:#ffd479}.actions{justify-content:flex-start}.button.primary{background:#24345b;border-color:#344b7b}.button.danger{color:#ff92a0;margin-left:auto;background:transparent}.empty{grid-column:1/-1;text-align:center;border:1px dashed #2b3850;border-radius:17px;padding:65px 20px;color:var(--muted)}.empty-icon{font-size:32px;margin-bottom:10px}dialog{width:min(600px,calc(100% - 28px));max-height:90vh;overflow:auto;padding:0;border:1px solid #303d58;border-radius:20px;background:var(--surface);color:var(--text);box-shadow:0 30px 90px #000b}dialog::backdrop{background:#02050bd9;backdrop-filter:blur(5px)}.modal-head,.modal-foot{display:flex;align-items:center;justify-content:space-between;padding:20px 23px;border-bottom:1px solid var(--line)}.modal-head h3{margin:0;font-size:19px}.modal-body{padding:22px 23px}.modal-foot{border:0;border-top:1px solid var(--line);justify-content:flex-end}.close{background:transparent;border:0;color:var(--muted);font-size:24px;cursor:pointer}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:15px}.field{display:grid;gap:7px}.field.full{grid-column:1/-1}.field span{font-size:12px;color:#acb8cc;font-weight:600}.field input,.field select{width:100%;border:1px solid #2b3954;border-radius:10px;padding:11px 12px;background:#0a111e;color:var(--text);outline:none}.field input:focus,.field select:focus{border-color:var(--brand)}.divider{height:1px;background:var(--line);margin:22px 0}.toggle-row{display:flex;align-items:center;justify-content:space-between;gap:15px}.toggle-copy strong{display:block}.toggle-copy small{display:block;color:var(--muted);margin-top:4px}.switch{position:relative;width:46px;height:26px}.switch input{opacity:0}.switch i{position:absolute;inset:0;background:#273248;border-radius:20px;cursor:pointer}.switch i:after{content:"";position:absolute;width:20px;height:20px;left:3px;top:3px;border-radius:50%;background:#fff;transition:.2s}.switch input:checked+i{background:var(--brand)}.switch input:checked+i:after{transform:translateX(20px)}.repo-fields{display:grid;gap:15px;margin-top:19px}.hidden{display:none}.notice{position:fixed;right:22px;bottom:22px;max-width:360px;background:#172238;border:1px solid #354667;border-radius:12px;padding:13px 16px;box-shadow:0 18px 55px #0008;transform:translateY(120px);opacity:0;transition:.25s}.notice.show{transform:none;opacity:1}.notice.error{border-color:#7b3542;color:#ffadb7}.auth-link{display:block;word-break:break-all;color:#a9c4ff;background:#09111f;border:1px solid var(--line);border-radius:10px;padding:12px;margin:16px 0}.auth-link.hidden{display:none}.button:disabled{opacity:.45;cursor:not-allowed;transform:none}.waiting{color:var(--muted);font-size:13px}@media(max-width:650px){.shell{padding:22px 15px}.hero{align-items:flex-start;flex-direction:column}.hero h2{font-size:28px}.stats{grid-template-columns:1fr}.form-grid{grid-template-columns:1fr}.field.full{grid-column:auto}.create-button{width:100%;justify-content:center}}
</style></head><body><main class="shell"><header class="topbar"><div class="brand"><div class="logo">C</div><div><h1>Colab SSH</h1><p>Runtime control plane</p></div></div><button class="icon-button" onclick="load()" title="Refresh sessions">↻ Refresh</button></header><section class="hero"><div><span class="eyebrow">Overview</span><h2>Your Colab runtimes</h2><p>Create, connect and clean up SSH-enabled sessions from one place.</p></div><button class="button create-button" onclick="openCreate()"><span class="plus">+</span> New session</button></section><section class="stats"><div class="stat"><span>Active sessions</span><strong id="activeCount">—</strong></div><div class="stat"><span>SSH ready</span><strong id="readyCount">—</strong></div><div class="stat"><span>Accelerators</span><strong id="gpuCount">—</strong></div></section><div class="section-head"><h3>Running sessions</h3><span class="sync">Auto-refreshes every 15 seconds</span></div><section id="list" class="grid"></section></main>
<dialog id="createDialog"><form id="createForm"><div class="modal-head"><div><h3>Create a new session</h3></div><button class="close" type="button" onclick="closeCreate()" aria-label="Close">×</button></div><div class="modal-body"><div class="form-grid"><label class="field"><span>Session name</span><input name="session" placeholder="Auto-generated if empty"></label><label class="field"><span>Accelerator</span><select name="gpu"><option>T4</option><option>L4</option><option>G4</option><option>A100</option><option>H100</option></select></label></div><div class="divider"></div><div class="toggle-row"><div class="toggle-copy"><strong>Mount Google Drive</strong><small>May require browser authorization for this runtime.</small></div><label class="switch"><input id="mountDrive" type="checkbox"><i></i></label></div><div class="divider"></div><div class="toggle-row"><div class="toggle-copy"><strong>Restore from backup</strong><small>Restore workspace code using a Google Drive backup key.</small></div><label class="switch"><input id="restoreEnabled" type="checkbox"><i></i></label></div><div id="restoreFields" class="repo-fields hidden"><label class="field"><span>Backup key</span><input name="restore_key" id="restoreKey" placeholder="bk-••••••••"></label></div><div class="divider"></div><div class="toggle-row"><div class="toggle-copy"><strong>Initialize from GitHub</strong><small>Clone a repository into the new runtime.</small></div><label class="switch"><input id="repoEnabled" type="checkbox"><i></i></label></div><div id="repoFields" class="repo-fields hidden"><label class="field"><span>Repository URL</span><input name="url" placeholder="https://github.com/OWNER/REPO"></label><div class="form-grid"><label class="field"><span>Branch or tag</span><input name="branch" placeholder="main (optional)"></label><label class="field"><span>Credentials</span><select name="credential" id="credential"><option value="mapped">Saved mapping / public</option><option value="pat">New personal access token</option></select></label></div><label id="patField" class="field hidden"><span>GitHub personal access token</span><input name="pat" type="password" autocomplete="off" placeholder="github_pat_••••••••"></label></div></div><div class="modal-foot"><button type="button" class="button" onclick="closeCreate()">Cancel</button><button class="button create-button" type="submit">Create session</button></div></form></dialog><dialog id="driveDialog"><div class="modal-head"><div><h3>Authorize Google Drive</h3></div></div><div class="modal-body"><p id="driveStatus" class="waiting">Waiting for Colab to request Drive authorization…</p><a id="driveLink" class="auth-link hidden" target="_blank" rel="noopener">Open Google authorization page ↗</a><p>After granting access in the Google page, return here and confirm to continue provisioning.</p></div><div class="modal-foot"><button id="driveConfirm" class="button create-button" type="button" disabled>I’ve granted access</button></div></dialog><dialog id="backupDialog"><div class="modal-head"><div><h3>Backup completed</h3></div><button class="close" type="button" onclick="document.querySelector('#backupDialog').close()" aria-label="Close">×</button></div><div class="modal-body"><p>Your session workspace has been backed up to Google Drive.</p><label class="field"><span>Backup Key</span><input id="backupKeyResult" readonly></label><p id="backupMeta" class="waiting" style="margin-top:10px"></p></div><div class="modal-foot"><button class="button primary" type="button" onclick="navigator.clipboard.writeText(document.querySelector('#backupKeyResult').value);toast('Copied backup key!')">Copy key</button><button class="button" type="button" onclick="document.querySelector('#backupDialog').close()">Close</button></div></dialog><div id="notice" class="notice"></div>
<script>
const E=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])),dlg=document.querySelector('#createDialog'),mountDrive=document.querySelector('#mountDrive'),restoreToggle=document.querySelector('#restoreEnabled'),restoreFields=document.querySelector('#restoreFields'),repoToggle=document.querySelector('#repoEnabled'),repoFields=document.querySelector('#repoFields'),credential=document.querySelector('#credential'),patField=document.querySelector('#patField'),driveDlg=document.querySelector('#driveDialog'),driveLink=document.querySelector('#driveLink'),driveStatus=document.querySelector('#driveStatus'),driveConfirm=document.querySelector('#driveConfirm'),backupDlg=document.querySelector('#backupDialog'),backupKey=document.querySelector('#backupKeyResult'),backupMeta=document.querySelector('#backupMeta');let driveSession=null,driveTimer=null;async function A(p,o){let r=await fetch(p,o),x=await r.json();if(!r.ok)throw Error(x.error||r.statusText);return x}function toast(message,error=false){let n=document.querySelector('#notice');n.textContent=message;n.className='notice show'+(error?' error':'');setTimeout(()=>n.className='notice',4000)}function openCreate(){dlg.showModal()}function closeCreate(){dlg.close()}repoToggle.onchange=()=>repoFields.classList.toggle('hidden',!repoToggle.checked);credential.onchange=()=>patField.classList.toggle('hidden',credential.value!=='pat');
restoreToggle.onchange=()=>{let on=restoreToggle.checked;restoreFields.classList.toggle('hidden',!on);if(on){repoToggle.checked=false;repoFields.classList.add('hidden');repoToggle.disabled=true;mountDrive.checked=true;mountDrive.disabled=true;}else{repoToggle.disabled=false;mountDrive.disabled=false;}};
async function pollDrive(name){driveSession=name;clearTimeout(driveTimer);try{let x=await A('/api/jobs/'+encodeURIComponent(name));if(x.awaiting_drive_authorization){driveStatus.textContent='Authorization is ready. Grant access, then confirm below.';driveLink.href=x.authorization_url;driveLink.classList.remove('hidden');driveConfirm.disabled=false;driveTimer=setTimeout(()=>pollDrive(name),1200);return}driveStatus.textContent='Preparing session: '+x.stage+' · '+x.progress+'%';driveLink.removeAttribute('href');driveLink.classList.add('hidden');driveConfirm.disabled=true;if(x.finished){driveStatus.textContent=x.exit_code===0?'Session is ready.':'Provisioning failed. The Colab runtime is still available without Drive.';setTimeout(()=>driveDlg.close(),1800);toast(x.exit_code===0?'Session is ready':'Google Drive mount failed',x.exit_code!==0);load();return}}catch(e){driveStatus.textContent=e.message;driveConfirm.disabled=true}driveTimer=setTimeout(()=>pollDrive(name),1200)}driveConfirm.onclick=async()=>{driveConfirm.disabled=true;driveStatus.textContent='Checking the granted access…';try{await A('/api/jobs/'+encodeURIComponent(driveSession)+'/drive-confirm',{method:'POST'});driveLink.classList.add('hidden');driveTimer=setTimeout(()=>pollDrive(driveSession),500)}catch(e){driveStatus.textContent=e.message;driveConfirm.disabled=true;driveTimer=setTimeout(()=>pollDrive(driveSession),1200)}};
async function backupS(n){toast('Backing up '+decodeURIComponent(n)+' to Google Drive...');try{let x=await A('/api/sessions/'+n+'/backup',{method:'POST'});backupKey.value=x.key;backupMeta.textContent='Size: '+(x.size_mb||'0')+' MB · '+x.path;backupDlg.showModal();toast('Backup created: '+x.key)}catch(e){toast(e.message,true)}}
async function load(){try{let x=await A('/api/sessions'),sessions=x.sessions,b=document.querySelector('#list');document.querySelector('#activeCount').textContent=sessions.length;document.querySelector('#readyCount').textContent=sessions.filter(s=>s.status==='ready').length;document.querySelector('#gpuCount').textContent=new Set(sessions.map(s=>s.gpu)).size;b.innerHTML=sessions.length?sessions.map(s=>{let label=s.status==='ready'?'READY':s.status==='failed'?'FAILED':s.status==='awaiting_authorization'?'ACTION REQUIRED':'STARTING';return `<article class="card"><div class="card-top"><h4>${E(s.name)}</h4><span class="status ${E(s.status)}"><i class="dot"></i>${label}</span></div><div class="meta"><span class="chip">${E(s.gpu)}</span><span class="chip">${E(s.shape)}</span></div><code class="ssh" title="${E(s.ssh_command)}">${E(s.ssh_command)}</code><p class="ready">${E(s.stage)} · ${Number(s.progress)||0}%</p><div class="progress"><i style="width:${Number(s.progress)||0}%"></i></div><div class="actions">${s.status==='ready'?`<button class="button primary" onclick="notebook('${encodeURIComponent(s.name)}')">Open notebook ↗</button><button class="button" onclick="backupS('${encodeURIComponent(s.name)}')">Backup</button>`:''}<button class="button danger" onclick="stopS('${encodeURIComponent(s.name)}')">Stop</button></div></article>`}).join(''):'<div class="empty"><div class="empty-icon">◇</div><strong>No active sessions</strong><p>Use “+ New session” to launch your first runtime.</p></div>'}catch(e){toast(e.message,true)}}async function stopS(n){if(confirm('Stop this runtime and remove its SSH state?')){try{await A('/api/sessions/'+n,{method:'DELETE'});toast('Session stopped');load()}catch(e){toast(e.message,true)}}}async function notebook(n){try{let x=await A('/api/sessions/'+n+'/url');open(x.url,'_blank','noopener')}catch(e){toast(e.message,true)}}
document.querySelector('#createForm').onsubmit=async e=>{e.preventDefault();let f=Object.fromEntries(new FormData(e.target)),isRestore=restoreToggle.checked,restore_key=isRestore?(f.restore_key||'').trim():'',repository={enabled:!isRestore&&repoToggle.checked};if(repository.enabled){repository.url=f.url;repository.branch=f.branch;repository.credential=f.credential;if(f.credential==='pat')repository.pat=f.pat}try{let wantsDrive=isRestore||mountDrive.checked,x=await A('/api/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session:f.session,gpu:f.gpu,mount_drive:wantsDrive,restore_key,repository})});e.target.reset();restoreToggle.checked=false;restoreFields.classList.add('hidden');repoToggle.disabled=false;mountDrive.disabled=false;repoFields.classList.add('hidden');patField.classList.add('hidden');dlg.close();toast('Creating '+x.session+' in the background');if(wantsDrive){driveStatus.textContent='Waiting for Colab to request Drive authorization…';driveLink.classList.add('hidden');driveConfirm.disabled=true;driveDlg.showModal();pollDrive(x.session)}setTimeout(load,1500)}catch(x){toast(x.message,true)}};dlg.addEventListener('click',e=>{if(e.target===dlg)closeCreate()});load();setInterval(load,15000)
</script></body></html>'''

class App:
    def __init__(self, cli):
        self.cli = cli
        self.logs = Path.home() / '.config/colab-ssh/logs'
        self.logs.mkdir(parents=True, exist_ok=True)
        self.jobs = {}
        self.jobs_lock = threading.Lock()

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
        mount_drive = bool(payload.get('mount_drive', False))
        restore_key = str(payload.get('restore_key') or '').strip()
        if restore_key:
            backup_manager.validate_key(restore_key)
            cmd += ['--restore', restore_key]
            mount_drive = True
        elif not mount_drive:
            cmd.append('--skip-drive')
        repository = payload.get('repository') or {}
        if restore_key and repository.get('enabled'):
            raise ValueError('Cannot initialize from GitHub when restoring from a backup')
        token = ''
        if repository.get('enabled'):
            repo = str(repository.get('url') or '').strip()
            if not repo:
                raise ValueError('GitHub repository URL is required')
            branch = str(repository.get('branch') or '').strip()
            if branch:
                cmd += ['--branch', branch]
            credential = repository.get('credential') or 'mapped'
            if credential == 'pat':
                token = str(repository.get('pat') or '').strip()
                if not token:
                    raise ValueError('GitHub PAT is required')
                cmd.append('--pat-stdin')
            elif credential != 'mapped':
                raise ValueError('Unsupported credential method')
            cmd.append(repo)
        log = (self.logs / f'{name}.log').open('wb')
        needs_input = bool(token) or mount_drive
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE if needs_input else subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        if token:
            process.stdin.write((token + '\n').encode())
            process.stdin.flush()
        token = ''
        if needs_input and not mount_drive:
            process.stdin.close()
        with self.jobs_lock:
            self.jobs[name] = {'process': process, 'log': self.logs / f'{name}.log',
                               'mount_drive': mount_drive, 'confirmed': False, 'gpu': gpu}
        log.close()
        return name

    def backup(self, name):
        session_manager.validate_name(name)
        return backup_manager.backup(self.cli, name)

    def job_status(self, name):
        session_manager.validate_name(name)
        with self.jobs_lock:
            job = self.jobs.get(name)
        if not job:
            raise ValueError('Provisioning job not found')
        try:
            with job['log'].open('rb') as stream:
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - 131072))
                output = stream.read().decode(errors='replace')
        except FileNotFoundError:
            output = ''
        urls = re.findall(r'https://accounts\.google\.com/[^\s]+', output)
        exit_code = job['process'].poll()
        running = exit_code is None
        awaiting = bool(urls and running and not job['confirmed'])
        stages = [
            ('Creating runtime', 8, 'Creating '),
            ('Runtime allocated', 18, 'Session READY.'),
            ('SSH configured', 25, 'SSH:'),
            ('Configuring workspace and GPU', 32, 'Configuring workspace and GPU...'),
            ('Workspace and GPU ready', 44, 'Workspace and GPU ready.'),
            ('Mounting Google Drive', 46, 'Mounting Google Drive...'),
            ('Google Drive mounted', 52, 'Google Drive mounted.'),
            ('Restoring workspace from backup', 54, 'Restoring workspace from backup...'),
            ('Workspace restored', 58, 'Workspace restored from backup.'),
            ('Installing development tools', 60, 'Preparing Codex, Antigravity'),
            ('Development tools ready', 70, 'Environment ready.'),
            ('Syncing agent context', 78, 'Syncing agent context...'),
            ('Agent context synced', 90, 'Agent context synced.'),
            ('Verifying session', 96, 'Verifying session...'),
            ('Ready', 100, 'READY:'),
        ]
        stage, progress = 'Queued', 3
        for label, percent, marker in stages:
            if marker in output:
                stage, progress = label, percent
        status = 'provisioning'
        if awaiting:
            status, stage, progress = 'awaiting_authorization', 'Waiting for Drive authorization', 46
        elif exit_code == 0 or 'READY:' in output:
            status, stage, progress = 'ready', 'Ready', 100
        elif exit_code is not None:
            status, stage, progress = 'failed', 'Provisioning failed', 100
        return {'session': name, 'gpu': job['gpu'], 'running': running,
                'status': status, 'stage': stage, 'progress': progress,
                'awaiting_drive_authorization': awaiting,
                'authorization_url': urls[-1] if awaiting else None,
                'finished': not running, 'exit_code': exit_code}

    def dashboard_sessions(self):
        rows = {item['name']: item for item in session_manager.sessions(cli=self.cli)}
        with self.jobs_lock:
            names = list(self.jobs)
        stale = []
        for name in names:
            job = self.job_status(name)
            if job['finished'] and name not in rows:
                stale.append(name)
                continue
            alias = alias_for(name)
            row = rows.setdefault(name, {
                'name': name, 'gpu': job['gpu'], 'shape': 'Provisioning',
                'ssh_alias': alias, 'ssh_command': f'ssh {alias}',
                'ssh_configured': False, 'last_execution': None,
            })
            row.update({key: job[key] for key in ('status', 'stage', 'progress')})
        if stale:
            with self.jobs_lock:
                for name in stale:
                    self.jobs.pop(name, None)
        for row in rows.values():
            row.setdefault('status', 'ready')
            row.setdefault('stage', 'Ready')
            row.setdefault('progress', 100)
        return sorted(rows.values(), key=lambda item: item['name'])

    def stop(self, name):
        session_manager.validate_name(name)
        with self.jobs_lock:
            job = self.jobs.pop(name, None)
        if job and job['process'].poll() is None:
            try:
                if job['process'].stdin:
                    job['process'].stdin.close()
            except (BrokenPipeError, OSError):
                pass
            job['process'].terminate()
        session_manager.stop(self.cli, name)

    def confirm_drive(self, name):
        session_manager.validate_name(name)
        with self.jobs_lock:
            job = self.jobs.get(name)
            if not job or not job['mount_drive']:
                raise ValueError('Drive authorization is not pending for this session')
            if job['confirmed']:
                return
            if job['process'].poll() is not None:
                raise ValueError('Provisioning process has already finished')
            job['process'].stdin.write(b'\n')
            job['process'].stdin.flush()
            job['process'].stdin.close()
            job['confirmed'] = True


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, value, status=200):
            data=json.dumps(value).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
        def body(self):
            return json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))) or b'{}')
        def do_GET(self):
            path=urlparse(self.path).path
            try:
                if path=='/':
                    data=HTML.encode(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
                elif path=='/api/sessions': self.reply({'sessions':app.dashboard_sessions()})
                elif re.fullmatch(r'/api/sessions/[^/]+/url',path): self.reply({'url':session_manager.notebook_url(app.cli,unquote(path.split('/')[3]))})
                elif re.fullmatch(r'/api/jobs/[^/]+',path): self.reply(app.job_status(unquote(path.split('/')[3])))
                else: self.reply({'error':'Not found'},404)
            except Exception as exc: self.reply({'error':str(exc)},400)
        def validate_origin(self):
            origin = self.headers.get('Origin')
            if origin:
                parsed = urlparse(origin)
                if parsed.hostname not in ('127.0.0.1', 'localhost'):
                    self.reply({'error': 'Cross-origin request forbidden'}, 403)
                    return False
            return True
        def do_POST(self):
            if not self.validate_origin(): return
            try:
                if urlparse(self.path).path=='/api/sessions': self.reply({'session':app.create(self.body())},202)
                elif urlparse(self.path).path=='/api/reconcile': self.reply({'removed':[str(p) for p in session_manager.reconcile(cli=app.cli)]})
                elif re.fullmatch(r'/api/jobs/[^/]+/drive-confirm', urlparse(self.path).path):
                    name = unquote(urlparse(self.path).path.split('/')[3]); app.confirm_drive(name); self.reply({'confirmed': name})
                elif re.fullmatch(r'/api/sessions/[^/]+/backup', urlparse(self.path).path):
                    name = unquote(urlparse(self.path).path.split('/')[3]); self.reply(app.backup(name))
                else: self.reply({'error':'Not found'},404)
            except Exception as exc: self.reply({'error':str(exc)},400)
        def do_DELETE(self):
            if not self.validate_origin(): return
            try:
                match=re.fullmatch(r'/api/sessions/([^/]+)',urlparse(self.path).path)
                if not match: return self.reply({'error':'Not found'},404)
                name=unquote(match.group(1)); app.stop(name); self.reply({'stopped':name})
            except Exception as exc: self.reply({'error':str(exc)},400)
        def log_message(self, *args): pass
    return Handler


def serve(host='127.0.0.1', port=6767, interval=30):
    cli=find_colab_cli()
    if not cli: raise RuntimeError('Colab CLI missing. Install with: uv tool install -e .')
    app=App(cli)
    server=ThreadingHTTPServer((host,port),handler_for(app))
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
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--host',default='127.0.0.1'); parser.add_argument('--port',type=int,default=6767); args=parser.parse_args(argv); serve(args.host,args.port)

if __name__=='__main__': main()
