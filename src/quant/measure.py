"""Mac-correct memory and latency measurement.

Two memory numbers are always reported together, because on Metal they disagree:

- `mx.get_peak_memory()` — what MLX believes it allocated. Documented to under-report on Metal
  (roughly 2x) because it does not see allocations made outside MLX's own allocator.
- `footprint(pid)` / Activity Monitor "Real Memory" — what the OS says the process holds.

Reporting only the MLX figure would flatter the model. Reporting only the OS figure would include
Python, torch, FAISS and the embedding model. The gap between them is itself the finding.

Swap is sampled too: on an 8GB machine, "it ran" and "it ran without thrashing" are different
claims, and only the swap delta distinguishes them.
"""
import os
import re
import subprocess
import time


def swap_used_mb():
    try:
        out = subprocess.run(["sysctl", "vm.swapusage"], capture_output=True, text=True).stdout
        m = re.search(r"used\s*=\s*([\d.]+)M", out)
        return float(m.group(1)) if m else None
    except Exception:
        return None


def footprint_mb(pid=None):
    """Real memory for the process, via the `footprint` tool. None if unavailable."""
    pid = pid or os.getpid()
    try:
        out = subprocess.run(["footprint", "-p", str(pid)], capture_output=True, text=True,
                             timeout=30).stdout
        m = re.search(r"([\d.]+)\s*MB\s+.*[Pp]hys", out) or re.search(r"phys_footprint:\s*([\d.]+)M", out)
        if m:
            return float(m.group(1))
        m = re.search(r"([\d,]+)\s+bytes", out)
        if m:
            return float(m.group(1).replace(",", "")) / 1e6
    except Exception:
        pass
    return None


def rss_mb(pid=None):
    """Resident set size via ps.

    MEASURED CAVEAT: on Metal this is useless as a memory figure for MLX work. With a 7B INT4
    model loaded and generating, `ps` reported **~50 MB** while `footprint` reported **5.6 GB**
    for the same process — Metal's unified-memory buffers are not counted in RSS. Kept only as a
    contrast datapoint; `footprint_mb()` is the number to trust and to report alongside MLX's own.
    """
    pid = pid or os.getpid()
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)],
                             capture_output=True, text=True).stdout.strip()
        return float(out) / 1024 if out else None
    except Exception:
        return None


class MemoryProbe:
    """Context manager capturing MLX peak, OS resident memory and swap delta around a block."""

    def __init__(self):
        self.mlx_peak_gb = None
        self.rss_start_mb = None
        self.rss_end_mb = None
        self.footprint_mb = None
        self.swap_start_mb = None
        self.swap_end_mb = None
        self.elapsed_s = None

    def __enter__(self):
        import mlx.core as mx
        mx.reset_peak_memory()
        self.rss_start_mb = rss_mb()
        self.swap_start_mb = swap_used_mb()
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        import mlx.core as mx
        self.elapsed_s = time.perf_counter() - self._t0
        self.mlx_peak_gb = mx.get_peak_memory() / 1e9
        self.rss_end_mb = rss_mb()
        self.footprint_mb = footprint_mb()
        self.swap_end_mb = swap_used_mb()
        return False

    @property
    def swap_delta_mb(self):
        if self.swap_start_mb is None or self.swap_end_mb is None:
            return None
        return self.swap_end_mb - self.swap_start_mb

    def as_dict(self):
        return {
            "mlx_peak_gb": round(self.mlx_peak_gb, 3) if self.mlx_peak_gb else None,
            "os_rss_end_gb": round(self.rss_end_mb / 1024, 3) if self.rss_end_mb else None,
            "os_footprint_gb": round(self.footprint_mb / 1024, 3) if self.footprint_mb else None,
            "swap_start_mb": self.swap_start_mb,
            "swap_end_mb": self.swap_end_mb,
            "swap_delta_mb": self.swap_delta_mb,
            "elapsed_s": round(self.elapsed_s, 2) if self.elapsed_s else None,
        }


def percentile(values, p):
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (p / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)
