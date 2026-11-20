# TrajRoll - artifact

Artifact for *TrajRoll: Failure Recovery for Multi-Turn LLM Agents without Touching the
Inference Engine* (IEEE ISPA 2026, paper #1571369905).

TrajRoll deletes a failed turn's message branch and appends one ~40-token structured record at
the **tail** of the message list, so the system prompt and the committed history stay
byte-identical and the prefix cache keeps hitting. Nothing here touches the inference engine.

    code/        the experiment loop (e5_loop.py) and every analysis script
    frozen/      frozen summary files; the paper's tables and figures are computed from these
    prereg/      pre-registrations and result records, written before the runs
    DECIDER.md   the failure decider: the exact rules and where they live in the code
    TASKGEN.md   the synthetic task family: every parameter that induces the retries

## What was pre-registered, and where

`prereg/A1A2_preregistration.md` was frozen on 2026-09-18, before any run of the main batch,
against three code hashes quoted in its header. It fixes exactly two primary comparisons:

1. **TrajRoll vs discard-only** (`ours` vs `rollback`), N = 20.
2. **TrajRoll vs the truncation tier whose per-turn footprint is closest to TrajRoll's.** The
   tier is selected by that rule, not by name. In the realised batch the gaps were
   79 tokens (truncate-4), 235 (truncate-8) and 859 (truncate-16), so the rule resolved to
   **truncate-4**, which is the comparison the paper reports.

Every other pairwise comparison is exploratory. The same file fixes the reporting rule (the
lowest of five batches is reported, not the best) and the statistics (two-sided Fisher exact,
Wilson interval for each arm, Newcombe interval for the difference). `prereg/` keeps the
criterion files as written; where a criterion failed it is kept as a failure, and the
corresponding gate file under `frozen/gate_*.txt` is shipped unrepaired.

## Frozen code hashes

The paper's pre-registrations quote these (SHA-256, first 16 hex digits). `HASHES.txt` carries
the SHA-256 of every file in this repository, so a reader can confirm the tree was not edited
after publication.

    e5_loop.py (as shipped)                            B94A3B41131496DB
    e5_loop.py (E11 revision, adds sysend/syshead)      D487A8DD9729A73B
    e5_loop.py (frozen for the A1/A2 batch)            7006ED537A8DB647
    e5_loop.py (frozen for L2/L3/E9 batches)           843243FF0ECCD290
    summarize.py                                       71778466DD1C7266
    run_ablations.sh                                   FF3A011828455CBB
    run_L3.sh                                          90AE36FC0C675E86
    check_ablations.py (self-check gate)               EA7F84C9D2D0CCFA
    e15_ttft_scale.py (frozen for E15)                 261EC21540B92A2C
    e16_batched_placement.py (v2, frozen for E16)      6C6B7EB086359C00

The main batch ran against the 7006ED53... revision, the placement batch against D487A8DD...,
which differs only by two added failure-handling branches, and the field / second-model batches
against 843243FF..., which differs only by the added `worldonly` mode. The shipped file is the
B94A3B41... revision, which adds the C3 modes and two flags on top; in every case the earlier
modes are untouched line by line. `HASHES.txt` covers the shipped revision, which is the one a
reader can rerun.

## Which frozen file backs which number
| Paper | Frozen file |
|---|---|
| Table II, Fig. 2 (Qwen3-4B, seven strategies, one batch) | `frozen/ablations_summary_N20.txt` |
| Table II (Qwen3-8B block) | `frozen/l3_qwen3_8b_summary.txt` |
| Fig. 3(a) placement, 1.00x / 1.85x / 2.78x | `prereg/E11_results.md` (per-arm aggregate of the 60-run batch) |
| Fig. 3(b) TTFT against context length, 46x at 30k | `frozen/e15_ttft_scale.json` |
| Batched placement tax (p99 inter-token, K = 3 / 7) | `frozen/e16_batched_placement.json`, `frozen/e16_sizing_probe.json` |
| Content ladder (0/20, 0/20, 12/20, 19/20, 14/20) | `frozen/e12_placebo_summary.txt` |
| temperature-0.7 batch (5/20, 8/20, 16/20) | `frozen/e13_sampling_summary.txt` |
| Field ablation, 12/20 vs 13/20 | `frozen/l2_worldonly_summary.txt` |
| Success vs footprint Pareto | `frozen/pareto.csv`, `frozen/pareto_l3.csv` |
| 57.0% T2 precision, 100 annotated turns | `frozen/e9d_score_final_2026-10-05.txt` |
| Second annotator, Cohen's kappa = 0.795 | `frozen/e9d_second_annotation.csv`, `frozen/e9d_kappa_second_annotator.txt` |
| SWE-agent ledger, 5,512-turn replay | `code/analyze_swe_traces.py`, `code/replay_swe_prefix.py`, `frozen/ablations_summary_N20.txt` accounting |

## Reproducing the numbers

Engine: vLLM 0.18.1 serving Qwen3-4B (bf16) on one RTX 4090, started with
`--enable-prefix-caching --enable-prompt-tokens-details --max-model-len 40960
--gpu-memory-utilization 0.90`. The loop needs only the standard library plus `requests`.

    # main batch: 2x2 + sliding window, 140 runs, one interleaved batch
    NSEED=20 NTRUNC=20 ARMS="b0 label rollback ours truncate" bash code/run_ablations.sh
    python code/check_ablations.py ablations_summary.txt     # gate, before reading accuracy
    python code/summarize.py ablations_summary.txt --ref ours --csv pareto.csv

    # placement batch (Fig. 3a)
    NSEED=20 NTRUNC=0 ARMS="ours sysend syshead" bash code/run_ablations.sh

    # field ablation (L2), 60 runs
    NSEED=20 NTRUNC=0 ARMS="b0 ours worldonly" SUMMARY=l2_worldonly_summary.txt \
      bash code/run_ablations.sh 2>&1 | tee l2_worldonly.log

    # second model (L3), 140 runs; run the gate before reading any accuracy number
    MODEL=/path/to/Qwen3-8B NAME=Qwen3-8B PORT=18202 CUDA_VISIBLE_DEVICES=<idle> \
      bash code/serve_qwen3_18201.sh &
    bash code/run_L3.sh 2>&1 | tee l3_qwen3_8b.log
    python code/check_ablations.py l3_qwen3_8b_summary.txt
    python code/summarize.py l3_qwen3_8b_summary.txt --ref b0 --csv pareto_l3.csv

    # content ladder / temperature-0.7 / TTFT (280 runs)
    PORT=18201 bash code/run_C3.sh all          # or e12 / e13 / e14
    python code/check_ablations.py e12_placebo_summary.txt
    python code/c3_ttft_stats.py --dir .

    # figures, recomputed from the frozen summaries (no transcribed numbers)
    python code/make_figs.py
    python code/make_fig4_panels.py

    # real-trajectory ledger and the hold-out point
    python code/analyze_pi_traces.py
    python code/pi_holdout.py
    python code/analyze_swe_traces.py

    # E9-d annotation sample and scoring (130 rows, LLM pass + author review)
    python code/e9d_sample.py
    python code/e9d_score.py
    python code/e9_bootstrap.py

    # E15 real-scale placement TTFT; E16 batched placement tax
    python code/e15_ttft_scale.py --port <port> --mode measure --out e15_ttft_scale.json
    python code/e16_batched_placement.py --port <port> --mode probe --probe-order 7,3
    python code/e16_batched_placement.py --port <port> --mode measure --ks 0,3,7

    # second independent annotator: blind relabelling of the 100 hit-pool rows
    python code/e9d_second_pkg.py
    python code/e9d_kappa.py --csv <returned.csv>

### The self-check gate on the second-model batch

`check_ablations.py` reports three failures on the Qwen3-8B batch (checks 1, 2 and 4). We judge
them mis-specified rather than implementation bugs and record the post-hoc replacement criteria
in `prereg/L3_results.md`; `code/out/l3_gate_diag.py` and `code/out/l3_gate_paired.py` recompute
the quantities from the run logs without changing them. The gate is read before the accuracy
numbers, as the pre-registration specifies.

### The self-check gate on the temperature-0.7 batch

`check_ablations.py` check 3 fails on E13 (33.5%). It was written for deterministic decoding,
where both discard arms freeze at the same per-turn context; under sampling the discard-only arm
returns to its checkpoint every turn and accumulates no records, so the gap is mechanical. The
judgement and the log-level evidence are in `prereg/C3_results_reading.md` section 1.1.

## The E9-d annotation tables

Three tables ship, in deliberate order:

* `frozen/e9d_sample_superseded.csv` - a superseded informal first pass (provenance only).
* `frozen/e9d_sample_final_2026-10-05.csv` - the table the paper reports: a rubric-guided LLM
  labelling pass with one-line justification per row (`code/e9d_relabel_2026-10-05.py`), then
  reviewed row by row by the author (130/130 confirmed;
  `frozen/e9d_author_review_export_2026-10-05.csv` is the review export). Scored by
  `e9d_score.py` (`frozen/e9d_score_final_2026-10-05.txt`).
* `frozen/e9d_second_annotation.csv` - an independent annotator who labelled the 100 hit-pool
  rows blind (pool, template and the paper's annotation hidden). Scored against the final table
  by `e9d_kappa.py`: raw agreement 90.0%, Cohen's kappa = 0.795
  (`frozen/e9d_kappa_second_annotator.txt`).

The T001-T100 key that maps the blind ids back to rows is **not** shipped, because it is the
document that would have broken the blind had it travelled with the annotation package. The
agreement figure above is recomputable from the two shipped tables once the key is obtained from
the authors on request.

## Data (public, not redistributed here)

* CacheWise (Claude Code) traces - public, redacted by the upstream release.
* pi traces, `MaxDevv/real-pi-coding-agent-traces-sessions` - public (178 sessions downloaded;
  166 parse with at least three turns).
* `nebius/SWE-agent-trajectories` - public, 80,036 records. The analysis uses shard 0, model
  `swe-agent-llama-70b`: 6,914 trajectories, 177,791 turns, 348 unique instances. The `.arrow`
  files are Arrow IPC *streams* (`pa.ipc.open_stream`), not files.

## Paths

Several scripts carry absolute local paths as constants near the top of the file. They are path
constants only; adjust them to your own layout before running.
