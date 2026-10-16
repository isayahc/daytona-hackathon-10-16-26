"""Sandbox-side entry point; invoke OpenCode without interpolating user input."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    """Read a private request file, run one turn, and forward JSON events."""
    request = json.loads(Path(sys.argv[1]).read_text())
    command = ['opencode', 'run', '--format', 'json', '--model', request['model']]
    if request.get('session_id'):
        command += ['--session', request['session_id']]
    command += ['--', request['prompt']]
    try:
        result = subprocess.run(command, cwd='/home/daytona/workspace', timeout=request['timeout'], check=False)
        raise SystemExit(result.returncode)
    except subprocess.TimeoutExpired:
        print(json.dumps({'type': 'error', 'error': {'message': 'Agent turn timed out; do not retry external actions blindly'}}))
        raise SystemExit(124)


if __name__ == '__main__':
    main()
