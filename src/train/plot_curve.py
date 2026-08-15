"""Parse an mlx_lm.lora training log into a curve plot and a machine-readable series.

    python -m src.train.plot_curve results/train_log.txt

The plot deliberately shows train and validation loss on the SAME axes with the validation
series marked as non-evidence. Validation data here shares a generator with the training data,
so a falling validation loss demonstrates the model learned the *generated* task and says nothing
about the real one. Labelling that on the figure itself keeps the caveat attached to the artifact
rather than living only in prose that can be read separately from the chart.
"""
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

TRAIN = re.compile(r"Iter (\d+): Train loss ([\d.]+).*?(?:It/sec ([\d.]+))?.*?"
                   r"(?:Peak mem ([\d.]+) GB)?", re.I)
VAL = re.compile(r"Iter (\d+): Val loss ([\d.]+)", re.I)


def parse(log_text):
    train, val, peak = [], [], []
    for line in log_text.splitlines():
        mv = VAL.search(line)
        if mv:
            val.append((int(mv.group(1)), float(mv.group(2))))
            continue
        if "Train loss" in line:
            it = re.search(r"Iter (\d+)", line)
            ls = re.search(r"Train loss ([\d.]+)", line)
            pk = re.search(r"Peak mem ([\d.]+) GB", line)
            ts = re.search(r"Tokens/sec ([\d.]+)", line)
            if it and ls:
                train.append((int(it.group(1)), float(ls.group(1))))
            if it and pk:
                peak.append((int(it.group(1)), float(pk.group(1)),
                             float(ts.group(1)) if ts else None))
    return train, val, peak


def main():
    log_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "results" / "train_log.txt"
    out_png = REPO_ROOT / "results" / "training_curve.png"
    train, val, peak = parse(Path(log_path).read_text(errors="ignore"))
    if not train:
        print(f"no training points parsed from {log_path}")
        return 1

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(9, 7), sharex=True,
                                  gridspec_kw={"height_ratios": [3, 1]})
    ax.plot(*zip(*train), lw=1.4, color="#2b6cb0", label="train loss")
    if val:
        ax.plot(*zip(*val), lw=1.6, ls="--", marker="o", ms=4, color="#c05621",
                label="val loss  (NOT evidence of improvement — shared generator)")
    ax.set_ylabel("loss")
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(alpha=0.25)
    ax.set_title("Qwen2.5-3B-Instruct-4bit — LoRA r8, multi-doc partial-answer task", fontsize=10)
    ax.text(0.01, 0.02,
            "Validation shares the generator with training.\n"
            "Only eval/multidoc_expanded.json (hand-authored) can show real improvement.",
            transform=ax.transAxes, fontsize=7.5, va="bottom", color="#742a2a")

    if peak:
        its = [p[0] for p in peak]
        ax2.plot(its, [p[1] for p in peak], lw=1.2, color="#2f855a")
        ax2.axhline(5.73, ls=":", color="#9b2c2c", lw=1)
        ax2.text(its[0], 5.75, "Metal recommended working set 5.73 GB",
                 fontsize=7, color="#9b2c2c")
        ax2.set_ylabel("peak mem (GB)")
    ax2.set_xlabel("iteration")
    ax2.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)

    series = {"train": train, "val": val,
              "peak_mem": [{"iter": i, "gb": g, "tok_s": t} for i, g, t in peak]}
    (REPO_ROOT / "results" / "training_curve.json").write_text(json.dumps(series, indent=2))
    print(f"train points {len(train)}  val points {len(val)}")
    if train:
        print(f"  train loss {train[0][1]:.3f} -> {train[-1][1]:.3f}")
    if val:
        print(f"  val   loss {val[0][1]:.3f} -> {val[-1][1]:.3f}")
    if peak:
        print(f"  peak mem max {max(p[1] for p in peak):.2f} GB")
    print(f"wrote {out_png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
