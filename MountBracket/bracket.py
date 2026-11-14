# -*- coding: utf-8 -*-
"""
SimpleFOC 触觉旋钮台架 —— 参数化 3D 打印支架生成器

零依赖：只用 Python 标准库。改下面的参数区，运行 `regen.bat` 即可重新导出。

输出：
  stl/01_base_plate.stl    底板 / 电子层（板卡角码 + 立柱孔 + 走线孔）
  stl/02_motor_plate.stl   电机顶板（中心让位孔 + 4 条径向长槽）
  stl/03_sensor_plate.stl  AS5600 托板（中心观察孔 + M2 长槽 + 减重窗）
  stl/04_post_lower.stl    备选打印立柱 - 下段（单根，需 4 根）
  stl/05_post_upper.stl    备选打印立柱 - 上段（单根，需 4 根，长度按气隙自动算）
  stl/plates_preview.svg   三块板 1:1 俯视图，打印前核对孔位用
  stl/assembly.svg         侧视装配图 + 层高 + 五金 BOM + 装配步骤
  stl/build_report.txt     网格自检报告（水密性 / 体积 / 尺寸 / 层高 / BOM）

几何内核：2D 轮廓（外环 CCW + 洞环 CW）沿 Z 拉伸。
顶/底面用「扫描线梯形分解」三角化，侧壁按同样的扫描线切分，
因此顶底边界与侧壁严格一一对应，输出水密流形。
"""

import math
import os
import struct
from collections import defaultdict

# ======================================================================
#  参数区：所有尺寸单位 mm。量完实物改这里即可，其余代码不用动。
# ======================================================================
P = dict(
    # ---- 三块板共用的外形与立柱 ----
    plate_w        = 130.0,   # 板长 X
    plate_d        = 85.0,    # 板宽 Y
    plate_t        = 4.0,     # 板厚
    corner_r       = 5.0,     # 板角圆角
    post_inset     = 9.0,     # 立柱孔中心距板边 -> (±56, ±33.5)
    post_hole_d    = 3.4,     # M3 螺杆过孔
    mount_inset    = 3.5,     # 桌面固定孔距板角
    mount_hole_d   = 4.0,     # 桌面固定孔（M3 盘头 / 自攻）
    wire_hole_d    = 6.0,     # 通用走线 / 扎带孔

    # ---- 底板：两块板卡（无安装孔，用四角角码限位）----
    # (名称, 中心X, 中心Y, 长X, 宽Y)
    boards         = [
        ("ESP32-S3-DevKitC-1", 0.0, -16.0, 63.0, 25.5),
        ("DengFOC-Mini",       0.0,  18.0, 26.0, 21.0),
    ],
    pad_size       = 8.0,     # 角码垫台边长
    pad_h          = 3.0,     # 垫台高（给板底排针让位）
    fence_w        = 2.0,     # 挡边宽
    fence_h        = 3.0,     # 挡边高（高出垫台）
    fence_len      = 12.0,    # 挡边长度
    fence_gap      = 0.35,    # 挡边与板边的间隙（打印余量）

    # ---- 电机顶板 ----
    motor_center_d = 10.0,    # 中心让位孔（电机底部凸台/轴）；若凸台更大就调大并同步调槽起点
    motor_slot_r0  = 8.5,     # 径向长槽内端半径
    motor_slot_r1  = 17.5,    # 径向长槽外端半径
    motor_slot_w   = 3.4,     # 槽宽（M3）
    motor_wire_d   = 8.0,     # 三相线过孔
    motor_wire_x   = 24.0,

    # ---- AS5600 托板 ----
    sensor_center_d = 16.0,   # 中央观察孔：芯片朝下从这里露出，正对磁铁
    sensor_slot_r0  = 10.5,   # M2 径向长槽内端（兼容四角孔距 15~19mm）
    sensor_slot_r1  = 14.0,
    sensor_slot_w   = 2.2,    # 槽宽（M2）
    win_w           = 28.0,   # 减重窗
    win_h           = 20.0,
    win_x           = 34.0,
    win_y           = 18.0,
    win_r           = 3.0,

    # ---- 备选打印立柱（主方案用 M3 螺杆，不需要打印这个）----
    post_d         = 8.0,
    post_len       = 30.0,
    tenon_d        = 3.0,     # 两端定位榫，插进 Ø3.4 孔
    tenon_len      = 4.0,

    # ---- 装配层高（只写进报告，不影响 STL 几何）----
    gap_electronics = 30.0,   # 底板顶面 -> 电机顶板底面
    motor_body_h    = 20.0,   # 电机本体高度（假设，实测后改）
    magnet_above    = 4.0,    # 磁铁顶面高出电机本体的距离
    target_gap      = 1.5,    # AS5600 芯片到磁铁的目标气隙（0.5~3mm）
    sensor_pcb_t    = 1.6,    # AS5600 模块 PCB 厚度
    chip_protrude   = 1.0,    # 芯片凸出 PCB 下表面的高度
    board_pcb_t     = 1.6,    # 板卡 PCB 厚度

    # ---- 离散化精度 ----
    circle_seg     = 24,      # 圆孔多边形段数
    corner_seg     = 6,       # 圆角弧段数
    slot_seg       = 10,      # 长圆槽端部半圆段数
)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stl")


# ======================================================================
#  2D 几何工具
# ======================================================================
def signed_area(poly):
    s = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return s * 0.5


def as_ccw(poly):
    return list(poly) if signed_area(poly) > 0 else list(poly)[::-1]


def as_cw(poly):
    return list(poly) if signed_area(poly) < 0 else list(poly)[::-1]


def rect(cx, cy, w, h):
    """轴对齐矩形"""
    x0, x1 = cx - w / 2, cx + w / 2
    y0, y1 = cy - h / 2, cy + h / 2
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def rounded_rect(cx, cy, w, h, r, seg=None):
    """圆角矩形，CCW"""
    seg = seg or P["corner_seg"]
    r = min(r, w / 2 - 0.01, h / 2 - 0.01)
    x0, x1 = cx - w / 2, cx + w / 2
    y0, y1 = cy - h / 2, cy + h / 2
    corners = [
        (x1 - r, y0 + r, -90.0, 0.0),
        (x1 - r, y1 - r, 0.0, 90.0),
        (x0 + r, y1 - r, 90.0, 180.0),
        (x0 + r, y0 + r, 180.0, 270.0),
    ]
    pts = []
    for ax, ay, a0, a1 in corners:
        for i in range(seg + 1):
            a = math.radians(a0 + (a1 - a0) * i / seg)
            pts.append((ax + r * math.cos(a), ay + r * math.sin(a)))
    return pts


def circle(cx, cy, r, seg=None):
    seg = seg or P["circle_seg"]
    return [(cx + r * math.cos(-2 * math.pi * i / seg),
             cy + r * math.sin(-2 * math.pi * i / seg)) for i in range(seg)]


def capsule(p0, p1, r, seg=None):
    """长圆槽（胶囊形），中心线 p0 -> p1"""
    seg = seg or P["slot_seg"]
    a0 = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    pts = []
    for i in range(seg + 1):
        a = a0 - math.pi / 2 + math.pi * i / seg
        pts.append((p1[0] + r * math.cos(a), p1[1] + r * math.sin(a)))
    for i in range(seg + 1):
        a = a0 + math.pi / 2 + math.pi * i / seg
        pts.append((p0[0] + r * math.cos(a), p0[1] + r * math.sin(a)))
    return pts


def radial_slot(angle_deg, r0, r1, width):
    a = math.radians(angle_deg)
    u = (math.cos(a), math.sin(a))
    return capsule((r0 * u[0], r0 * u[1]), (r1 * u[0], r1 * u[1]), width / 2)


def dehorizontalize(rings):
    """把水平边的一端 Y 抬起 0.05mm，消除水平边。

    这样每个 slab 的梯形上/下水平边都落在材料内部（相邻 slab 互相配对），
    所有外边界都落在斜边上，顶底边界与侧壁才能严格一一对应。
    0.05mm 远小于 FDM 层高/线宽，成品尺寸看不出差别；但必须远大于
    binary STL 的 float32 量化误差（坐标 ±65mm 处约 4e-6 mm），
    否则极窄三角形写进文件后法线会翻转。
    """
    out = [list(r) for r in rings]
    eps = 0.05
    for r in out:
        n = len(r)
        for i in range(n):
            j = (i + 1) % n
            if abs(r[j][1] - r[i][1]) < 1e-9:
                x, y = r[j]
                # 扰动方向朝板中心，避免外轮廓超出标称 130×85 尺寸
                inward = 1.0 if y < 0 else -1.0
                r[j] = (x, y + inward * eps * (1 + 0.001 * i))
    return out


# ======================================================================
#  网格内核
# ======================================================================
def _cross(u, v):
    return (u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _x_at(p0, p1, y):
    dy = p1[1] - p0[1]
    if abs(dy) < 1e-12:
        return p0[0]
    return p0[0] + (y - p0[1]) * (p1[0] - p0[0]) / dy


class Mesh:
    def __init__(self, name):
        self.name = name
        self.tris = []
        self.prism_count = 0

    def tri(self, a, b, c, want):
        u = _sub(b, a)
        v = _sub(c, a)
        n = _cross(u, v)
        d = n[0] * want[0] + n[1] * want[1] + n[2] * want[2]
        if abs(d) < 1e-12:          # 退化三角形，丢弃
            return
        if d < 0:
            b, c = c, b
        self.tris.append((a, b, c))

    def quad(self, a, b, c, d, want):
        self.tri(a, b, c, want)
        self.tri(a, c, d, want)

    def prism(self, outer, holes, z0, z1, tag=""):
        """把一个 2D 区域（外环 + 若干洞）沿 Z 拉伸成封闭实体"""
        rings = dehorizontalize([as_ccw(outer)] + [as_cw(h) for h in holes])
        rings = [as_ccw(rings[0])] + [as_cw(r) for r in rings[1:]]
        self.prism_count += 1

        ys = sorted({y for r in rings for (_, y) in r})
        # 合并数值上几乎相同的扫描线
        merged = [ys[0]]
        for y in ys[1:]:
            if y - merged[-1] > 1e-7:
                merged.append(y)
        ys = merged

        edges = []   # (p0, p1, 方向向量)
        for r in rings:
            n = len(r)
            for i in range(n):
                p0, p1 = r[i], r[(i + 1) % n]
                if abs(p1[1] - p0[1]) < 1e-12:
                    continue        # 理论上已被 dehorizontalize 消除
                edges.append((p0, p1))

        # ---- 侧壁：每条边按扫描线切分 ----
        for p0, p1 in edges:
            ylo, yhi = min(p0[1], p1[1]), max(p0[1], p1[1])
            cuts = [y for y in ys if ylo - 1e-7 <= y <= yhi + 1e-7]
            if len(cuts) < 2:
                continue
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]
            want = (dy, -dx, 0.0)   # 统一外法线公式（外环 CCW / 洞环 CW 均成立）
            for ya, yb in zip(cuts, cuts[1:]):
                xa, xb = _x_at(p0, p1, ya), _x_at(p0, p1, yb)
                self.quad((xa, ya, z0), (xb, yb, z0),
                          (xb, yb, z1), (xa, ya, z1), want)

        # ---- 顶 / 底面：逐 slab 做扫描线梯形分解 ----
        # 第一遍：求出每个 slab 的成对交点，记录梯形在上下两条扫描线上的 X 区间
        slabs = []
        for ya, yb in zip(ys, ys[1:]):
            ym = 0.5 * (ya + yb)
            cs = []
            for p0, p1 in edges:
                if (p0[1] <= ym < p1[1]) or (p1[1] <= ym < p0[1]):
                    cs.append((_x_at(p0, p1, ym), p0, p1))
            cs.sort(key=lambda e: e[0])
            if len(cs) % 2:
                raise RuntimeError("[%s/%s] slab y=%.6f 交点数为奇数，检查洞是否相交"
                                   % (self.name, tag, ym))
            pairs = []
            for k in range(0, len(cs), 2):
                L, R = cs[k], cs[k + 1]
                pairs.append((_x_at(L[1], L[2], ya), _x_at(R[1], R[2], ya),
                              _x_at(L[1], L[2], yb), _x_at(R[1], R[2], yb)))
            slabs.append((ya, yb, pairs))

        # 第二遍：每条扫描线收集全局 X 断点。
        # 洞的起止会让上下相邻 slab 的水平边端点不一致（T-junction），
        # 用统一断点把每个梯形沿 X 切成若干子梯形，边界就能严格配对。
        xcuts = defaultdict(set)
        for i, (ya, yb, pairs) in enumerate(slabs):
            for xLa, xRa, xLb, xRb in pairs:
                xcuts[i].update((round(xLa, 7), round(xRa, 7)))
                xcuts[i + 1].update((round(xLb, 7), round(xRb, 7)))
        xcuts = {k: sorted(v) for k, v in xcuts.items()}

        # 第三遍：上下边界各自按全局断点切分，用 zigzag 条带三角化连接。
        # 这样每条水平边的端点都来自 xcuts[k]，相邻 slab 严格对齐。
        def split_edge(lo, hi, y, cuts):
            pts = [(lo, y)]
            for x in cuts:
                if lo + 1e-6 < x < hi - 1e-6:
                    pts.append((x, y))
            pts.append((hi, y))
            return pts

        def strip_tris(A, D):
            """A=下边界点(左->右), D=上边界点(左->右)，返回三角形集合"""
            m, n = len(A) - 1, len(D) - 1
            i = j = 0
            out = []
            while i < m or j < n:
                if i < m and (j == n or A[i + 1][0] <= D[j + 1][0] + 1e-9):
                    out.append((A[i], A[i + 1], D[j]))
                    i += 1
                else:
                    out.append((A[i], D[j + 1], D[j]))
                    j += 1
            return out

        for i, (ya, yb, pairs) in enumerate(slabs):
            for xLa, xRa, xLb, xRb in pairs:
                A = split_edge(xLa, xRa, ya, xcuts.get(i, ()))
                D = split_edge(xLb, xRb, yb, xcuts.get(i + 1, ()))
                for p, q, r in strip_tris(A, D):
                    for z, nz in ((z1, 1.0), (z0, -1.0)):
                        self.tri((p[0], p[1], z), (q[0], q[1], z),
                                 (r[0], r[1], z), (0, 0, nz))

    # ------------------------------------------------------------------
    def validate(self):
        """流形自检：每条无向边必须恰好出现 2 次且方向相反；有符号体积 > 0"""
        directed = defaultdict(int)
        vol = 0.0
        xyz = []
        for a, b, c in self.tris:
            xyz.extend((a, b, c))
            for p, q in ((a, b), (b, c), (c, a)):
                kp = (round(p[0], 5), round(p[1], 5), round(p[2], 5))
                kq = (round(q[0], 5), round(q[1], 5), round(q[2], 5))
                directed[(kp, kq)] += 1
            vol += (a[0] * (b[1] * c[2] - b[2] * c[1])
                    + a[1] * (b[2] * c[0] - b[0] * c[2])
                    + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
        undirected = defaultdict(int)
        for (kp, kq), cnt in directed.items():
            undirected[(kp, kq) if kp <= kq else (kq, kp)] += cnt
        bad = sum(1 for v in undirected.values() if v != 2)
        # 方向相反检查
        opposite = sum(1 for (kp, kq) in directed
                       if directed.get((kq, kp), 0) != directed[(kp, kq)])
        bb = (min(p[0] for p in xyz), max(p[0] for p in xyz),
              min(p[1] for p in xyz), max(p[1] for p in xyz),
              min(p[2] for p in xyz), max(p[2] for p in xyz))
        return dict(tris=len(self.tris), prisms=self.prism_count,
                    bad_edges=bad, bad_direction=opposite,
                    volume=vol, bbox=bb)

    def save(self, path):
        with open(path, "wb") as f:
            hdr = ("SimpleFOC Mount Bracket - %s" % self.name).encode("ascii", "replace")
            f.write(hdr[:80].ljust(80, b"\0"))
            f.write(struct.pack("<I", len(self.tris)))
            for a, b, c in self.tris:
                n = _cross(_sub(b, a), _sub(c, a))
                L = math.sqrt(sum(x * x for x in n)) or 1.0
                n = (n[0] / L, n[1] / L, n[2] / L)
                f.write(struct.pack("<12fH", n[0], n[1], n[2],
                                    a[0], a[1], a[2],
                                    b[0], b[1], b[2],
                                    c[0], c[1], c[2], 0))


# ======================================================================
#  零件
# ======================================================================
def post_points():
    hx = P["plate_w"] / 2 - P["post_inset"]
    hy = P["plate_d"] / 2 - P["post_inset"]
    return [(sx * hx, sy * hy) for sx in (-1, 1) for sy in (-1, 1)]


def mount_points():
    hx = P["plate_w"] / 2 - P["mount_inset"]
    hy = P["plate_d"] / 2 - P["mount_inset"]
    return [(sx * hx, sy * hy) for sx in (-1, 1) for sy in (-1, 1)]


def wire_points():
    return [(0.0, P["plate_d"] / 2 - 5.5), (0.0, -(P["plate_d"] / 2 - 5.5)),
            (-P["motor_wire_x"] - 21.0, 0.0), (P["motor_wire_x"] + 21.0, 0.0)]


def plate_outline():
    return rounded_rect(0, 0, P["plate_w"], P["plate_d"], P["corner_r"])


def common_holes():
    return ([circle(x, y, P["post_hole_d"] / 2) for x, y in post_points()]
            + [circle(x, y, P["mount_hole_d"] / 2) for x, y in mount_points()]
            + [circle(x, y, P["wire_hole_d"] / 2) for x, y in wire_points()])


def board_fences(mesh, cx, cy, w, h):
    """给一块无安装孔的板卡做 4 组角码：垫台（排针让位）+ L 形挡边（XY 限位）"""
    t = P["plate_t"]
    pad = P["pad_size"]
    fw = P["fence_w"]
    gap = P["fence_gap"]
    fl = P["fence_len"]
    for sx in (-1, 1):
        for sy in (-1, 1):
            ex = cx + sx * w / 2
            ey = cy + sy * h / 2
            # 垫台：向板内侧偏 2mm，内侧 6mm 托住板角
            mesh.prism(rect(ex - sx * (pad / 2 - 2), ey - sy * (pad / 2 - 2), pad, pad),
                       [], t - 0.4, t + P["pad_h"], "pad")
            off = gap + fw / 2
            z0 = t + P["pad_h"] - 0.4
            z1 = t + P["pad_h"] + P["fence_h"]
            # 沿 X 的挡边（贴在板卡上/下边外侧）
            mesh.prism(rect(ex - sx * (fl / 2 - 2), ey + sy * off, fl, fw),
                       [], z0, z1, "fenceX")
            # 沿 Y 的挡边（贴在板卡左/右边外侧）
            mesh.prism(rect(ex + sx * off, ey - sy * (fl / 2 - 2), fw, fl),
                       [], z0, z1, "fenceY")


def make_base():
    m = Mesh("01_base_plate")
    m.prism(plate_outline(), common_holes(), 0.0, P["plate_t"], "base")
    for name, cx, cy, w, h in P["boards"]:
        board_fences(m, cx, cy, w, h)
    return m


def make_motor_plate():
    m = Mesh("02_motor_plate")
    holes = ([circle(x, y, P["post_hole_d"] / 2) for x, y in post_points()]
             + [circle(0, 0, P["motor_center_d"] / 2)]
             + [radial_slot(a, P["motor_slot_r0"], P["motor_slot_r1"], P["motor_slot_w"])
                for a in (45, 135, 225, 315)]
             + [circle(x, 0, P["motor_wire_d"] / 2)
                for x in (-P["motor_wire_x"], P["motor_wire_x"])])
    m.prism(plate_outline(), holes, 0.0, P["plate_t"], "motor_plate")
    return m


def make_sensor_plate():
    m = Mesh("03_sensor_plate")
    holes = ([circle(x, y, P["post_hole_d"] / 2) for x, y in post_points()]
             + [circle(0, 0, P["sensor_center_d"] / 2)]
             + [radial_slot(a, P["sensor_slot_r0"], P["sensor_slot_r1"], P["sensor_slot_w"])
                for a in (45, 135, 225, 315)]
             + [rounded_rect(sx * P["win_x"], sy * P["win_y"],
                             P["win_w"], P["win_h"], P["win_r"])
                for sx in (-1, 1) for sy in (-1, 1)])
    m.prism(plate_outline(), holes, 0.0, P["plate_t"], "sensor_plate")
    return m


def layer_heights():
    """装配层高（只用于图纸/报告，不改变 STL 几何）"""
    t = P["plate_t"]
    z_motor_bottom = t + P["gap_electronics"]
    z_motor_top = z_motor_bottom + t
    z_magnet_top = z_motor_top + P["motor_body_h"] + P["magnet_above"]
    # 芯片朝下：PCB 上表面贴托板下表面，芯片凸出 PCB 下表面
    z_sensor_bottom = (z_magnet_top + P["target_gap"]
                       + P["sensor_pcb_t"] + P["chip_protrude"])
    return dict(z_motor_bottom=z_motor_bottom, z_motor_top=z_motor_top,
                z_magnet_top=z_magnet_top, z_sensor_bottom=z_sensor_bottom,
                z_sensor_top=z_sensor_bottom + t)


def make_post(length, name):
    m = Mesh(name)
    m.prism(circle(0, 0, P["post_d"] / 2), [], 0.0, length, "shaft")
    m.prism(circle(0, 0, P["tenon_d"] / 2), [],
            -P["tenon_len"] + 0.4, 0.4, "tenon_bottom")
    m.prism(circle(0, 0, P["tenon_d"] / 2), [],
            length - 0.4, length + P["tenon_len"] - 0.4, "tenon_top")
    return m


# ======================================================================
#  1:1 俯视图（SVG）
# ======================================================================
def _svg_path(rings, scale=2.0, ox=0.0, oy=0.0):
    def fmt(x, y):
        return "%.2f,%.2f" % (ox + x * scale, oy - y * scale)
    parts = []
    for r in rings:
        parts.append("M" + " L".join(fmt(x, y) for x, y in r) + " Z")
    return " ".join(parts)


def write_preview(parts):
    s = P["circle_seg"]
    layouts = [
        ("01 底板 / 电子层", make_base_rings()),
        ("02 电机顶板", make_motor_plate_rings()),
        ("03 AS5600 托板", make_sensor_plate_rings()),
    ]
    scale = 2.0
    cw_, ch_ = P["plate_w"] * scale, P["plate_d"] * scale
    margin, gap = 40, 46
    W = 2 * margin + 3 * cw_ + 2 * gap
    H = 2 * margin + ch_ + 90
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
           'viewBox="0 0 %d %d" font-family="Segoe UI, Microsoft YaHei, sans-serif">'
           % (W, H, W, H)]
    svg.append('<rect width="100%%" height="100%%" fill="#f7f8fa"/>')
    svg.append('<text x="%d" y="26" font-size="16" font-weight="600" fill="#1a1d21">'
               'SimpleFOC 台架 — 三块板 1:1 俯视图（单位 mm，可直接量图核对）</text>' % margin)
    for i, (title, rings) in enumerate(layouts):
        ox = margin + i * (cw_ + gap) + cw_ / 2
        oy = margin + ch_ + 20
        svg.append('<g transform="translate(0,0)">')
        svg.append('<text x="%.1f" y="%.1f" font-size="12" fill="#495057" '
                   'text-anchor="middle">%s</text>' % (ox, margin + 24, title))
        d = _svg_path([as_ccw(rings[0])] + [as_cw(r) for r in rings[1:]],
                      scale, ox, oy)
        svg.append('<path d="%s" fill="#dfe6ee" fill-rule="evenodd" '
                   'stroke="#2d3742" stroke-width="1.2"/>' % d)
        # 中心十字
        svg.append('<path d="M%.1f %.1f h14 M%.1f %.1f v14" stroke="#e05252" '
                   'stroke-width="1" opacity="0.8"/>'
                   % (ox - 7, oy, ox, oy - 7))
        svg.append('</g>')
    note = [
        "外形 130 × 85 × 4 mm ｜ 四角 Ø3.4 立柱孔 (X=±56, Y=±33.5) ｜ 四角 Ø4 桌面固定孔 ｜ Ø6 走线孔",
        "底板：角码垫台高 3mm（给 DevKitC-1 底面排针让位），L 形挡边限位 63×25.5 / 26×21 两块无孔板卡",
        "电机顶板：中心 Ø10 让位孔 + 4 条径向长槽 (r=8.5~17.5, 宽 3.4 / M3)，适配对角孔距 17~35mm",
        "AS5600 托板：中心 Ø16 观察孔 + 4 条 M2 径向长槽 (r=10.5~14)，芯片朝下从孔中露出正对磁铁",
    ]
    for i, t in enumerate(note):
        svg.append('<text x="%d" y="%d" font-size="11.5" fill="#495057">%s</text>'
                   % (margin, margin + ch_ + 50 + i * 17, t))
    svg.append('</svg>')
    path = os.path.join(OUT_DIR, "plates_preview.svg")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(svg))
    return path


def make_base_rings():
    rings = [plate_outline()] + common_holes()
    t = P["plate_t"]
    for name, cx, cy, w, h in P["boards"]:
        for sx in (-1, 1):
            for sy in (-1, 1):
                ex, ey = cx + sx * w / 2, cy + sy * h / 2
                fw, fl, gap = P["fence_w"], P["fence_len"], P["fence_gap"]
                off = gap + fw / 2
                rings.append(rect(ex - sx * (fl / 2 - 2), ey + sy * off, fl, fw))
                rings.append(rect(ex + sx * off, ey - sy * (fl / 2 - 2), fw, fl))
    return rings


def make_motor_plate_rings():
    return ([plate_outline()]
            + [circle(x, y, P["post_hole_d"] / 2) for x, y in post_points()]
            + [circle(0, 0, P["motor_center_d"] / 2)]
            + [radial_slot(a, P["motor_slot_r0"], P["motor_slot_r1"], P["motor_slot_w"])
               for a in (45, 135, 225, 315)]
            + [circle(x, 0, P["motor_wire_d"] / 2)
               for x in (-P["motor_wire_x"], P["motor_wire_x"])])


def make_sensor_plate_rings():
    return ([plate_outline()]
            + [circle(x, y, P["post_hole_d"] / 2) for x, y in post_points()]
            + [circle(0, 0, P["sensor_center_d"] / 2)]
            + [radial_slot(a, P["sensor_slot_r0"], P["sensor_slot_r1"], P["sensor_slot_w"])
               for a in (45, 135, 225, 315)]
            + [rounded_rect(sx * P["win_x"], sy * P["win_y"],
                            P["win_w"], P["win_h"], P["win_r"])
               for sx in (-1, 1) for sy in (-1, 1)])


def write_assembly_svg(H, upper_len):
    """侧视装配图 + 层高标注 + BOM / 步骤"""
    W, Ht = 1120, 680
    scale, ox, oy = 3.0, 275.0, 545.0

    def X(x):
        return ox + x * scale

    def Y(z):
        return oy - z * scale

    def box(x0, x1, z0, z1, fill, rx=0, stroke="#2f3a45", sw=1.2):
        return (f'<rect x="{X(x0):.2f}" y="{Y(z1):.2f}" '
                f'width="{(x1 - x0) * scale:.2f}" height="{(z1 - z0) * scale:.2f}" '
                f'rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')

    def vline(x, z0, z1, color="#8895a3", sw=1.5, dash=""):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        return (f'<line x1="{X(x):.2f}" y1="{Y(z0):.2f}" x2="{X(x):.2f}" '
                f'y2="{Y(z1):.2f}" stroke="{color}" stroke-width="{sw}"{d}/>')

    def dim(x, z0, z1, label, color="#c05621"):
        s = [f'<line x1="{X(x):.2f}" y1="{Y(z0):.2f}" x2="{X(x):.2f}" '
             f'y2="{Y(z1):.2f}" stroke="{color}" stroke-width="1"/>']
        for z in (z0, z1):
            s.append(f'<line x1="{X(x) - 5:.2f}" y1="{Y(z):.2f}" '
                     f'x2="{X(x) + 5:.2f}" y2="{Y(z):.2f}" stroke="{color}" stroke-width="1"/>')
        s.append(f'<text x="{X(x) + 9:.2f}" y="{Y((z0 + z1) / 2) + 4:.2f}" '
                 f'font-size="11" fill="{color}">{label}</text>')
        return "".join(s)

    t = P["plate_t"]
    zm = H["z_motor_top"]
    zg = H["z_magnet_top"]
    zs = H["z_sensor_bottom"]
    zc = zs - P["sensor_pcb_t"] - P["chip_protrude"]   # 芯片底面

    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{Ht}" '
         f'viewBox="0 0 {W} {Ht}" font-family="Segoe UI, Microsoft YaHei, sans-serif">',
         f'<rect width="100%" height="100%" fill="#f7f8fa"/>',
         '<defs><marker id="ar" markerWidth="8" markerHeight="8" refX="4" refY="4" '
         'orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="#c05621"/></marker></defs>',
         f'<text x="30" y="34" font-size="19" font-weight="600" fill="#1a1d21">'
         f'SimpleFOC 触觉旋钮台架 — 装配侧视图</text>',
         f'<text x="30" y="56" font-size="12" fill="#5b6672">'
         f'X-Z 剖面（沿板长方向）｜ 三块 130×85×4 mm 板 + 4 根 M3 长螺杆 ｜ 尺寸单位 mm</text>',
         '<line x1="575" y1="24" x2="575" y2="656" stroke="#d8dee6" stroke-width="1"/>',
         ]

    # --- 螺杆（背景）---
    for px in (-56, 56):
        s.append(vline(px, -4, H["z_sensor_top"] + 6, "#9aa6b2", 2.0))
    s.append(f'<text x="{X(56) - 105:.1f}" y="{Y(H["z_sensor_top"] + 5):.1f}" '
             f'font-size="10.5" fill="#7a8794">M3 螺杆 + 螺母 ×4</text>')

    # --- 底板 + 电子层 ---
    s.append(box(-65, 65, 0, t, "#dfe6ee", rx=2))
    for px in (-29, 29):
        s.append(box(px - 3, px + 3, t, t + P["pad_h"], "#c5d2df", rx=1))
    s.append(box(-31.5, 31.5, t + P["pad_h"],
                 t + P["pad_h"] + P["board_pcb_t"], "#80b78f", rx=1))
    s.append(f'<text x="{X(0):.1f}" y="{Y(t + P["pad_h"] + 0.8) + 3:.1f}" '
             f'font-size="10" fill="#1f3d2b" text-anchor="middle">'
             f'ESP32-S3-DevKitC-1 + DengFOC-Mini（角码限位，底面排针悬空）</text>')
    s.append(f'<text x="{X(-65):.1f}" y="{Y(0) + 20:.1f}" font-size="11" '
             f'fill="#2f3a45">01 底板 / 电子层</text>')

    # --- 电机顶板 ---
    s.append(box(-65, 65, H["z_motor_bottom"], zm, "#dfe6ee", rx=2))
    s.append(box(-5, 5, H["z_motor_bottom"], zm, "#f7f8fa", stroke="none", sw=0))
    s.append(f'<text x="{X(-65):.1f}" y="{Y(H["z_motor_bottom"]) - 6:.1f}" '
             f'font-size="11" fill="#2f3a45">02 电机顶板（中心 Ø{P["motor_center_d"]:.0f} 让位孔 + 4 条径向长槽）</text>')

    # --- 电机 + 磁铁 ---
    s.append(box(-14, 14, zm, zm + P["motor_body_h"], "#b9c7d6", rx=4))
    s.append(f'<text x="{X(0):.1f}" y="{Y(zm + P["motor_body_h"] / 2) + 4:.1f}" '
             f'font-size="10.5" fill="#263445" text-anchor="middle">无刷云台电机</text>')
    s.append(box(-2, 2, zm + P["motor_body_h"], zg - 2, "#8e9dac", rx=1))
    s.append(box(-4, 4, zg - 2, zg, "#cf5c5c", rx=1))
    s.append(f'<text x="{X(6):.1f}" y="{Y(zg - 1) + 3:.1f}" font-size="10" '
             f'fill="#a03b3b">径向充磁磁铁</text>')

    # --- AS5600 板（芯片朝下）+ 托板 ---
    s.append(box(-11.5, 11.5, zs - P["sensor_pcb_t"], zs, "#80b78f", rx=1))
    s.append(box(-2.5, 2.5, zc, zs - P["sensor_pcb_t"], "#3f6f52", rx=0.5))
    s.append(box(-65, 65, zs, H["z_sensor_top"], "#dfe6ee", rx=2))
    s.append(box(-8, 8, zs, H["z_sensor_top"], "#f7f8fa", stroke="none", sw=0))
    s.append(f'<text x="{X(-65):.1f}" y="{Y(H["z_sensor_top"]) - 7:.1f}" '
             f'font-size="11" fill="#2f3a45">03 AS5600 托板（中央 Ø{P["sensor_center_d"]:.0f} 观察孔，芯片朝下）</text>')
    s.append(f'<text x="{X(14):.1f}" y="{Y(zs - 0.8) + 3:.1f}" font-size="10" '
             f'fill="#1f3d2b">AS5600 模块（芯片面朝下）</text>')

    # --- 气隙标注（按真实比例只有几像素，用引线拉到空白处写清楚）---
    gap_y0, gap_y1 = Y(zc), Y(zg)
    mid = (gap_y0 + gap_y1) / 2
    s.append(f'<line x1="{X(0):.1f}" y1="{gap_y1:.1f}" x2="{X(0):.1f}" '
             f'y2="{gap_y0:.1f}" stroke="#c05621" stroke-width="1.4"/>')
    for gy in (gap_y0, gap_y1):
        s.append(f'<line x1="{X(0) - 4:.1f}" y1="{gy:.1f}" '
                 f'x2="{X(0) + 4:.1f}" y2="{gy:.1f}" stroke="#c05621" stroke-width="1.2"/>')
    s.append(f'<line x1="{X(0):.1f}" y1="{mid:.1f}" x2="{X(-16):.1f}" '
             f'y2="{mid:.1f}" stroke="#c05621" stroke-width="1" stroke-dasharray="3 2"/>')
    s.append(f'<text x="{X(-17):.1f}" y="{mid + 4:.1f}" font-size="11" '
             f'font-weight="600" fill="#c05621" text-anchor="end">'
             f'气隙 {zc - zg:.1f} mm（螺母微调，目标 0.5~3）</text>')

    # --- 层高尺寸线 ---
    s.append(dim(-72, t, H["z_motor_bottom"], f"电子层净空 {P['gap_electronics']:.0f}"))
    s.append(dim(-72, zm, zs, f"电机层 {zs - zm:.1f}"))
    s.append(f'<text x="30" y="{Y(-6) + 8:.1f}" font-size="10.5" fill="#7a8794">'
             f'z=0 为底板底面；层高由 M3 螺母无级调节，气隙不需要垫片也能对准</text>')

    # --- 右侧：BOM + 步骤 ---
    rx = 600
    lines = [
        ("装配顺序", 17, "#1a1d21", 0),
        ("1  底板平放，4 根 M3 螺杆从下方穿入四角孔，底部拧螺母当支脚。", 12, "#374151", 22),
        ("2  把 ESP32-S3 与 DengFOC-Mini 放进角码（板底排针悬空）；", 12, "#374151", 19),
        ("   角码处点一点热熔胶防脱。接好三相线、共地、12V 与 USB。", 12, "#374151", 18),
        ("3  套上 02 电机顶板，用 8 个螺母夹住，板下留 30mm 净空。", 12, "#374151", 22),
        ("4  电机坐到顶板中央，M3 螺丝沿 4 条径向长槽滑动对准底部孔距。", 12, "#374151", 19),
        ("   轴端装径向充磁磁铁，磁铁顶面朝上、与芯片平行。", 12, "#374151", 18),
        ("5  套上 03 托板：AS5600 芯片面朝下，用 4 颗 M2 螺丝穿过", 12, "#374151", 22),
        ("   径向长槽固定，芯片正好从中央观察孔露出。", 12, "#374151", 18),
        ("6  上下拧螺母微调托板高度，把芯片到磁铁的气隙调到 1~2mm，", 12, "#374151", 19),
        ("   左右微调 AS5600 板让芯片正对磁铁中心，然后锁紧。", 12, "#374151", 18),
        ("", 12, "#374151", 14),
        ("五金 BOM", 15, "#1a1d21", 12),
        (f"M3 长螺杆 ×4（≥{H['z_sensor_top'] + 8:.0f}mm）+ 螺母 ×16 + 垫片 ×8", 12, "#374151", 20),
        ("M3×8 ×4（电机底座，若电机是 M2 螺纹加垫片）", 12, "#374151", 18),
        ("M2×10 ×4 + M2 螺母 ×4（AS5600 板）", 12, "#374151", 18),
        ("M3×10 ×4（底板锁桌面 / 洞洞板，可选）", 12, "#374151", 18),
        ("", 12, "#374151", 12),
        ("备选：不用螺杆时打印 04/05 立柱（各 4 根）", 14, "#1a1d21", 12),
        (f"下段 {P['post_len']:.1f}mm / 上段 {upper_len:.1f}mm，两端 Ø3 榫插入板孔；",
         12, "#374151", 19),
        ("少量胶固定，气隙靠薄垫片微调。", 12, "#374151", 18),
        ("", 12, "#374151", 10),
        ("关键提醒", 15, "#1a1d21", 12),
        ("• 两块板卡都没有安装孔，只能用角码边沿限位，别想着打孔。", 12, "#8a4b12", 19),
        ("• 芯片必须正对磁铁中心且平行；同心度差会让闭环角度非线性。", 12, "#8a4b12", 19),
        ("• 上电 initFOC() 会正反各转一下，保持 12V、三相接好、轴空转。", 12, "#8a4b12", 19),
        ("• 电机线、传感器线、USB 都从 Ø6 走线孔引出并扎好，别缠住转轴。", 12, "#8a4b12", 19),
    ]
    yy = 92
    for text, size, color, dy in lines:
        yy += dy
        weight = ' font-weight="600"' if size >= 14 else ""
        s.append(f'<text x="{rx}" y="{yy}" font-size="{size}" fill="{color}"{weight}>{text}</text>')

    s.append('</svg>')
    path = os.path.join(OUT_DIR, "assembly.svg")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(s))
    return path


# ======================================================================
#  主流程
# ======================================================================
def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    H = layer_heights()
    upper_len = H["z_sensor_bottom"] - H["z_motor_top"]
    parts = [
        ("01_base_plate.stl", make_base()),
        ("02_motor_plate.stl", make_motor_plate()),
        ("03_sensor_plate.stl", make_sensor_plate()),
        ("04_post_lower.stl", make_post(P["post_len"], "04_post_lower")),
        ("05_post_upper.stl", make_post(upper_len, "05_post_upper")),
    ]
    lines = ["SimpleFOC 台架 STL 自检报告", "=" * 58]
    ok = True
    for fname, mesh in parts:
        path = os.path.join(OUT_DIR, fname)
        r = mesh.validate()
        mesh.save(path)
        bb = r["bbox"]
        watertight = (r["bad_edges"] == 0 and r["bad_direction"] == 0
                      and r["volume"] > 0)
        ok = ok and watertight
        lines.append("%-24s %s" % (fname, "PASS" if watertight else "FAIL"))
        lines.append("  三角面 %6d ｜ 拉伸体 %2d ｜ 体积 %10.1f mm^3"
                     % (r["tris"], r["prisms"], r["volume"]))
        lines.append("  包围盒 X %.2f..%.2f  Y %.2f..%.2f  Z %.2f..%.2f mm"
                     % bb)
        lines.append("  未配对边 %d ｜ 方向异常 %d ｜ 文件 %.1f KB"
                     % (r["bad_edges"], r["bad_direction"],
                        os.path.getsize(path) / 1024.0))

    t = P["plate_t"]
    zchip = H["z_sensor_bottom"] - P["sensor_pcb_t"] - P["chip_protrude"]
    lines += ["", "装配层高建议（主方案：4 根 M3 长螺杆 + 螺母）", "-" * 58]
    lines.append("  底板                z = 0 .. %.1f" % t)
    lines.append("  板卡角码垫台顶面    z = %.1f  (板底排针向下到 z=%.1f，离底板顶面 %.1fmm)"
                 % (t + P["pad_h"], t + P["pad_h"] - 2.5, P["pad_h"] - 2.5))
    lines.append("  电机顶板底面        z = %.1f  (电子层净空 %.1f)"
                 % (H["z_motor_bottom"], P["gap_electronics"]))
    lines.append("  电机顶板顶面        z = %.1f" % H["z_motor_top"])
    lines.append("  磁铁顶面（估算）    z = %.1f" % H["z_magnet_top"])
    lines.append("  AS5600 托板下表面   z = %.1f" % H["z_sensor_bottom"])
    lines.append("  AS5600 芯片底面     z = %.1f  -> 气隙 %.1f mm (目标 0.5~3)"
                 % (zchip, zchip - H["z_magnet_top"]))
    lines.append("  托板上表面          z = %.1f  -> 螺杆需 >= %.0f mm"
                 % (H["z_sensor_top"], H["z_sensor_top"] + 8))
    lines.append("  下段立柱长 %.1f / 上段立柱长 %.1f（打印立柱备选方案，各 4 根）"
                 % (P["post_len"], upper_len))
    lines += [
        "", "五金 BOM", "-" * 58,
        "  M3 长螺杆 x4（长度 >= %.0f mm）+ M3 螺母 x16 + 垫片 x8" % (H["z_sensor_top"] + 8),
        "  M3x8 螺丝 x4：电机底座 -> 顶板径向长槽（若电机是 M2 螺纹，加垫片或改槽宽）",
        "  M2x10 螺丝 x4 + M2 螺母 x4：AS5600 板芯片朝下固定在托板下表面",
        "  M3x10 x4：把底板锁到桌面 / 洞洞板（可选）",
        "  热熔胶或双面胶少许：板卡角码处防脱（板卡本身无安装孔，靠角码限位）",
        "", "参数联动约束（改参数时务必一起改）", "-" * 58,
        "  1) motor_center_d 调大时，motor_slot_r0 需 > motor_center_d/2 + motor_slot_w/2 + 1",
        "     否则长槽与中心孔相交，会出现非流形网格（生成器会直接报错）。",
        "  2) sensor_slot_r0 需 > sensor_center_d/2 + sensor_slot_w/2 + 1（同理）。",
        "  3) 改 motor_body_h / magnet_above / target_gap 会同步刷新层高、上段立柱长度与图纸。",
        "  4) 板卡尺寸改了要检查角码挡边不与四角立柱孔 (X=±%.1f, Y=±%.1f) 相撞。"
        % (P["plate_w"] / 2 - P["post_inset"], P["plate_d"] / 2 - P["post_inset"]),
        "", "注意：motor_body_h / magnet_above / sensor_pcb_t 均为假设值，实测后改 P 里对应参数，",
        "      重新运行 regen.bat 会同步刷新 STL、层高、BOM 与两张图纸。",
    ]
    lines.append("")
    lines.append("总判定: %s" % ("全部水密，可切片" if ok else "存在异常，请检查上方 FAIL 项"))

    svg = write_preview(parts)
    asm = write_assembly_svg(H, upper_len)
    lines.append("图纸: %s / %s" % (os.path.basename(svg), os.path.basename(asm)))

    report = os.path.join(OUT_DIR, "build_report.txt")
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
