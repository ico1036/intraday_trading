---
name: research
description: Conduct keyword-based research for a new alpha topic and produce a durable note in research/notes/. Invoke before implementing a new strategy when no existing note covers the topic.
---

# Research skill

Goal: ground every alpha attempt in external sources before code is written.
Output: a single `research/notes/<topic>.md` file plus an index update.

## When to invoke

- Before implementing a new alpha whose intended cell vector or idea family is
  not already covered by an existing `research/notes/*.md`.
- Skip and reuse the existing note if the planned idea_family already has one.

## Inputs

- `topic` slug (snake_case): e.g. `vpin_crypto`, `kyle_lambda_intraday`
- short hypothesis sentence

## Steps

1. **Read existing notes** — `research/index.csv` plus any related notes. If a
   prior note covers the topic, return its path and stop.
2. **Search** with WebSearch (3–5 queries):
   - one academic-leaning query (e.g. `"VPIN" crypto futures intraday alpha`)
   - one practitioner query (e.g. `crypto orderflow strategy backtest 2025`)
   - one community query (e.g. `reddit algotrading CVD divergence reversal`)
3. **Fetch** with WebFetch:
   - 1–2 academic sources (arxiv / ssrn / jstor)
   - 1–2 practitioner or exchange-research pages
   - 0–1 community thread (treat as hypothesis source only)
4. **Theory check** with `/market-microstructure` if the topic touches Kyle,
   Glosten-Milgrom, VPIN, bid-ask spread, or related microstructure concepts.
5. **Synthesize** into `research/notes/<topic>.md` using
   `research/notes/_template.md` schema. Required fields:
   - `hypothesis`: one sentence
   - `data_required`: which `panel` / `manifest` / bar fields are needed
   - `applicability`: explicit yes/no/conditional given our 7-symbol crypto
     1m bars and 0.20% taker fee
   - `## Sources`: minimum 2 sources, each with category tag, URL, access date
   - `## Mechanism`: 3–5 sentences explaining the signal's information content
   - `## Verdict`: actionable recommendation
6. **Append** one row to `research/index.csv`:
   `<topic>,open,<sources_count>,,<today>`
7. **Return** the absolute path of the new note.

## Source whitelist

See `research/README.md`. Forbidden: anonymous Telegram signals, paid YouTube
ads, vendor sales pages.

## Saturation guard

Before doing the full search, check whether the intended cell vector
`(bar, transform, horizon, universe, exit, idea_family)` is saturated by
running:

```
uv run python scripts/governance/check.py --only coverage --json
```

If saturated, do not produce a new note for that cell — pick a different cell
first.

## Anti-pattern

Do not write a note that simply paraphrases an existing one with a different
parameter setting. Each note represents a distinct mechanism, not a parameter
variant.
