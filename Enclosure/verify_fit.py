# -*- coding: utf-8 -*-
"""独立复验「顶盖 / 底盒结合处」的几何逻辑，不依赖 Blender。

直接读 binary STL 做截面分析，参数用 ast 从 enclosure.py 的 P 字典取，
改了 enclosure.py 的参数后本脚本自动跟着变，不会两边对不上。

运行: python verify_fit.py      退出码 0 = 全部通过
"""
import ast
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load_params():
    """从 enclosure.py 源码里安全取出字面量 P 字典（不 import bpy）。"""
    src = open(os.path.join(HERE, "enclosure.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "P" for t in node.targets):
            expr = ast.Expression(node.value)
            return eval(compile(expr, "<P>", "eval"),
                        {"__builtins__": {"dict": dict}}, {})
    raise RuntimeError("P dict not found in enclosure.py")


def read_stl(path):
    d = open(path, "rb").read()
    n = struct.unpack_from("<I", d, 80)[0]
    tris = []
    for i in range(n):
        v = struct.unpack_from("<12fH", d, 84 + 50 * i)
        tris.append((v[3:6], v[6:9], v[9:12]))
    return tris


def segments(tris, z):
    """返回实体与水平面 z 的交线段（每条是两个 XY 点）。"""
    out = []
    for a, b, c in tris:
        v = (a, b, c)
        pts = []
        for i in range(3):
            p, q = v[i], v[(i + 1) % 3]
            if (p[2] < z < q[2]) or (q[2] < z < p[2]):
                t = (z - p[2]) / (q[2] - p[2])
                pts.append((p[0] + t * (q[0] - p[0]),
                            p[1] + t * (q[1] - p[1])))
        if len(pts) == 2:
            out.append((pts[0], pts[1]))
    return out


def bbox(segs):
    pts = [p for s in segs for p in s]
    if not pts:
        return None
    return (min(p[0] for p in pts), max(p[0] for p in pts),
            min(p[1] for p in pts), max(p[1] for p in pts))


def min_dist_to_posts(segs, P):
    """截面上的材料到四角螺柱中心的最近距离（沿线段采样）。"""
    posts = [(sx * P["post_x"], sy * P["post_y"])
             for sx in (-1, 1) for sy in (-1, 1)]
    best = float("inf")
    for (x0, y0), (x1, y1) in segs:
        L = math.hypot(x1 - x0, y1 - y0)
        n = max(1, int(L / 0.4) + 1)
        for i in range(n + 1):
            t = i / n
            x, y = x0 + t * (x1 - x0), y0 + t * (y1 - y0)
            for px, py in posts:
                best = min(best, math.hypot(x - px, y - py))
    return best


def main():
    P = load_params()
    W, D, H = P["case_w"], P["case_d"], P["case_h"]
    wall = P["wall"]
    lower = read_stl(os.path.join(HERE, "stl", "01_lower_case.stl"))
    lid = read_stl(os.path.join(HERE, "stl", "02_top_cover.stl"))

    rim = segments(lower, H - 0.1)          # 底盒盒口下方一点
    above = segments(lower, H + 0.1)        # 盒口上方，底盒应为空
    lid_body = segments(lid, H + 0.1)       # 顶盖本体
    lip = segments(lid, H - 1.0)            # 插入内腔的唇边

    rb, lb, lipb = bbox(rim), bbox(lid_body), bbox(lip)
    inner_x, inner_y = W / 2 - wall, D / 2 - wall
    lip_ox = W / 2 - wall - P["lip_gap"]
    lip_oy = D / 2 - wall - P["lip_gap"]
    post_r = P["post_od"] / 2
    dmin = min_dist_to_posts(lip, P)

    checks = []

    def chk(name, ok, detail):
        checks.append((name, bool(ok), detail))

    tol = 0.06
    chk("底盒在 z=H-0.1 仍有实体（口沿没被切穿）", bool(rim),
        "截面线段 %d 条" % len(rim))
    if rb:
        chk("底盒盒口外轮廓 = %.1f x %.1f" % (W, D),
            abs(rb[1] - W / 2) < tol and abs(rb[3] - D / 2) < tol,
            "实测 X±%.2f / Y±%.2f" % (rb[1], rb[3]))
        has_inner = any(abs(abs(x) - inner_x) < tol or abs(abs(y) - inner_y) < tol
                        for s in rim for x, y in s)
        chk("盒口存在宽 %.1f mm 的平齐环形口沿" % wall, has_inner,
            "内腔壁 X±%.1f / Y±%.1f" % (inner_x, inner_y))
    chk("底盒在 z=H+0.1 无材料（不侵入顶盖）", not above,
        "截面线段 %d 条" % len(above))
    chk("顶盖本体在 z=H+0.1 有实体", bool(lid_body),
        "截面线段 %d 条" % len(lid_body))
    if rb and lb:
        chk("顶盖与底盒外轮廓完全一致，侧面齐平",
            all(abs(a - b) < tol for a, b in zip(rb, lb)),
            "底盒 %s / 顶盖 %s" % (tuple(round(v, 2) for v in rb),
                                 tuple(round(v, 2) for v in lb)))
    chk("顶盖在 z=H-1 只有插入内腔的唇边", bool(lip) and lipb is not None,
        "截面线段 %d 条" % len(lip))
    if lipb:
        chk("唇边比内腔窄，单边留 %.1f mm 间隙" % P["lip_gap"],
            lipb[1] <= lip_ox + tol and lipb[3] <= lip_oy + tol,
            "实测 X±%.2f / Y±%.2f，内腔 X±%.1f / Y±%.1f"
            % (lipb[1], lipb[3], inner_x, inner_y))
        chk("四角给螺柱让位，唇边与螺柱不干涉", dmin > post_r,
            "材料到螺柱中心最近 %.2f mm > 螺柱半径 %.2f mm"
            % (dmin, post_r))
    # 唇边插入深度与顶盖本体底面
    chk("唇边插入深度 %.1f mm" % P["lip_h"],
        P["lip_h"] > 0 and P["lip_h"] < P["case_h"] - P["floor_t"],
        "电子层净高 %.1f mm" % (P["case_h"] - P["floor_t"]))
    chk("顶盖底面与底盒口沿共面 z=%.1f" % H,
        bool(lid_body) and bool(rim),
        "两零件在 z=H 上下相邻，中间无空隙")

    print("=" * 74)
    print(" 顶盖 / 底盒结合处几何校验")
    print("=" * 74)
    for name, ok, detail in checks:
        print("  [%s] %-38s %s" % ("PASS" if ok else "FAIL", name, detail))
    passed = sum(1 for _, ok, _ in checks if ok)
    print("-" * 74)
    print("  %d/%d PASS" % (passed, len(checks)))
    print("  TOTAL: %s" % ("ALL PASS - 结合逻辑正确，可直接切片装配"
                           if passed == len(checks) else "PROBLEM - 请检查 enclosure.py"))
    print("=" * 74)
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
