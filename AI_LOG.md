# AI Log

Running log of what the coding assistant (Claude Code) did each phase, and anything it got
wrong that the user corrected. Feeds the AI-disclosure section of `MEMO.md`.

## Phase 0 — Setup

- Environment check: confirmed hardware is a MacBook Air, Apple M1, 8GB unified memory —
  matches the build spec's locked hardware plan.
- Found the system default `python3` is 3.7.0 (`/Library/Frameworks/Python.framework/Versions/3.7`),
  too old for `mlx-lm` (needs 3.9+). Located Python 3.11.5 via an existing Anaconda install
  (`/Users/mangilipallinagaraj/anaconda3`). Created a dedicated conda env (`doc-intel`, py3.11)
  rather than using `base`, to keep dependencies isolated and reproducible.
- Homebrew is not installed on this machine. Not a blocker for Phase 0 (only needed later if
  `camelot`/Ghostscript fallback is required for stubborn tables) — flagged for awareness.
- Created repo skeleton, `requirements.txt`, `.gitignore`, `README.md` stub, this log.
- No git identity was configured on this machine (`user.name`/`user.email` unset). Asked the
  user rather than assuming; also clarified that SSH/GPG keys are unrelated to this (those
  matter for pushing/signing, not for local commit authorship) since the user asked about them.
  Set locally (`git config --local`, this repo only) per user's answer: Nagaraj Mangilipalli /
  nagarajmangilipalli@gmail.com.
- Installed `mlx-lm sentence-transformers faiss-cpu pdfplumber pymupdf pandas cryptography`
  into the `doc-intel` env. All imports verified clean. `mx.default_device()` → `Device(gpu, 0)`,
  confirming Metal is visible to MLX.
- Downloaded `mlx-community/Qwen2.5-7B-Instruct-4bit` (~4.0GB on disk, matches expected INT4
  footprint). Ran the offline proof with `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` rather than
  physically disabling the machine's Wi-Fi — chose not to take that action unilaterally on the
  user's machine; the env-var approach proves the same thing (no network call possible) and is
  reproducible in CI. Full transcript + interpretation in `results/phase0_offline_proof.md`.
- **Correction I made myself before reporting:** the first `generate()` call measured a
  misleadingly slow 0.39 tok/s. This is MLX's one-time Metal shader JIT-compilation cost on
  first use, not real throughput — caught it by re-running warm calls in the same process
  before reporting a baseline, rather than reporting the cold number at face value. Warm
  steady-state baseline: **~9 tok/s** at INT4, batch size 1.
- Noted system-wide swap was already at 9.2GB used before this session's model run — flagged as
  a pre-existing condition (other background apps), not something Phase 0's test caused, and as
  a reminder that Phase 5 swap measurements need a clean baseline.
- **Foundation check passed:** model loads and generates offline within budget (peak MLX memory
  4.41GB, well under the ~4-5GB usable budget on this 8GB machine). Proceeding to Phase 1.
