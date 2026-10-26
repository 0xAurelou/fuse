# Payout-dependent barrier pricing

The terminal offers a dropdown for total payout presets **M ∈ {2, 5, 10, 25, 50, 100, 250, 1000, 10000}**. One accepted stage lasts 30 seconds. Its payout is stake × M, including the original stake. This document defines `brownian-first-mode-v1`, the research model used by the Go backend and browser preview.

For entry price P₀, target house edge h and assumed 30-second relative volatility v₃₀, use:

\[
q_* = \frac{1-h}{M},\qquad
w \approx \frac{\pi v_{30}}{\sqrt{8\ln\left(\frac{4M}{\pi(1-h)}\right)}}
\]

\[
\text{Lower} = P_0(1-w),\qquad \text{Upper} = P_0(1+w).
\]

Here v₃₀ is a standard deviation of relative price change across the complete 30-second window. It is **not annualized volatility**, and not a per-second value. If a per-second diffusion coefficient σ is estimated, v₃₀ = σ√30. Holding volatility and edge constant, higher M narrows the corridor; holding M and edge constant, doubling volatility doubles the width. Stake affects payout and underwriting capacity, not the corridor probability.

## Derivation and numerical accuracy

Assume driftless arithmetic Brownian relative price changes, starting at the center of absorbing barriers ±w. Specializing the absorbing-interval survival series in Hartmann and Majumdar, *Physical Review E* 111, 044134 (2025), Appendix C, Eq. C8, gives:

\[
S(w)=\frac4\pi\sum_{n=0}^{\infty}\frac{(-1)^n}{2n+1}
\exp\left[-\frac{(2n+1)^2\pi^2v_{30}^2}{8w^2}\right].
\]

This measures staying within the interval over the entire path, rather than only finishing inside it. [Primary source, Eq. C8](https://journals.aps.org/pre/pdf/10.1103/PhysRevE.111.044134#page=14).

Our pricing choice is to target M × q* = 1 − h. Inverting the first term of this series gives the closed-form width above. This is an approximation, not an exact inverse of the full series. For all supported M ≥ 2 and h ≥ 0, its continuous-model survival error is bounded by the first omitted alternating term:

\[
0 \le q_* - S(w) \le \frac4{3\pi}\left(\frac{\pi q_*}{4}\right)^9
< 0.000095.
\]

That is less than 0.0095 percentage points in survival probability **before quantization**, separate from real-world model error. It slightly increases the model-implied edge relative to the target. The configured edge is a target, not a promised realized result.

## Default research assumptions

The shipped paper/local policies explicitly configure:

```json
"dnt": {
  "rule": "brownian-first-mode-v1",
  "volatility_30s_ppm": 1000,
  "house_edge_bps": 500
}
```

These BTC defaults mean v₃₀ = 0.10% and target h = 5%. The optional ETH and HYPE models use v₃₀ = 0.15% and 0.30% respectively, also with a 5% target edge. Each asset uses its own entry price and model; [Degen mode](DEGEN_MODE.md) does not multiply or combine their payouts. These are visible assumptions, not fitted oracle estimates or approved economic parameters. At the illustrative BTC entry price $68,492.50:

| Payout | Model survival target | Half-width | Lower barrier | Upper barrier |
|---|---:|---:|---:|---:|
| 2× | 47.50% | 11.18575 bps | $68,415.886002 | $68,569.113998 |
| 5× | 19.00% | 8.05315 bps | $68,437.341963 | $68,547.658037 |
| 10× | 9.50% | 6.89444 bps | $68,445.278257 | $68,539.721743 |
| 25× | 3.80% | 5.92712 bps | $68,451.903674 | $68,533.096326 |
| 50× | 1.90% | 5.41661 bps | $68,455.400284 | $68,529.599716 |
| 100× | 0.95% | 5.01873 bps | $68,458.125464 | $68,526.874536 |
| 250× | 0.38% | 4.60633 bps | $68,460.950094 | $68,524.049906 |
| 1,000× | 0.095% | 4.13923 bps | $68,464.149379 | $68,520.850621 |
| 10,000× | 0.0095% | 3.60304 bps | $68,467.821878 | $68,517.178122 |

Only the nine listed presets are selectable. Every preset uses the formula directly; this table is an example, not a pricing lookup table.

## Deterministic implementation

Go and TypeScript use the same Q12 constants, range-reduced atanh logarithm (32 positive terms) and integer square root. Quantize w downward to parts per billion, then compute `delta = floor(P₀ * width_ppb / 1_000_000_000)` in atomic price units. Actual barriers are `P₀ − delta` and `P₀ + delta`. Quantization can narrow the corridor further; extremely small volatility/price combinations can create equal-width adjacent selections. Reject a zero/unrepresentable corridor or an upper price beyond the arithmetic safety envelope. No floating-point money is used.

The model rejects nonpositive volatility, 30-second volatility above 100,000 ppm, edge outside 0–5,000 bps, unknown rules and a widest corridor exceeding `max_width_bps`. These are implementation bounds, not recommended production settings.

Accepted quotes commit the pricing rule, volatility assumption, target edge, target survival, width, exact barriers, selected multiplier and model/policy versions. Policy updates cannot change those accepted terms. Historical `multiplier_widths_ppm` policies still replay, but a policy cannot select both that table and the new formula.

Independent tests compare the integer implementation with a floating-point formula and full survival series across all nine payout presets, verify volatility scaling and monotonicity, and share reference vectors between Go and TypeScript.

## Calibration required for the actual oracle

Continuous Brownian motion is a pricing hypothesis. FUSE resolves **discrete admitted HyperCore oracle observations**, which can have flat periods, jumps, serial dependence and changing volatility. A continuously monitored diffusion probability is not the actual oracle survival probability. Higher multipliers also require more data to validate rare losses/wins and correlated LP liabilities.

Before public-money use, estimate volatility from time-indexed, healthy canonical observations; pin its estimation window, sample/freshness gates and regime policy; then validate realized first-passage survival and net LP returns for each payout on independent prospective data. No automatic volatility estimation or production calibration is claimed here. Update model versions explicitly rather than silently tuning accepted barriers.

## Preset policy compatibility

Current `markets-v5` paper/local policies freeze the nine choices in `multipliers`; other values reject before underwriting. Policies without this field retain their historical 2–100 rules for deterministic journal replay. Reopen an existing journal with its original initial policy, then submit an explicit versioned policy update, or start a separate database. Account and LP liability caps still apply to every high-payout quote.
