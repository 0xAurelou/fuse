# ETH and HYPE volatility opening gate test

This paired test asks whether recent asset volatility can govern admission to a thirty-second corridor. It uses the oracle volatility already available before each entry, with separate ETH/HYPE thresholds. It does not use the Cboe VIX: that index measures thirty-day expected S&P 500 volatility ([Cboe](https://www.cboe.com/tradable-products/volatility-trading/)). The data here supports a realized-volatility gate, not an options-implied volatility index.

The gate uses the existing thirty-second-scaled oracle volatility estimates derived from the preceding sixty-second and five-minute windows. It changes admission while retaining the underlying formula’s widths and flat-oracle/book/risk checks. Existing corridors still settle normally. High volatility is a hypothesis to test, not an assurance that the oracle will keep updating. Since these formulas already scale widths with volatility, a volatility gate only helps pricing if their residual errors depend on that regime.

The mild sixty-second gate illustrates a useful tradeoff for HYPE X100 weekdays: survival falls from 1.861% to 1.551%; total quote availability falls from 67.909% to 56.257%. The stricter Q75 gate reaches 0.955% survival but retains only 21.042% availability. This is a historical comparison, not a threshold recommendation. X1000 remains miscalibrated or too sparse at usable availability.

For the HYPE X100 strict sixty-second gate, the weekday open share is 23.521% and quotes are available on 89.458% of those open entries. This can inform an intermittent-admission product, but does not preserve all-day availability or establish a validated safe regime.

## Frozen policy and comparison

Each UTC midnight, fit exact date-balanced 25th, 50th and 75th percentiles using only matured admissible paths on the last three observed earlier training dates. Test preceding sixty-second volatility and preceding five-minute volatility separately. Early training can use monthly samples; no interpolation fills the intervals. The thresholds and seven gate variants were declared before replay, and no gate is selected from September outcomes.

Two fixed underlying formulas are compared: `active_hybrid` uses the active-state empirical tail at X100 and the native parametric marginal-calibrated tail at X1000; `conditional_recent` uses the previous conditional-tail revision at both payouts. The hybrid was declared before gate replay, after observing that the empirical X1000 model lacked rare-tail support and that the parametric X100 fit regressed. This is outcome-informed development, not an untouched comparison.

The full replay retains fourteen earlier monthly out-of-sample dates and September 1–10, 2026. All rules use the same clean-path denominators. Zero wins on a tiny quote set do not establish calibration. Opening is evaluated on the thirty-second entry grid, without hysteresis, minimum dwell time or execution costs.

## Weekday and weekend results

Targets are 0.950% trader survival at X100 and 0.095% at X1000. The table uses clean oracle paths with fresh strictly prior books. Quote availability remains measured across every eligible entry, including entries when the gate closes.

### ETH X100

| Formula | Gate | Weekday wins / quotes (rate) | Weekday quote availability | Weekend wins / quotes (rate) | Weekend quote availability |
| --- | --- | ---: | ---: | ---: | ---: |
| active_hybrid | No added gate | 58 / 9,312 (0.623%) | 49.210% | 11 / 1,198 (0.918%) | 24.901% |
| active_hybrid | 60s volatility ≥ prior Q25 | 45 / 8,723 (0.516%) | 46.097% | 9 / 1,113 (0.809%) | 23.134% |
| active_hybrid | 60s volatility ≥ prior Q50 | 32 / 7,146 (0.448%) | 37.764% | 5 / 795 (0.629%) | 16.525% |
| active_hybrid | 60s volatility ≥ prior Q75 | 14 / 4,394 (0.319%) | 23.220% | 2 / 387 (0.517%) | 8.044% |
| active_hybrid | 300s volatility ≥ prior Q25 | 48 / 8,823 (0.544%) | 46.626% | 11 / 1,159 (0.949%) | 24.091% |
| active_hybrid | 300s volatility ≥ prior Q50 | 36 / 7,246 (0.497%) | 38.292% | 8 / 871 (0.918%) | 18.104% |
| active_hybrid | 300s volatility ≥ prior Q75 | 19 / 4,730 (0.402%) | 24.996% | 3 / 394 (0.761%) | 8.190% |
| conditional_recent | No added gate | 131 / 9,811 (1.335%) | 51.847% | 5 / 721 (0.693%) | 14.986% |
| conditional_recent | 60s volatility ≥ prior Q25 | 114 / 9,256 (1.232%) | 48.914% | 5 / 697 (0.717%) | 14.488% |
| conditional_recent | 60s volatility ≥ prior Q50 | 82 / 7,718 (1.062%) | 40.786% | 3 / 559 (0.537%) | 11.619% |
| conditional_recent | 60s volatility ≥ prior Q75 | 38 / 4,692 (0.810%) | 24.795% | 2 / 314 (0.637%) | 6.527% |
| conditional_recent | 300s volatility ≥ prior Q25 | 109 / 9,293 (1.173%) | 49.110% | 5 / 711 (0.703%) | 14.779% |
| conditional_recent | 300s volatility ≥ prior Q50 | 80 / 7,897 (1.013%) | 41.732% | 5 / 621 (0.805%) | 12.908% |
| conditional_recent | 300s volatility ≥ prior Q75 | 40 / 5,055 (0.791%) | 26.714% | 4 / 348 (1.149%) | 7.233% |

### ETH X1000

| Formula | Gate | Weekday wins / quotes (rate) | Weekday quote availability | Weekend wins / quotes (rate) | Weekend quote availability |
| --- | --- | ---: | ---: | ---: | ---: |
| active_hybrid | No added gate | 17 / 4,441 (0.383%) | 23.469% | 3 / 450 (0.667%) | 9.354% |
| active_hybrid | 60s volatility ≥ prior Q25 | 17 / 4,366 (0.389%) | 23.072% | 3 / 443 (0.677%) | 9.208% |
| active_hybrid | 60s volatility ≥ prior Q50 | 14 / 3,958 (0.354%) | 20.916% | 2 / 398 (0.503%) | 8.273% |
| active_hybrid | 60s volatility ≥ prior Q75 | 10 / 2,812 (0.356%) | 14.860% | 1 / 245 (0.408%) | 5.092% |
| active_hybrid | 300s volatility ≥ prior Q25 | 17 / 4,402 (0.386%) | 23.263% | 3 / 449 (0.668%) | 9.333% |
| active_hybrid | 300s volatility ≥ prior Q50 | 16 / 4,066 (0.394%) | 21.487% | 3 / 426 (0.704%) | 8.855% |
| active_hybrid | 300s volatility ≥ prior Q75 | 9 / 3,019 (0.298%) | 15.954% | 3 / 294 (1.020%) | 6.111% |
| conditional_recent | No added gate | 1 / 923 (0.108%) | 4.878% | 0 / 153 (0.000%) | 3.180% |
| conditional_recent | 60s volatility ≥ prior Q25 | 1 / 920 (0.109%) | 4.862% | 0 / 152 (0.000%) | 3.159% |
| conditional_recent | 60s volatility ≥ prior Q50 | 1 / 913 (0.110%) | 4.825% | 0 / 146 (0.000%) | 3.035% |
| conditional_recent | 60s volatility ≥ prior Q75 | 1 / 829 (0.121%) | 4.381% | 0 / 110 (0.000%) | 2.286% |
| conditional_recent | 300s volatility ≥ prior Q25 | 1 / 923 (0.108%) | 4.878% | 0 / 153 (0.000%) | 3.180% |
| conditional_recent | 300s volatility ≥ prior Q50 | 1 / 916 (0.109%) | 4.841% | 0 / 153 (0.000%) | 3.180% |
| conditional_recent | 300s volatility ≥ prior Q75 | 1 / 856 (0.117%) | 4.524% | 0 / 145 (0.000%) | 3.014% |

### HYPE X100

| Formula | Gate | Weekday wins / quotes (rate) | Weekday quote availability | Weekend wins / quotes (rate) | Weekend quote availability |
| --- | --- | ---: | ---: | ---: | ---: |
| active_hybrid | No added gate | 239 / 12,845 (1.861%) | 67.909% | 30 / 2,207 (1.359%) | 45.826% |
| active_hybrid | 60s volatility ≥ prior Q25 | 165 / 10,641 (1.551%) | 56.257% | 23 / 1,996 (1.152%) | 41.445% |
| active_hybrid | 60s volatility ≥ prior Q50 | 98 / 7,517 (1.304%) | 39.741% | 12 / 1,498 (0.801%) | 31.105% |
| active_hybrid | 60s volatility ≥ prior Q75 | 38 / 3,980 (0.955%) | 21.042% | 6 / 831 (0.722%) | 17.255% |
| active_hybrid | 300s volatility ≥ prior Q25 | 187 / 10,859 (1.722%) | 57.409% | 23 / 1,965 (1.170%) | 40.801% |
| active_hybrid | 300s volatility ≥ prior Q50 | 92 / 7,429 (1.238%) | 39.276% | 17 / 1,602 (1.061%) | 33.264% |
| active_hybrid | 300s volatility ≥ prior Q75 | 30 / 4,030 (0.744%) | 21.306% | 8 / 952 (0.840%) | 19.767% |
| conditional_recent | No added gate | 115 / 6,134 (1.875%) | 32.429% | 55 / 1,861 (2.955%) | 38.642% |
| conditional_recent | 60s volatility ≥ prior Q25 | 76 / 5,091 (1.493%) | 26.915% | 42 / 1,671 (2.513%) | 34.697% |
| conditional_recent | 60s volatility ≥ prior Q50 | 37 / 3,721 (0.994%) | 19.672% | 23 / 1,255 (1.833%) | 26.059% |
| conditional_recent | 60s volatility ≥ prior Q75 | 14 / 2,214 (0.632%) | 11.705% | 10 / 732 (1.366%) | 15.199% |
| conditional_recent | 300s volatility ≥ prior Q25 | 79 / 5,144 (1.536%) | 27.195% | 41 / 1,617 (2.536%) | 33.576% |
| conditional_recent | 300s volatility ≥ prior Q50 | 29 / 3,604 (0.805%) | 19.054% | 26 / 1,333 (1.950%) | 27.679% |
| conditional_recent | 300s volatility ≥ prior Q75 | 8 / 2,330 (0.343%) | 12.318% | 12 / 834 (1.439%) | 17.317% |

### HYPE X1000

| Formula | Gate | Weekday wins / quotes (rate) | Weekday quote availability | Weekend wins / quotes (rate) | Weekend quote availability |
| --- | --- | ---: | ---: | ---: | ---: |
| active_hybrid | No added gate | 15 / 3,031 (0.495%) | 16.024% | 0 / 198 (0.000%) | 4.111% |
| active_hybrid | 60s volatility ≥ prior Q25 | 11 / 2,710 (0.406%) | 14.327% | 0 / 196 (0.000%) | 4.070% |
| active_hybrid | 60s volatility ≥ prior Q50 | 8 / 2,127 (0.376%) | 11.245% | 0 / 185 (0.000%) | 3.841% |
| active_hybrid | 60s volatility ≥ prior Q75 | 3 / 1,416 (0.212%) | 7.486% | 0 / 139 (0.000%) | 2.886% |
| active_hybrid | 300s volatility ≥ prior Q25 | 11 / 2,755 (0.399%) | 14.565% | 0 / 196 (0.000%) | 4.070% |
| active_hybrid | 300s volatility ≥ prior Q50 | 6 / 2,056 (0.292%) | 10.870% | 0 / 193 (0.000%) | 4.007% |
| active_hybrid | 300s volatility ≥ prior Q75 | 3 / 1,476 (0.203%) | 7.803% | 0 / 179 (0.000%) | 3.717% |
| conditional_recent | No added gate | 7 / 1,111 (0.630%) | 5.874% | 0 / 60 (0.000%) | 1.246% |
| conditional_recent | 60s volatility ≥ prior Q25 | 5 / 976 (0.512%) | 5.160% | 0 / 60 (0.000%) | 1.246% |
| conditional_recent | 60s volatility ≥ prior Q50 | 2 / 699 (0.286%) | 3.695% | 0 / 60 (0.000%) | 1.246% |
| conditional_recent | 60s volatility ≥ prior Q75 | 1 / 434 (0.230%) | 2.294% | 0 / 51 (0.000%) | 1.059% |
| conditional_recent | 300s volatility ≥ prior Q25 | 5 / 995 (0.503%) | 5.260% | 0 / 60 (0.000%) | 1.246% |
| conditional_recent | 300s volatility ≥ prior Q50 | 4 / 618 (0.647%) | 3.267% | 0 / 60 (0.000%) | 1.246% |
| conditional_recent | 300s volatility ≥ prior Q75 | 2 / 382 (0.524%) | 2.020% | 0 / 58 (0.000%) | 1.204% |

## Open share versus quotes while open

Open share is the fraction of clean eligible sampled entries where the volatility gate allows admission. It is not uninterrupted wall-clock uptime. Quotes while open divide accepted quotes by that open count; existing book and risk vetoes can still refuse. These two rates are reported alongside total availability to keep closed periods visible. Values below are for `active_hybrid`; open share is identical for both bases and payouts.

| Asset | Gate | Weekday open share | X100 weekday quotes while open | X1000 weekday quotes while open | Weekend open share | X100 weekend quotes while open | X1000 weekend quotes while open |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ETH | No added gate | 100.000% | 49.210% | 23.469% | 100.000% | 24.901% | 9.354% |
| ETH | 60s volatility ≥ prior Q25 | 83.163% | 55.430% | 27.744% | 49.262% | 46.962% | 18.692% |
| ETH | 60s volatility ≥ prior Q50 | 58.215% | 64.869% | 35.930% | 24.569% | 67.259% | 33.672% |
| ETH | 60s volatility ≥ prior Q75 | 29.477% | 78.774% | 50.412% | 10.102% | 79.630% | 50.412% |
| ETH | 300s volatility ≥ prior Q25 | 85.895% | 54.282% | 27.083% | 47.080% | 51.170% | 19.823% |
| ETH | 300s volatility ≥ prior Q50 | 58.595% | 65.350% | 36.670% | 23.904% | 75.739% | 37.043% |
| ETH | 300s volatility ≥ prior Q75 | 30.069% | 83.128% | 53.058% | 9.042% | 90.575% | 67.586% |
| HYPE | No added gate | 100.000% | 67.909% | 16.024% | 100.000% | 45.826% | 4.111% |
| HYPE | 60s volatility ≥ prior Q25 | 72.038% | 78.093% | 19.888% | 68.937% | 60.120% | 5.904% |
| HYPE | 60s volatility ≥ prior Q50 | 47.232% | 84.139% | 23.808% | 43.169% | 72.054% | 8.899% |
| HYPE | 60s volatility ≥ prior Q75 | 23.521% | 89.458% | 31.827% | 21.553% | 80.058% | 13.391% |
| HYPE | 300s volatility ≥ prior Q25 | 73.804% | 77.787% | 19.735% | 64.120% | 63.633% | 6.347% |
| HYPE | 300s volatility ≥ prior Q50 | 46.291% | 84.845% | 23.481% | 44.539% | 74.685% | 8.998% |
| HYPE | 300s volatility ≥ prior Q75 | 22.934% | 92.900% | 34.025% | 22.716% | 87.020% | 16.362% |

## Earlier monthly comparisons

These fourteen dates span July 2025–August 2026. The initial six monthly dates are fit warmup. They are not a consecutive sample and do not select a cutoff.

| Asset / payout | Formula | Gate | Wins / quotes (rate) | Total quote availability | Worst date availability |
| --- | --- | --- | ---: | ---: | ---: |
| ETH X100 | active_hybrid | No added gate | 133 / 18,426 (0.722%) | 48.034% | 3.035% |
| ETH X100 | active_hybrid | 60s volatility ≥ prior Q25 | 105 / 17,111 (0.614%) | 44.606% | 2.962% |
| ETH X100 | active_hybrid | 60s volatility ≥ prior Q50 | 64 / 14,016 (0.457%) | 36.538% | 2.348% |
| ETH X100 | active_hybrid | 60s volatility ≥ prior Q75 | 32 / 8,992 (0.356%) | 23.441% | 0.795% |
| ETH X100 | active_hybrid | 300s volatility ≥ prior Q25 | 103 / 17,085 (0.603%) | 44.539% | 3.035% |
| ETH X100 | active_hybrid | 300s volatility ≥ prior Q50 | 77 / 14,048 (0.548%) | 36.621% | 1.842% |
| ETH X100 | active_hybrid | 300s volatility ≥ prior Q75 | 46 / 9,457 (0.486%) | 24.653% | 0.361% |
| ETH X100 | conditional_recent | No added gate | 209 / 18,024 (1.160%) | 46.986% | 2.240% |
| ETH X100 | conditional_recent | 60s volatility ≥ prior Q25 | 156 / 16,571 (0.941%) | 43.199% | 2.204% |
| ETH X100 | conditional_recent | 60s volatility ≥ prior Q50 | 101 / 13,681 (0.738%) | 35.665% | 1.951% |
| ETH X100 | conditional_recent | 60s volatility ≥ prior Q75 | 49 / 8,886 (0.551%) | 23.165% | 0.686% |
| ETH X100 | conditional_recent | 300s volatility ≥ prior Q25 | 150 / 16,552 (0.906%) | 43.149% | 2.240% |
| ETH X100 | conditional_recent | 300s volatility ≥ prior Q50 | 94 / 13,736 (0.684%) | 35.808% | 1.481% |
| ETH X100 | conditional_recent | 300s volatility ≥ prior Q75 | 53 / 9,339 (0.568%) | 24.346% | 0.361% |
| ETH X1000 | active_hybrid | No added gate | 9 / 5,672 (0.159%) | 14.786% | 0.036% |
| ETH X1000 | active_hybrid | 60s volatility ≥ prior Q25 | 7 / 5,608 (0.125%) | 14.619% | 0.036% |
| ETH X1000 | active_hybrid | 60s volatility ≥ prior Q50 | 6 / 5,178 (0.116%) | 13.498% | 0.036% |
| ETH X1000 | active_hybrid | 60s volatility ≥ prior Q75 | 0 / 4,134 (0.000%) | 10.777% | 0.036% |
| ETH X1000 | active_hybrid | 300s volatility ≥ prior Q25 | 7 / 5,600 (0.125%) | 14.599% | 0.036% |
| ETH X1000 | active_hybrid | 300s volatility ≥ prior Q50 | 3 / 5,118 (0.059%) | 13.342% | 0.036% |
| ETH X1000 | active_hybrid | 300s volatility ≥ prior Q75 | 0 / 4,153 (0.000%) | 10.826% | 0.036% |
| ETH X1000 | conditional_recent | No added gate | 10 / 6,788 (0.147%) | 17.696% | 0.289% |
| ETH X1000 | conditional_recent | 60s volatility ≥ prior Q25 | 7 / 6,652 (0.105%) | 17.341% | 0.289% |
| ETH X1000 | conditional_recent | 60s volatility ≥ prior Q50 | 5 / 6,231 (0.080%) | 16.243% | 0.289% |
| ETH X1000 | conditional_recent | 60s volatility ≥ prior Q75 | 2 / 5,049 (0.040%) | 13.162% | 0.181% |
| ETH X1000 | conditional_recent | 300s volatility ≥ prior Q25 | 9 / 6,696 (0.134%) | 17.456% | 0.289% |
| ETH X1000 | conditional_recent | 300s volatility ≥ prior Q50 | 5 / 6,226 (0.080%) | 16.230% | 0.289% |
| ETH X1000 | conditional_recent | 300s volatility ≥ prior Q75 | 3 / 5,188 (0.058%) | 13.525% | 0.145% |
| HYPE X100 | active_hybrid | No added gate | 174 / 34,991 (0.497%) | 91.253% | 51.282% |
| HYPE X100 | active_hybrid | 60s volatility ≥ prior Q25 | 88 / 26,443 (0.333%) | 68.961% | 14.758% |
| HYPE X100 | active_hybrid | 60s volatility ≥ prior Q50 | 43 / 18,346 (0.234%) | 47.845% | 3.126% |
| HYPE X100 | active_hybrid | 60s volatility ≥ prior Q75 | 19 / 10,606 (0.179%) | 27.659% | 0.800% |
| HYPE X100 | active_hybrid | 300s volatility ≥ prior Q25 | 85 / 25,678 (0.331%) | 66.966% | 6.834% |
| HYPE X100 | active_hybrid | 300s volatility ≥ prior Q50 | 52 / 18,227 (0.285%) | 47.534% | 1.272% |
| HYPE X100 | active_hybrid | 300s volatility ≥ prior Q75 | 22 / 11,120 (0.198%) | 29.000% | 0.727% |
| HYPE X100 | conditional_recent | No added gate | 387 / 35,319 (1.096%) | 92.108% | 60.166% |
| HYPE X100 | conditional_recent | 60s volatility ≥ prior Q25 | 197 / 26,449 (0.745%) | 68.976% | 14.467% |
| HYPE X100 | conditional_recent | 60s volatility ≥ prior Q50 | 92 / 18,303 (0.503%) | 47.732% | 3.126% |
| HYPE X100 | conditional_recent | 60s volatility ≥ prior Q75 | 38 / 10,593 (0.359%) | 27.626% | 0.800% |
| HYPE X100 | conditional_recent | 300s volatility ≥ prior Q25 | 174 / 25,670 (0.678%) | 66.945% | 6.798% |
| HYPE X100 | conditional_recent | 300s volatility ≥ prior Q50 | 81 / 18,148 (0.446%) | 47.328% | 1.272% |
| HYPE X100 | conditional_recent | 300s volatility ≥ prior Q75 | 32 / 11,093 (0.288%) | 28.929% | 0.727% |
| HYPE X1000 | active_hybrid | No added gate | 32 / 18,070 (0.177%) | 47.125% | 12.062% |
| HYPE X1000 | active_hybrid | 60s volatility ≥ prior Q25 | 19 / 15,424 (0.123%) | 40.224% | 9.960% |
| HYPE X1000 | active_hybrid | 60s volatility ≥ prior Q50 | 9 / 11,500 (0.078%) | 29.991% | 2.363% |
| HYPE X1000 | active_hybrid | 60s volatility ≥ prior Q75 | 5 / 7,399 (0.068%) | 19.296% | 0.654% |
| HYPE X1000 | active_hybrid | 300s volatility ≥ prior Q25 | 14 / 15,071 (0.093%) | 39.304% | 5.053% |
| HYPE X1000 | active_hybrid | 300s volatility ≥ prior Q50 | 9 / 11,284 (0.080%) | 29.428% | 0.872% |
| HYPE X1000 | active_hybrid | 300s volatility ≥ prior Q75 | 5 / 7,586 (0.066%) | 19.784% | 0.582% |
| HYPE X1000 | conditional_recent | No added gate | 22 / 18,093 (0.122%) | 47.185% | 16.601% |
| HYPE X1000 | conditional_recent | 60s volatility ≥ prior Q25 | 15 / 15,912 (0.094%) | 41.497% | 7.415% |
| HYPE X1000 | conditional_recent | 60s volatility ≥ prior Q50 | 6 / 12,094 (0.050%) | 31.540% | 1.672% |
| HYPE X1000 | conditional_recent | 60s volatility ≥ prior Q75 | 3 / 7,848 (0.038%) | 20.467% | 0.436% |
| HYPE X1000 | conditional_recent | 300s volatility ≥ prior Q25 | 11 / 15,647 (0.070%) | 40.806% | 3.780% |
| HYPE X1000 | conditional_recent | 300s volatility ≥ prior Q50 | 7 / 11,965 (0.059%) | 31.204% | 0.654% |
| HYPE X1000 | conditional_recent | 300s volatility ≥ prior Q75 | 1 / 8,111 (0.012%) | 21.153% | 0.436% |

## Screens, evidence and reproducibility

The inherited descriptive screens are unchanged: nonempty quotes every date, at least 85% quote availability every date, pooled survival within 75–125% of target, nonnegative zero-cost gross and at least twenty target-expected evaluated wins. Deliberately closing the protocol changes the product’s availability tradeoff; quotes while open do not satisfy that original all-entry requirement. The complete packet retains daily counts, open exposure, all clean-oracle denominators, refusals, unresolved offers, gross stake arithmetic and screen reasons.

This sample contains only two September weekend dates and repeatedly inspected outcomes. It can measure historical associations and identify bad gates; it cannot ensure future thirty-second survival probabilities or establish that low liquidity causes weekend wins. X1000 tails remain especially sparse. No rule is deployed, and the ongoing fresh recorder remains unchanged.

The audit independently reconstructed 3,760,540 paired gate decisions, refitted all earlier-only thresholds using independent exact weighted quantiles, checked that gating never adds an offer or changes a width, and reconciled every daily/calendar/cohort result. A separate exposure pass independently checked both opening predicates on every row. Thirty-eight regression tests pass across the research stack.

Packet: `/Volumes/dev/fuse/.local/adaptive-corridor/20261029-volatility-open-gate-v1`. Research SHA-256: `631950e1e40a592d6238e125456879eef802a7f8dbc7c1e2bf12f81f45d49f2d`. Audit SHA-256: `bd3d1106cfee59abbf739895c28774d3914ce09a07316443df5715ca8ff851ce`. Exposure SHA-256: `848b9771a2a123aad98b1a72b12a1c0e8bd94d0bf5c5a5fd6075582b85a1aa08`. Complete local sources and input hashes were frozen before gate replay. Underlying formula development is documented in [ACTIVE_TAIL_PAYOUT_RESEARCH.md](/Volumes/dev/fuse/docs/ACTIVE_TAIL_PAYOUT_RESEARCH.md).

```sh
python3 -B scripts/research_volatility_open_gate.py --declare --active .local/adaptive-corridor/20261029-active-tail-payout-v1 --conditional .local/adaptive-corridor/20261029-conditional-tail-payout-v1 --output .local/adaptive-corridor/NEW-VOLATILITY-GATE
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_volatility_open_gate.py --output .local/adaptive-corridor/NEW-VOLATILITY-GATE
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B scripts/research_volatility_open_gate.py --audit --output .local/adaptive-corridor/NEW-VOLATILITY-GATE
python3 -B scripts/report_volatility_open_gate.py --research .local/adaptive-corridor/NEW-VOLATILITY-GATE --output docs/VOLATILITY_OPEN_GATE_RESEARCH.md
PYTHONPATH=scripts OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=1 python3 -B -m unittest scripts.test_historical_liquidity scripts.test_trial_liquidity scripts.test_trial_payout scripts.test_flat_aware_payout scripts.test_flat_risk_overlay scripts.test_active_tail_payout scripts.test_conditional_tail_payout scripts.test_volatility_open_gate
```
