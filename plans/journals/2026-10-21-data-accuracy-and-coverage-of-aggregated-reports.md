---
title: Data accuracy and coverage of aggregated reports
date: 2026-10-21
---

# Data accuracy and coverage of aggregated reports

Community digests used to drop messages that did not fit max_chars forever, because the next digest only took items stored after the previous one. Coverage is now tracked by the ids each digest showed Claude (all_item_ids), with old digests without ids covering what was stored before them. Busy channels are filled oldest first so the leftover is the newest and goes into the next digest.

Topic mentions/people are counted by code from Claude-listed related_ids plus reply chains instead of Claude's own count.

Weekly report: dismissed items excluded (also from the overview brief), backlog classified before writing, prompt states shown/total, unclassified count and failing sources, reads the week's community digests; coverage and deadlines tables come from the database.

Classification: platform changes read up to platform_content_chars (4000); every item must come back with area and reason.

Not done yet: feedback buttons, radar eval, data-quality page, keyword-drop sampling.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
