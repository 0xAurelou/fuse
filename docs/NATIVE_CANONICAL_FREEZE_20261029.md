# Native-canonical preparation for future adaptive captures

The separate `scripts/freeze_adaptive_capture_v2.py` prevents the known
omitted-zero policy mismatch in a **future** packet. It does not repair or
replace the running 28 October trial. That trial keeps its original deadline,
original analyzer and expected procedural failure; its separately disclosed
compatibility replay remains the completion path already prepared for it.

The new freezer preserves the archived model selection, numerical analyzer,
health rules, quote denominators and eight-hour horizon. After constructing the
transport policy, `canonical_capture_policy.py` invokes the exact retained
recorder twice against an invalid URL scheme and a one-millisecond horizon.
These empty offline probes cannot supply market observations. The first emits
the native policy; only the previously identified omitted integer-zero fields
may expand. The second confirms exact policy and native policy-hash equality
after reading that canonical JSON. Unknown fields and wrong integer types fail
preparation. The final policy is bound before any root market manifest exists.

Both old and new freezer sources, the strict comparison helper and the new
canonicalization helper are copied into the future packet and hash-bound.
The final policy remains subject to the **unchanged analyzer's exact JSON
comparison**. Preparation does not weaken that comparison or use a supplemental
analyzer. Probe evidence has a separately recorded hash in `freeze.json`.

## Evidence

`.local/capture-readiness/20261029-future-canonical-freeze-v1/` exercises the
actual archived model bundle through the new freezer. A separate copied
fixture has a conspicuous synthetic marker and an artificial historical clock.
The exact original recorder independently verifies its **14,400 synthetic
receipts**. The unchanged original analyzer then processes all **960 windows**
and produces **5,760 prediction records**, with the expected **959 healthy
windows**. No compatibility comparison repair is used. All **285 retained
artifact hashes** were rechecked, and all **110 bound files** of the ongoing
trial still verify unchanged. No live receipt file is opened by this preflight.

Four new native integration tests cover exact roundtrips, unknown fields,
boolean/float rejection, evidence reuse, preparation without a root capture,
analyzer identity and policy-tamper rejection. With the exact recorder and
policy supplied through `FUSE_TEST_RECORDER` and `FUSE_TEST_POLICY`, the full
current workspace suite passes **425 tests with three existing optional
skips**. The larger count includes independently developed workspace tests;
this change adds four tests.

The first empty-probe attempt is retained under
`.local/capture-readiness/20261029-native-canonical-policy-v1/`. Native `-verify`
cannot JSON-encode its zero-receipt head (`json.RawMessage` has no payload).
The revised empty-probe procedure therefore claims policy roundtrip conformance
only. The **nonempty** synthetic end-to-end fixture supplies independent native
receipt-chain verification. The binary and existing trial were not changed to
work around the empty-head encoding limitation.

## Use and limits

For a later, separately justified trial, use the same preparation arguments
with `scripts/freeze_adaptive_capture_v2.py`: `--directory`, `--research`,
`--policy` and `--recorder`. Preparation does not start the live supervisor.
No new live capture was launched for this software check.

This closes a preparation defect, not a pricing hypothesis. Synthetic survival
rates and quality gates provide no real-market calibration, prospective
evidence, economic validation or production approval. It also cannot prevent
lid closure, insufficient physical power or internet loss. The current frozen
candidate remains unvalidated, with known earlier cross-period shortcomings.
