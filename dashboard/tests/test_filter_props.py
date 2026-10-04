#!/usr/bin/env python3
"""Property-based test of the dashboard filter engine.

Random filter states (facet selections in "any" and "match all" mode,
hierarchy values, year ranges, fuzzy text including misspellings, every sort
and direction) are generated from the facet definitions in ``dist/bundle.json``.
Each state is evaluated twice: by the JavaScript engine (``src/engine.js``, the
file inlined into the page, run under Node through ``tests/run_engine.js``) and
by the independent reference implementation in this file, written from the
semantics stated at the top of ``engine.js``. The ordered result ids, the live
counts of every facet value and the range histograms must be identical.

The reference implementation is deliberately naive (set algebra over Python
dicts, no index) so that it is easy to read and hard to get wrong; the engine
is optimised (postings and byte masks) and is what the test checks.

Run: ``python3 tests/test_filter_props.py [--bundle PATH] [--n 400] [--seed 1]``
(exit 0 when every query agrees). Also works under pytest.
"""

from __future__ import annotations

import argparse
import functools
import json
import math
import os
import random
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_BUNDLE = (HERE.parent / "dist-test" / "bundle.json") if (HERE.parent / "dist-test" / "bundle.json").exists() else HERE.parent / "dist" / "bundle.json"
HARNESS = HERE / "run_engine.js"
TEXT_THRESHOLD = 0.6
NAME_BONUS = 0.5
NAME_TOKEN_BONUS = 0.25
NAME_WORD_BONUS = 0.25
NAME_EXACT_BONUS = 0.5
ID_EXACT_BONUS = 1.0
SORTS = {
    "relevance": (None, "desc"), "name": ("name", "asc"), "provider": ("provider", "asc"),
    "date_catalogued": ("date_catalogued", "desc"), "date_verified": ("date_verified", "desc"), "last_updated": ("last_updated", "desc"),
}


# ----------------------------------------------------------------- reference

def normalise(text: Any) -> str:
    s = unicodedata.normalize("NFKD", "" if text is None else str(text))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = "".join(c if unicodedata.category(c)[0] in ("L", "N") else " " for c in s)
    return " ".join(s.split())


def trigrams(token: str) -> list[str]:
    padded = f" {token} "
    return [padded[i:i + 3] for i in range(len(padded) - 2)]


def walk(obj: Any, path: str) -> list[Any]:
    current = [obj]
    for part in path.split(".") if path else []:
        iterate = part.endswith("[]")
        key = part[:-2] if iterate else part
        nxt = []
        for item in current:
            if isinstance(item, dict) and key in item:
                v = item[key]
                if iterate:
                    if isinstance(v, list):
                        nxt.extend(v)
                else:
                    nxt.append(v)
        current = nxt
    return current


def transform(values: list[Any], kind: str | None, facet: dict[str, Any] | None = None) -> list[Any]:
    out: list[Any] = []
    for v in values:
        if kind == "year_span":
            def year(x: Any) -> int | None:
                if isinstance(x, int) and not isinstance(x, bool):
                    return x
                m = re.match(r"^\s*(\d{4})", str(x)) if x not in (None, "") else None
                return int(m.group(1)) if m else None
            if isinstance(v, dict):
                a = year(v.get("start"))
                b = (facet or {}).get("open_end", a) if v.get("end") is None else year(v.get("end"))
                if a is not None and b is not None and a <= b <= a + 400:
                    out.extend(range(a, b + 1))
        elif kind == "number":
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                out.append(int(v) if isinstance(v, float) and v.is_integer() else v)
        elif kind == "presence":
            if v not in (None, ""):
                out.append("checked")
        elif kind == "year":
            m = re.match(r"^\s*(\d{4})", str(v)) if v not in (None, "") else None
            if m:
                out.append(int(m.group(1)))
        elif kind == "bool":
            if isinstance(v, bool):
                out.append("yes" if v else "no")
        elif kind == "link_status":
            if isinstance(v, dict):
                out.append("not checked" if not v.get("checked") else "dead links" if v.get("dead") else "some links unverified" if v.get("unverified") else "all links alive")
        else:
            for item in (v if isinstance(v, list) else [v]):
                if isinstance(item, bool):
                    out.append("yes" if item else "no")
                elif isinstance(item, (str, int, float)) and str(item) != "":
                    out.append(str(item))
    if kind in ("link_status", "presence") and not out:
        out.append("not checked")
    return out


class Reference:
    """Naive evaluation of a filter state over the records."""

    def __init__(self, bundle: dict[str, Any]):
        self.records = bundle["records"]
        self.facets = {f["id"]: f for f in bundle["facets"]}
        self.text_fields = bundle["meta"]["text_fields"]
        self.values: dict[str, list[set[Any]]] = {}
        for fid, f in self.facets.items():
            if f["kind"] == "text":
                continue
            parents = {v["value"]: v["parent"] for v in f.get("values", []) if v.get("parent")}
            children: dict[str, list[str]] = {}
            for v in f.get("values", []):
                if v.get("parent"):
                    children.setdefault(v["parent"], []).append(v["value"])
            per_record = []
            for r in self.records:
                vals = set(transform(walk(r, f["path"]), f.get("transform"), f))
                if f["kind"] == "hierarchy":
                    for v in list(vals):
                        if v in parents:
                            vals.add(parents[v])
                        vals.update(children.get(v, []))
                per_record.append(vals)
            self.values[fid] = per_record
        self.texts = [normalise(" ".join(" ".join(r[k]) if isinstance(r.get(k), list) else str(r[k]) for k in self.text_fields if r.get(k) is not None)) for r in self.records]
        self.names = [normalise(r.get("name")) for r in self.records]
        self.titles = [normalise(r.get("title_en") or r.get("name")) for r in self.records]
        self.ids = [str(r["id"]) for r in self.records]
        self.text_trigrams = [{g for tok in t.split() for g in trigrams(tok)} for t in self.texts]

    def facet_ok(self, i: int, fid: str, sel: dict[str, Any]) -> bool:
        f = self.facets[fid]
        vals = self.values[fid][i]
        if f["kind"] == "range":
            lo = sel.get("min"); hi = sel.get("max")
            return any((lo is None or v >= lo) and (hi is None or v <= hi) for v in vals)
        chosen = sel.get("values") or []
        return all(v in vals for v in chosen) if sel.get("all") else any(v in vals for v in chosen)

    def text_score(self, i: int, query: str) -> float | None:
        toks = normalise(query).split()
        if not toks:
            return 0.0
        total = 0.0
        for tok in toks:
            grams = trigrams(tok)
            hits = sum(1 for g in grams if g in self.text_trigrams[i])
            if tok in self.texts[i]:
                score = 1.0
            elif hits > 0:
                score = hits / len(grams)
            else:
                score = 0.0
            if score < TEXT_THRESHOLD:
                return None
            total += score
        name_tri = {g for w in (self.names[i] + " " + self.titles[i]).split() for g in trigrams(w)}
        in_name = sum(1 for tok in toks if tok in self.names[i] or tok in self.titles[i] or sum(1 for g in trigrams(tok) if g in name_tri) / len(trigrams(tok)) >= TEXT_THRESHOLD)
        q = normalise(query)
        hit = q in self.names[i] or q in self.titles[i]
        word = hit and any((" " + title + " ").find(" " + q + " ") >= 0 for title in [self.names[i], self.titles[i]])
        return total / len(toks) + (NAME_BONUS if hit else 0.0) + (NAME_WORD_BONUS if word else 0.0) + (NAME_EXACT_BONUS if q in [self.names[i], self.titles[i]] else 0.0) + (ID_EXACT_BONUS if normalise(self.records[i].get("id")) == q else 0.0) + NAME_TOKEN_BONUS * in_name / len(toks)

    def query(self, state: dict[str, Any]) -> dict[str, Any]:
        active = [(fid, sel) for fid, sel in (state.get("facets") or {}).items()
                  if fid in self.facets and sel and ((self.facets[fid]["kind"] == "range" and (sel.get("min") is not None or sel.get("max") is not None))
                                                     or (self.facets[fid]["kind"] != "range" and sel.get("values")))]
        n = len(self.records)
        text = state.get("text") or ""
        scores = [self.text_score(i, text) for i in range(n)] if normalise(text) else [0.0] * n
        text_ok = [s is not None for s in scores]

        def passes(i: int, skip: str | None) -> bool:
            return text_ok[i] and all(self.facet_ok(i, fid, sel) for fid, sel in active if fid != skip)

        result = [i for i in range(n) if passes(i, None)]

        counts: dict[str, dict[str, int]] = {}
        ranges: dict[str, dict[str, int]] = {}
        for fid, f in self.facets.items():
            if f["kind"] == "text":
                continue
            own = dict(active).get(fid)
            include_own = own is not None and bool(own.get("all")) and f["kind"] != "range"
            base = [i for i in range(n) if passes(i, None if (own is None or include_own) else fid)]
            if f["kind"] == "range":
                hist: dict[str, int] = {}
                for i in base:
                    for v in self.values[fid][i]:
                        hist[str(v)] = hist.get(str(v), 0) + 1
                ranges[fid] = hist
            else:
                present = {v for vals in self.values[fid] for v in vals}
                counts[fid] = {v: sum(1 for i in base if v in self.values[fid][i]) for v in present}

        sort = state.get("sort") if state.get("sort") in SORTS else "relevance"
        field, default_dir = SORTS[sort]
        direction = state.get("dir") if state.get("dir") in ("asc", "desc") else default_dir
        if sort == "relevance":
            has_text = bool(normalise(text))
            if has_text:
                result.sort(key=lambda i: ((-scores[i] if direction == "desc" else scores[i]), self.names[i], self.ids[i]))
            else:
                result.sort(key=lambda i: (self.names[i], self.ids[i]))
        else:
            def key_of(i: int) -> str | None:
                if field == "name":
                    return self.titles[i]
                if field == "provider":
                    return normalise(self.records[i].get("provider"))
                v = self.records[i].get(field)
                return None if v in (None, "") else str(v)

            keys = {i: key_of(i) for i in result}
            sign = 1 if direction == "asc" else -1

            def compare(a: int, b: int) -> int:
                ka, kb = keys[a], keys[b]
                if ka is None and kb is None:
                    return (self.ids[a] > self.ids[b]) - (self.ids[a] < self.ids[b])
                if ka is None:
                    return 1
                if kb is None:
                    return -1
                c = sign * ((ka > kb) - (ka < kb))
                if c:
                    return c
                if field == "provider":
                    c = (self.names[a] > self.names[b]) - (self.names[a] < self.names[b])
                    if c:
                        return c
                return (self.ids[a] > self.ids[b]) - (self.ids[a] < self.ids[b])

            result.sort(key=functools.cmp_to_key(compare))
        return {"ids": [self.ids[i] for i in result], "counts": counts, "ranges": ranges, "sort": sort, "dir": direction}


# ---------------------------------------------------------------- generation

def word_bank(records: list[dict[str, Any]]) -> list[str]:
    words: set[str] = set()
    for r in records:
        for field in ("name", "provider", "description", "tags"):
            v = r.get(field)
            text = " ".join(v) if isinstance(v, list) else str(v or "")
            words.update(w for w in normalise(text).split() if 3 <= len(w) <= 14)
    return sorted(words)


def misspell(rng: random.Random, word: str) -> str:
    if len(word) < 4:
        return word
    i = rng.randrange(1, len(word) - 1)
    choice = rng.random()
    if choice < 0.4:
        return word[:i] + word[i + 1:]                      # deletion
    if choice < 0.7:
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]  # transposition
    return word[:i] + rng.choice("aeioux") + word[i:]        # insertion


def random_state(rng: random.Random, bundle: dict[str, Any], words: list[str]) -> dict[str, Any]:
    facets = [f for f in bundle["facets"] if f["kind"] != "text" and not f.get("empty")]
    state: dict[str, Any] = {"facets": {}, "text": "", "sort": rng.choice(list(SORTS)), "dir": rng.choice([None, "asc", "desc"])}
    for f in rng.sample(facets, k=min(len(facets), rng.choice([0, 1, 1, 2, 2, 3, 4]))):
        if f["kind"] == "range":
            lo, hi = f["min"], f["max"]
            between = (lambda: rng.randint(lo - 2, hi + 2)) if isinstance(lo, int) and isinstance(hi, int) else (lambda: rng.uniform(lo * 0.5, hi * 1.5))
            a = rng.choice([None, lo - 1, lo, hi, hi + 1, between()])
            b = rng.choice([None, lo, hi, hi + 1, between()])
            if a is None and b is None:
                b = hi
            state["facets"][f["id"]] = {"min": a, "max": b}
        else:
            pool = f["values"]
            used = [v for v in pool if v.get("count")] or pool
            k = rng.choice([1, 1, 2, 3])
            source = used if rng.random() < 0.8 else pool
            picks = rng.sample(source, k=min(k, len(source)))
            values = [v["value"] for v in picks]
            if rng.random() < 0.1:
                values.append("no_such_value")
            state["facets"][f["id"]] = {"values": values, "all": rng.random() < 0.35}
    roll = rng.random()
    if roll < 0.35 and words:
        w = rng.choice(words)
        state["text"] = misspell(rng, w) if rng.random() < 0.5 else w
    elif roll < 0.5 and words:
        state["text"] = " ".join(rng.sample(words, k=2))
    elif roll < 0.58:
        state["text"] = rng.choice(["ab", "a", "5", "Ü", "  ", "x-y", "example", "sy"])
    return state


# ------------------------------------------------------------------- runner

def run_engine(bundle_path: Path, queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    env = dict(os.environ, ENGINE_TIMING="1")
    proc = subprocess.run(["node", str(HARNESS)], input=json.dumps({"bundle": str(bundle_path), "queries": queries}),
                          capture_output=True, text=True, check=True, env=env)
    if proc.stderr.strip():
        print(proc.stderr.strip())
    return json.loads(proc.stdout)


def compare(state: dict[str, Any], js: dict[str, Any], ref: dict[str, Any]) -> list[str]:
    problems = []
    if js["ids"] != ref["ids"]:
        problems.append(f"ids differ: js={js['ids']} ref={ref['ids']}")
    if js["sort"] != ref["sort"] or js["dir"] != ref["dir"]:
        problems.append(f"sort differs: js={js['sort']}/{js['dir']} ref={ref['sort']}/{ref['dir']}")
    for fid, ref_counts in ref["counts"].items():
        js_counts = js["counts"].get(fid, {})
        if js_counts != ref_counts:
            diff = {k: (js_counts.get(k), ref_counts.get(k)) for k in set(js_counts) | set(ref_counts) if js_counts.get(k) != ref_counts.get(k)}
            problems.append(f"counts differ for {fid}: {diff}")
    for fid, ref_hist in ref["ranges"].items():
        if js["ranges"].get(fid, {}) != ref_hist:
            problems.append(f"range histogram differs for {fid}: js={js['ranges'].get(fid)} ref={ref_hist}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare the JS filter engine with a Python reference over random filter states.")
    parser.add_argument("--bundle", default=str(DEFAULT_BUNDLE))
    parser.add_argument("--n", type=int, default=400)
    parser.add_argument("--seed", type=int, default=20260924)
    args = parser.parse_args(argv)

    bundle_path = Path(args.bundle).resolve()
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    rng = random.Random(args.seed)
    words = word_bank(bundle["records"])
    states = [random_state(rng, bundle, words) for _ in range(args.n)]
    # fixed corner cases in addition to the random ones
    states += [
        {"facets": {}, "text": "", "sort": "relevance", "dir": None},
        {"facets": {}, "text": "   ", "sort": "name", "dir": "desc"},
        {"facets": {f["id"]: {"values": [v["value"] for v in f["values"][:2]], "all": True} for f in bundle["facets"] if f["kind"] == "multi" and f.get("values")}, "text": "", "sort": "provider", "dir": None},
    ]
    ref = Reference(bundle)
    js_results = run_engine(bundle_path, states)
    failures = 0
    for k, (state, js) in enumerate(zip(states, js_results)):
        problems = compare(state, js, ref.query(state))
        if problems:
            failures += 1
            print(f"FAIL #{k}: state={json.dumps(state)}")
            for p in problems:
                print("   ", p)
    n_nonempty = sum(1 for r in js_results if r["ids"])
    print(f"{len(states)} states over {len(bundle['records'])} records: {len(states) - failures} agree, {failures} differ; "
          f"{n_nonempty} states returned at least one record")
    return 1 if failures else 0


def test_engine_matches_reference() -> None:
    """pytest entry point."""
    assert main(["--n", "200"]) == 0


if __name__ == "__main__":
    sys.exit(main())
