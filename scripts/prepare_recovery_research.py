#!/usr/bin/env python3
"""Build an isolated paper-only fee/recovery research bridge from exact sources.

The production engine tree, old research bridge and active capture stay intact.
No RPC, signature, transaction submission or deployment is performed.
"""
import argparse
import difflib
import json
import os
from pathlib import Path
import shutil
import subprocess

from capture_dataset import file_hash
from research_bursty_optimizer import dump

ROOT=Path(__file__).resolve().parent.parent
TEMPLATES=dict(bridge='scripts/research_engine/fuse-research/main.go',
    bridge_tests='scripts/research_engine/fuse-research/main_test.go',
    projection='scripts/research_engine/engine/research_projection.go',
    tests='scripts/research_engine/engine/research_projection_test.go')


def prepare(output,go=None):
    if output.exists():raise ValueError('preserve previous builds; use a new output')
    if go is None:
        goroot=subprocess.check_output(['go','env','GOROOT'],cwd=ROOT/'engine',text=True).strip()
        go=Path(goroot)/'bin/go'
    go=go.resolve()
    inputs=[p for folder in ('internal','config','testdata','cmd/fuse-research')
            for p in (ROOT/'engine'/folder).rglob('*') if p.is_file()]
    inputs+=[ROOT/'engine/go.mod',ROOT/'engine/go.sum',Path(__file__).resolve()]
    inputs+=[ROOT/name for name in TEMPLATES.values()]
    bindings={str(p.relative_to(ROOT)):file_hash(p) for p in inputs}
    output.mkdir();module=output/'engine';module.mkdir()
    protocol=dict(version='isolated-fee-recovery-bridge-v2',source_sha256=bindings,
        original_engine=str((ROOT/'engine').resolve()),go=str(go),
        go_version=subprocess.check_output([str(go),'version'],text=True).strip(),
        scope='Separate engine copy with one projection helper and bridge replacement. Original module and active capture are not changed. Explicit paper successful-operation projections only.',
        fee_rule='Monotonic fee accrual invokes unchanged localEffect LPVault.ReserveFeeAccrued; same handler as real local effects. Repeated equal fees do not charge twice. Fee reduction/funding and operator-cost accrual are outside this version.',
        production_approved=False)
    dump(output/'protocol.json',protocol)
    shutil.copyfile(Path(__file__),output/'prepare-source.py')
    for folder in ('internal','config','testdata','cmd/fuse-research'):
        shutil.copytree(ROOT/'engine'/folder,module/folder)
    for name in ('go.mod','go.sum'):shutil.copyfile(ROOT/'engine'/name,module/name)
    for key,target in (('bridge','cmd/fuse-research/main.go'),('projection','internal/engine/research_projection.go'),
                       ('tests','internal/engine/research_projection_test.go'),('bridge_tests','cmd/fuse-research/main_test.go')):
        shutil.copyfile(ROOT/TEMPLATES[key],module/target)
    diff=''.join(difflib.unified_diff((ROOT/'engine/cmd/fuse-research/main.go').read_text().splitlines(True),
        (module/'cmd/fuse-research/main.go').read_text().splitlines(True),
        fromfile='original/engine/cmd/fuse-research/main.go',tofile='isolated/engine/cmd/fuse-research/main.go'))
    (output/'bridge-diff.patch').write_text(diff)
    env=dict(os.environ,GOCACHE='/private/tmp/fuse-go-cache')
    tests=[str(go),'test','-race','./internal/engine','./cmd/fuse-research',
           '-run','^Test(Research|RecoveryLPFlowsAndFeeFundingCannotResetLimits|RecoveryRollingBoundaryAndHardFloor|SourceVerifierRecomputesHashes)','-count=1','-v']
    with (output/'go-tests.txt').open('x') as log:subprocess.run(tests,cwd=module,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    with (output/'go-vet.txt').open('x') as log:
        subprocess.run([str(go),'vet','./internal/engine','./cmd/fuse-research'],cwd=module,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    binary=output/'fuse-research-v2'
    subprocess.run([str(go),'build','-o',str(binary),'./cmd/fuse-research'],cwd=module,env=env,check=True)
    for name,digest in bindings.items():
        if file_hash(ROOT/name)!=digest:raise ValueError('original source changed during build: '+name)
    copied={str(p.relative_to(module)):file_hash(p) for p in module.rglob('*') if p.is_file()}
    report=dict(protocol,completed=True,copied_source_sha256=copied,binary_sha256=file_hash(binary),
        bridge_diff_sha256=file_hash(output/'bridge-diff.patch'),tests_sha256=file_hash(output/'go-tests.txt'),
        vet_sha256=file_hash(output/'go-vet.txt'),original_sources_unchanged=True,active_capture_changed=False)
    dump(output/'build.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--go',type=Path);a=p.parse_args();r=prepare(a.output.resolve(),a.go)
    print(json.dumps(dict(completed=r['completed'],binary_sha256=r['binary_sha256'],
        original_sources_unchanged=True,production_approved=False),indent=2))
