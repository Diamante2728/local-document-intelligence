"""Hybrid retrieval: BM25 lexical scoring fused with dense embedding scores.

WHY THIS EXISTS (measured, not assumed). P07 asks for FDIC aggregate net income. The answer is
in `fdic_quarterly_banking_profile_2024q1` p1 — the text "net income ... increased by $28.4
billion (79.5 percent) ... to $64.2 billion" is definitely in the chunk store. Dense retrieval
never surfaced it, so the prose path correctly returned NOT_IN_CONTEXT and the question was
scored a miss.

Dense embeddings compress a passage into 384 dimensions and are good at topical similarity but
weak on the things that actually pin a fact down: proper nouns, institution names, and figures.
BM25 is the opposite — it is exact-term matching with document-frequency weighting, so rare
tokens like "FDIC-insured" or "64.2" carry a lot of signal. Fusing the two covers both.

Implemented from scratch rather than adding a dependency: `rank_bm25` is one more package to
pin, and the corpus is small enough (3,861 chunks) that a plain inverted index over tokenised
chunks is fast and auditable. Constraint #1 also means fewer moving parts is better — this runs
entirely offline with no model.

FUSION: Reciprocal Rank Fusion (RRF), score = sum over rankers of 1/(k + rank). RRF is used in
preference to score-normalised averaging because BM25 scores and cosine similarities live on
incomparable scales; RRF only uses the ORDER each ranker produces, so no calibration between
them is required. k=60 is the value from the original RRF paper and is not tuned here — tuning
it against the gold set is exactly the overfitting this project is trying to avoid.
"""
import math
import re
from collections import Counter, defaultdict

RRF_K = 60
BM25_K1 = 1.5
BM25_B = 0.75

_TOKEN = re.compile(r"[a-z0-9][a-z0-9.,\-]*")
_STOP = {
    "the", "a", "an", "and", "or", "of", "in", "on", "for", "to", "was", "were", "is", "are",
    "at", "by", "with", "from", "that", "this", "it", "as", "be", "been", "has", "have", "had",
}


def tokenize(text):
    out = []
    for t in _TOKEN.findall(str(text).lower()):
        t = t.strip(".,-")
        if not t or t in _STOP or len(t) < 2:
            continue
        out.append(t)
    return out


class BM25:
    """Minimal BM25 over the prose chunk store. Built once, reused across queries."""

    def __init__(self, docs):
        """docs: list of (chunk_id, doc_id, page, text)."""
        self.meta = [(c, d, p) for c, d, p, _t in docs]
        self.postings = defaultdict(list)   # term -> [(doc_index, term_freq)]
        self.doc_len = []
        df = Counter()
        for i, (_c, _d, _p, text) in enumerate(docs):
            toks = tokenize(text)
            self.doc_len.append(len(toks))
            tf = Counter(toks)
            for term, freq in tf.items():
                self.postings[term].append((i, freq))
                df[term] += 1
        self.n = len(docs)
        self.avg_len = (sum(self.doc_len) / self.n) if self.n else 0.0
        # BM25 idf with the +0.5 smoothing; floored at a small positive so that a term appearing
        # in most documents contributes ~nothing rather than a negative score.
        self.idf = {
            t: max(math.log((self.n - d + 0.5) / (d + 0.5) + 1.0), 1e-6) for t, d in df.items()
        }

    def search(self, query, top_k=10, doc_ids=None):
        scores = defaultdict(float)
        for term in tokenize(query):
            if term not in self.postings:
                continue
            idf = self.idf[term]
            for i, freq in self.postings[term]:
                dl = self.doc_len[i] or 1
                denom = freq + BM25_K1 * (1 - BM25_B + BM25_B * dl / (self.avg_len or 1))
                scores[i] += idf * (freq * (BM25_K1 + 1)) / (denom or 1)
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        out = []
        for i, s in ranked:
            chunk_id, doc_id, page = self.meta[i]
            if doc_ids and doc_id not in doc_ids:
                continue
            out.append({"chunk_id": chunk_id, "doc_id": doc_id, "page": page, "bm25": s})
            if len(out) >= top_k:
                break
        return out


def build_bm25(conn):
    rows = conn.execute("SELECT chunk_id, doc_id, page, text FROM chunks").fetchall()
    return BM25(rows)


def rrf_fuse(dense_hits, lexical_hits, top_k=5, k=RRF_K):
    """Reciprocal Rank Fusion over two ranked lists keyed by chunk_id."""
    fused = {}
    for rank, h in enumerate(dense_hits, start=1):
        e = fused.setdefault(h["chunk_id"], {**h, "rrf": 0.0, "dense_rank": None, "lex_rank": None})
        e["rrf"] += 1.0 / (k + rank)
        e["dense_rank"] = rank
    for rank, h in enumerate(lexical_hits, start=1):
        e = fused.setdefault(h["chunk_id"], {**h, "rrf": 0.0, "dense_rank": None, "lex_rank": None})
        e["rrf"] += 1.0 / (k + rank)
        e["lex_rank"] = rank
    out = sorted(fused.values(), key=lambda e: -e["rrf"])[:top_k]
    for e in out:
        # Keep a `score` field so downstream confidence maths is unchanged. RRF values are tiny
        # by construction, so reuse the dense cosine when present and fall back to a scaled RRF.
        if "score" not in e or e.get("dense_rank") is None:
            e["score"] = e.get("score", min(0.99, e["rrf"] * k))
    return out
