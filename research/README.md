# Research

Durable research notes that ground every alpha attempt. Each note distills one
topic from external sources into a reusable hypothesis with applicability
checks for our universe and contract.

The research workflow itself lives in the `/research` Claude Code skill
(see `.claude/skills/research/SKILL.md`); this directory only stores the
output.

## Files

- `index.csv` — flat saturation tracker, one row per topic.
- `notes/<topic>.md` — distilled note for a single topic.
- `notes/_template.md` — schema template.

## Note schema

```markdown
---
topic: <slug>
status: open | explored | validated_in_<alpha_id> | refuted_in_<alpha_id>
hypothesis: <one sentence>
data_required: <fields used; e.g. panel.volume_imbalance>
applicability: <does our 7-symbol crypto 1m universe support this?>
date_created: YYYY-MM-DD
last_updated: YYYY-MM-DD
linked_alphas: [is_002, is_006, ...]
---

## Sources

- [academic|practitioner|exchange|community] <citation>
  - URL: <url>
  - Date accessed: YYYY-MM-DD
  - Key: <one-line takeaway>

## Mechanism

3-5 sentences: why does this signal carry information?

## Applicability check

- Required data fields: ✅ / ⚠ / ❌
- Required bar type: TIME / VOLUME / DOLLAR / TICK
- Universe restriction: none | pair | basket
- Fee headroom: minimum per-trade edge needed at our 0.20% taker fee

## Verdict

Whether and how to attempt under our contract.
```

## Source whitelist

| Tier | Sources | Treatment |
|------|---------|-----------|
| academic | arxiv.org, ssrn.com, jstor, NBER, journal articles | full credit |
| practitioner | quantocracy.com, López de Prado writings, EP Chan blog, exchange research desks | full credit |
| exchange | binance research, deribit insights, kraken intel | medium credit |
| community | reddit /r/algotrading, /r/quant, twitter quant accounts | hypothesis source only |
| forbidden | anonymous Telegram signals, paid YouTube ads, vendor sales pages | do not cite |

## Saturation rules

A topic is **saturated** when the same `(bar, transform, horizon, universe, exit, idea_family)` cell vector has been attempted and any one of:

- 1 alpha exists with status `IS_PASS` for that cell, or
- 2+ alphas exist with status `IS_FAIL` for that cell.

The governance `coverage` check refuses new attempts on saturated cells.
