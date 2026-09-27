# QA log

QA only; not reported in results.md (SPEC §8). Window 2020–2024, outliers dropped; ± 90% MOE.

## Out-of-state residents in the universe

| Group | Records | Workers | Weighted wages (earnings) | Below floor | Gap |
|---|---:|---:|---:|---:|---:|
| Mississippi residents | 136 | 3,658 ± 610 | $311.7M ± $68.1M | 785 ± 277 | $11.6M ± $5.0M |
| Other-state residents (not LA or MS) | 77 | 1,926 ± 508 | $193.1M ± $77.6M | 641 ± 328 | $8.3M ± $4.6M |

## Outlier drops

Hourly wage < $2 or > $500: 54 records, 931 ± 298 weighted workers, dropped from every table except the outliers-included sensitivity.

## Self-employed and unpaid family workers

Excluded from the gap (SPEC §4), place of work Orleans: 23,198 ± 1,526 weighted.

## Crosswalk coverage

455 distinct (COW, NAICSP) pairs in the universe (outliers included), all mapped to exactly one BEA line (455 crosswalk rows; `apply_crosswalk` raises on any missing or duplicate pair).

## GOS method validation

Louisiana: max |SAGDP2 − SAGDP4 − SAGDP3 − SAGDP7| over line 1 and the 20 industry lines, 2020–2024: $49,000 (tolerance $500,000).

## Industry-years with suppressed BEA cells

| Line | Industry | Year | GDP suppressed | Compensation suppressed |
|---|---:|---:|---:|---:|
| 3 | Agriculture, forestry, fishing and hunting | 2024 | False | True |
| 6 | Mining, quarrying, and oil and gas extraction | 2024 | False | True |

## Families with more than 3 children

Capped at 3 for MIT typing: 87 universe records, 2,464 ± 627 weighted workers.

## Workers under 18

59 universe records, 1,194 ± 327 weighted workers. The MIT typing (Decision 1) counts them as children in their parents' family unit, so table 6 compares them with that family's threshold rather than a single adult's (the headline floor applies to everyone).
