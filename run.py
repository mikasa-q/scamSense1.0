import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
VENV = ROOT / '.venv'
PY = VENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
FRONT = ROOT / 'frontend'

def run(args, cwd=ROOT):
    subprocess.run([str(a) for a in args], cwd=cwd, check=True)

def main():
    parser = argparse.ArgumentParser(description='ScamSense 本地训练服务')
    parser.add_argument('--setup', action='store_true', help='安装项目依赖、构建前端，然后启动本地服务')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if args.setup:
        if sys.version_info < (3, 11):
            parser.exit(1, '需要 Python 3.11 或更高版本，推荐 3.13。\n')
        npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
        if not npm:
            parser.exit(1, '需要先安装 Node.js 22.12 或更高版本（含 npm）。\n')
        if not PY.exists():
            run([sys.executable, '-m', 'venv', VENV])
        run([PY, '-m', 'pip', 'install', '-r', 'requirements.txt'])
        run([npm, 'ci' if (FRONT / 'package-lock.json').exists() else 'install', '--ignore-scripts', '--no-audit', '--no-fund'], FRONT)
        run([npm, 'run', 'build'], FRONT)
    if not PY.exists() or not (FRONT / 'dist/index.html').exists():
        parser.exit(1, '尚未准备好本地依赖或前端产物。首次运行请使用 run.py --setup。\n')
    run([PY, '-m', 'alembic', 'upgrade', 'head'])
    print(f'ScamSense: http://127.0.0.1:{args.port}  (Ctrl+C 停止)', flush=True)
    try:
        run([PY, '-m', 'uvicorn', 'backend.main:create_app', '--factory', '--host', '127.0.0.1', '--port', args.port, '--no-access-log'])
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
