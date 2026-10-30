# Redemption access during betting pause

30 October 2026 (WITA). **Implemented and locally tested; no deployment or
production activation.** This closes the current-source coupling between the
betting pause and token redemption admission. It does not implement per-bet
funded reward promises or approve a redemption policy.

`RedemptionReserve.openRedemptionEpoch`, `startEpoch` and `requestRedeem` now
work while betting is paused. Scheduling still requires the redemption
scheduler role; starting an authorized window remains permissionless.
Activation, transfer enablement, time bounds, voluntary burn allowance,
snapshot limits and the final-token restriction remain enforced. Claims
were already independent of betting pause and remain so. No new redemption
pause is introduced that could erase an accepted holder's access.

Both explicit and request-triggered starts snapshot actual free backing and
all outstanding supply at the actual start time. Later backing additions
apply to future windows. An old unpaid redemption remains segregated from
new backing. Paying an old claim reduces reserve cash and debt equally, so
it cannot invalidate a later window's free-backing calculation. Failed cash
transfers revert the claim update and preserve its debt for retry. LP capital
cannot consume the segregated reserve.

The new pure capability method `supportsPausedRedemptions()` returns true.
The local `/v1/tokenomics` view checks whether the deployment-pinned ABI
declares that method, and if so reads it at the confirmed block. It reports
paused availability only for a supporting deployment. Older immutable
deployments with no capability keep their legacy pause behavior; a failed
declared capability read returns an error rather than advertising access.

The API retains an exact executable backing ratio only after a snapshot
exists and the activated window is currently open. An authorized unstarted
window can report `start_required: true` when it can start, including during
a supported betting pause. It does not invent a ratio for a snapshot that
has not happened. Actual starts/ends and the underlying confirmed block
remain in the response.

## Verification

Seven new Foundry tests cover paused scheduling, delayed explicit start,
request-triggered start, burns, locked-supply inclusion, claims, unpaid
liabilities crossing windows, duplicate claims, failed transfer retry,
unchanged authorization/window/activation requirements and split requests
across a pause. The split-request property passes 1,000 randomized cases.
The full default contract suite passes **102 tests** with no failures/skips.

A Go RPC-fixture test exercises the complete tokenomics view in eleven
scenarios: legacy/new capability, true/false support, betting pause, missing
snapshot, before/end boundaries, empty backing, disabled activation/transfers,
and unavailable capability reads. Every contract and header read must use
the same confirmed block. The full default Go suite passes. These checks
use local fixtures; no public-chain execution is implied.

Three internal workers covering twelve audit lenses found no concrete new
finding or actionable lead. The [review record](release/redemption-pause-review.json)
binds the reviewed sources and limitations. This is not an independent
external security review. The verification packet at
`.local/release-redemption/20261030-pause-v1/` retains logs and source hashes.

## Remaining release work

Existing immutable deployments require a separately reviewed new deployment
or migration; changing source does not change their behavior. A release
promising redemption through betting pauses must verify the capability,
bytecode and selected window/activation parameters on its actual deployment.
Rehearse the complete user path and display actual claim dates/availability.

The exact funded-dollar reward reservation, accepted minimum, future haircut
constraints, persistent publication/recovery, final residual policy, funded
operating budget and independent reviews remain separate release requirements.
Scheduling authority and external cash-token availability are still real
dependencies; this change is not a promise of instant or unconditional cash.
