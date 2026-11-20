# The failure decider

The paper's Section III-B describes the decider in prose. This file is the exact version, with
code pointers, because the rules are short enough to state completely and a false positive
deletes a turn that made progress.

All of it is rule-based. No language model is called anywhere in the decision path.

## Where a verdict is produced

| # | Stage | Code | What it does |
|---|---|---|---|
| 1 | Checkpoint | `code/e5_loop.py:499` | `ckpt = len(msgs)` before the request of every turn |
| 2 | Tool execution | `code/e5_loop.py:227` (`run_tool`) | returns `(ok, code, world, has_info)`; `code` is one of `NO_SUCH_FILE`, `NOT_A_DIR`, `EMPTY_DIR`, `NO_MATCH`, `BAD_CALL`, or empty |
| 3 | Verdict | `code/e5_loop.py:530` | `failed = (not ok) or (not info)` |
| 4 | Rollback | `code/e5_loop.py:589` | `del msgs[ckpt:]`, then the record is appended at the tail |

A turn is failed when it produced no usable information. Concretely, and exhaustively:

| Rule | Trigger | `ok` / `has_info` | Fail? |
|---|---|---|---|
| R1 | `read_file` on a path that is not a file (`NO_SUCH_FILE`) | False / False | yes |
| R2 | `list_dir` on a path that is not a directory (`NOT_A_DIR`) | False / False | yes |
| R3 | `list_dir` on an existing empty directory (`EMPTY_DIR`) | True / False | yes |
| R4 | `grep` with zero matches (`NO_MATCH`) | True / False | yes |
| R5 | Model output does not match the one-line calling protocol (`BAD_CALL`) | False / False | yes |
| R6 | Any tool call that returns content | True / True | no |

R6 is the only keep case. Note the shape: R3 and R4 are formal successes that carry no
information, which is why the verdict is `(not ok) or (not info)` rather than `not ok`.

## What the verdict is used for, and what it is not

The verdict drives exactly one thing: whether the turn's message branch is deleted. Repeat
counts (`n` in the record) and the `advice` / `strategy` / `reset` fields are built from a
separate counter of identical `(act, target, err)` tuples and identical error classes; they
supply text to the model and **do not** enter the delete/keep decision. See the last paragraph
of Section III-B and Table I.

## Interaction with the task's target rule (please read)

Two different rules exist, and they are **not** the same function, but they are adjacent enough
that the paper's wording matters:

* **Progress rule (this file, R1-R6).** Reads the tool return of one turn. Decides delete/keep.
* **Target rule (`code/e5_loop.py:110`, `answer_ok`).** Reads the final answer text. For the
  long-tail family it requires the answer to name `core/loader.py` **and** to contain the value
  stored in `data/<real>.json`; for the `missing_file` family it requires the value.

The target rule is applied twice, for two different jobs:

1. inside the loop, at `code/e5_loop.py:505`, to decide whether to reject an answer and append
   the rejection message (`REJECT_MSG`) so the agent tries again; this branch can be disabled
   with `--no-validate`;
2. at the end of the run, at `code/e5_loop.py:637`, to set the run-level `correct` flag.

Both call the same predicate. A run therefore ends with `correct = 1` only if its final answer
satisfies the target rule, and the in-loop rejection uses the same predicate to supply feedback.
What keeps the reported success rate from being vacuous is that the loop does not stop on a
rejected answer: a run can and does end at the turn cap with an answer that fails the check, and
that is counted as a failure. The arms differ by 55 points under the same predicate, so the
metric discriminates even though it is not an oracle.

Section IV-A calls this rule "independent". What it is independent *of* is the turn-level
progress rule: it reads the final answer, not a tool return, and it is not consulted when the
decider decides whether to delete a branch. It is however the same predicate that the rejection
branch uses, and this file says so explicitly so that no reader has to infer it from the code.
