# Stage 2 — reproduction guide

How to reproduce the Stage 2 results on a fresh machine. Written after a clean-clone test, which
found three things broken; all three are fixed and re-verified (§6).

`README.md` covers Stage 1 and is still the prerequisite: **do its §1–§5 first** (environment,
model download, corpus fetch, index build). Nothing here works without the index.

---

## 0. What Stage 2 is

Stage 1 shipped on **Qwen2.5-7B-Instruct-4bit**. Stage 2 fine-tunes a *different, smaller* model —
**Qwen2.5-3B-Instruct-4bit** — with LoRA, to try to fix multi-document question answering, and
compares three arms against a hand-authored 35-question eval set.

The headline: **the fine-tune made the system worse.** See `MEMO_STAGE2.md` for why.

## 1. Extra prerequisites beyond Stage 1

```bash
# the 3B base model (Stage 1 only downloads the 7B)
python -c "from huggingface_hub import snapshot_download; \
           snapshot_download('mlx-community/Qwen2.5-3B-Instruct-4bit')"

# ARC, for the regression suite only (~5 MB)
python -c "from huggingface_hub import snapshot_download; \
           snapshot_download('allenai/ai2_arc', repo_type='dataset')"
```

ARC is located via `HF_HUB_CACHE` / `HF_HOME` / `~/.cache/huggingface/hub`, in that order. If it is
missing the regression suite exits with the download command rather than a stack trace.

## 2. Tier A — reproduce the results WITHOUT retraining (~25 min)

Everything in `results/stage2_comparison.md` can be reproduced from the committed adapter. **No
training required.**

The trained adapter is committed at `results/adapters/multidoc_r8/adapters.safetensors` (26.6 MB).
The intermediate checkpoints (`0000200_…` through `0000800_…`) are **not** committed — they are
26.6 MB each and are only needed to re-examine checkpoint selection, not to reproduce anything.

```bash
# sanity check: the adapter loads on top of the base model and generates
python -c "
from src.qa import llm
llm.MODEL_ID = 'mlx-community/Qwen2.5-3B-Instruct-4bit'
llm.ADAPTER_PATH = 'results/adapters/multidoc_r8'
print(llm.generate_text('Say hello in five words.', max_tokens=24)[0])
"
```

Then the three arms (each ~35 questions; base ~28 min, tuned ~23 min, prompted ~22 min on an M1
8 GB — they are checkpointed per question and resume if interrupted):

```bash
python -m src.stage2_compare --arm base
python -m src.stage2_compare --arm tuned
python -m src.stage2_compare --arm prompted
```

Regression suites:

```bash
python -m src.stage2_regression --suite arc    --arm base
python -m src.stage2_regression --suite arc    --arm tuned
python -m src.stage2_regression --suite stage1 --arm base
python -m src.stage2_regression --suite stage1 --arm tuned
```

Build the comparison document:

```bash
python -m src.stage2_compare --report      # writes results/stage2_comparison.md
```

Expected numbers (what the memo reports):

| arm | overall | cross-doc (26) | controls (9) |
|---|---|---|---|
| base | 5/35 | 0/26 | 5/9 |
| tuned | 2/35 | 2/26 | 0/9 |
| prompted | 5/35 | 2/26 | 3/9 |

ARC: base **97/120**, tuned **3/120**. Stage 1 prose/numeric: base **7/16**, tuned **6/16**.

Greedy decoding is used throughout, so these should reproduce exactly on the same MLX version.
A different mlx-lm version may shift individual questions.

## 3. Tier B — the training run (~3 h, optional)

**Only needed if you want to retrain from scratch.** Tier A does not require this.

Resource envelope, measured on an M1 8 GB:

| | |
|---|---|
| wall clock | **~3.1 hours** for 800 iterations |
| peak memory | **4.70 GB** (Metal recommended working set is 5.73 GB) |
| throughput | ~14 s/iteration |
| output | `results/adapters/multidoc_r8/adapters.safetensors` |

Close other GPU-using applications first — the margin to the memory ceiling is under 1 GB.

```bash
python -m mlx_lm lora \
  --model mlx-community/Qwen2.5-3B-Instruct-4bit --train --data data \
  --fine-tune-type lora --num-layers 16 --batch-size 1 --grad-accumulation-steps 4 \
  --max-seq-length 2048 --grad-checkpoint --mask-prompt \
  --learning-rate 1e-4 --iters 800 --steps-per-report 20 --steps-per-eval 100 \
  --val-batches 12 --save-every 200 --adapter-path results/adapters/multidoc_r8 --seed 42
```

`--data data` reads `data/train.jsonl` (621) and `data/valid.jsonl` (68), both committed.

Every flag is justified in `results/train_config.md`. Three that are load-bearing:

- **`--mask-prompt`** — loss on assistant tokens only. Without it the model is trained to
  reproduce the excerpts rather than the answering behaviour.
- **`--max-seq-length 2048`** — **not** 512. 91.9% of examples exceed 512 tokens and mlx_lm
  truncates from the END, where the assistant target lives.
- **`--iters 800`** — `--iters` counts **batches, not optimizer steps**. With
  `--grad-accumulation-steps 4` this is 200 weight updates over 1.29 epochs.

Expect train loss ~1.9 → ~0.03 and validation ~3.9 → ~0.12. Plot with:

```bash
python -m src.train.plot_curve results/train_log_v2.txt
```

**Validation loss is not a result.** `valid.jsonl` shares a generator with `train.jsonl`, so it
measures fit to the generated format. Only `eval/multidoc_expanded.json` shows real improvement.

### Regenerating the training data (optional)

```bash
python -m src.train.gen_multidoc --n 700     # -> data/train_multidoc.raw.jsonl
python -m src.train.qc_multidoc               # -> data/train_multidoc.jsonl (689 kept)
python -m src.train.analyse                   # -> train/valid split + diversity report
```

Seeded and deterministic. To see what the QC gate actually rejects:

```bash
python -m src.train.gen_multidoc --n 700 --no-prefilter --out data/ablation.raw.jsonl
python -m src.train.qc_multidoc --inp data/ablation.raw.jsonl --out /tmp/abl.jsonl --report /tmp/abl.md
# rejects ~78% of unguarded data vs ~1.6% of clean
```

## 4. Eval-set integrity checks

```bash
python -m src.eval_checks
```

Verifies all 26 cross-document questions genuinely require both sources, all 35 figures appear on
their cited pages, and no partner leaks. Re-run this after any change to `src/eval_match.py` — the
checks consume the matcher, so a matcher change can silently alter what they report.

## 5. Stage 2 file map

```
MEMO_STAGE2.md                    the analytical write-up — start here
eval/multidoc_expanded.json       35 hand-authored multi-doc questions (26 cross-doc + 9 controls)
data/train_multidoc.jsonl         689 training examples (700 generated, 11 QC-rejected)
data/train.jsonl / valid.jsonl    621 / 68 split
data/qc_report.md                 QC trajectory, ablation, rejected examples
data/diversity_report.md          six-axis diversity + contamination vs all 64 eval questions
results/adapters/multidoc_r8/     the trained adapter (checkpoints NOT committed)
results/stage2_comparison.md      three-arm results
results/training_issues.md        four build failures + two measurement errors
results/arc_collapse_analysis.md  raw ARC outputs at both token budgets
results/failure_split.md          M01/M02 vs M03/H09 + 20-example training-set sample
results/training_curve.png        loss curves
results/train_config.md           hyperparameters and reasoning
src/stage2_compare.py             three-arm harness
src/stage2_regression.py          ARC + Stage 1 regression
src/train/                        generator, QC, analysis, plotting
```

## 6. What the clean-clone test found

Run against a fresh clone of tag `stage-2`. Three failures, all fixed:

| # | failure | impact | fix |
|---|---|---|---|
| 1 | `.gitignore`'s `*.safetensors` excluded the **adapter weights**. A clone got `adapter_config.json` (963 B) and nothing else. | **Blocking.** `RuntimeError: [load_safetensors] Failed to open file …/adapters.safetensors`. Tier A was completely unreproducible. | negation rule `!results/adapters/*/adapters.safetensors`; checkpoints stay ignored |
| 2 | `README.md` had **zero** mentions of Stage 2 — no 3B model, no adapter, no training command, no comparison scripts. | **Blocking.** Nothing in Stage 2 was documented for a stranger. | this file |
| 3 | `src/stage2_regression.py` hardcoded `/Users/mangilipallinagaraj/.cache/huggingface/...` | Regression suite could not run on any other machine. | resolves via `HF_HUB_CACHE` / `HF_HOME` / default, with a clear error if ARC is absent |

**Not** failures, though the clone lacks them: `index/` and the corpus PDFs are build artifacts,
already documented in `README.md` §4–§5, and correctly gitignored.

## 7. What a stranger can and cannot reproduce

**Can**, from this repo plus README §1–§5:

- load the adapter and generate
- reproduce all three arms and both regression suites, and regenerate
  `results/stage2_comparison.md` (~25 min)
- regenerate the training data deterministically, including the QC ablation
- re-run the eval-set integrity checks
- launch the training run and see it converge

**Cannot:**

- reproduce the *exact* adapter by retraining. Training is seeded, but MLX GPU kernel
  non-determinism means the weights will differ slightly. The committed adapter is the artifact
  the reported numbers came from.
- inspect the intermediate 200/400/600/800 checkpoints — not committed (106 MB total).
- decrypt `answer_key.enc` — deliberately, see `README.md` §6.
