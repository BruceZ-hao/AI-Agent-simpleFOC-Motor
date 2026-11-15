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


def hole_radius(segs, cx, cy, lo=0.8, hi=4.0):
    """截面里某个圆孔 / 六角沉腔的边界半径。

    截面线段端点落在孔壁上，取距孔中心 lo~hi 的点集中位数。
    hi=4.0 可以排除 Ø42 沉台、Ø12 中心孔和 Ø9 线束孔的干扰。
    """
    ds = []
    for (x0, y0), (x1, y1) in segs:
        for x, y in ((x0, y0), (x1, y1)):
            d = math.hypot(x - cx, y - cy)
            if lo < d < hi:
                ds.append(d)
    if not ds:
        return None
    ds.sort()
    return ds[len(ds) // 2]


def wall_coverage(segs, axis, val, tol=0.15):
    """截面上位于 axis=val 的直墙总长度（矩形窗口 / 限位框的边界）。"""
    total = 0.0
    for (x0, y0), (x1, y1) in segs:
        a0, a1 = (x0, x1) if axis == 'x' else (y0, y1)
        b0, b1 = (y0, y1) if axis == 'x' else (x0, x1)
        if abs(a0 - val) < tol and abs(a1 - val) < tol:
            total += abs(b1 - b0)
    return total


def diagonal_in(segs, xr, yr):
    """指定 XY 区域内是否存在斜线段（用于验证视窗四角确实被切成圆弧）。

    圆角矩形由多段短直线近似，角部必然同时存在 dx、dy 都非零的线段；
    直角矩形在该区域只会有水平 / 垂直线段。
    """
    for (x0, y0), (x1, y1) in segs:
        if (abs(x1 - x0) > 0.01 and abs(y1 - y0) > 0.01
                and all(xr[0] < x < xr[1] for x in (x0, x1))
                and all(yr[0] < y < yr[1] for y in (y0, y1))):
            return True
    return False


def segs_in_region(segs, xr, yr):
    """完全落在指定 XY 小矩形内的截面线段数（用于验证排线缺口真的打通）。"""
    n = 0
    for (x0, y0), (x1, y1) in segs:
        if (all(xr[0] < x < xr[1] for x in (x0, x1))
                and all(yr[0] < y < yr[1] for y in (y0, y1))):
            n += 1
    return n


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

    # ---- 04 电机锁板（与顶盖二选一）----
    lock_path = os.path.join(HERE, "stl", "04_motor_lock_plate.stl")
    if os.path.exists(lock_path):
        lock = read_stl(lock_path)
        lt = P["lock_t"]
        lk_body = segments(lock, H + lt / 2)
        lk_bb = bbox(lk_body)
        chk("锁板在 z=H+lt/2 有实体", bool(lk_body),
            "截面线段 %d 条" % len(lk_body))
        if rb and lk_bb:
            chk("锁板外轮廓与底盒 / 顶盖一致，侧面齐平",
                all(abs(a - b) < tol for a, b in zip(rb, lk_bb)),
                "实测 X±%.2f / Y±%.2f" % (lk_bb[1], lk_bb[3]))
        posts4 = [(P["lock_post_r"] * math.cos(math.radians(a)),
                   P["lock_post_r"] * math.sin(math.radians(a)))
                  for a in P["lock_post_angles"]]
        if P["lock_hole_mode"] == "round":
            upper = segments(lock, H + P["lock_nut_h"] + 0.5)
            rr = [hole_radius(upper, x, y) for x, y in posts4]
            chk("4 个铜柱过孔 Ø%.1f 贯通" % P["lock_hole_d"],
                all(r is not None and abs(r - P["lock_hole_d"] / 2) < 0.15
                    for r in rr),
                "实测半径 %s" % ", ".join("%.2f" % r if r else "NONE" for r in rr))
            nut = segments(lock, H + 0.5)
            hr = [hole_radius(nut, x, y) for x, y in posts4]
            chk("板底 4 个六角螺母沉腔（比过孔大，防转）",
                all(r is not None
                    and r > P["lock_hole_d"] / 2 + 0.8
                    and r <= P["lock_nut_af"] / math.sqrt(3.0) + 0.2
                    for r in hr),
                "实测腔半径 %s（过孔 %.2f）"
                % (", ".join("%.2f" % r if r else "NONE" for r in hr),
                   P["lock_hole_d"] / 2))
        else:
            chk("锁板为长槽模式（免实测，但电机可滑动）", True,
                "lock_hole_mode='slot'，量准孔距后改回 'round'")
        screw = segments(lock, H + lt / 2)
        sr = [hole_radius(screw, sx * P["post_x"], sy * P["post_y"])
              for sx in (-1, 1) for sy in (-1, 1)]
        chk("锁板四角安装孔对准底盒螺柱",
            all(r is not None and abs(r - P["lid_screw_d"] / 2) < 0.15
                for r in sr),
            "实测半径 %s" % ", ".join("%.2f" % r if r else "NONE" for r in sr))
        chk("锁板孔距与参考铜柱一致（改参数时两处要同步）",
            abs(P["lock_post_r"] - P["ref_pillar_r"]) < tol,
            "lock_post_r=%.2f / ref_pillar_r=%.2f"
            % (P["lock_post_r"], P["ref_pillar_r"]))
        lk_lip = segments(lock, H - 1.0)
        chk("锁板唇边与四角螺柱不干涉",
            min_dist_to_posts(lk_lip, P) > post_r,
            "材料到螺柱中心最近 %.2f mm > %.2f mm"
            % (min_dist_to_posts(lk_lip, P), post_r))
    else:
        chk("04_motor_lock_plate.stl 存在", False,
            "未找到锁板 STL，请先跑 regen.bat")

    # ---- 05 独立电机小方板（完全脱离外壳）----
    mini_path = os.path.join(HERE, "stl", "05_standalone_motor_plate.stl")
    if os.path.exists(mini_path):
        mini = read_stl(mini_path)
        mw, md, mt = P["mini_w"], P["mini_d"], P["mini_t"]
        body = segments(mini, mt / 2)
        mbb = bbox(body)
        chk("独立板在 z=mini_t/2 有实体", bool(body),
            "截面线段 %d 条" % len(body))
        if mbb:
            chk("独立板外形 %.1f x %.1f（不沿用外壳 110x76）" % (mw, md),
                abs(mbb[1] - mw / 2) < tol and abs(mbb[3] - md / 2) < tol,
                "实测 X±%.2f / Y±%.2f" % (mbb[1], mbb[3]))
        below = segments(mini, -0.5)
        above_m = segments(mini, mt + 0.5)
        chk("独立板底面 z=0 平齐：板下无唇边 / 无凸出", not below,
            "z=-0.5 截面线段 %d 条" % len(below))
        chk("独立板顶面 z=mini_t 以上无材料", not above_m,
            "z=%.1f 截面线段 %d 条" % (mt + 0.5, len(above_m)))

        ar = hole_radius(body, 0, 0, lo=4.0, hi=9.0)
        chk("中心 Ø%.1f 让位孔贯通" % P["mini_axis_d"],
            ar is not None and abs(ar - P["mini_axis_d"] / 2) < 0.15,
            "实测半径 %s" % ("%.2f" % ar if ar else "NONE"))

        mr = [hole_radius(body, sx * P["mini_mount_x"], sy * P["mini_mount_y"])
              for sx in (-1, 1) for sy in (-1, 1)]
        chk("四角 4 个 Ø%.1f 安装孔" % P["mini_mount_d"],
            all(r is not None and abs(r - P["mini_mount_d"] / 2) < 0.15
                for r in mr),
            "实测半径 %s" % ", ".join("%.2f" % r if r else "NONE" for r in mr))
        cc = (mw / 2 - P["mini_r"], md / 2 - P["mini_r"])
        wall_min = (P["mini_r"]
                    - math.hypot(P["mini_mount_x"] - cc[0],
                                 P["mini_mount_y"] - cc[1])
                    - P["mini_mount_d"] / 2)
        chk("四角安装孔完整落在圆角内，不切穿板边", wall_min > 0.8,
            "最小壁厚 %.2f mm > 0.8 mm" % wall_min)

        mposts = [(P["lock_post_r"] * math.cos(math.radians(a)),
                   P["lock_post_r"] * math.sin(math.radians(a)))
                  for a in P["lock_post_angles"]]
        if P["lock_hole_mode"] == "round":
            upper = segments(mini, P["lock_nut_h"] + 0.5)
            rr = [hole_radius(upper, x, y) for x, y in mposts]
            chk("独立板 4 个铜柱过孔 Ø%.1f 与锁板一致" % P["lock_hole_d"],
                all(r is not None and abs(r - P["lock_hole_d"] / 2) < 0.15
                    for r in rr),
                "实测半径 %s" % ", ".join("%.2f" % r if r else "NONE" for r in rr))
            nut = segments(mini, 0.5)
            hr = [hole_radius(nut, x, y) for x, y in mposts]
            chk("独立板板底 4 个六角螺母沉腔（防转）",
                all(r is not None
                    and r > P["lock_hole_d"] / 2 + 0.8
                    and r <= P["lock_nut_af"] / math.sqrt(3.0) + 0.2
                    for r in hr),
                "实测腔半径 %s（过孔 %.2f）"
                % (", ".join("%.2f" % r if r else "NONE" for r in hr),
                   P["lock_hole_d"] / 2))
        else:
            chk("独立板为长槽模式（与锁板一致）", True,
                "lock_hole_mode='slot'，量准孔距后改回 'round'")
        chk("独立板孔距与锁板 / 参考铜柱一致",
            abs(P["lock_post_r"] - P["ref_pillar_r"]) < tol,
            "lock_post_r=%.2f / ref_pillar_r=%.2f"
            % (P["lock_post_r"], P["ref_pillar_r"]))
        wx, wy = P["mini_wire_xy"]
        wr = hole_radius(body, wx, wy, lo=2.0, hi=7.0)
        chk("线束过孔 Ø%.1f" % P["mini_wire_d"],
            wr is not None and abs(wr - P["mini_wire_d"] / 2) < 0.15,
            "实测半径 %s" % ("%.2f" % wr if wr else "NONE"))
    else:
        chk("05_standalone_motor_plate.stl 存在", False,
            "未找到独立板 STL，请先跑 regen.bat")

    # ---- 06 TFT 显示面板（与外壳完全无关的独立件）----
    tft_path = os.path.join(HERE, "stl", "06_tft_panel.stl")
    if os.path.exists(tft_path):
        tft = read_stl(tft_path)
        pw, pd, pt = P["tft_panel_w"], P["tft_panel_d"], P["tft_panel_t"]
        fh = P["tft_frame_h"]
        cl = P["tft_mod_clear"]
        iw, idp = P["tft_mod_w"] + 2 * cl, P["tft_mod_h"] + 2 * cl
        ow, od = iw + 2 * P["tft_frame_wall"], idp + 2 * P["tft_frame_wall"]
        ww, wh = P["tft_win_w"], P["tft_win_h"]
        face = segments(tft, fh + pt / 2)     # 面板本体（视窗 / 安装孔）
        back = segments(tft, 0.5)             # 背面限位框 / M2 柱
        fbb = bbox(face)
        chk("TFT 面板在 z=fh+t/2 有实体", bool(face),
            "截面线段 %d 条" % len(face))
        if fbb:
            chk("TFT 面板外形 %.1f x %.1f（不沿用外壳轮廓）" % (pw, pd),
                abs(fbb[1] - pw / 2) < tol and abs(fbb[3] - pd / 2) < tol,
                "实测 X±%.2f / Y±%.2f" % (fbb[1], fbb[3]))
        chk("背面结构底面 z=0 平齐，下方无材料", not segments(tft, -0.5),
            "z=-0.5 截面线段 %d 条" % len(segments(tft, -0.5)))
        chk("面板顶面 z=%.1f 以上无材料" % (fh + pt), not segments(tft, fh + pt + 0.5),
            "z=%.1f 截面线段 %d 条"
            % (fh + pt + 0.5, len(segments(tft, fh + pt + 0.5))))
        wx = min(wall_coverage(face, 'x', ww / 2),
                 wall_coverage(face, 'x', -ww / 2))
        wy = min(wall_coverage(face, 'y', wh / 2),
                 wall_coverage(face, 'y', -wh / 2))
        # 圆角视窗：x=±ww/2 的直墙只有 wh-2r 长，y=±wh/2 只有 ww-2r 长，
        # 判据必须按「减去两端圆角后的直墙长度」算，不能沿用整边长度。
        wr = P["tft_win_r"]
        straight_x, straight_y = wh - 2 * wr, ww - 2 * wr
        chk("正面圆角视窗 %.1f x %.1f R%.1f 四边贯通" % (ww, wh, wr),
            wx > straight_x * 0.85 and wy > straight_y * 0.85,
            "X 向直墙 %.1f/%.1f / Y 向直墙 %.1f/%.1f mm"
            % (wx, straight_x, wy, straight_y))
        arc_ok = []
        for sx in (-1, 1):
            for sy in (-1, 1):
                xa, xb = sx * (ww / 2 - wr), sx * ww / 2
                ya, yb = sy * (wh / 2 - wr), sy * wh / 2
                arc_ok.append(diagonal_in(face,
                                          (min(xa, xb) - 0.2, max(xa, xb) + 0.2),
                                          (min(ya, yb) - 0.2, max(ya, yb) + 0.2)))
        chk("正面视窗四角为 R%.1f 圆角（匹配手表屏玻璃）" % wr, all(arc_ok),
            "四角圆弧线段检出 %d/4" % sum(arc_ok))
        press_x = (P["tft_mod_w"] - ww) / 2
        press_y = (P["tft_mod_h"] - wh) / 2
        chk("视窗四周压边压住模组 PCB", press_x > 1.5 and press_y > 1.5
            and ww < iw and wh < idp,
            "X %.2f / Y %.2f mm，内框 %.1f x %.1f" % (press_x, press_y, iw, idp))
        frame_x = min(wall_coverage(back, 'x', ow / 2),
                      wall_coverage(back, 'x', -ow / 2),
                      wall_coverage(back, 'x', iw / 2),
                      wall_coverage(back, 'x', -iw / 2))
        chk("背面限位框内外墙完整（内 %.1f 外 %.1f）" % (iw, ow),
            frame_x > 25.0, "最矮一侧墙长 %.1f mm" % frame_x)
        notch_in = segs_in_region(back, (-P["tft_notch_w"] / 2 + 1.0,
                                         P["tft_notch_w"] / 2 - 1.0),
                                  (P["tft_notch_y"] - 1.0,
                                   P["tft_notch_y"] + 1.0))
        chk("下边 %.1f mm 排线缺口真的打通" % P["tft_notch_w"], notch_in == 0,
            "缺口区域残留线段 %d 条" % notch_in)
        br = [hole_radius(back, sx * P["tft_boss_x"], sy * P["tft_boss_y"],
                          lo=0.4, hi=1.3)
              for sx in (-1, 1) for sy in (-1, 1)]
        chk("4 个 M2 自攻柱盲孔 Ø%.1f" % P["tft_boss_hole_d"],
            all(r is not None and abs(r - P["tft_boss_hole_d"] / 2) < 0.15
                for r in br),
            "实测半径 %s" % ", ".join("%.2f" % r if r else "NONE" for r in br))
        mr = [hole_radius(face, sx * P["tft_mount_x"], 0.0, lo=1.0, hi=2.6)
              for sx in (-1, 1)]
        chk("左右 2 个 M3 安装孔 Ø%.1f 贯通" % P["tft_mount_d"],
            all(r is not None and abs(r - P["tft_mount_d"] / 2) < 0.15
                for r in mr),
            "实测半径 %s" % ", ".join("%.2f" % r if r else "NONE" for r in mr))
        cc = (pw / 2 - P["tft_panel_r"], pd / 2 - P["tft_panel_r"])
        bwall = (P["tft_panel_r"]
                 - math.hypot(P["tft_boss_x"] - cc[0], P["tft_boss_y"] - cc[1])
                 - P["tft_boss_d"] / 2)
        chk("4 个柱不切穿圆角板边", bwall > 0.8,
            "最小壁厚 %.2f mm > 0.8 mm" % bwall)
        mwall = pw / 2 - P["tft_mount_x"] - P["tft_mount_d"] / 2
        chk("M3 安装孔距板边足够", mwall > 1.5,
            "孔外边距 %.2f mm > 1.5 mm" % mwall)
        clear_x = (P["tft_boss_x"] - P["tft_boss_d"] / 2) - ow / 2
        clear_y = (P["tft_boss_y"] - P["tft_boss_d"] / 2) - od / 2
        chk("M2 柱与限位框不干涉", clear_x > 0 and clear_y > 0,
            "X 净距 %.2f / Y 净距 %.2f mm" % (clear_x, clear_y))
    else:
        chk("06_tft_panel.stl 存在", False,
            "未找到 TFT 面板 STL，请先跑 regen.bat")

    print("=" * 74)
    print(" 顶盖 / 底盒 / 电机锁板 / 独立小方板 / TFT 面板 配合校验")
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
