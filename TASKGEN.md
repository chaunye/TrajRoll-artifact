# The synthetic task family

Section IV-A says the tasks "induce retries through similar function names, misleading
documentation pointers, and renamed configuration files" and attach a 3,000-character traceback
to a failing tool result. This file fixes every parameter, because a generator that is not
pinned cannot be rebuilt from a description.

## Entry point

`code/e5_loop.py:161`, `build_sandbox(root, scenario, seed)`. Called at `code/e5_loop.py:450`
with `--scenario` (default `missing_file`) and `--seed`.

## The `longtail` family (the paper's main task)

The sandbox is a small repository. With `seed > 0` the data-file names are drawn from an
8-name pool, so different seeds are different tasks rather than repeats of one task under
deterministic decoding.

    src/core/loader.py     the file that actually defines parse_config, at line 4
    src/core/legacy.py     a same-named decoy: def load_config(path) -> return None
    docs/guide.md          says the entry point is load_config in src/core/legacy.py (the trap)
    src/adapters/json_adapter.py, src/utils/{helpers,paths}.py, README.md
    data/<real>.json       {"a": <100 + seed>}
    data/<real>_bak.json   {"a": 0}, a near-name decoy

| Parameter | Value | Effect |
|---|---|---|
| `NAME_POOL` | config, settings, params, options, prefs, profile, manifest, registry | the 8 names; `<real>` and `<want>` are two distinct draws |
| `value` | `100 + seed` | deliberately outside the range of plausible line numbers, so the target rule cannot pass on a line number |
| decoy path | `src/core/legacy.py` | reached first by any agent that trusts `docs/guide.md` |
| near-name data file | `data/<real>_bak.json` | a wrong read that still returns a file |
| error padding | `--error-padding 3000` | 3,000 characters of a plausible traceback appended to every failing tool result |
| turn cap | `--max-turns 20` | a run that does not answer in 20 turns is a failure |
| decoding | `temperature 0` (`--temperature` to override) | the batch at 0.7 is the sampling check |
| tools | `read_file`, `grep`, `list_dir` | read-only, so no environment state has to be restored |

The padding matters for the paper's claim: without it a failed turn costs ~200 tokens and the
context-growth argument would be an artefact of a short failure log. With it, one failing turn
can dominate the request, which is what a real traceback does.

## The `missing_file` family

The task names `data/<want>.json`, which does not exist; the repository actually contains
`data/<real>.json`. Used for the early mechanism checks, not for the paper's main table.

## Why the target rule is two-part

`answer_ok` for `longtail` requires both `core/loader.py` and the value. Requiring only
`loader.py` would accept `config_loader.py`, which contains the substring, and would score a
hallucinated answer correct. Requiring both is what makes the task unsolvable by a lucky single
call and therefore what produces the failure-retry loop the paper studies.
