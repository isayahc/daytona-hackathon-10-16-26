"""Run the NYC nonprofit planning agent inside Daytona with optional Arize tracing."""
from __future__ import annotations
import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from dotenv import load_dotenv
from .runtime import DaytonaOpenCodeRuntime, RuntimeConfig


def main() -> None:
    """Configure the agent, upload optional context, and run one or more turns."""
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prompt-file', type=Path, action='append', required=True,
                        help='UTF-8 prompt; repeat for sequential turns in the same session')
    parser.add_argument('--context', type=Path, help='Explicit JSON context, e.g. the mock workspace')
    parser.add_argument('--model', default=os.environ.get('OPENCODE_MODEL', ''))
    parser.add_argument('--tracing', choices=['off', 'arize', 'phoenix'],
                        default=os.environ.get('AGENT_TRACING', 'off'))
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--category', choices=['weather', 'climate', 'defense', 'energy'], default='',
                        help='Restrict retrieved source documents to this topic')
    parser.add_argument('--no-document-memory', action='store_true', help='Skip retrieval for this run')
    args = parser.parse_args()
    prompts = [path.read_text(encoding='utf-8') for path in args.prompt_file]
    if any(not prompt.strip() for prompt in prompts):
        raise ValueError('Prompt files cannot be empty')
    config = RuntimeConfig(args.model, args.tracing, args.timeout, os.environ.get('DAYTONA_SNAPSHOT') or None,
                           document_category=args.category, retrieve_documents=not args.no_document_memory)
    with DaytonaOpenCodeRuntime(config) as runtime:
        if args.context:
            runtime.upload_context(args.context)
        for prompt in prompts:
            result = runtime.run(prompt)
            print(json.dumps(asdict(result)), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Keep the traceback and chained ingestion/provider failures actionable.
        import traceback
        traceback.print_exc()
        sys.exit(1)
