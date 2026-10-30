"""Canonicalize a future policy with its exact recorder, without oracle access.

An invalid URL scheme exercises native policy decoding and manifest writing.
The empty probe is software evidence only; it never becomes a market capture.
Only the previously identified omitted integer-zero expansion is accepted.
"""
import json
from pathlib import Path
import subprocess

from capture_dataset import file_hash
from capture_policy_equivalence import compare_policy


ENDPOINT = 'offline-policy-probe://no-network'


def _emit(policy, recorder, evidence):
    evidence.mkdir(mode=0o700)
    source = evidence/'input-policy.json'
    source.write_text(json.dumps(policy, indent=2, allow_nan=False)+'\n')
    capture = evidence/'empty-native-probe'
    command = [str(recorder), '-config', str(source.resolve()),
               '-output', str(capture.resolve()), '-oracle', ENDPOINT,
               '-duration', '1ms']
    with (evidence/'probe.stdout').open('x') as stdout, (evidence/'probe.stderr').open('x') as stderr:
        result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=10)
    # A zero-receipt run intentionally fails the recorder's collection gate.
    # Require its specific terminal reason instead of accepting arbitrary errors.
    if result.returncode != 1 or 'no receipts collected' not in (evidence/'probe.stderr').read_text():
        raise ValueError('empty native policy probe did not reach its expected terminal gate')
    manifest = json.loads((capture/'manifest.json').read_text())
    if ((capture/'receipts.jsonl').stat().st_size != 0 or
            manifest['endpoint'] != ENDPOINT or manifest['duration_ms'] != 1 or
            manifest['production_approved'] is not False):
        raise ValueError('policy probe is not the declared empty offline fixture')
    return manifest, command


def canonical_policy(policy, recorder, evidence):
    recorder = Path(recorder).resolve()
    evidence = Path(evidence)
    if evidence.exists():
        raise ValueError('preserve prior policy probe; choose a new path')
    evidence.mkdir(mode=0o700)
    binary_hash = file_hash(recorder)
    manifest, command = _emit(policy, recorder, evidence/'input-roundtrip')
    canonical = manifest['policy']
    comparison = compare_policy(canonical, policy)
    second, second_command = _emit(canonical, recorder, evidence/'canonical-roundtrip')
    if (second['policy'] != canonical or second['policy_hash'] != manifest['policy_hash'] or
            not compare_policy(second['policy'], canonical)['exact_json_object_match']):
        raise ValueError('native canonical policy is not idempotent')
    if file_hash(recorder) != binary_hash:
        raise ValueError('native recorder changed during policy probe')
    report = dict(version=1, software_only=True, market_observations=0,
        live_capture_started=False, production_approved=False,
        recorder_sha256=binary_hash,
        input_policy_sha256=file_hash(evidence/'input-roundtrip/input-policy.json'),
        manifest_sha256=file_hash(evidence/'input-roundtrip/empty-native-probe/manifest.json'),
        canonical_manifest_sha256=file_hash(evidence/'canonical-roundtrip/empty-native-probe/manifest.json'),
        comparison=comparison, commands=[command, second_command],
        expected_probe_exit_code=1, native_policy_roundtrip_passed=True,
        native_receipt_chain_verification=False,
        policy_rule='Freeze the exact native-emitted JSON before collection; original analyzer retains exact comparison.')
    (evidence/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return canonical, report
