# -*- coding: utf-8 -*-
"""独立复验 STL：不依赖 Blender，直接读 binary STL 检查法线、退化面、流形与尺寸。

运行: python verify_stl.py
"""
import glob
import math
import os
import struct
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
files = sorted(glob.glob(os.path.join(HERE, "stl", "*.stl")))
all_ok = True

for path in files:
    d = open(path, "rb").read()
    n = struct.unpack_from("<I", d, 80)[0]
    size_ok = len(d) == 84 + 50 * n
    bad_normal = degenerate = 0
    edges = Counter()
    coords = []
    for i in range(n):
        v = struct.unpack_from("<12fH", d, 84 + 50 * i)
        nx, ny, nz = v[0:3]
        a, b, c = v[3:6], v[6:9], v[9:12]
        u = [b[k] - a[k] for k in range(3)]
        w = [c[k] - a[k] for k in range(3)]
        cr = [u[1] * w[2] - u[2] * w[1],
              u[2] * w[0] - u[0] * w[2],
              u[0] * w[1] - u[1] * w[0]]
        L = math.sqrt(sum(q * q for q in cr))
        if L < 1e-9:
            degenerate += 1     # 零面积面：切片软件会忽略，但其边仍要参与配对统计
        elif (nx * cr[0] + ny * cr[1] + nz * cr[2]) / L < 0.999:
            bad_normal += 1
        coords.extend((a, b, c))
        for p, q in ((a, b), (b, c), (c, a)):
            edges[tuple(sorted((p, q)))] += 1
    unmatched = sum(1 for k, c in edges.items() if c != 2)
    ok = size_ok and bad_normal == 0 and unmatched == 0
    all_ok = all_ok and ok
    if coords:
        dims = tuple(round(max(p[k] for p in coords) - min(p[k] for p in coords), 2)
                     for k in range(3))
        zmin = round(min(p[2] for p in coords), 2)
        zmax = round(max(p[2] for p in coords), 2)
    else:
        dims, zmin, zmax = (0, 0, 0), 0, 0
    print("%-22s n=%5d size=%-5s normal_bad=%-3d degen=%-3d unpaired_edges=%-4d "
          "dims=%s z=%s..%s -> %s"
          % (os.path.basename(path), n, size_ok, bad_normal, degenerate,
             unmatched, dims, zmin, zmax, "OK" if ok else "FAIL"))

print("TOTAL:", "ALL PASS" if all_ok and files else "PROBLEM / NO FILES")
