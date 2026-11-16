"""Run only on GitHub-hosted Actions runners; no provider credentials needed."""
import json
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request

image, app = sys.argv[1:]
repos = {'jugo': 'JUGO', 'naturalgrounding': 'NaturalGrounding-Tiktok-Ying-Video-Manager', 'napoleon': 'NAPOLEON_HILLS_AI_MASTERMIND_CLASSES'}
root = '/opt/safrano9999/' + repos[app]
name = 'standalone-smoke'
volume = 'standalone-smoke-data'
subprocess.run(['docker', 'volume', 'create', volume], check=True)
env = {'FASTAPI_HOST': '0.0.0.0', 'JUGO_PORT': '8080', 'USE_TMUX': 'false', 'TMUX_SHELL': 'false',
       'JUGO_TMUX_SESSION_PREFIX': 'jugo', 'JUGO_DB_BACKEND': 'sqlite', 'NAPOLEON_PORT': '8080',
       'NAPOLEON_DB_BACKEND': 'sqlite', 'NATURALGROUNDING_PORT': '8080',
       'NATURALGROUNDING_DB_BACKEND': 'sqlite', 'NATURALGROUNDING_DJANGO_SECRET_KEY': secrets.token_urlsafe(48)}
if app == 'jugo':
    env['JUGO_OPENAI_V1_DEFAULT_LLM'] = 'default'
    env['OPENAI_V1_URL'] = 'http://127.0.0.1:9/v1'
cmd = ['docker', 'run', '-d', '--name', name, '-p', '127.0.0.1::8080', '-v', volume + ':' + root + '/sqlite']
for key, value in env.items(): cmd += ['-e', key + '=' + value]
cmd.append(image)
path = '/healthz' if app == 'naturalgrounding' else '/'

def ready():
    port = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]['NetworkSettings']['Ports']['8080/tcp'][0]['HostPort']
    last = None
    for _ in range(90):
        try:
            with urllib.request.urlopen('http://127.0.0.1:' + port + path, timeout=3) as response:
                body = response.read()
                assert response.status == 200 and body
                return
        except Exception as exc:
            last = exc
            if subprocess.check_output(['docker', 'inspect', '-f', '{{.State.Running}}', name], text=True).strip() != 'true': break
            time.sleep(1)
    raise RuntimeError(f'Application failed to start: {last}')

try:
    subprocess.run(cmd, check=True)
    ready()
    marker = root + '/sqlite/smoke-persistence'
    subprocess.run(['docker', 'exec', name, 'python3', '-c', 'from pathlib import Path; Path(' + repr(marker) + ').write_text("persistent")'], check=True)
    subprocess.run(['docker', 'restart', name], check=True)
    ready()
    subprocess.run(['docker', 'exec', name, 'python3', '-c', 'from pathlib import Path; assert Path(' + repr(marker) + ').read_text()=="persistent"'], check=True)
    if app == 'jugo':
        subprocess.run(['docker', 'exec', name, 'python3', '-c', "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8080/chat/providers'))['providers']; assert data and data[0]['default_model']=='default' and data[0]['models']==['default'], data"], check=True)
    if app == 'naturalgrounding':
        subprocess.run(['docker', 'exec', name, 'python3', 'manage.py', 'check'], check=True)
    print('Application routes and persistent data survived restart without provider keys.')
except Exception:
    subprocess.run(['docker', 'logs', name])
    raise
finally:
    subprocess.run(['docker', 'rm', '-f', name])
    subprocess.run(['docker', 'volume', 'rm', volume])
