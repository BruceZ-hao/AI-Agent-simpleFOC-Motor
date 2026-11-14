# -*- coding: utf-8 -*-
"""
SimpleFOC 触觉旋钮整机外壳 —— Blender 5.3 参数化生成器

运行:
  blender --background --factory-startup --python enclosure.py
或双击 regen.bat

产出:
  stl/01_lower_case.stl   底盒（电子层：板卡槽、螺柱、散热格栅、USB/出线孔）
  stl/02_top_cover.stl    顶盖 / 电机座（沉台、四柱长槽、中心让位、按钮孔、散热孔）
  stl/03_knob.stl         可选旋钮（滚花 + 轴孔 + 紧定螺钉孔）
  render/01_assembled.png 成品渲染
  render/02_exploded.png  爆炸装配图
  render/03_interior.png  内部俯视（板卡布局）
  Enclosure.blend         Blender 源文件（含参考体：电机/编码器/两块板卡）
  build_report.txt        参数表、假设清单、BOM、装配步骤、网格自检

单位 mm。所有尺寸集中在 P 字典，量完实物改数字重跑即可。
几何内核：Blender 原生 EXACT 布尔 + Bevel，全部应用为单一实体。
"""

import math
import os
import struct
import bpy
import bmesh
from mathutils import Vector

OUT = os.path.dirname(os.path.abspath(__file__))
STL_DIR = os.path.join(OUT, "stl")
RENDER_DIR = os.path.join(OUT, "render")
os.makedirs(STL_DIR, exist_ok=True)
os.makedirs(RENDER_DIR, exist_ok=True)

# ======================================================================
#  参数区（mm）—— 实测后改这里
# ======================================================================
P = dict(
    # ---- 外形 ----
    case_w=110.0, case_d=76.0, case_h=36.0,
    wall=2.4, floor_t=2.4, corner_r=6.0,
    lid_t=3.0, lip_h=2.0, lip_gap=0.4,

    # ---- 四角螺柱 / 沉头螺钉 ----
    post_x=49.0, post_y=32.0,
    post_od=6.2, post_hole_d=2.6, post_hole_depth=12.0,
    lid_screw_d=3.4, lid_cs_d=6.4, lid_cs_h=1.8,

    # ---- 板卡固定（两块板都没有安装孔，只能边沿限位）----
    pad_h=3.0, pad_size=8.0,
    fence_w=2.0, fence_h=4.8, fence_len=12.0, fence_gap=0.35,
    esp32_center=(-18.0, -12.0), esp32_w=63.0, esp32_d=25.5, esp32_t=1.6,
    driver_center=(22.0, 12.0), driver_w=26.0, driver_d=21.0, driver_t=1.6,

    # ---- 开口 / 散热 ----
    usb_w=12.0, usb_h=5.0, usb_z=8.6,
    wire_d=8.0, wire_y=12.0, wire_z=14.0,
    vent_w=14.0, vent_h=2.6,
    vent_xs=(-36.0, -18.0, 0.0, 18.0, 36.0),
    vent_zs=(13.0, 19.0, 25.0),
    foot_d=8.0, foot_depth=1.0, foot_x=40.0, foot_y=26.0,

    # ---- 顶盖：电机座 ----
    motor_recess_d=42.0, motor_recess_h=0.8,
    axis_hole_d=12.0,
    pillar_slot_r0=12.0, pillar_slot_r1=19.0, pillar_slot_w=6.0,
    pillar_slot_angles=(45.0, 135.0, 225.0, 315.0),
    motor_wire_d=9.0, motor_wire_xy=(18.0, -14.0),
    lid_vent_d=3.2, lid_vent_x=34.0, lid_vent_y=20.0, lid_vent_dy=5.0,
    btn_d=4.0, btn_xy=((-43.0, -17.0), (-43.0, -7.0)),

    # ---- 可选旋钮 ----
    knob_d=38.0, knob_h=13.0, shaft_d=5.0,
    knob_relief_d=16.0, knob_relief_h=3.0,
    knob_dish_d=30.0, knob_dish_h=0.8,
    knurl_n=28, knurl_w=1.0, knurl_depth=0.6,
    set_screw_d=3.0, set_screw_z=5.0,

    # ---- 参考体（只用于 .blend / 渲染，不导出 STL）----
    ref_motor_d=28.0, ref_motor_h=22.0,
    ref_disc_d=34.0, ref_disc_h=3.0,
    ref_enc_d=30.0, ref_enc_t=1.6,
    ref_pillar_d=5.5, ref_pillar_h=9.0, ref_pillar_r=14.0,
    ref_shaft_d=5.0, ref_shaft_h=12.0,

    render_w=1200, render_h=900,
    circle_seg=32, corner_seg=6,
)

# ======================================================================
#  基础工具
# ======================================================================
def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for c in list(bpy.data.collections):
        if c.name != "Collection":
            bpy.data.collections.remove(c)


def collection(name):
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c


def move_to(obj, coll):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    coll.objects.link(obj)
    return obj


def material(name, rgb, rough=0.55, metal=0.0):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*rgb, 1.0)
    m.use_nodes = True
    bs = m.node_tree.nodes.get("Principled BSDF")
    if bs:
        bs.inputs["Base Color"].default_value = (*rgb, 1.0)
        bs.inputs["Roughness"].default_value = rough
        bs.inputs["Metallic"].default_value = metal
    return m


def shade(obj, mat):
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    obj.color = mat.diffuse_color
    return obj


def active(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def box(name, w, d, h, cx, cy, cz, coll=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(cx, cy, cz))
    o = bpy.context.object
    o.name = name
    o.dimensions = (w, d, h)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if coll:
        move_to(o, coll)
    return o


def cylinder(name, r, h, cx, cy, cz, verts=None, rot=None, coll=None):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=verts or P["circle_seg"], radius=r, depth=h,
        location=(cx, cy, cz), rotation=rot or (0, 0, 0))
    o = bpy.context.object
    o.name = name
    if coll:
        move_to(o, coll)
    return o


def rounded_box(name, w, d, h, cx, cy, z0, r, coll=None):
    """圆角长方体，底面在 z0。"""
    o = box(name, w, d, h, cx, cy, z0 + h / 2, coll)
    be = o.modifiers.new("outer_round", 'BEVEL')
    be.width = r
    be.segments = P["corner_seg"]
    be.limit_method = 'NONE'
    active(o)
    bpy.ops.object.modifier_apply(modifier=be.name)
    return o


def signed_area(poly):
    s = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        s += x0 * y1 - x1 * y0
    return 0.5 * s


def ccw(poly):
    return list(poly) if signed_area(poly) > 0 else list(poly)[::-1]


def prism(name, poly, z0, z1, coll=None):
    """任意 CCW 2D 轮廓沿 Z 拉伸成棱柱。"""
    poly = ccw(poly)
    n = len(poly)
    v = [(x, y, z0) for x, y in poly] + [(x, y, z1) for x, y in poly]
    f = [tuple(reversed(range(n))), tuple(range(n, 2 * n))]
    for i in range(n):
        j = (i + 1) % n
        f.append((i, j, j + n, i + n))
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(v, [], f)
    mesh.update()
    o = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(o)
    recalc(o)
    if coll:
        move_to(o, coll)
    return o


def rounded_rect_poly(w, d, r, seg=8):
    """XY 平面圆角矩形轮廓（CCW），用于内腔与唇边，避免直角与外圆角相交出碎面。"""
    pts = []
    for cx, cy, a0 in ((w / 2 - r, d / 2 - r, 0),
                       (-w / 2 + r, d / 2 - r, 90),
                       (-w / 2 + r, -d / 2 + r, 180),
                       (w / 2 - r, -d / 2 + r, 270)):
        for i in range(seg + 1):
            a = math.radians(a0 + 90.0 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return ccw(pts)


def capsule_poly(p0, p1, r, seg=12):
    """长圆孔（槽）的 2D 轮廓。"""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(dx, dy)
    a0 = math.atan2(dy, dx)
    pts = []
    for i in range(seg + 1):
        a = a0 - math.pi / 2 + math.pi * i / seg
        pts.append((p1[0] + r * math.cos(a), p1[1] + r * math.sin(a)))
    for i in range(seg + 1):
        a = a0 + math.pi / 2 + math.pi * i / seg
        pts.append((p0[0] + r * math.cos(a), p0[1] + r * math.sin(a)))
    return ccw(pts)


def capsule(name, p0, p1, w, z0, z1, coll=None):
    return prism(name, capsule_poly(p0, p1, w / 2.0), z0, z1, coll)


def recalc(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    # 布尔常在切点处留下零面积面 / 零长度边，导出时若简单丢弃会撕开相邻面的边配对
    try:
        bmesh.ops.dissolve_degenerate(bm, edges=list(bm.edges), dist=1e-5)
    except Exception:
        pass
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def join(objs, name):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    objs[0].name = name
    return objs[0]


def boolean(target, cutters, op='DIFFERENCE'):
    """逐个应用布尔。

    注意：不能把多个互相重叠的 cutter join 成一个网格再做 EXACT 布尔 ——
    重叠壳的 winding number 会相互抵消/叠加，把主体整个削掉（已实测）。
    逐个差分既幂等又稳定，代价只是多几次 modifier_apply。
    """
    for i, c in enumerate(cutters):
        m = target.modifiers.new("bool_%s_%02d" % (op, i), 'BOOLEAN')
        m.operation = op
        m.solver = 'EXACT'
        m.object = c
        active(target)
        bpy.ops.object.modifier_apply(modifier=m.name)
        bpy.data.objects.remove(c, do_unlink=True)
    recalc(target)
    return target


def mesh_stats(obj):
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    try:
        me.calc_loop_triangles()
    except Exception:
        pass
    ntri = len(me.loop_triangles)
    bm = bmesh.new()
    bm.from_mesh(me)
    nonmanifold = sum(1 for e in bm.edges if not e.is_manifold)
    boundary = sum(1 for e in bm.edges if e.is_boundary)
    try:
        vol = abs(bm.calc_volume(signed=True))
    except Exception:
        vol = 0.0
    bm.free()
    bb = [obj.matrix_world @ v.co for v in me.vertices]
    dims = (tuple(round(max(p[i] for p in bb) - min(p[i] for p in bb), 2)
                  for i in range(3)) if bb else (0, 0, 0))
    ev.to_mesh_clear()
    return dict(tris=ntri, nonmanifold=nonmanifold, boundary=boundary,
                volume_cm3=round(vol / 1000.0, 2), dims=dims)


def write_stl(obj, path):
    """自己写 binary STL：保持 Z-up，法线由叉积保证一致。"""
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    try:
        me.calc_loop_triangles()
    except Exception:
        pass
    vs = [obj.matrix_world @ v.co for v in me.vertices]
    # 写入全部三角形（含退化面），保证边配对完整；零面积面用兜底法线
    tris = []
    for t in me.loop_triangles:
        ia, ib, ic = tuple(t.vertices)
        n = (vs[ib] - vs[ia]).cross(vs[ic] - vs[ia])
        if n.length > 1e-12:
            n.normalize()
        else:
            n = Vector((0.0, 0.0, 1.0))
        tris.append((ia, ib, ic, n))
    header = b"SimpleFOC haptic knob enclosure - " + obj.name.encode("ascii", "replace")
    header = header[:80].ljust(80, b"\0")
    with open(path, "wb") as f:
        f.write(header)
        f.write(struct.pack("<I", len(tris)))
        for ia, ib, ic, n in tris:
            a, b, c = vs[ia], vs[ib], vs[ic]
            f.write(struct.pack("<12fH", n.x, n.y, n.z,
                                a.x, a.y, a.z, b.x, b.y, b.z, c.x, c.y, c.z, 0))
    ev.to_mesh_clear()
    return os.path.getsize(path)


# ======================================================================
#  零件 1：底盒
# ======================================================================
def build_lower(coll, mat):
    W, D, H = P["case_w"], P["case_d"], P["case_h"]
    wall, ft = P["wall"], P["floor_t"]
    shell = rounded_box("01_lower_case", W, D, H, 0, 0, 0, P["corner_r"], coll)

    # --- 第一批差集：内腔 + 侧壁开口 + 脚垫凹坑 ---
    cuts = []
    # 内腔底面必须严格落在底板上表面 z=ft，顶面超出盒口形成开口
    inner_h = H - ft + 3
    cuts.append(prism("cut_cavity",
                      rounded_rect_poly(W - 2 * wall, D - 2 * wall,
                                        P["corner_r"] - wall),
                      ft, ft + inner_h, coll))

    # 长侧壁散热格栅（±Y 两面）
    for sy in (-1, 1):
        for x in P["vent_xs"]:
            for z in P["vent_zs"]:
                cuts.append(box("cut_vent", P["vent_w"], wall + 3, P["vent_h"],
                                x, sy * (D / 2 - wall / 2), z, coll))

    # USB-C 开口（-X 端，对准 ESP32-S3 板）
    cuts.append(box("cut_usb", wall + 4, P["usb_w"], P["usb_h"],
                    -(W / 2 - wall / 2), P["esp32_center"][1], P["usb_z"], coll))

    # 12V / 电机线出线孔（+X 端，对准驱动板）
    cuts.append(cylinder("cut_wire", P["wire_d"] / 2, wall + 4,
                         W / 2 - wall / 2, P["wire_y"], P["wire_z"],
                         rot=(0, math.pi / 2, 0), coll=coll))

    # 底面脚垫凹坑
    for sx in (-1, 1):
        for sy in (-1, 1):
            cuts.append(cylinder("cut_foot", P["foot_d"] / 2, P["foot_depth"] + 2,
                                 sx * P["foot_x"], sy * P["foot_y"],
                                 P["foot_depth"] / 2 - 1, coll=coll))
    boolean(shell, cuts, 'DIFFERENCE')

    # --- 加法特征：板卡垫台 + L 形挡边 + 四角螺柱 ---
    adds = []
    for (bx, by), bw, bd in (
            (P["esp32_center"], P["esp32_w"], P["esp32_d"]),
            (P["driver_center"], P["driver_w"], P["driver_d"])):
        for sx in (-1, 1):
            for sy in (-1, 1):
                cx, cy = bx + sx * bw / 2, by + sy * bd / 2
                pad = P["pad_size"]
                # 垫台：位于板角内侧，顶面给板底排针让位
                adds.append(box("pad", pad, pad, P["pad_h"] + 0.2,
                                cx - sx * pad / 2, cy - sy * pad / 2,
                                ft + P["pad_h"] / 2 - 0.1, coll))
                # 沿 X 的挡边（在板的 ±Y 外侧）
                adds.append(box("fence_x", P["fence_len"], P["fence_w"], P["fence_h"] + 0.2,
                                cx - sx * P["fence_len"] / 2,
                                cy + sy * (P["fence_gap"] + P["fence_w"] / 2),
                                ft + P["fence_h"] / 2 - 0.1, coll))
                # 沿 Y 的挡边（在板的 ±X 外侧）
                adds.append(box("fence_y", P["fence_w"], P["fence_len"], P["fence_h"] + 0.2,
                                cx + sx * (P["fence_gap"] + P["fence_w"] / 2),
                                cy - sy * P["fence_len"] / 2,
                                ft + P["fence_h"] / 2 - 0.1, coll))

    for sx in (-1, 1):
        for sy in (-1, 1):
            adds.append(cylinder("post", P["post_od"] / 2, H - ft + 0.2,
                                 sx * P["post_x"], sy * P["post_y"],
                                 ft + (H - ft) / 2 - 0.1, coll=coll))
    boolean(shell, adds, 'UNION')

    # --- 第二批差集：螺柱自攻螺钉孔（穿过加法特征）---
    holes = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            holes.append(cylinder("cut_post_hole", P["post_hole_d"] / 2,
                                  P["post_hole_depth"] + 2,
                                  sx * P["post_x"], sy * P["post_y"],
                                  H - P["post_hole_depth"] / 2 + 1, coll=coll))
    boolean(shell, holes, 'DIFFERENCE')
    shade(shell, mat)
    return shell


# ======================================================================
#  零件 2：顶盖 / 电机座
# ======================================================================
def build_lid(coll, mat):
    W, D, H = P["case_w"], P["case_d"], P["case_h"]
    wall, lt = P["wall"], P["lid_t"]
    lid = rounded_box("02_top_cover", W, D, lt, 0, 0, H, P["corner_r"], coll)

    # 下表面定位唇边（插入底盒内腔）
    lip = prism("lip",
                rounded_rect_poly(W - 2 * wall - 2 * P["lip_gap"],
                                  D - 2 * wall - 2 * P["lip_gap"],
                                  P["corner_r"] - wall - P["lip_gap"]),
                H - P["lip_h"], H + 0.4, coll)
    boolean(lid, [lip], 'UNION')

    top = H + lt
    cuts = []

    # 电机沉台（Ø42，深 0.8）
    cuts.append(cylinder("cut_recess", P["motor_recess_d"] / 2,
                         P["motor_recess_h"] + 2, 0, 0,
                         top - P["motor_recess_h"] / 2 + 1, coll=coll))
    # 中心让位孔（编码器 / 轴端 / 磁铁）
    cuts.append(cylinder("cut_axis", P["axis_hole_d"] / 2, lt + 6,
                         0, 0, H + lt / 2, coll=coll))
    # 四根支撑柱的径向长槽（45° 方向）
    for a_deg in P["pillar_slot_angles"]:
        a = math.radians(a_deg)
        p0 = (P["pillar_slot_r0"] * math.cos(a), P["pillar_slot_r0"] * math.sin(a))
        p1 = (P["pillar_slot_r1"] * math.cos(a), P["pillar_slot_r1"] * math.sin(a))
        cuts.append(capsule("cut_pillar", p0, p1, P["pillar_slot_w"],
                            H - 2, top + 2, coll))
    # 电机三相线 + 编码器线束过孔
    cuts.append(cylinder("cut_motor_wire", P["motor_wire_d"] / 2, lt + 6,
                         P["motor_wire_xy"][0], P["motor_wire_xy"][1],
                         H + lt / 2, coll=coll))
    # 四角螺钉过孔 + 沉头
    for sx in (-1, 1):
        for sy in (-1, 1):
            x, y = sx * P["post_x"], sy * P["post_y"]
            cuts.append(cylinder("cut_lid_screw", P["lid_screw_d"] / 2, lt + 6,
                                 x, y, H + lt / 2, coll=coll))
            cuts.append(cylinder("cut_lid_cs", P["lid_cs_d"] / 2,
                                 P["lid_cs_h"] + 2, x, y,
                                 top - P["lid_cs_h"] / 2 + 1, coll=coll))
    # 顶盖散热孔（每角 3 个）
    for sx in (-1, 1):
        for sy in (-1, 1):
            for k in (-1, 0, 1):
                cuts.append(cylinder("cut_lid_vent", P["lid_vent_d"] / 2, lt + 6,
                                     sx * P["lid_vent_x"],
                                     sy * P["lid_vent_y"] + k * P["lid_vent_dy"],
                                     H + lt / 2, coll=coll))
    # 可选：BOOT / RESET 针孔（对准 ESP32-S3 板 USB 端附近的按键）
    for x, y in P["btn_xy"]:
        cuts.append(cylinder("cut_btn", P["btn_d"] / 2, lt + 6,
                             x, y, H + lt / 2, coll=coll))
    boolean(lid, cuts, 'DIFFERENCE')
    shade(lid, mat)
    return lid


# ======================================================================
#  零件 3：可选旋钮
# ======================================================================
def build_knob(coll, mat):
    d, h = P["knob_d"], P["knob_h"]
    # 旋钮套在电机轴上，位于白色转盘上方 1mm，避免与转盘干涉
    z0 = (P["case_h"] + P["lid_t"] + P["ref_enc_t"] + P["ref_motor_h"]
          + P["ref_disc_h"] + 1.0)
    knob = cylinder("03_knob", d / 2, h, 0, 0, z0 + h / 2,
                    verts=64, coll=coll)
    # 顶部轻微倒角
    be = knob.modifiers.new("knob_round", 'BEVEL')
    be.width = 1.2
    be.segments = 3
    be.limit_method = 'ANGLE'
    active(knob)
    bpy.ops.object.modifier_apply(modifier=be.name)

    cuts = []
    # 轴孔（通孔）
    cuts.append(cylinder("cut_shaft", P["shaft_d"] / 2, h + 4,
                         0, 0, z0 + h / 2, coll=coll))
    # 底部让位（避开电机轴端凸台 / 顶盖中心孔）
    cuts.append(cylinder("cut_relief", P["knob_relief_d"] / 2,
                         P["knob_relief_h"] + 2, 0, 0,
                         z0 + P["knob_relief_h"] / 2 - 1, coll=coll))
    # 顶面浅碟（指尖定位）
    cuts.append(cylinder("cut_dish", P["knob_dish_d"] / 2,
                         P["knob_dish_h"] + 2, 0, 0,
                         z0 + h - P["knob_dish_h"] / 2 + 1, coll=coll))
    # 侧向紧定螺钉孔
    r_out, r_in = d / 2, P["shaft_d"] / 2
    length = r_out - r_in + 2
    cuts.append(cylinder("cut_setscrew", P["set_screw_d"] / 2, length,
                         (r_out + r_in) / 2, 0,
                         z0 + P["set_screw_z"], rot=(0, math.pi / 2, 0), coll=coll))
    # 滚花
    for i in range(P["knurl_n"]):
        a = 2 * math.pi * i / P["knurl_n"]
        r = d / 2 - P["knurl_depth"] / 2 + 0.05
        o = box("cut_knurl", 2 * P["knurl_depth"], P["knurl_w"], h + 2,
                r * math.cos(a), r * math.sin(a), z0 + h / 2, coll)
        o.rotation_euler[2] = a
        cuts.append(o)
    boolean(knob, cuts, 'DIFFERENCE')
    shade(knob, mat)
    return knob


# ======================================================================
#  参考体（不导出 STL）
# ======================================================================
def build_references(coll, mats):
    top = P["case_h"] + P["lid_t"]
    objs = {}

    def add(o, key, m):
        shade(o, mats[m])
        objs[key] = o
        return o

    # 电机本体
    z0 = top + P["ref_enc_t"]
    add(cylinder("REF_motor_body", P["ref_motor_d"] / 2, P["ref_motor_h"],
                 0, 0, z0 + P["ref_motor_h"] / 2, verts=48, coll=coll),
        "motor", "motor")
    # 顶部白色转盘
    add(cylinder("REF_white_disc", P["ref_disc_d"] / 2, P["ref_disc_h"],
                 0, 0, z0 + P["ref_motor_h"] + P["ref_disc_h"] / 2,
                 verts=48, coll=coll), "disc", "white")
    # 轴
    add(cylinder("REF_shaft", P["ref_shaft_d"] / 2, P["ref_shaft_h"],
                 0, 0, z0 + P["ref_motor_h"] + P["ref_disc_h"] + P["ref_shaft_h"] / 2 - 2,
                 coll=coll), "shaft", "steel")
    # 底部编码器板
    add(cylinder("REF_encoder_pcb", P["ref_enc_d"] / 2, P["ref_enc_t"],
                 0, 0, top - P["motor_recess_h"] + P["ref_enc_t"] / 2,
                 verts=48, coll=coll), "encoder", "pcb")
    # 四根向下的尼龙支撑柱（穿过顶盖长槽）
    pillars = []
    for a_deg in P["pillar_slot_angles"]:
        a = math.radians(a_deg)
        r = P["ref_pillar_r"]
        pillars.append(cylinder("REF_pillar", P["ref_pillar_d"] / 2,
                                P["ref_pillar_h"],
                                r * math.cos(a), r * math.sin(a),
                                top - P["motor_recess_h"] - P["ref_pillar_h"] / 2,
                                coll=coll))
    add(join(pillars, "REF_pillars"), "pillars", "black")

    # ESP32-S3 DevKitC-1
    bx, by = P["esp32_center"]
    bz = P["floor_t"] + P["pad_h"] + P["esp32_t"] / 2
    add(box("REF_esp32_pcb", P["esp32_w"], P["esp32_d"], P["esp32_t"],
            bx, by, bz, coll), "esp32", "pcb_blue")
    add(box("REF_esp32_chip", 18, 18, 1.0, bx - 4, by, bz + 1.3, coll),
        "esp32_chip", "chip")
    add(box("REF_usb_c", 7.5, 9.0, 3.2,
            bx - P["esp32_w"] / 2 - 0.5, by, bz + 1.0, coll),
        "usb", "steel")
    # DengFOC-Mini
    dx, dy = P["driver_center"]
    dz = P["floor_t"] + P["pad_h"] + P["driver_t"] / 2
    add(box("REF_driver_pcb", P["driver_w"], P["driver_d"], P["driver_t"],
            dx, dy, dz, coll), "driver", "pcb")
    add(box("REF_driver_chip", 9, 9, 0.9, dx, dy, dz + 1.2, coll),
        "driver_chip", "chip")
    return objs


# ======================================================================
#  渲染
# ======================================================================
def setup_stage(mats):
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = P["render_w"]
    scene.render.resolution_y = P["render_h"]
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.film_transparent = False
    try:
        scene.eevee.taa_render_samples = 48
    except Exception:
        pass
    world = bpy.data.worlds.new("stage_world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.68, 0.72, 0.78, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.5
    scene.world = world

    bpy.ops.mesh.primitive_plane_add(size=500, location=(0, 0, -1.8))
    ground = bpy.context.object
    ground.name = "STAGE_ground"
    shade(ground, mats["ground"])

    for name, loc, energy, size in (
            ("key", (120, -140, 190), 2600, 90),
            ("fill", (-140, -60, 110), 700, 100),
            ("rim", (10, 150, 140), 1600, 80)):
        bpy.ops.object.light_add(type='AREA', location=loc)
        l = bpy.context.object
        l.name = "STAGE_light_" + name
        l.data.energy = energy
        l.data.shape = 'DISK'
        l.data.size = size

    bpy.ops.object.camera_add(location=(150, -170, 125))
    cam = bpy.context.object
    cam.name = "STAGE_camera"
    cam.data.lens = 50
    scene.camera = cam
    return cam, ground


def aim(cam, loc, target, ortho=None):
    cam.location = Vector(loc)
    cam.rotation_euler = (Vector(target) - cam.location).to_track_quat('-Z', 'Y').to_euler()
    if ortho:
        cam.data.type = 'ORTHO'
        cam.data.ortho_scale = ortho
    else:
        cam.data.type = 'PERSP'


def render(path, cam, loc, target, ortho=None):
    aim(cam, loc, target, ortho)
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return os.path.getsize(path)


def label(text, loc, cam, mat, size=4.6):
    bpy.ops.object.text_add(location=loc)
    t = bpy.context.object
    t.name = "LABEL_" + text.replace(" ", "_")
    t.data.body = text
    t.data.size = size
    t.data.extrude = 0.08
    t.data.align_x = 'CENTER'
    # 与相机同朝向：文字 +Z 正对镜头、+Y 朝屏幕上，不会倒字或镜像
    t.rotation_euler = cam.rotation_euler.copy()
    shade(t, mat)
    return t


# ======================================================================
#  主流程
# ======================================================================
def main():
    clear_scene()
    parts_coll = collection("01_PRINT_PARTS")
    ref_coll = collection("02_REFERENCE")
    helper = collection("03_HELPERS")

    mats = dict(
        case=material("外壳 - 深蓝灰", (0.10, 0.14, 0.20), 0.62),
        lid=material("顶盖 - 浅灰", (0.28, 0.33, 0.40), 0.58),
        knob=material("旋钮 - 橙", (0.95, 0.36, 0.07), 0.42),
        motor=material("电机 - 黑金属", (0.06, 0.07, 0.09), 0.38, 0.55),
        white=material("白色转盘", (0.95, 0.96, 0.97), 0.5),
        steel=material("金属件", (0.62, 0.65, 0.70), 0.3, 0.8),
        black=material("尼龙柱", (0.10, 0.10, 0.12), 0.7),
        pcb=material("PCB - 黑", (0.06, 0.13, 0.10), 0.65),
        pcb_blue=material("PCB - 深蓝", (0.07, 0.11, 0.22), 0.6),
        chip=material("芯片", (0.12, 0.12, 0.14), 0.45),
        ground=material("地面", (0.70, 0.73, 0.77), 0.9),
        inspect=material("检视 - 浅灰", (0.52, 0.57, 0.63), 0.8),
        text=material("标注", (0.10, 0.12, 0.16), 0.8),
    )

    lower = build_lower(parts_coll, mats["case"])
    lid = build_lid(parts_coll, mats["lid"])
    knob = build_knob(parts_coll, mats["knob"])
    refs = build_references(ref_coll, mats)

    print("=== BUILD DONE ===")
    for o in (lower, lid, knob):
        st = mesh_stats(o)
        print("  %-18s tris=%5d nonmanifold=%d boundary=%d vol=%.1f cm3 dims=%s"
              % (o.name, st["tris"], st["nonmanifold"], st["boundary"],
                 st["volume_cm3"], st["dims"]))

    # ---- 导出 STL ----
    exports = [
        (lower, "01_lower_case.stl"),
        (lid, "02_top_cover.stl"),
        (knob, "03_knob.stl"),
    ]
    stl_report = []
    for o, fn in exports:
        path = os.path.join(STL_DIR, fn)
        size = write_stl(o, path)
        st = mesh_stats(o)
        stl_report.append((fn, size, st))
        print("  STL %-22s %7d bytes" % (fn, size))

    # ---- 渲染 ----
    cam, ground = setup_stage(mats)
    r_assembled = render(os.path.join(RENDER_DIR, "01_assembled.png"), cam,
                         (150, -170, 125), (0, 0, 34))
    print("  RENDER assembled", r_assembled)

    # 内部俯视：隐藏顶盖 / 电机 / 旋钮 / 地面
    hidden = [lid, knob, refs["motor"], refs["disc"], refs["shaft"],
              refs["encoder"], refs["pillars"], ground]
    for o in hidden:
        o.hide_render = True
    # 检视视图临时用浅色底盒，让挡边 / 螺柱 / 内腔轮廓和深色 PCB 分开
    case_mat = lower.data.materials[0]
    lower.data.materials[0] = mats["inspect"]
    r_interior = render(os.path.join(RENDER_DIR, "03_interior.png"), cam,
                        (35, -75, 190), (0, 0, 6), ortho=150)
    print("  RENDER interior", r_interior)
    lower.data.materials[0] = case_mat
    for o in hidden:
        o.hide_render = False

    # 爆炸图
    offsets = dict(
        lower=(0, 0, 0), lid=(0, 0, 40), knob=(0, 0, 104),
        motor=(0, 0, 74), disc=(0, 0, 74), shaft=(0, 0, 74),
        encoder=(0, 0, 56), pillars=(0, 0, 56),
        esp32=(0, 0, 16), esp32_chip=(0, 0, 16), usb=(0, 0, 16),
        driver=(0, 0, 16), driver_chip=(0, 0, 16),
    )
    moved = [(lower, Vector((0, 0, 0))), (lid, Vector(offsets["lid"])),
             (knob, Vector(offsets["knob"]))]
    for k, o in refs.items():
        moved.append((o, Vector(offsets.get(k, (0, 0, 20)))))
    originals = [(o, o.location.copy()) for o, _ in moved]
    for o, v in moved:
        o.location += v

    cam.data.lens = 40
    aim(cam, (240, -280, 220), (0, 0, 90))   # 先把相机摆好，标签才能对齐朝向
    labels = [
        label("03  KNOB (optional)", (0, -30, 192), cam, mats["text"]),
        label("02  TOP COVER / MOTOR MOUNT", (0, -40, 86), cam, mats["text"]),
        label("MOTOR + ENCODER + 4 PILLARS", (0, -40, 148), cam, mats["text"]),
        label("ESP32-S3 DevKitC-1", (-20, -60, 26), cam, mats["text"], 4.0),
        label("DengFOC-Mini", (24, -60, 26), cam, mats["text"], 4.0),
        label("01  LOWER CASE", (0, -64, 4), cam, mats["text"]),
    ]
    r_exploded = render(os.path.join(RENDER_DIR, "02_exploded.png"), cam,
                        (240, -280, 220), (0, 0, 90))
    print("  RENDER exploded", r_exploded)
    for t in labels:
        bpy.data.objects.remove(t, do_unlink=True)
    cam.data.lens = 50
    for o, loc in originals:
        o.location = loc

    # ---- 保存 .blend（装配状态）----
    aim(cam, (150, -170, 125), (0, 0, 34))
    blend_path = os.path.join(OUT, "Enclosure.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print("  BLEND", os.path.getsize(blend_path))

    # ---- 报告 ----
    write_report(stl_report, blend_path, (r_assembled, r_exploded, r_interior))
    print("=== ALL DONE ===")


def write_report(stl_report, blend_path, renders):
    W, D, H = P["case_w"], P["case_d"], P["case_h"]
    top = H + P["lid_t"]
    lines = []
    A = lines.append
    A("=" * 66)
    A(" SimpleFOC 触觉旋钮 —— 整机外壳（Blender 5.3 参数化生成）")
    A("=" * 66)
    A("生成器 : enclosure.py   源文件 : Enclosure.blend")
    A("Blender: %s   单位: mm" % bpy.app.version_string)
    A("")
    A("【外形】")
    A("  底盒   %.1f x %.1f x %.1f mm（壁厚 %.1f，底厚 %.1f，圆角 R%.1f）"
      % (W, D, H, P["wall"], P["floor_t"], P["corner_r"]))
    A("  顶盖   %.1f x %.1f x %.1f mm，带 %.1f mm 定位唇边" % (W, D, P["lid_t"], P["lip_h"]))
    A("  总高（含电机与白色转盘，不含旋钮）约 %.1f mm" % (top + P["ref_enc_t"] + P["ref_motor_h"] + P["ref_disc_h"]))
    A("  电子层内净高 %.1f mm；电机装在顶盖上方，散热好、装配简单。" % (H - P["floor_t"]))
    A("")
    A("【四个关键结构】")
    A("  1) 板卡无固定孔 -> 四角 8x8 垫台 + L 形挡边限位，垫台抬高 %.1f mm 给板底排针让位。" % P["pad_h"])
    A("     ESP32-S3-DevKitC-1  %.1f x %.1f  中心 (%.1f, %.1f)" % (P["esp32_w"], P["esp32_d"], *P["esp32_center"]))
    A("     DengFOC-Mini          %.1f x %.1f  中心 (%.1f, %.1f)" % (P["driver_w"], P["driver_d"], *P["driver_center"]))
    A("  2) 顶盖中央 Ø%.1f 沉台 + 中心 Ø%.1f 让位孔 + 4 条 45° 径向长槽（宽 %.1f，半径 %.1f~%.1f）。"
      % (P["motor_recess_d"], P["axis_hole_d"], P["pillar_slot_w"],
         P["pillar_slot_r0"], P["pillar_slot_r1"]))
    A("     长槽对应照片里电机底部那 4 根向下的尼龙支撑柱，兼容对角孔距 24~38 mm。")
    A("  3) -X 侧壁 USB-C 开口 %.1f x %.1f（中心 z=%.1f），+X 侧壁 Ø%.1f 出线孔，"
      % (P["usb_w"], P["usb_h"], P["usb_z"], P["wire_d"]))
    A("     两侧壁各 15 条散热格栅，顶盖 12 个散热孔 + 2 个 BOOT/RESET 针孔。")
    A("  4) 四角 M3 螺柱 + 沉头螺钉固定顶盖；底面 4 个 Ø%.1f 橡胶脚垫凹坑。" % P["foot_d"])
    A("")
    A("【STL 自检】")
    total_bad = 0
    for fn, size, st in stl_report:
        total_bad += st["nonmanifold"] + st["boundary"]
        A("  %-22s %7d bytes | 三角 %5d | 非流形边 %3d | 边界边 %3d | 体积 %6.1f cm3 | 包围盒 %s"
          % (fn, size, st["tris"], st["nonmanifold"], st["boundary"],
             st["volume_cm3"], " x ".join(str(v) for v in st["dims"])))
    A("  判定: %s" % ("全部水密，可直接切片" if total_bad == 0 else "存在非流形边，请检查"))
    A("")
    A("【假设尺寸 —— 务必实测后改 P 字典再跑 regen.bat】")
    A("  - 电机本体 Ø%.1f x %.1f、白色转盘 Ø%.1f x %.1f、编码器板 Ø%.1f"
      % (P["ref_motor_d"], P["ref_motor_h"], P["ref_disc_d"], P["ref_disc_h"], P["ref_enc_d"]))
    A("  - 4 根支撑柱 Ø%.1f、长 %.1f、分布半径 %.1f（照片估算）"
      % (P["ref_pillar_d"], P["ref_pillar_h"], P["ref_pillar_r"]))
    A("  - 轴径 Ø%.1f（旋钮孔径），M3 紧定螺钉横孔 Ø%.1f"
      % (P["shaft_d"], P["set_screw_d"]))
    A("  - ESP32-S3 板 USB-C 端中心高度 z=%.1f；BOOT/RESET 针孔位置按常见 DevKitC-1 估计。" % P["usb_z"])
    A("  - 两块板卡尺寸沿用上次查证的标准值：63 x 25.5 / 26 x 21 mm。")
    A("")
    A("【五金 BOM】")
    A("  M3 x 12 沉头螺钉 x4（顶盖 -> 底盒螺柱，自攻进 Ø2.6 孔）")
    A("  M3 螺母 + 垫片(Ø10) x4（把电机 4 根支撑柱锁在顶盖长槽上；若柱内是 M3 螺纹则改用 M3x10 螺钉）")
    A("  橡胶脚垫 Ø8 x4、少量热熔胶（固定线束）、扎带 x2")
    A("  USB-C 数据线 x1、12V 电源线 x1（从 +X 出线孔引出）")
    A("")
    A("【打印建议】")
    A("  PLA 或 PETG；层高 0.2 mm；填充 20%；壁 3 圈；底盒开口朝上打印，无需支撑。")
    A("  顶盖沉台朝上；旋钮竖放（轴孔垂直），滚花朝外。")
    A("  螺柱自攻孔 Ø2.6 若太紧可用 M3 丝锥或 3.0 钻头轻扩。")
    A("")
    A("【装配顺序】")
    A("  1. 底盒朝上，把 ESP32-S3 与 DengFOC-Mini 按挡边位置压到垫台上。")
    A("  2. 12V 电源线从 +X 出线孔穿入并接到驱动板；三相线 + 编码器线从顶盖 Ø9 过孔穿入。")
    A("  3. 电机 4 根支撑柱对准顶盖长槽插入，从盒内侧用螺母/垫片或螺钉锁紧。")
    A("  4. 盖上顶盖（唇边插入内腔），四角拧入 M3x12 沉头螺钉。")
    A("  5. 白色转盘即现成旋钮；若要更大握持感，套上 03_knob.stl 并用 M3 紧定螺钉固定。")
    A("")
    A("【与固件的配合 / 安全】")
    A("  - 上电 initFOC() 会让电机正反各走一个电周期，务必让旋钮自由、别用手捏住。")
    A("  - 校准需 12V 与三相线都接好；失败会打印 Failed to notice movement 并卡住，按 RESET 重来。")
    A("  - 手扭住不放时电机持续堵转输出，MP6536 会发热，不用时发 T0 并断 12V。")
    A("  - 重烧固件前关闭上位机 / IDE 串口监视器，释放串口。")
    A("  - 本外壳与之前的 MountBracket 三板支架是两套独立方案，二选一即可。")
    A("")
    A("【渲染图】")
    for name, size in zip(("01_assembled.png", "02_exploded.png", "03_interior.png"), renders):
        A("  render/%-20s %7d bytes" % (name, size))
    A("  源文件 %s (%d bytes)" % (os.path.basename(blend_path), os.path.getsize(blend_path)))
    A("")
    A("改参数：打开 enclosure.py 顶部的 P 字典 -> 双击 regen.bat -> STL / 渲染 / 报告一起刷新。")
    A("=" * 66)

    path = os.path.join(OUT, "build_report.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("  REPORT", os.path.getsize(path))


if __name__ == "__main__":
    main()
