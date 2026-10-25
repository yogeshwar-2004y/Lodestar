# Internal health score

The health score is an **internal diagnostic**. It is not a Google metric and does not predict
rankings.

* Start at 100.
* For each rule with affected pages: subtract `severity_points × rule_weight × coverage`
  where severity points are critical 25, high 12, medium 6, low 2, info 0, and
  `coverage = min(1, sqrt(affected_pages / crawled_pages))`.
* Heuristic rules (opportunities, e.g. thin content, length ranges) count 50%.
* Category scores apply the same penalties ×2.5 within their category.
* Clamp to 0–100. The per-rule penalties are stored in `sites.health_breakdown` and shown in the UI.

Deterministic rules (verifiable defects) and heuristic rules are listed in
`apps/api/aseo/rules/engine.py` and the `seo_rules` table.
