#!/usr/bin/env python3
"""Run additional atomicity differentials in a temporary engine copy."""
import argparse
from pathlib import Path
import shutil
import os
import subprocess
from tempfile import TemporaryDirectory

from capture_dataset import file_hash
from research_bursty_optimizer import dump
from research_recovery_economics import verify_build,ROOT


def verify(build,output):
    if output.exists():raise ValueError('preserve existing evidence; use a new output')
    report=verify_build(build);output.mkdir()
    source=ROOT/'scripts/research_engine/extra_tests/atomic_projection_test.go'
    shutil.copyfile(source,output/'atomic_projection_test.go')
    protocol=dict(build=str(build.resolve()),build_sha256=file_hash(build/'build.json'),
        test_source_sha256=file_hash(source),verifier_source_sha256=file_hash(Path(__file__)),
        rule='Add three tests to a temporary copy only; preserve production and frozen isolated modules',
        production_approved=False)
    dump(output/'protocol.json',protocol)
    with TemporaryDirectory(prefix='fuse-projection-atomicity-') as temp:
        module=Path(temp)/'engine';shutil.copytree(build/'engine',module)
        shutil.copyfile(source,module/'internal/engine/atomic_projection_test.go')
        env=dict(os.environ,GOCACHE='/private/tmp/fuse-go-cache')
        with (output/'go-tests.txt').open('x') as log:
            subprocess.run([report['go'],'test','-race','./internal/engine','-run','^TestResearchExtra','-count=1','-v'],
                cwd=module,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    verify_build(build)
    dump(output/'verification.json',dict(protocol,completed=True,tests=3,race=True,
        tests_sha256=file_hash(output/'go-tests.txt'),original_and_frozen_sources_unchanged=True,
        active_capture_changed=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--build',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();verify(a.build.resolve(),a.output.resolve())
