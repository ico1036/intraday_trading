# Proposal: what the harness should take from the five notes, and whether it could have done today's work alone

Written 2026-09-13. Status: draft for the owner. Scope: `intraday_trading`.
Inputs: the five notes at https://ico1036.github.io/notes/ (Deterministic and
Probabilistic; Fat Skill, Thin Multi-Agents; Overfit and Dynamic; Abstraction
Layer, but Think First; Look-Ahead Bias and Path Dependency), a read of the
harness code (listed in section 7), and the 2026-09-12 session in which the
engine gained funding and slippage. The earlier draft
`2026-09-02-hypothesis-market-and-referee.md` is the reference for the
referee and claim-card ideas; this document does not repeat it, it says where
the notes change its priorities.

## 0. Summary

- The harness is four generators. The question assumed one. Only one of them (the markdown
  agent loop) has the shape the notes describe. The composite autoresearch
  loop scores and prompts on out-of-sample Sharpe across 119 iterations, so
  its 135 composites are not holdout evidence. That is the first thing to fix.
- Two gates are documented as doing something they do not do: the
  cell-saturation guard (disabled 2026-05-22, still described as enforced in
  `AGENT.md`, `AUTORESEARCH.md`, `CLAUDE.md`) and the 11-gate classifier
  described in `research/cutoff_analysis.md` (the code now has three gates).
  The notes' own duplicate-gate story applies here word for word.
- The resident procedure is thin. `RESEARCH.md` is section headings with
  empty bodies. Every judgment that mattered today (funding is a cost,
  slippage is a cost, 365 not 252, do not tune on OS, structural fix not
  fine-tuning) was supplied in conversation because nothing resident held it.
- Both look-ahead instruments exist, which I got wrong in the first draft:
  `backtest.py` runs a truncation check on every backtest (a child run to 80%
  of the window, weight events compared at 1e-9), and `integrity_test.py` is
  the start-shift test. The truncation check compares rebalance events rather
  than held books, has no synthetic leaking strategy to prove it fires, emits
  no non-coverage list, and cannot see a leak that lives in the data, which
  is why the placeholder-bar problem got past it. It also doubles every
  backtest's wall time.
- Could today's session have run unattended? About two thirds of it, once
  the checks it produced exist as code. The remaining third was the owner
  choosing which question mattered and when to stop. The notes give a way to
  measure that split instead of asserting it; section 5 designs the test.

## 1. What the harness is today

| Generator | Where | What decides | Trials on disk |
|---|---|---|---|
| Markdown agent loop | `AGENT.md`, `AUTORESEARCH.md`, `CLAUDE.md` | agent writes one strategy file from `_alpha_template.py`; `backtest.py` runs IS; quality gates delete failures | `is_sharpe1_search` 283, `physics_reversion` 5 |
| Queue runner | `scripts/tools/run_alpha_queue.py` | fixed parameter list in `queue.json`; no agent | `tv_100` 100, `tv_100_recent2m` 100, `sharpe1_search` 100 |
| Factor zoo | `scripts/tools/generate_factor_zoo.py`, `scripts/attempt_loop.py` | deterministic grid of signals x concentrations; classifier on IS and OS | 2,362 strategy files, 6 kept on the 641 run |
| Composite autoresearch | `scripts/autoresearch/composite_harness.py`, `prompt_template.md` | `claude` in print mode writes one composite file; harness backtests IS and OS; leaderboard by OS Sharpe | 119 iterations, 135 composite modules |

Around it: `scripts/governance/check.py` (five checks, run by the pre-commit
hook), `scripts/governance/seal_check.py` (a PreToolUse hook that blocks reads
of OS artefacts unless `SEAL_OPEN=1`), `scripts/tools/validate_is_os.py`
(labels drift, never gates), `scripts/tools/integrity_test.py` (start-shift
path test), `research/wiki/alpha_memory.jsonl` (572 rows), `research/notes`
(668 files), and a 3,555-line dashboard.

The 641-symbol point-in-time run, the funding study, the tail filter, and
the cost model in the engine were all produced in conversation, outside every
generator above.

## 2. Audit against the five notes

### 2.1 Deterministic and probabilistic

The note's rule: thresholds, budgets, orchestration and schemas are scripts;
hypothesis, code and narrative are the model. Then check that the scripts do
what their docstrings say.

Where the repo already follows it. Quality gates live in `splits.json` and
are applied by `backtest.py` at write time. The editable surface, universe
consistency and research-note requirement are scripts. The composite runner
strips `os_*` columns before user code sees the index. The OS seal is a hook,
which is a wall rather than a rule, and is better than what the note
describes.

Where it does not.

| Documented | Actual | Evidence |
|---|---|---|
| Cell saturation refuses a repeated six-tuple (`AGENT.md` step 2 and 9, `AUTORESEARCH.md` step 3 and 8, `CLAUDE.md`) | disabled: the signature is computed and discarded | `scripts/tools/backtest.py` around line 392, comment dated 2026-05-22 |
| Eleven standalone gates R1..R4, S1..S7 (`research/cutoff_analysis.md`) | three gates, fee-only: bps > 0, trades > 100, MDD < 0.6 | `alpha_dashboard_lib.classify_alpha` |
| Sharpe annualized (`metrics.py` said sqrt(252)) | daily series has 365 rows a year; every archived Sharpe was low by 1.20 until 2026-09-12 | commit 3182fe1 |
| Fees, slippage and funding are fixed assumptions the agent must not change (`AGENT.md`) | until 2026-09-12 funding was not charged at all and there was no slippage model; `src/intraday/funding.py` existed and nothing called it | commit 3182fe1 |
| Composite selection uses IS only (`_composite_template.py`) | the loop's objective, leaderboard and prompt use OS (section 2.3) | `composite_harness.py:518`, `prompt_template.md` |

The note's diagnosis fits: a gate that quietly does less than its docstring
is worse than no gate, because you stop watching. The saturation guard was
switched off for a reason the owner stated (family labels were too narrow),
but the three documents that promise it were not updated, so a fresh agent
reads a coverage guarantee that does not exist.

The golden engine test (`tests/perf/test_backtest_engine_invariance.py`)
is the right instrument for reproducibility and it did its job today, but
it compares the engine to itself. It cannot see a constant that is wrong in
both the baseline and the code, which is how 252 survived.

### 2.2 Fat skill, thin agents

The note's rule: put accumulated judgment where it is read every time; fan
out only to construct a reader who cannot see what you saw.

The resident procedure here is 176 lines of `AGENT.md` plus 148 lines of
`RESEARCH.md`, of which the second is headings over empty bullets. The note
reports a 24:1 ratio of resident procedure to orchestration and an ablation
where the resident plan alone added 1.4 correct picks out of 10 and the
rejection ledger another 1.0. There is nothing here to ablate yet.

What the fat skill would have to hold, taken from what the owner had to say
today rather than from theory:

- a cost checklist that a number cannot be reported without: taker and maker
  fee, slippage model and its calibration, funding at every settlement,
  delisting handling, survivorship of the universe, annualization basis;
- a read-order rule: re-read the strategy before reading any metric, and
  never read OS while a rule is still being chosen (I read OS around fifty
  times during the filter work; the pre-registration note records it);
- the closed verdict vocabulary the note describes (pinned, expression
  leaky, no story, ceiling or dead), so that "do not tune the failing alpha"
  becomes a state the loop can act on rather than a sentence it can forget;
- the falsifiable-sentence test before a story is allowed to steer: "if this
  were merely X, this number would look different, and it does not". Today's
  version was "if the tail were predictable from clustering, onset cells
  would not carry 82% of the loss";
- the difference between a structural change and a parameter change, stated
  as a rule, because the owner had to draw it in conversation ("that is
  fine-tuning; the goal was the structural funding problem").

Where fan-out is justified by the note's three cases, the repo has none of
them: no verifier that sees the code and the claim but not the reasoning, no
refuter with a fresh context, no web escape for ideas outside the model's
prior. The 09-02 draft's critic pass is the right shape; the note's addition
is that the verifier must be denied the proposer's justification, or it
verifies the justification.

### 2.3 Overfit and dynamic

The note's rule: the durable output of a search is a map; the holdout is a
budget; the map must evaporate; and a fourteen-year fit says nothing about
next year unless someone tests that assumption.

The composite loop is the opposite of the note's design on every point.
`prompt_template.md` opens with "You are scored only by the OS Sharpe from
the actual backtest", the state file keeps a top-10 leaderboard by OS
Sharpe, `update_leaderboard` and `append_log_row` write OS Sharpe, return
and drawdown per attempt, `load_tried_ideas` feeds the last thirty rows of
that log back into the next prompt, and the template itself carries
hand-written OS conclusions ("anti-bias selection goes OS negative", "Gram
Schmidt failed 9 of 9", "top OS Sharpes sit in 0.30 to 0.41"). After 119
iterations the holdout has been queried 116 times with the answers in view.
The note treats 2,900 pass/fail bits against one window as a
multiple-comparison problem; this is 116 full score vectors against one
window. The best composite's OS 0.84 (0.71 after costs on the 641 universe)
is an in-sample number under another name.

On the alpha side there is no map. The cell guard is off, the wiki is an
index the loop does not read, and `alpha_index.csv` records outcomes without
decay. The factor zoo ran 2,000-plus deterministic variants through the same
IS and OS windows with no deflation, which is the note's "greedy search
concentrates" without even the greed.

The note's hardest point, that the map decays over trials while the world
decays over calendar time, has a concrete instance in this repo. Binance
moved symbols from 8-hour to 4-hour and 1-hour funding between 2023-12 and
2026-09 (0% of cells to 77%). That policy change is why the same short book
paid 4.5% a year in funding before and 6 to 13% after, and it is why a
feature that encoded settlement count extrapolated a spurious coefficient
from 23 early rows. Nothing in the harness can represent an event of this
kind. A region cannot cool because the exchange changed its settlement
schedule.

### 2.4 Abstraction layer, but think first

The note's rule: an abstraction earns steering authority only by staking a
prediction on an untried target before the result is known; annexed
explanations get a name and no authority; two misses kill a theory; and the
enforcement is the ordering of writes plus an unreadable scoreboard, nothing
more.

Today's session produced one abstraction that would qualify. Negative
funding is a fat left tail because cash-and-carry caps positive rates and
spot borrow does not exist for alts; onset days carry the loss and
continuation days do not; therefore only a level cut on predicted funding
removes cost without removing the leg. It was pre-registered
(`research/notes/funding_tail_filter_v1_prereg.md`) with outcomes stated
for three and six months, and the engine change that followed had its own
prepaid prediction: overlay funding on the base book was −3,350, the engine
charged −3,370.

The harness has no place to put any of this. `research/notes` are idea
notes, `alpha_memory.jsonl` is a metrics row, and neither has a field for a
falsifier, a predicted signature, or a declared family membership. The
09-02 draft's claim card is the right container. The note adds the rules
that make it more than a form: a name exists only if it stakes a prediction;
a hit counts only if declared before, gated after, and residual-distinct
from existing members; two consecutive misses is a death verdict; the
corpse stays with the reason. Also the honest position, which the draft
lacks: no script can decide whether two economic stories are the same
story, so the ledger will be honour-system prose, and the two things that
make it work are that cards are committed before execution and that the
scoreboard cannot be read.

The note's four diagnostic tests (neutralize the blamed dimension, flip the
sign, change the weighting, cross-channel) are portable. Two of them were
run today without being named: the sign-flip test (would the reverse book
pay funding instead of receiving it) and the cross-channel test (funding
level versus funding change as a signal; only the level had a t-stat above
2 and it was offset by carry). Writing them into the analysis procedure
costs a page.

### 2.5 Look-ahead bias and path dependency

The note's rule: two instruments with each other's blind spots, a
truncation test at tolerance 1e-10 on a union grid and a start-shift test at
a stated band, plus a synthetic strategy whose job is to be caught, plus a
declared non-coverage list.

The repo has both instruments. `_enforce_prefix_invariance` in
`backtest.py` reruns every backtest as a child ending at 80% of the window
and compares weight events up to that cutoff on an outer join at 1e-9, so a
row present in one run and absent in the other counts as a mismatch, which
is the join lesson of the note applied to events rather than to held books.
It runs unconditionally, which is where roughly half of every backtest's
wall time goes, and its verdict is reported but only deletes the artefact
when the quality gate is enforced. `integrity_test.py` is the start-shift
test: two overlapping windows compared after 90 bars of warm-up. What the
pair does not cover is exactly what surfaced today:

- placeholder zero-volume bars after a delisting changed the ranking of
  live names. Both the parent and the child run see the same placeholder
  bars, so a truncation check at fixed data cannot see it; it was found by
  comparing runs on differently prepared data;
- the research feature panel used the same-day settlement count, which is
  not observable at the open; it surfaced only when the filter was
  reimplemented for live trading and the timing had to be written down;
- `AERGOUSDT` had no local data and would have raised at load; the forward
  runner now drops such symbols and `splits.json` declares them.

The feature panel of the filter has its own truncation and no-lookahead
tests (`tests/test_funding_filter.py`) because it is built outside the
engine. What is missing around the two instruments: a linter for negative
shifts, centred windows and backfill; a synthetic leaking strategy in the
test suite whose job is to be caught by the prefix check; a non-coverage
list emitted with the verdict (data-level contamination, uniform
contamination, hand-rolled forward slices); and a comparison of held books
on a union grid rather than rebalance events, which is the form the note
argues for. I did not verify which join `integrity_test.py` uses and list
that in section 7.

## 3. Could today's session have run without the owner?

The session's substantive steps, classified by what decided them.

| Step | Decided by | Would the current harness have done it | With the proposals below |
|---|---|---|---|
| Is the live pipeline running | script check | no job for it; found by hand | yes, a heartbeat check is a script |
| Survivorship: the 273 and 530 universes are biased | owner's question | no; `AGENT.md` forbids data fetching and no check compares the universe to listings | yes, as a universe audit against onboard and delivery dates |
| Build the 641 point-in-time universe and rerun | mechanical once decided | no (forbidden surface) | yes, if universe construction is a sanctioned tool |
| Delisting bugs in the engine (stale bars, placeholder bars) | comparing runs on differently prepared data | the prefix check runs but sees the same data in both runs | partly; a data-preparation audit, not the prefix check, is what catches it |
| Is the strategy deployable with real money | owner's question | the loop never asks; it reports IS Sharpe | partly: the cost checklist forces the question "which costs are missing" |
| Funding was never modelled | reading the engine with the checklist in mind | no; documents said cost assumptions were fixed, and the engine had none | yes, P1 and P3 make this a refusal to report, not a discovery |
| Why negative funding is a fat tail; onset versus continuation | dialogue | no mechanism originates this | no; a claim card can hold it once someone has it |
| The 4-hour settlement rollout is a policy change, not a regime | dialogue plus a chart | no | partly: a structural-break flag can raise it; naming it stays with a person |
| Prediction target, R² versus AUC, class imbalance, uncertainty | owner's corrections | no | partly; these are the kind of judgment the note puts in the fat skill |
| "OS must not be tuned" after fifty OS looks | owner's correction | the seal would have blocked the reads; I bypassed it with `SEAL_OPEN=1` | yes, if the bypass is logged and counted (P2) |
| "That is fine-tuning; the goal was the structural problem" | owner's correction | no | partly, as a verdict-vocabulary rule; the judgment of what is structural is not mechanizable |
| 365 not 252 | owner's correction | no; the golden test agreed with itself | yes, once written as a constant with a test |
| Rerun every archive with costs, take the filtered strategy live | mechanical | partly; the archive tool did not exist | yes |

Roughly, two thirds of the rows are checks that did not exist and now do,
or could be written in an afternoon of model time. Those rows are where the
notes say the machine belongs, and the harness will not need the owner for
them again. The other third are questions and stops: which question to ask
next, when a result is an artefact of a policy change, when improvement has
turned into tuning. The notes' evidence is that resident procedure raises
the quality of choices made from a fixed menu; it does not claim procedure
generates the menu. So the honest answer is: unattended research at today's
level is not available, unattended research that cannot report a number
without its costs, cannot tune on the holdout, and cannot mistake a schedule
change for a regime is available, and that is most of what went wrong before
today.

## 4. Proposals

Effort is in model time. Verification is stated up front so each item can be
checked rather than trusted.

P1. Gate audit with one-digit tests. For every documented gate (saturation,
classifier, quality gates, seal, annualization, cost assumptions), a test
that feeds two inputs differing in one place and asserts the gate moves.
Update or delete the documentation that promises a gate that is off. Effort:
one session. Verification: the test file exists and the three documents no
longer promise saturation.

P2. Close the composite holdout. Remove OS from the loop's objective, prompt
and leaderboard; score on IS with the referee's deflated Sharpe (N from the
archive) and run OS once per accepted composite, as the alpha loop already
promises. Log every `SEAL_OPEN=1` invocation with a reason to a ledger, and
count those invocations into N. Mark the 135 existing composites as
holdout-contaminated in their manifests. Effort: half a session. Verification:
`grep os_ prompt_template.md` returns nothing; the state file has no OS
leaderboard; a ledger file grows when the seal is bypassed.

P3. Write the resident procedure. Fill `RESEARCH.md` from the 09-02 draft's
consensus table plus today's cost checklist, read order, verdict vocabulary,
falsifiable-sentence rule, the four diagnostic tests, and the structural
versus parameter distinction with today's example. Effort: one session.
Verification: the ablation in section 5.

P4. Claim cards and a ledger, with the note's rules. Card before the attempt
(mechanism, predicted signature, falsifier, family); ledger states predicted
hit, annexed, miss; two misses kills; corpse kept. Apply the same prepayment
to engine changes, as was done informally today. Effort: one session for the
format and the two scripts that validate card presence and ledger schema; no
script judges content. Verification: an attempt without a card is refused by
`backtest.py` pre-flight.

P5. Finish the two look-ahead instruments. Make the existing prefix check
compare held books on the union grid of dates and symbols rather than
rebalance events; make it opt-out so research reruns of unchanged strategies
stop paying for it twice, and require it at freeze; state the start-shift
test's band; add a synthetic leaking strategy to the test suite that the
prefix check must catch; add an AST linter for negative shifts, centred
windows, backfill, and manual weight shifts; and print a non-coverage list
with every verdict (data-level contamination, uniform contamination,
hand-rolled forward slices). Effort: one session. Verification: the
synthetic strategy is caught; the non-coverage list is asserted by a
regression test.

P6. A map with two clocks. Reinstate a coverage map keyed on idea family,
universe and horizon, with per-trial evaporation as in the note, and add a
calendar clock: a structural-break flag (settlement schedule, listing rules,
fee tier changes) that cools every region whose evidence predates the break.
The 4-hour rollout is the worked example and the test case. Effort: one
session for the map; the break flag is a table someone maintains.
Verification: after flagging 2023-12, regions with only pre-2023-12 evidence
report as cold.

P7. Fan-out only for the three cases. A verifier that receives the code, the
card and the one-sentence claim and not the reasoning; a refuter with a fresh
context after each causal story; web search dispatched at several angles when
an idea is outside the archive. No leaderboards over parallel drafts. Add
the note's cheap pre-flight critic that asks whether drafts in a batch
differ only in portfolio construction. Effort: half a session each.
Verification: the verifier prompt contains no field for the proposer's
rationale.

P8. Retire what the notes say to retire. The queue runner and the factor
zoo are parameter sweeps; keep them as deterministic baselines but count
their trials into N and stop treating their survivors as discoveries.

## 5. The test that decides

Two experiments, predictions stated before they run.

Ablation, the note's design. Rewind to three archive dates, show forty
candidate strategies with comments stripped, ask for ten backtest slots,
score against the archived outcomes, three conditions: bare model, plus
`RESEARCH.md` as written under P3, plus the claim ledger under P4. Prediction:
the resident procedure adds at least one correct pick out of ten on average
over nine paired timepoints (the note found 1.4), and the ledger adds less
than the procedure. If procedure adds nothing, P3 is decoration and should
be cut to a checklist.

Replay of today. Give a loop built on P1 to P5 the 641 universe, the
`xs_volume_rank` archive as of 2026-09-11, and the single question "is this
deployable with real money", with no other hints, and read its report.
Prediction: it finds the missing funding and slippage (they are now checklist
items), builds the cost table, and stops at "breakeven after costs". It does
not produce the onset versus continuation distinction or the policy-change
diagnosis without a person. If it produces either, section 3 is too
pessimistic and the fat skill should take more of the owner's role than
proposed. If it fails to find the costs, P1 and P3 are not written well
enough to be read.

## 6. Order and cost

P2 first because it is a live contamination and half a session. P1 and P5
next because they are the checks today's findings were made of. P3 and P4
together, then the section 5 experiments, then P6 and P7. Total: about eight
model sessions of the length of today's, plus backtest time. P8 costs a
decision and no work.

## 7. What was read and what was not

Read in full or in structure: `AGENT.md`, `AUTORESEARCH.md`, `AGENTS.md`,
`RESEARCH.md`, `CLAUDE.md`, `README.md`, `docs/ALPHA_ARTIFACT_CONTRACT.md`,
`docs/proposals/2026-09-02-hypothesis-market-and-referee.md`,
`scripts/autoresearch/{composite_harness.py, prompt_template.md,
AUTORESEARCH_COMPOSITE.md, state.json, iterations/119}`,
`scripts/attempt_loop.py`, `scripts/tools/{run_alpha_queue.py,
backtest.py, validate_is_os.py, verify_artifact.py, integrity_test.py,
load_alpha.py, research_wiki.py, generate_factor_zoo.py,
oracle_ceiling_eda.py, build_is_only_weight_composite.py,
alpha_dashboard_lib.classify_alpha}`, `scripts/governance/{check.py,
seal_check.py}`, `src/intraday/composites/{_runner.py, _optim_helpers.py,
_composite_template.py}`, `src/intraday/strategies/multi/_alpha_template.py`,
`src/intraday/backtest/multi_tick_runner.py`, the pre-commit hook,
`research/cutoff_analysis.md`, and the wiki's row format.

Not read: the 2,362 strategy files, the 135 composite modules beyond their
Sharpe constants, the dashboard beyond its structure, the 668 research
notes, and the body of `integrity_test.py` past its docstring. Two claims
above depend on the last item: whether the path test uses an intersection
or a union join, and what its tolerance is. Both are in section 2.5 as
unverified.
