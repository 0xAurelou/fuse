#!/usr/bin/env python3
"""Isolated daily settlement binding rehearsal; never contacts a public chain."""
import argparse
import json
import os
from pathlib import Path

from local_stack import ENGINE, ROOT, Stack, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError('Preserve previous E2E evidence: '+str(output))
    # Never inherit an external database or caller-selected shared network ports.
    for key in ('FUSE_LOCAL_DATABASE_URL', 'FUSE_LOCAL_RPC_PORT', 'FUSE_LOCAL_PG_PORT', 'FUSE_LOCAL_HTTP_PORT'):
        os.environ.pop(key, None)
    stack = Stack(output/'stack', ephemeral=True)
    try:
        stack.up(serve=False)
        env = dict(stack.env, FUSE_DAILY_E2E_RPC=stack.rpc,
                   FUSE_DAILY_E2E_MANIFEST=str(stack.manifest),
                   FUSE_DAILY_E2E_DATABASE=stack.database,
                   FUSE_DAILY_E2E_OUTPUT=str(output/'evidence'))
        transcript = run([stack.go, 'test', '-race', './internal/localdev', '-run',
                          '^TestDailySharedEngineBindingsE2E$', '-count=1', '-v'],
                         cwd=ENGINE, env=env, capture=True)
        (output/'e2e.log').write_text(transcript+'\n')
        print(transcript)
    finally:
        stack.down()
        (output/'services-stopped.json').write_text(json.dumps({'stopped': True, 'public_transactions': False})+'\n')
        print('Evidence retained at '+str(output))


if __name__ == '__main__':
    main()
