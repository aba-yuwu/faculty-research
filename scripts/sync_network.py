#!/usr/bin/env python3
"""Remap network node ids and edge indices after a re-rank, then verify.

Edge indices are positional (id-1). Renumbering nodes without rewriting edges
attaches relationships to the wrong people, silently.

Usage: python sync_network.py graph.json --map oldnew.json --out graph_new.json
       oldnew.json: {"old_id": new_id, ...}  or  {"name": new_id, ...} with --by-name
"""
import argparse, json, sys
from collections import defaultdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("graph"); ap.add_argument("--map", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--by-name", action="store_true")
    a = ap.parse_args()
    g = json.load(open(a.graph, encoding="utf-8"))
    raw = json.load(open(a.map, encoding="utf-8"))
    nodes, edges = g["nodes"], g["edges"]

    before = {n["id"]: n["name"] for n in nodes}
    before_edges = [(before[e[0] + 1], before[e[1] + 1], e[2],
                     e[3] if len(e) > 3 else 1) for e in edges]

    mapping = ({n["id"]: raw[n["name"]] for n in nodes if n["name"] in raw}
               if a.by_name else {int(k): v for k, v in raw.items()})
    missing = [n["id"] for n in nodes if n["id"] not in mapping]
    if missing:
        sys.exit(f"ERROR: {len(missing)} nodes have no mapping: {missing[:10]}")

    for n in nodes:
        n["id"] = mapping[n["id"]]
    nodes.sort(key=lambda n: n["id"])
    ids = [n["id"] for n in nodes]
    if ids != list(range(1, len(nodes) + 1)):
        sys.exit("ERROR: new ids are not a contiguous 1..N sequence")

    o2n = {o - 1: v - 1 for o, v in mapping.items()}
    for e in edges:
        e[0], e[1] = o2n[e[0]], o2n[e[1]]

    # verification: every relationship must still join the same two people
    after = {n["id"]: n["name"] for n in nodes}
    after_edges = [(after[e[0] + 1], after[e[1] + 1], e[2],
                    e[3] if len(e) > 3 else 1) for e in edges]
    if sorted(map(str, before_edges)) != sorted(map(str, after_edges)):
        sys.exit("ERROR: edge endpoints changed identity — aborting, file not written")

    deg, tot = defaultdict(int), defaultdict(int)
    for e in edges:
        if e[2] != "coauthor":
            continue
        w = e[3] if len(e) > 3 else 1
        for x in (e[0], e[1]):
            deg[x + 1] += 1; tot[x + 1] += w
    mk = lambda k: {"id": k, "name": after[k], "partners": deg[k], "papers": tot[k]}
    g["board"] = {
        "byPartners": [mk(k) for k, _ in sorted(deg.items(), key=lambda z: (-z[1], z[0]))[:5]],
        "byPapers": [mk(k) for k, _ in sorted(tot.items(), key=lambda z: (-z[1], z[0]))[:5]],
        "full": [mk(k) for k in sorted(deg, key=lambda k: (-tot[k], -deg[k], k))],
    }
    json.dump(g, open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"OK: {len(nodes)} nodes, {len(edges)} edges remapped and verified -> {a.out}")


if __name__ == "__main__":
    main()
