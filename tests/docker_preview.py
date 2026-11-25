"""Check a locally built preview image using disposable containers and a fresh volume."""
import argparse
from contextlib import contextmanager
import json
import re
import subprocess
import time
from urllib.request import ProxyHandler, Request, build_opener


local_http = build_opener(ProxyHandler({}))


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def wait_for_health(container):
    deadline = time.monotonic() + 90
    while True:
        state = docker('inspect', '--format', '{{.State.Status}} {{.State.Health.Status}}', container)
        if state == 'running healthy':
            return
        if state != 'running starting' or time.monotonic() >= deadline:
            subprocess.run(['docker', 'logs', '--tail', '30', container], check=False)
            raise RuntimeError(f'Preview did not become ready: {state}')
        time.sleep(1)


@contextmanager
def preview(image, volume):
    container = docker('run', '--detach', '--health-interval=2s', '--publish', '127.0.0.1::8765',
                       '--mount', f'type=volume,src={volume},dst=/app/data', image)
    try:
        wait_for_health(container)
        assert docker('exec', container, 'id', '-u') == '10001', 'Preview must run as the application user'
        migration = ['exec', container, 'python', '-m', 'alembic']
        heads = docker(*migration, 'heads')
        assert heads and docker(*migration, 'current') == heads, 'Database has not reached the migration head'
        base = 'http://' + docker('port', container, '8765/tcp')
        health = request_json(base + '/api/health')
        assert health['service'] == 'ScamSense' and health['model_configured'] is False
        yield base
    finally:
        docker('rm', '--force', container)


def request_json(url, *, method='GET', token=None, body=None):
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    data = None
    if body is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(body).encode()
    with local_http.open(Request(url, method=method, headers=headers, data=data), timeout=5) as response:
        return json.load(response)


def check_frontend(base):
    with local_http.open(base, timeout=5) as response:
        html = response.read().decode()
    assert '<title>ScamSense' in html, 'Missing production page'
    script = re.search(r'<script\b[^>]*\bsrc="(/assets/[^" ]+\.js)"', html)
    assert script, 'Missing built script reference'
    with local_http.open(base + script[1], timeout=5) as asset:
        assert 'javascript' in asset.headers.get_content_type() and asset.read(1), 'Missing built script'


def verify(image):
    volume = docker('volume', 'create')
    try:
        with preview(image, volume) as base:
            check_frontend(base)
            session = request_json(base + '/api/sessions', method='POST')
            path = '/api/sessions/' + session['id']
            token = session['token']
            decision = {'kind': 'decision', 'choice': 'verify', 'reason': '先核实转发来源。'}
            review = request_json(base + path + '/finish', method='POST', token=token, body=decision)
            assert review['ending']['choice'] == decision['choice'] and review['ending']['reason'] == decision['reason']
            snapshot = request_json(base + path, token=token)
            assert snapshot['closed'] and snapshot['review'] == review
        with preview(image, volume) as base:
            assert request_json(base + path, token=token) == snapshot, 'Archived session changed after replacement'
    finally:
        docker('volume', 'rm', volume)
    print('OK: production assets served; authenticated session and review survived container replacement.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', help='Local preview image tag or ID')
    verify(parser.parse_args().image)
