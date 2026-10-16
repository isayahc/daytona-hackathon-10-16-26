"""Run the NYC nonprofit planning agent inside Daytona with optional Arize tracing."""
from __future__ import annotations
import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from .runtime import DaytonaOpenCodeRuntime, RuntimeConfig


def main() -> None:
    """Configure the agent, upload optional context, and run one or more turns."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prompt-file', type=Path, action='append', required=True,
                        help='UTF-8 prompt; repeat for sequential turns in the same session')
    parser.add_argument('--context', type=Path, help='Explicit JSON context, e.g. the mock workspace')
    parser.add_argument('--model', default=os.environ.get('OPENCODE_MODEL', ''))
    parser.add_argument('--tracing', choices=['off', 'arize', 'phoenix'],
                        default=os.environ.get('AGENT_TRACING', 'off'))
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    prompts = [path.read_text(encoding='utf-8') for path in args.prompt_file]
    if any(not prompt.strip() for prompt in prompts):
        raise ValueError('Prompt files cannot be empty')
    config = RuntimeConfig(args.model, args.tracing, args.timeout, os.environ.get('DAYTONA_SNAPSHOT') or None)
    with DaytonaOpenCodeRuntime(config) as runtime:
        if args.context:
            runtime.upload_context(args.context)
        for prompt in prompts:
            result = runtime.run(prompt)
            print(json.dumps(asdict(result)), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error) if isinstance(error, ValueError) else
              f'Agent runtime failed ({type(error).__name__}); check private Daytona logs and sandbox cleanup.',
              file=sys.stderr)
        sys.exit(1)
