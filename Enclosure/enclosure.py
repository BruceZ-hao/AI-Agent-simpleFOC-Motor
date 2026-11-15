# -*- coding: utf-8 -*-
"""
SimpleFOC 触觉旋钮整机外壳 —— Blender 5.3 参数化生成器

运行:
  blender --background --factory-startup --python enclosure.py
或双击 regen.bat

产出:
  stl/01_lower_case.stl   底盒（完整平底内腔，无板卡槽；四角螺柱、散热格栅、USB/出线/电源开关孔）
                          三块板（ESP32 / 驱动板 / 5x3.5cm 电源模块）排针朝下直接堆放
  stl/02_top_cover.stl    顶盖 / 电机座（沉台、四柱长槽、中心让位、按钮孔、散热孔）
  stl/03_knob.stl         可选旋钮（滚花 + 轴孔 + 紧定螺钉孔）
  stl/04_motor_lock_plate.stl  ★ 电机锁板（与 02 顶盖二选一）：4 个精确铜柱孔
                          + 板底六角螺母沉腔，把电机 4 根铜柱真正锁死
  stl/05_standalone_motor_plate.stl  ★ 独立小方板（完全脱离外壳）：60x60，
                          同样 4 个铜柱孔 + 六角沉腔，四角通用安装孔
  render/01_assembled.png 成品渲染
  render/02_exploded.png  爆炸装配图
  render/03_interior.png  内部俯视（三块板卡堆放布局）
  render/04_fit.png       结合细节（顶盖抬高，正交展示口沿 / 螺柱 / 同宽外形）
  render/05_lip.png       顶盖底面仰视特写（橙色标注四条直唇边 + 四角给螺柱让位）
  render/06_lock_plate.png 电机锁板爆炸示意（铜柱 / 锁板 / 六角螺母的锁止关系）
  render/07_lock_underside.png 锁板底面仰视（橙色高亮 4 个六角螺母沉腔）
  render/08_standalone_plate.png 独立小方板顶面俯视（4 铜柱孔 + 4 安装孔 + 中心/线束孔）
  render/09_standalone_underside.png 独立小方板底面仰视（六角沉腔 + 四角安装孔）
  Enclosure.blend         Blender 源文件（含参考体：电机/编码器/ESP32/驱动板/电源模块）
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
    # 结合方式：底盒 z=H 处是平齐口沿，顶盖底面同高、整面贴合；
    # 四条直唇边插入内腔起 XY 定位作用，四角让位给螺柱。
    lid_t=3.0,
    lip_h=2.0, lip_gap=0.4, lip_w=2.0, lip_post_clear=0.3,

    # ---- 四角螺柱 / 沉头螺钉 ----
    post_x=49.0, post_y=32.0,
    post_od=6.2, post_hole_d=2.6, post_hole_depth=12.0,
    lid_screw_d=3.4, lid_cs_d=6.4, lid_cs_h=1.8,

    # ---- 板卡：三块板都无固定孔、排针朝下，平底直接堆放，不做任何定位槽 ----
    # pin_h 只是「排针高度」，仅用于渲染参考体的摆放高度，STL 里不产生任何凸起
    pin_h=2.5,
    esp32_center=(-18.0, -12.0), esp32_w=63.0, esp32_d=25.5, esp32_t=1.6,
    driver_center=(-28.0, 15.0), driver_w=26.0, driver_d=21.0, driver_t=1.6,
    # 5 x 3.5 cm 电源模块 = 50 x 35 mm；竖放后实际占位 X=35 / Y=50
    psu_center=(32.0, 0.0), psu_w=50.0, psu_d=35.0, psu_t=1.6,
    psu_rotate=True,

    # ---- 开口 / 散热 ----
    usb_w=12.0, usb_h=5.0, usb_z=8.6,
    wire_d=8.0, wire_y=12.0, wire_z=14.0,
    # 侧边电源开关口（+X 侧壁，靠近电源模块；与 Ø8 出线孔错开 Y）
    # "round" = 拨动开关圆形开孔 / "rect" = 船型开关矩形开孔 / "none" = 不开孔
    sw_shape="round", sw_d=6.5,
    sw_rect_w=19.0, sw_rect_h=13.0,   # 船型开孔：沿侧壁 Y 宽 x 竖直 Z 高
    sw_y=-18.0, sw_z=16.0,
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

    # ---- 电机锁板（04_motor_lock_plate.stl；与 02 顶盖二选一打印）----
    # 四根铜柱穿过 4 个精确圆孔，M3 六角螺母嵌在板底六角沉腔里防转，拧紧即锁死电机。
    # 顶盖的 4 条长槽只是让位（能滑动）；锁板是真正把电机固定住的那块板。
    lock_t=5.0,                    # 板厚：沉腔深 2.6 后仍有 2.4mm 承力
    lock_post_r=14.0,              # 铜柱中心到板中心距离，★实测后改这里
    lock_post_angles=(45.0, 135.0, 225.0, 315.0),
    lock_hole_d=3.4,               # M3 铜柱 / M3 螺钉过孔
    lock_nut_af=5.8,               # 六角沉腔对边（M3 螺母对边 5.5 + 0.3 间隙）
    lock_nut_h=2.6,                # 沉腔深（M3 螺母厚约 2.4）
    # "round" = 4 个精确圆孔锁死（默认）；"slot" = 4 条径向长槽，免实测兼容孔距
    lock_hole_mode="round",
    lock_slot_r0=10.0, lock_slot_r1=22.0, lock_slot_w=6.0,

    # ---- 05 独立电机小方板（完全脱离外壳，单独一块板锁住电机）----
    # 铜柱孔 / 六角沉腔 / 长槽全部复用上面那组 lock_* 参数：量一次孔距，
    # 04 锁板与 05 独立板一起对；这里只定义「板本身」的外形与安装方式。
    # 与外壳没有任何装配关系：没有 110x76 轮廓、没有唇边、没有沉头孔位。
    mini_w=60.0, mini_d=60.0, mini_t=5.0, mini_r=5.0,
    # 四角安装孔：默认 (±25, ±25) 正好落在 R5 圆角圆心上，四周壁厚均匀 2.9mm。
    # 用 M4 螺钉 + 螺母把板锁到桌面 / 支架 / 型材上；板尺寸改了要同步改这里。
    mini_mount_d=4.2, mini_mount_x=25.0, mini_mount_y=25.0,
    mini_axis_d=12.0,              # 中心让位孔（编码器磁铁 / 轴端）
    mini_wire_d=9.0, mini_wire_xy=(0.0, -20.0),  # 三相线 + 编码器线过孔
    mini_blend_x=150.0,            # .blend 里把独立板摆到底盒旁边，避免视觉重叠

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
    """【已弃用，勿用于装配面】整盒 BEVEL 圆角。

    薄件（如 3mm 顶盖）的圆角宽度会被 clamp，上下表面被削成斜面，
    盒口平面消失、外轮廓缩小到比内腔还窄，顶盖与底盒无法贴合。
    外壳 / 顶盖一律用 prism(rounded_rect_poly(...)) 生成精确圆角棱柱。
    此函数仅为历史参考保留。
    """
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


def rounded_rect_poly(w, d, r, seg=None):
    """XY 平面圆角矩形轮廓（CCW），用于外形 / 内腔 / 唇边。

    所有轮廓必须共用同一 seg 和同一圆角圆心，否则外框、内腔、唇边
    在角部是不同多边形近似的圆弧，配合间隙会忽大忽小甚至干涉。
    """
    if seg is None:
        seg = P["corner_seg"] * 2
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


def hex_poly(cx, cy, af, rot=0.0):
    """正六边形轮廓（对边 af），用于 M3 螺母防转沉腔。

    外接圆半径 R = af / sqrt(3)；rot=30° 时有一对边平行于 X，便于摆放。
    """
    R = af / math.sqrt(3.0)
    a0 = math.radians(rot)
    return ccw([(cx + R * math.cos(a0 + k * math.pi / 3.0),
                 cy + R * math.sin(a0 + k * math.pi / 3.0))
                for k in range(6)])


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
    # 精确圆角棱柱：侧壁一直垂直延伸到 z=H，盒口留出平齐环形承托面。
    # 不能用 BEVEL 削整个盒子 —— 3mm 量级的圆角会把薄壁顶/底面削成斜面，
    # 外轮廓在盒口处缩小到比内腔还小，侧壁被内腔切穿，顶盖无处落脚。
    shell = prism("01_lower_case", rounded_rect_poly(W, D, P["corner_r"]),
                  0, H, coll)

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

    # 12V / 电机线出线孔（+X 端，对准电源模块）
    cuts.append(cylinder("cut_wire", P["wire_d"] / 2, wall + 4,
                         W / 2 - wall / 2, P["wire_y"], P["wire_z"],
                         rot=(0, math.pi / 2, 0), coll=coll))

    # 侧边电源开关口（+X 端，与出线孔错开 Y）
    if P["sw_shape"] == "round":
        cuts.append(cylinder("cut_switch", P["sw_d"] / 2, wall + 4,
                             W / 2 - wall / 2, P["sw_y"], P["sw_z"],
                             rot=(0, math.pi / 2, 0), coll=coll))
    elif P["sw_shape"] == "rect":
        cuts.append(box("cut_switch", wall + 4, P["sw_rect_w"], P["sw_rect_h"],
                        W / 2 - wall / 2, P["sw_y"], P["sw_z"], coll))

    # 底面脚垫凹坑
    for sx in (-1, 1):
        for sy in (-1, 1):
            cuts.append(cylinder("cut_foot", P["foot_d"] / 2, P["foot_depth"] + 2,
                                 sx * P["foot_x"], sy * P["foot_y"],
                                 P["foot_depth"] / 2 - 1, coll=coll))
    boolean(shell, cuts, 'DIFFERENCE')

    # --- 加法特征：只有四角螺柱 ---
    # 内腔保持完整平底：三块板排针朝下直接堆放，不做垫台 / 挡边 / 定位槽，
    # 板子位置完全自由，也不占用内腔净高。
    adds = []
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
    # 与底盒完全相同的 XY 圆角轮廓：叠装后侧面齐平，底面 z=H 是完整平面，
    # 正好压在底盒口沿 + 四角螺柱顶面上（三者共面，零缝贴合）。
    lid = prism("02_top_cover", rounded_rect_poly(W, D, P["corner_r"]),
                H, H + lt, coll)

    # 定位唇边 = 四条直条，插入内腔 lip_h mm，单边留 lip_gap 间隙。
    # 四角必须空出来：螺柱顶面 z=H 要直接顶住顶盖底面当支撑，
    # 唇边若连到角上就与螺柱实体重叠，顶盖压不下去。
    gap, lw = P["lip_gap"], P["lip_w"]
    ox = W / 2 - wall - gap
    oy = D / 2 - wall - gap
    clear = P["post_od"] / 2 + P["lip_post_clear"]
    len_x = 2 * (P["post_x"] - clear)
    len_y = 2 * (P["post_y"] - clear)
    strips = []
    for sy in (-1, 1):
        strips.append(box("lip_x", len_x, lw, P["lip_h"] + 0.4,
                          0, sy * (oy - lw / 2),
                          H - P["lip_h"] / 2 + 0.2, coll))
    for sx in (-1, 1):
        strips.append(box("lip_y", lw, len_y, P["lip_h"] + 0.4,
                          sx * (ox - lw / 2), 0,
                          H - P["lip_h"] / 2 + 0.2, coll))
    boolean(lid, strips, 'UNION')

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
#  零件 4：电机锁板（与顶盖二选一打印）
# ======================================================================
def build_lock_plate(coll, mat):
    """四根铜柱穿过 4 个精确圆孔，M3 六角螺母嵌在板底沉腔里防转。

    顶盖的 4 条径向长槽只是让位（电机还能沿槽滑动 / 扭动时窜位）；
    锁板把铜柱位置定死，拧紧螺母后电机与板成为一个整体，板再锁到底盒上。
    外形、唇边、螺钉孔与顶盖完全一致，所以两块板可互换装配位。
    """
    W, D, H = P["case_w"], P["case_d"], P["case_h"]
    wall, lt = P["wall"], P["lock_t"]
    plate = prism("04_motor_lock_plate",
                  rounded_rect_poly(W, D, P["corner_r"]), H, H + lt, coll)

    # 四条定位唇边：与顶盖同一套参数，四角让位给螺柱
    gap, lw = P["lip_gap"], P["lip_w"]
    ox = W / 2 - wall - gap
    oy = D / 2 - wall - gap
    clear = P["post_od"] / 2 + P["lip_post_clear"]
    strips = []
    for sy in (-1, 1):
        strips.append(box("lip_x", 2 * (P["post_x"] - clear), lw,
                          P["lip_h"] + 0.4, 0, sy * (oy - lw / 2),
                          H - P["lip_h"] / 2 + 0.2, coll))
    for sx in (-1, 1):
        strips.append(box("lip_y", lw, 2 * (P["post_y"] - clear),
                          P["lip_h"] + 0.4, sx * (ox - lw / 2), 0,
                          H - P["lip_h"] / 2 + 0.2, coll))
    boolean(plate, strips, 'UNION')

    top = H + lt
    cuts = []

    # 电机沉台 + 中心让位孔（编码器磁铁 / 轴端）
    cuts.append(cylinder("cut_recess", P["motor_recess_d"] / 2,
                         P["motor_recess_h"] + 2, 0, 0,
                         top - P["motor_recess_h"] / 2 + 1, coll=coll))
    cuts.append(cylinder("cut_axis", P["axis_hole_d"] / 2, lt + 6,
                         0, 0, H + lt / 2, coll=coll))

    # ★ 核心：4 根铜柱的锁止孔
    for a_deg in P["lock_post_angles"]:
        a = math.radians(a_deg)
        x, y = P["lock_post_r"] * math.cos(a), P["lock_post_r"] * math.sin(a)
        if P["lock_hole_mode"] == "slot":
            p0 = (P["lock_slot_r0"] * math.cos(a), P["lock_slot_r0"] * math.sin(a))
            p1 = (P["lock_slot_r1"] * math.cos(a), P["lock_slot_r1"] * math.sin(a))
            cuts.append(capsule("cut_lock_slot", p0, p1, P["lock_slot_w"],
                                H - 2, top + 2, coll))
        else:
            # M3 过孔贯通；板底六角沉腔容纳螺母，螺母不会跟着螺杆打转
            cuts.append(cylinder("cut_lock_post", P["lock_hole_d"] / 2,
                                 lt + 6, x, y, H + lt / 2, coll=coll))
            cuts.append(prism("cut_lock_nut",
                              hex_poly(x, y, P["lock_nut_af"], rot=30.0),
                              H - 0.2, H + P["lock_nut_h"], coll))

    # 线束过孔
    cuts.append(cylinder("cut_motor_wire", P["motor_wire_d"] / 2, lt + 6,
                         P["motor_wire_xy"][0], P["motor_wire_xy"][1],
                         H + lt / 2, coll=coll))
    # 四角沉头螺钉（对准底盒螺柱）
    for sx in (-1, 1):
        for sy in (-1, 1):
            x, y = sx * P["post_x"], sy * P["post_y"]
            cuts.append(cylinder("cut_lock_screw", P["lid_screw_d"] / 2,
                                 lt + 6, x, y, H + lt / 2, coll=coll))
            cuts.append(cylinder("cut_lock_cs", P["lid_cs_d"] / 2,
                                 P["lid_cs_h"] + 2, x, y,
                                 top - P["lid_cs_h"] / 2 + 1, coll=coll))
    # 散热孔 / BOOT / RESET 针孔
    for sx in (-1, 1):
        for sy in (-1, 1):
            for k in (-1, 0, 1):
                cuts.append(cylinder("cut_lock_vent", P["lid_vent_d"] / 2,
                                     lt + 6, sx * P["lid_vent_x"],
                                     sy * P["lid_vent_y"] + k * P["lid_vent_dy"],
                                     H + lt / 2, coll=coll))
    for x, y in P["btn_xy"]:
        cuts.append(cylinder("cut_lock_btn", P["btn_d"] / 2, lt + 6,
                             x, y, H + lt / 2, coll=coll))
    boolean(plate, cuts, 'DIFFERENCE')
    shade(plate, mat)
    return plate


# ======================================================================
#  零件 5：独立电机小方板（完全脱离外壳）
# ======================================================================
def build_standalone_plate(coll, mat):
    """一块 60x60 的小方板，单独把电机 4 根铜柱锁死。

    铜柱孔位 / 六角沉腔 / 长槽模式全部复用 04 锁板的 lock_* 参数，
    所以量一次孔距，两块板一起对。区别只在「板本身」：
      - 不用 case_w/case_d 轮廓，不加唇边，不加沉头螺钉孔；
      - 底面 z=0，STL 以板底面为原点，切片软件可直接居中；
      - 四角换成 4 个通用 Ø4.2 安装孔，用 M4 螺钉锁到任意平台；
      - 不做电机沉台：电机由 4 根铜柱定位，平板上留线束孔更宽敞。
    """
    W, D, t = P["mini_w"], P["mini_d"], P["mini_t"]
    plate = prism("05_standalone_motor_plate",
                  rounded_rect_poly(W, D, P["mini_r"]), 0, t, coll)
    cuts = []

    # 中心让位孔（编码器磁铁 / 轴端）
    cuts.append(cylinder("cut_mini_axis", P["mini_axis_d"] / 2, t + 6,
                         0, 0, t / 2, coll=coll))

    # ★ 4 根铜柱的锁止孔：与 04 锁板逐字相同
    for a_deg in P["lock_post_angles"]:
        a = math.radians(a_deg)
        x, y = P["lock_post_r"] * math.cos(a), P["lock_post_r"] * math.sin(a)
        if P["lock_hole_mode"] == "slot":
            p0 = (P["lock_slot_r0"] * math.cos(a), P["lock_slot_r0"] * math.sin(a))
            p1 = (P["lock_slot_r1"] * math.cos(a), P["lock_slot_r1"] * math.sin(a))
            cuts.append(capsule("cut_mini_slot", p0, p1, P["lock_slot_w"],
                                -2, t + 2, coll))
        else:
            cuts.append(cylinder("cut_mini_post", P["lock_hole_d"] / 2,
                                 t + 6, x, y, t / 2, coll=coll))
            # 板底六角沉腔：M3 螺母从下方压入，拧紧时不会跟着螺杆自转
            cuts.append(prism("cut_mini_nut",
                              hex_poly(x, y, P["lock_nut_af"], rot=30.0),
                              -0.2, P["lock_nut_h"], coll))

    # 三相线 + 编码器线过孔
    cuts.append(cylinder("cut_mini_wire", P["mini_wire_d"] / 2, t + 6,
                         P["mini_wire_xy"][0], P["mini_wire_xy"][1],
                         t / 2, coll=coll))

    # 四角通用安装孔：M4 螺钉 + 螺母把整块板锁到桌面 / 支架 / 型材
    for sx in (-1, 1):
        for sy in (-1, 1):
            cuts.append(cylinder("cut_mini_mount", P["mini_mount_d"] / 2,
                                 t + 6, sx * P["mini_mount_x"],
                                 sy * P["mini_mount_y"], t / 2, coll=coll))

    boolean(plate, cuts, 'DIFFERENCE')
    shade(plate, mat)
    return plate


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

    # 三块板排针朝下、直接落在平底上；lift 只影响参考体，不改变底盒 STL
    lift = P["floor_t"] + P["pin_h"]
    pins = []

    # ESP32-S3 DevKitC-1
    bx, by = P["esp32_center"]
    bz = lift + P["esp32_t"] / 2
    add(box("REF_esp32_pcb", P["esp32_w"], P["esp32_d"], P["esp32_t"],
            bx, by, bz, coll), "esp32", "pcb_blue")
    add(box("REF_esp32_chip", 18, 18, 1.0, bx - 4, by, bz + 1.3, coll),
        "esp32_chip", "chip")
    add(box("REF_usb_c", 7.5, 9.0, 3.2,
            bx - P["esp32_w"] / 2 - 0.5, by, bz + 1.0, coll),
        "usb", "steel")
    for s in (-1, 1):
        pins.append(box("REF_pin_esp", P["esp32_w"] - 6, 2.54, P["pin_h"],
                        bx, by + s * (P["esp32_d"] / 2 - 3.0),
                        P["floor_t"] + P["pin_h"] / 2, coll))

    # DengFOC-Mini
    dx, dy = P["driver_center"]
    dz = lift + P["driver_t"] / 2
    add(box("REF_driver_pcb", P["driver_w"], P["driver_d"], P["driver_t"],
            dx, dy, dz, coll), "driver", "pcb")
    add(box("REF_driver_chip", 9, 9, 0.9, dx, dy, dz + 1.2, coll),
        "driver_chip", "chip")
    for s in (-1, 1):
        pins.append(box("REF_pin_drv", P["driver_w"] - 4, 2.54, P["pin_h"],
                        dx, dy + s * (P["driver_d"] / 2 - 2.5),
                        P["floor_t"] + P["pin_h"] / 2, coll))

    # 5 x 3.5 cm 电源模块（标称 50 x 35；竖放后 X 向 35 / Y 向 50）
    px, py = P["psu_center"]
    pw, pd = ((P["psu_d"], P["psu_w"]) if P["psu_rotate"]
              else (P["psu_w"], P["psu_d"]))
    pz = lift + P["psu_t"] / 2
    add(box("REF_psu_pcb", pw, pd, P["psu_t"], px, py, pz, coll), "psu", "psu")
    add(box("REF_psu_terminal", 11, 9, 6.0,
            px + pw / 2 - 6.5, py - pd / 2 + 7.0, pz + 3.4, coll),
        "psu_term", "steel")
    add(box("REF_psu_caps", 8, 8, 5.0,
            px - pw / 2 + 6.5, py + pd / 2 - 8.0, pz + 3.0, coll),
        "psu_caps", "chip")
    for s in (-1, 1):
        pins.append(box("REF_pin_psu", 2.54, pd - 6, P["pin_h"],
                        px + s * (pw / 2 - 3.0), py,
                        P["floor_t"] + P["pin_h"] / 2, coll))

    add(join(pins, "REF_pin_strips"), "pins", "chip")

    # 侧边电源开关（参考体，卡在 +X 侧壁开孔上）
    if P["sw_shape"] != "none":
        sx0 = P["case_w"] / 2 + 1.0
        if P["sw_shape"] == "round":
            add(cylinder("REF_switch_body", P["sw_d"] / 2 + 1.4, 6.0,
                         sx0, P["sw_y"], P["sw_z"],
                         rot=(0, math.pi / 2, 0), verts=24, coll=coll),
                "switch", "chip")
            add(box("REF_switch_lever", 6.0, 2.6, 2.6,
                    sx0 + 4.0, P["sw_y"], P["sw_z"] + 1.0, coll),
                "switch_lever", "steel")
        else:
            add(box("REF_switch_body", 4.0, P["sw_rect_w"] - 1.0,
                    P["sw_rect_h"] - 1.0,
                    sx0, P["sw_y"], P["sw_z"], coll), "switch", "chip")
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
        brass=material("铜柱 - 黄铜", (0.78, 0.55, 0.18), 0.32, 0.75),
        lock=material("电机锁板 - 蓝灰", (0.26, 0.36, 0.48), 0.62),
        mini=material("独立小方板 - 浅蓝灰", (0.48, 0.58, 0.68), 0.6),
        black=material("尼龙柱", (0.10, 0.10, 0.12), 0.7),
        pcb=material("PCB - 黑", (0.06, 0.13, 0.10), 0.65),
        pcb_blue=material("PCB - 深蓝", (0.07, 0.11, 0.22), 0.6),
        psu=material("电源模块 - 绿", (0.10, 0.32, 0.17), 0.6),
        chip=material("芯片", (0.12, 0.12, 0.14), 0.45),
        ground=material("地面", (0.70, 0.73, 0.77), 0.9),
        inspect=material("检视 - 浅灰", (0.52, 0.57, 0.63), 0.8),
        lip=material("定位唇边 - 高亮（仅渲染标注）", (0.95, 0.62, 0.15), 0.5),
        pocket=material("六角沉腔 - 高亮（仅渲染标注）", (1.0, 0.40, 0.04), 0.5),
        text=material("标注", (0.10, 0.12, 0.16), 0.8),
    )

    lower = build_lower(parts_coll, mats["case"])
    lid = build_lid(parts_coll, mats["lid"])
    lock = build_lock_plate(parts_coll, mats["lock"])
    mini = build_standalone_plate(parts_coll, mats["mini"])
    knob = build_knob(parts_coll, mats["knob"])
    refs = build_references(ref_coll, mats)

    # 锁板与顶盖共用同一装配位（二选一打印），默认在渲染里隐藏，
    # 只在 06_lock_plate.png 里单独展示；.blend 里对象仍在，可手动切换可见性。
    lock.hide_render = True
    # 独立小方板建模在 z=0..mini_t（STL 原点即板底面），与底盒空间重叠，
    # 除了 08 / 09 两张专属渲染一律隐藏；保存 .blend 前再挪到底盒旁边。
    mini.hide_render = True

    print("=== BUILD DONE ===")
    for o in (lower, lid, lock, mini, knob):
        st = mesh_stats(o)
        print("  %-18s tris=%5d nonmanifold=%d boundary=%d vol=%.1f cm3 dims=%s"
              % (o.name, st["tris"], st["nonmanifold"], st["boundary"],
                 st["volume_cm3"], st["dims"]))

    # ---- 导出 STL ----
    exports = [
        (lower, "01_lower_case.stl"),
        (lid, "02_top_cover.stl"),
        (knob, "03_knob.stl"),
        (lock, "04_motor_lock_plate.stl"),
        (mini, "05_standalone_motor_plate.stl"),
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

    # 结合细节：顶盖抬高、正交低视角，露出口沿 / 四角螺柱 / 顶盖下方四条唇边。
    # 正交投影避免"抬高的顶盖看起来比底盒大"的透视误导；底盒临时换浅色便于看清口沿。
    fit_hidden = [knob, refs["motor"], refs["disc"], refs["shaft"],
                  refs["encoder"], refs["pillars"], ground]
    for o in fit_hidden:
        o.hide_render = True
    case_mat = lower.data.materials[0]
    lower.data.materials[0] = mats["inspect"]
    lid.location += Vector((0, 0, 22))
    r_fit = render(os.path.join(RENDER_DIR, "04_fit.png"), cam,
                   (150, -180, 150), (0, 0, 38), ortho=170)
    print("  RENDER fit", r_fit)
    lid.location -= Vector((0, 0, 22))
    lower.data.materials[0] = case_mat
    for o in fit_hidden:
        o.hide_render = False

    # 唇边特写：复制顶盖，把 z<36 的唇边面临时上高亮色，从下方仰视。
    # 唇边与本体同色时均匀光下几乎看不出轮廓，上色后四条直条与四角空位一目了然。
    # 只改渲染副本，不影响导出的 STL / .blend 里的实际材质。
    dup = lid.copy()
    dup.data = lid.data.copy()
    dup.name = "RENDER_ONLY_lip_highlight"
    parts_coll.objects.link(dup)
    dup.data.materials.clear()
    dup.data.materials.append(mats["inspect"])
    dup.data.materials.append(mats["lip"])
    for poly in dup.data.polygons:
        if min(dup.data.vertices[i].co.z for i in poly.vertices) < P["case_h"] - 0.01:
            poly.material_index = 1
    saved = [(o, o.hide_render) for o in bpy.data.objects if o.type == 'MESH']
    for o, _ in saved:
        o.hide_render = (o != dup)
    bpy.ops.object.light_add(type='AREA', location=(0, 0, -70))
    under = bpy.context.object
    under.name = "RENDER_ONLY_under_light"
    under.rotation_euler[0] = math.pi      # 面光朝 +Z，照亮顶盖下表面
    under.data.energy = 2200
    under.data.shape = 'DISK'
    under.data.size = 160
    r_lip = render(os.path.join(RENDER_DIR, "05_lip.png"), cam,
                   (30, -40, -110), (0, 0, 36), ortho=140)
    print("  RENDER lip", r_lip)
    bpy.data.objects.remove(under, do_unlink=True)
    for o, v in saved:
        o.hide_render = v
    dup_mesh = dup.data
    bpy.data.objects.remove(dup, do_unlink=True)
    bpy.data.meshes.remove(dup_mesh)

    # 电机锁板装配示意（06）：爆炸展示「铜柱穿过 4 个精确孔 + 六角螺母从板底锁死」。
    # 只用临时示意件，渲染完即删；不改变导出 STL 与 .blend 的装配状态。
    saved = [(o, o.hide_render) for o in bpy.data.objects if o.type == 'MESH']
    for o, _ in saved:
        o.hide_render = True
    lock.hide_render = False
    temp = []

    def add_temp(o, m):
        shade(o, mats[m])
        temp.append(o)
        return o

    H, lt, R = P["case_h"], P["lock_t"], P["lock_post_r"]
    lift = 14.0
    for a_deg in P["lock_post_angles"]:
        a = math.radians(a_deg)
        x, y = R * math.cos(a), R * math.sin(a)
        add_temp(cylinder("TMP_brass_post", 1.6, 19.0, x, y,
                          H + 9.5 + lift, coll=helper), "brass")
        nut = prism("TMP_hex_nut", hex_poly(x, y, 5.5, rot=30.0),
                    H - 9.0, H - 6.6, helper)
        boolean(nut, [cylinder("TMP_nut_bore", 1.7, 6.0, x, y,
                               H - 7.8, coll=helper)], 'DIFFERENCE')
        add_temp(nut, "steel")
    add_temp(cylinder("TMP_encoder", P["ref_enc_d"] / 2, P["ref_enc_t"],
                      0, 0, H + lift + 8.0 + P["ref_enc_t"] / 2,
                      verts=48, coll=helper), "pcb")
    add_temp(cylinder("TMP_motor", P["ref_motor_d"] / 2, P["ref_motor_h"],
                      0, 0, H + lift + 8.0 + P["ref_enc_t"]
                      + P["ref_motor_h"] / 2, verts=48, coll=helper), "motor")
    add_temp(cylinder("TMP_disc", P["ref_disc_d"] / 2, P["ref_disc_h"],
                      0, 0, H + lift + 8.0 + P["ref_enc_t"]
                      + P["ref_motor_h"] + P["ref_disc_h"] / 2,
                      verts=48, coll=helper), "white")

    aim(cam, (160, -190, 150), (0, 0, 52), ortho=175)
    lock_labels = [
        label("MOTOR + 4 BRASS POSTS", (0, -62, 92), cam, mats["text"], 3.6),
        label("04  MOTOR LOCK PLATE", (0, -62, 44), cam, mats["text"], 3.6),
        label("M3 HEX NUTS IN ANTI-ROTATION POCKETS", (0, -62, 24), cam, mats["text"], 3.4),
        label("4 ROUND HOLES = NO SLIP", (0, -62, 13), cam, mats["text"], 3.4),
    ]
    r_lock = render(os.path.join(RENDER_DIR, "06_lock_plate.png"), cam,
                    (160, -190, 150), (0, 0, 52), ortho=175)
    print("  RENDER lock", r_lock)
    for t in lock_labels:
        bpy.data.objects.remove(t, do_unlink=True)
    for o in temp:
        bpy.data.objects.remove(o, do_unlink=True)
    for o, v in saved:
        o.hide_render = v

    # 锁板底面仰视特写（07）：橙色高亮 4 个六角螺母沉腔，螺母实地嵌在腔里。
    # 同色几何在均匀光下看不出轮廓（05_lip 已验证），上色后才一目了然。
    dup = lock.copy()
    dup.data = lock.data.copy()
    dup.name = "RENDER_ONLY_lock_pockets"
    parts_coll.objects.link(dup)
    dup.data.materials.clear()
    dup.data.materials.append(mats["inspect"])
    dup.data.materials.append(mats["pocket"])
    pockets = [(P["lock_post_r"] * math.cos(math.radians(a)),
                P["lock_post_r"] * math.sin(math.radians(a)))
               for a in P["lock_post_angles"]]
    for poly in dup.data.polygons:
        vv = [dup.data.vertices[i].co for i in poly.vertices]
        cx = sum(v.x for v in vv) / len(vv)
        cy = sum(v.y for v in vv) / len(vv)
        cz = sum(v.z for v in vv) / len(vv)
        if (cz < H + P["lock_nut_h"] + 0.25
                and any(math.hypot(cx - px, cy - py) < 4.0
                        for px, py in pockets)):
            poly.material_index = 1
    pocket_nuts = []
    for px, py in pockets:
        n = prism("TMP_pocket_nut", hex_poly(px, py, 5.5, rot=30.0),
                  H + 0.1, H + 2.5, helper)
        boolean(n, [cylinder("TMP_pocket_bore", 1.7, 6.0, px, py,
                             H + 1.3, coll=helper)], 'DIFFERENCE')
        shade(n, mats["black"])
        pocket_nuts.append(n)
    saved2 = [(o, o.hide_render) for o in bpy.data.objects if o.type == 'MESH']
    for o, _ in saved2:
        o.hide_render = True
    dup.hide_render = False
    for n in pocket_nuts:
        n.hide_render = False
    bpy.ops.object.light_add(type='AREA', location=(0, 0, -60))
    under = bpy.context.object
    under.name = "RENDER_ONLY_pocket_light"
    under.rotation_euler[0] = math.pi      # 面光朝 +Z，照亮板底
    under.data.energy = 3200
    under.data.shape = 'DISK'
    under.data.size = 150
    # 纯特写：正交尺度收到 72mm，只保留中央 4 个沉腔；不放文字标签，
    # 避免标签与几何重叠（装配关系由 06 图 + build_report 说明）。
    r_pocket = render(os.path.join(RENDER_DIR, "07_lock_underside.png"), cam,
                      (18, -24, -110), (0, 0, 36), ortho=72)
    print("  RENDER pocket", r_pocket)
    bpy.data.objects.remove(under, do_unlink=True)
    for o, v in saved2:
        o.hide_render = v
    dup_mesh = dup.data
    bpy.data.objects.remove(dup, do_unlink=True)
    bpy.data.meshes.remove(dup_mesh)
    for n in pocket_nuts:
        bpy.data.objects.remove(n, do_unlink=True)

    # 独立小方板顶面（08）：纯板件俯视特写，把 4 个铜柱孔 / 4 个安装孔 /
    # 中心让位 / 线束孔一次展示清楚。放电机示意件会挡住孔位，得不偿失；
    # 装配关系由 06 锁板爆炸图（同一套孔位）+ build_report 说明。
    saved3 = [(o, o.hide_render) for o in bpy.data.objects if o.type == 'MESH']
    for o, _ in saved3:
        o.hide_render = True
    mini.hide_render = False
    mini_mat = mini.data.materials[0]
    mini.data.materials[0] = mats["lid"]       # 临时深灰，孔透出浅背景更醒目
    mini_posts = [(P["lock_post_r"] * math.cos(math.radians(a)),
                   P["lock_post_r"] * math.sin(math.radians(a)))
                  for a in P["lock_post_angles"]]
    bpy.ops.object.light_add(type='AREA', location=(20, -30, 90))
    top_light = bpy.context.object
    top_light.name = "RENDER_ONLY_mini_top_light"
    top_light.data.energy = 3600
    top_light.data.shape = 'DISK'
    top_light.data.size = 120
    # 接近正上方俯视：板正立、四角完整入画；纯几何特写，不放文字标签
    # （标签与孔位抢空间，正俯视下反而看不清板；说明交给 build_report）。
    r_mini = render(os.path.join(RENDER_DIR, "08_standalone_plate.png"), cam,
                    (0, -6, 140), (0, 0, 2), ortho=100)
    print("  RENDER mini", r_mini)
    bpy.data.objects.remove(top_light, do_unlink=True)
    mini.data.materials[0] = mini_mat
    for o, v in saved3:
        o.hide_render = v

    # 独立板底面仰视（09）：橙色 4 个六角沉腔 + 深色螺母 + 四角安装孔。
    mdup = mini.copy()
    mdup.data = mini.data.copy()
    mdup.name = "RENDER_ONLY_mini_pockets"
    parts_coll.objects.link(mdup)
    mdup.data.materials.clear()
    mdup.data.materials.append(mats["inspect"])
    mdup.data.materials.append(mats["pocket"])
    for poly in mdup.data.polygons:
        vv = [mdup.data.vertices[i].co for i in poly.vertices]
        cx = sum(v.x for v in vv) / len(vv)
        cy = sum(v.y for v in vv) / len(vv)
        cz = sum(v.z for v in vv) / len(vv)
        if (cz < P["lock_nut_h"] + 0.25
                and any(math.hypot(cx - px, cy - py) < 4.0
                        for px, py in mini_posts)):
            poly.material_index = 1
    mini_nuts = []
    for px, py in mini_posts:
        n = prism("TMP_mini_pocket_nut", hex_poly(px, py, 5.5, rot=30.0),
                  0.1, 2.5, helper)
        boolean(n, [cylinder("TMP_mini_pocket_bore", 1.7, 6.0, px, py,
                             1.3, coll=helper)], 'DIFFERENCE')
        shade(n, mats["black"])
        mini_nuts.append(n)
    saved4 = [(o, o.hide_render) for o in bpy.data.objects if o.type == 'MESH']
    for o, _ in saved4:
        o.hide_render = True
    mdup.hide_render = False
    for n in mini_nuts:
        n.hide_render = False
    bpy.ops.object.light_add(type='AREA', location=(0, 0, -60))
    under = bpy.context.object
    under.name = "RENDER_ONLY_mini_light"
    under.rotation_euler[0] = math.pi
    under.data.energy = 3200
    under.data.shape = 'DISK'
    under.data.size = 150
    r_mini_under = render(os.path.join(RENDER_DIR, "09_standalone_underside.png"),
                          cam, (0, -8, -130), (0, 0, 2), ortho=105)
    print("  RENDER mini underside", r_mini_under)
    bpy.data.objects.remove(under, do_unlink=True)
    for o, v in saved4:
        o.hide_render = v
    mdup_mesh = mdup.data
    bpy.data.objects.remove(mdup, do_unlink=True)
    bpy.data.meshes.remove(mdup_mesh)
    for n in mini_nuts:
        bpy.data.objects.remove(n, do_unlink=True)

    # 内部俯视：隐藏顶盖 / 电机 / 旋钮 / 地面
    hidden = [lid, knob, refs["motor"], refs["disc"], refs["shaft"],
              refs["encoder"], refs["pillars"], ground]
    for o in hidden:
        o.hide_render = True
    # 检视视图临时用浅色底盒，让平底 / 螺柱 / 内腔轮廓和深色 PCB 分开
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
        psu=(0, 0, 16), psu_term=(0, 0, 16), psu_caps=(0, 0, 16),
        pins=(0, 0, 16),
        switch=(0, 0, 0), switch_lever=(0, 0, 0),   # 开关留在底盒侧壁上
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
        # 板卡标签放在盒体投影之外的前下方空白，避免被深色盒壁吃掉
        label("ESP32-S3 + DengFOC-Mini", (-26, -70, 10), cam, mats["text"], 3.2),
        label("PSU 50x35 + SIDE SWITCH", (36, -70, 10), cam, mats["text"], 3.2),
        label("01  LOWER CASE", (0, -88, -2), cam, mats["text"]),
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
    # STL 已按原点导出；这里把独立板摆到底盒旁边，打开 .blend 时能一眼看出
    # 它不属于外壳，也不会和底盒 / 锁板在视口里叠在一起。
    mini.location = Vector((P["mini_blend_x"], 0, 0))
    aim(cam, (150, -170, 125), (0, 0, 34))
    blend_path = os.path.join(OUT, "Enclosure.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print("  BLEND", os.path.getsize(blend_path))

    # ---- 报告 ----
    write_report(stl_report, blend_path,
                 (r_assembled, r_exploded, r_interior, r_fit, r_lip,
                  r_lock, r_pocket, r_mini, r_mini_under))
    print("=== ALL DONE ===")


def write_report(stl_report, blend_path, renders):
    W, D, H = P["case_w"], P["case_d"], P["case_h"]
    top = H + P["lid_t"]
    psu_x, psu_y = ((P["psu_d"], P["psu_w"]) if P["psu_rotate"]
                    else (P["psu_w"], P["psu_d"]))
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
    A("  顶盖   %.1f x %.1f x %.1f mm，与底盒共用同一 XY 圆角轮廓，叠装后侧面齐平"
      % (W, D, P["lid_t"]))
    A("  总高（含电机与白色转盘，不含旋钮）约 %.1f mm" % (top + P["ref_enc_t"] + P["ref_motor_h"] + P["ref_disc_h"]))
    A("  电子层内净高 %.1f mm；电机装在顶盖上方，散热好、装配简单。" % (H - P["floor_t"]))
    A("")
    gap = P["lip_gap"]
    lip_ox = W / 2 - P["wall"] - gap
    lip_oy = D / 2 - P["wall"] - gap
    clear = P["post_od"] / 2 + P["lip_post_clear"]
    len_x = 2 * (P["post_x"] - clear)
    len_y = 2 * (P["post_y"] - clear)
    A("【顶盖 / 底盒结合逻辑】（本次修复重点）")
    A("  1) 底盒侧壁垂直一直到 z=%.1f，内腔 %.1f x %.1f 贯通到盒口，"
      % (H, W - 2 * P["wall"], D - 2 * P["wall"]))
    A("     剩下 %.1f mm 宽的平齐环形口沿；四角 Ø%.1f 螺柱顶面也在 z=%.1f，"
      "与口沿共面。" % (P["wall"], P["post_od"], H))
    A("  2) 顶盖底面 z=%.1f 是完整平面，同时压在口沿和 4 个螺柱顶面上，零缝贴合。" % H)
    A("     外形与底盒完全一致（R%.1f 同心圆角），不会一角多出、一角缺料。" % P["corner_r"])
    A("  3) 定位靠顶盖下方 4 条直唇边：宽 %.1f、插入 %.1f mm，"
      "外边界 X±%.1f / Y±%.1f，与内腔壁单边留 %.1f mm 间隙。"
      % (P["lip_w"], P["lip_h"], lip_ox, lip_oy, gap))
    A("     唇边长度 X %.1f / Y %.1f，两端止于螺柱避让半径 %.1f，四角完全空出，"
      "不与螺柱干涉。" % (len_x, len_y, clear))
    A("  4) 4 颗 M3x12 沉头螺钉穿过顶盖 Ø%.1f 过孔 + Ø%.1f 沉头孔，"
      "拧进螺柱 Ø%.1f 自攻孔，把顶盖压紧在口沿上。"
      % (P["lid_screw_d"], P["lid_cs_d"], P["post_hole_d"]))
    A("  * 旧版用 BEVEL 削整个外壳：%.1f mm 薄板的圆角被 clamp 成上下斜切，"
      "盒口外轮廓反而比内腔小，侧壁被切穿，顶盖无处落脚；" % P["lid_t"])
    A("    唇边又是一整块实心板并压在螺柱上，顶盖根本盖不下去。现改为精确圆角棱柱"
      " + 平齐口沿 + 四条让位唇边。")
    A("  * 配合见 render/04_fit.png（抬升正交视图）；唇边与四角让位见 "
      "render/05_lip.png（顶盖底面仰视，橙色为唇边标注色）。配合数值由 verify_fit.py 自动复验。")
    A("")
    A("【四个关键结构】")
    A("  1) 底盒内腔是完整平底：不做垫台 / 挡边 / 板卡槽，三块板排针朝下直接堆放，位置自由。")
    A("     板底排针约 %.1f mm 自然把板撑起；需要更高就自行贴泡棉或尼龙脚垫。" % P["pin_h"])
    A("     ESP32-S3-DevKitC-1   %.1f x %.1f  中心 (%.1f, %.1f)" % (P["esp32_w"], P["esp32_d"], *P["esp32_center"]))
    A("     DengFOC-Mini           %.1f x %.1f  中心 (%.1f, %.1f)" % (P["driver_w"], P["driver_d"], *P["driver_center"]))
    A("     电源模块 5x3.5 cm      %.1f x %.1f  中心 (%.1f, %.1f)，竖放占 X %.1f / Y %.1f"
      % (P["psu_w"], P["psu_d"], *P["psu_center"], psu_x, psu_y))
    A("     三者互不重叠，且与四角螺柱留空；此为建议布局，实际可随意挪动。")
    A("  2) 顶盖中央 Ø%.1f 沉台 + 中心 Ø%.1f 让位孔 + 4 条 45° 径向长槽（宽 %.1f，半径 %.1f~%.1f）。"
      % (P["motor_recess_d"], P["axis_hole_d"], P["pillar_slot_w"],
         P["pillar_slot_r0"], P["pillar_slot_r1"]))
    A("     长槽对应照片里电机底部那 4 根向下的尼龙支撑柱，兼容对角孔距 24~38 mm。")
    A("  3) -X 侧壁 USB-C 开口 %.1f x %.1f（中心 z=%.1f），+X 侧壁 Ø%.1f 出线孔（y=%.1f）。"
      % (P["usb_w"], P["usb_h"], P["usb_z"], P["wire_d"], P["wire_y"]))
    if P["sw_shape"] == "round":
        A("     +X 侧壁电源开关口 Ø%.1f（y=%.1f, z=%.1f），适配小型拨动开关；串在 12V 正极上。"
          % (P["sw_d"], P["sw_y"], P["sw_z"]))
    elif P["sw_shape"] == "rect":
        A("     +X 侧壁电源开关口 %.1f x %.1f（y=%.1f, z=%.1f），适配船型开关；串在 12V 正极上。"
          % (P["sw_rect_w"], P["sw_rect_h"], P["sw_y"], P["sw_z"]))
    A("     两侧壁各 15 条散热格栅，顶盖 12 个散热孔 + 2 个 BOOT/RESET 针孔。")
    A("  4) 四角 M3 螺柱 + 沉头螺钉固定顶盖；底面 4 个 Ø%.1f 橡胶脚垫凹坑。" % P["foot_d"])
    A("")
    lr = P["lock_post_r"]
    A("【04 电机锁板 —— 把 4 根铜柱真正锁死】（本次新增）")
    A("  * 与 02_top_cover.stl 二选一打印：两者外形 / 唇边 / 四角螺钉孔完全相同，装在同一位置。")
    A("    02 是 4 条径向长槽（只让位，电机仍能沿槽窜动）；04 是 4 个精确孔 + 螺母沉腔（锁死）。")
    A("  板厚 %.1f mm（六角沉腔深 %.1f 后仍留 %.1f mm 承力），底面 z=%.1f 压在口沿与螺柱顶面上。"
      % (P["lock_t"], P["lock_nut_h"], P["lock_t"] - P["lock_nut_h"], H))
    if P["lock_hole_mode"] == "round":
        A("  4 个 Ø%.1f 通孔，中心在半径 R=%.1f mm、角度 %s°；"
          % (P["lock_hole_d"], lr, "/".join(str(int(a)) for a in P["lock_post_angles"])))
        A("  即坐标 (±%.2f, ±%.2f)，相邻孔距 %.2f mm、对角孔距 %.2f mm。"
          % (lr / math.sqrt(2), lr / math.sqrt(2), lr * math.sqrt(2), 2 * lr))
        A("  每个孔底面有对边 %.1f、深 %.1f 的六角沉腔：M3 螺母嵌进去不能自转，"
          "铜柱从上往下穿过后单手拧即可锁紧，电机不会再随旋钮扭动而窜位。"
          % (P["lock_nut_af"], P["lock_nut_h"]))
    else:
        A("  当前 lock_hole_mode='slot'：4 条径向长槽（半径 %.1f~%.1f、宽 %.1f），"
          "免实测兼容孔距，但可滑动；量准孔距后改回 'round' 才能真正锁死。"
          % (P["lock_slot_r0"], P["lock_slot_r1"], P["lock_slot_w"]))
    A("  若铜柱是内螺纹铜柱（standoff）而不是外螺纹螺杆：不改孔，从板底用 M3x10 螺钉")
    A("  穿过沉腔拧进铜柱即可，沉腔同样容纳螺钉头。")
    A("  ★ 孔距实测方法（照片无法精确定尺寸，默认 R=%.1f 是按现有参考体估算）：" % lr)
    A("      量对角两根铜柱中心距 L -> lock_post_r = L / 2")
    A("      或量相邻两根中心距 S   -> lock_post_r = S / 1.414")
    A("      若柱子沿 X/Y 轴而不是 45° 对角，把 lock_post_angles 改成 (0, 90, 180, 270)。")
    A("      一时量不准就先把 lock_hole_mode 设成 'slot' 装上，量准后再切回 'round' 重打一块。")
    A("  装配示意见 render/06_lock_plate.png（爆炸展示铜柱 / 锁板 / 六角螺母）；")
    A("  板底 4 个六角沉腔见 render/07_lock_underside.png（橙色为渲染标注色，打印件单色）。")
    A("")
    mw, md, mt = P["mini_w"], P["mini_d"], P["mini_t"]
    mx, my = P["mini_mount_x"], P["mini_mount_y"]
    corner_c = (mw / 2 - P["mini_r"], md / 2 - P["mini_r"])
    mount_wall = (P["mini_r"] - math.hypot(mx - corner_c[0], my - corner_c[1])
                  - P["mini_mount_d"] / 2)
    A("【05 独立电机小方板 —— 完全脱离外壳】（本次新增）")
    A("  * 定位：不装进 110x76 底盒，不用外壳轮廓 / 唇边 / 沉头螺钉孔，就是单独一块")
    A("    %.1f x %.1f x %.1f mm 小方板：4 根铜柱锁死电机，四角安装孔把板锁到任意平台。"
      % (mw, md, mt))
    A("    与 01~04 没有任何装配关系，打印这一块就能用，不必打印外壳。")
    A("  * 铜柱孔位与 04 锁板逐字共用 lock_post_r / lock_hole_d / lock_nut_af /")
    A("    lock_post_angles / lock_hole_mode：实测一次孔距，两块板一起对准，改一处即可。")
    A("    孔位 (±%.2f, ±%.2f)，相邻 %.2f / 对角 %.2f mm；"
      % (lr / math.sqrt(2), lr / math.sqrt(2), lr * math.sqrt(2), 2 * lr))
    A("    板底同样是 对边 %.1f、深 %.1f 的六角沉腔，M3 螺母嵌进去不能自转。"
      % (P["lock_nut_af"], P["lock_nut_h"]))
    A("  中心 Ø%.1f 让位孔、Ø%.1f 线束过孔 (%.1f, %.1f)、四角圆角 R%.1f。"
      % (P["mini_axis_d"], P["mini_wire_d"], *P["mini_wire_xy"], P["mini_r"]))
    A("  四角 Ø%.1f 安装孔 (±%.1f, ±%.1f) 落在圆角圆心，四周最小壁厚 %.2f mm："
      % (P["mini_mount_d"], mx, my, mount_wall))
    A("    M4 螺钉 + 螺母把板锁到桌面 / 支架 / 铝型材；也可换成尼龙柱把板架高。")
    A("  STL 以板底面为 z=0 原点，包围盒 %.1f x %.1f x %.1f，切片软件可直接居中。"
      % (mw, md, mt))
    A("  ★ 改板尺寸时同步改 mini_mount_x / mini_mount_y = mini_w/2 - mini_r（保持落在圆角圆心），")
    A("    否则安装孔会切穿圆角边；verify_fit.py 会自动检查这个壁厚。")
    A("  顶面孔位布局见 render/08_standalone_plate.png（纯板件俯视，不装外壳）；")
    A("  板底六角沉腔与四角安装孔见 render/09_standalone_underside.png（橙色为渲染标注色）；")
    A("  装配关系与 04 锁板完全相同，可对照 render/06_lock_plate.png 的爆炸示意。")
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
    A("  - ★ 锁板孔位 R=%.1f 与铜柱同按照片估算：打印前务必实测对角孔距并改 lock_post_r，"
      "否则 4 个孔会对不上实物铜柱。" % lr)
    A("  - 05 独立板 %.1f x %.1f x %.1f mm 是纯自定义尺寸（不是实物量测值）："
      % (P["mini_w"], P["mini_d"], P["mini_t"]))
    A("    改 mini_w / mini_d 时同步改 mini_mount_x / mini_mount_y = 边长/2 - mini_r，")
    A("    让四角安装孔始终落在圆角圆心，避免切穿圆角边。")
    A("  - 轴径 Ø%.1f（旋钮孔径），M3 紧定螺钉横孔 Ø%.1f"
      % (P["shaft_d"], P["set_screw_d"]))
    A("  - ESP32-S3 板 USB-C 端中心高度 z=%.1f；BOOT/RESET 针孔位置按常见 DevKitC-1 估计。" % P["usb_z"])
    A("  - 板卡尺寸：ESP32-S3 63 x 25.5 / DengFOC-Mini 26 x 21 / 电源模块 50 x 35 mm。")
    A("    用户说的「5*3.5」按 5 cm x 3.5 cm 理解；单位不同就改 P 里的 psu_w / psu_d。")
    A("  - 电源模块默认竖放（X 向 35 / Y 向 50）排在 +X 侧，靠近出线孔与开关。")
    A("  - 开关口默认 Ø%.1f 圆形拨动开关；用船型开关请把 sw_shape 改成 'rect' 并核对开孔尺寸。" % P["sw_d"])
    A("")
    A("【五金 BOM】")
    A("  电源模块 5x3.5cm x1（12V 输入 -> 给 ESP32 与驱动板供电，线束从 +X Ø8 孔进出）")
    A("  小型拨动开关 x1（开孔 Ø%.1f）或船型开关 x1（开孔 %.1f x %.1f），串在 12V 正极上"
      % (P["sw_d"], P["sw_rect_w"], P["sw_rect_h"]))
    A("  泡棉双面胶 / 尼龙脚垫 2~3mm 若干（可选，垫在板下防滑动、让排针不顶到底）")
    A("  M3 x 12 沉头螺钉 x4（顶盖 / 锁板 -> 底盒螺柱，自攻进 Ø2.6 孔）")
    A("  【用 02 顶盖】M3 螺母 + Ø10 垫片 x4（长槽只让位，电机仍可滑动）")
    A("  【用 04 锁板】M3 六角螺母 x4（嵌进板底六角沉腔，防转锁死；")
    A("                 若铜柱是内螺纹 standoff 则改 M3x10 螺钉 x4）")
    A("  【用 05 独立板】M3 六角螺母 x4（板底沉腔）+ M4x12 螺钉与螺母 x4")
    A("                 （四角 Ø%.1f 孔把板锁到平台；也可换 M3 + 垫片）" % P["mini_mount_d"])
    A("  橡胶脚垫 Ø8 x4、少量热熔胶（固定线束）、扎带 x2")
    A("  USB-C 数据线 x1、12V 电源线 x1（从 +X 出线孔引出）")
    A("")
    A("【打印建议】")
    A("  PLA 或 PETG；层高 0.2 mm；填充 20%；壁 3 圈；底盒开口朝上打印，无需支撑。")
    A("  顶盖沉台朝上；旋钮竖放（轴孔垂直），滚花朝外。")
    A("  04 锁板 / 05 独立板底面（六角沉腔面）朝下打印：沉腔上方是跨度 %.1f mm 的短桥，"
      "PLA 可直接桥接免支撑；若切片软件自动加支撑也很好拆。" % P["lock_nut_af"])
    A("  05 独立板平放打印即可（两面都是平面），是最容易打印的一个零件。")
    A("  螺柱自攻孔 Ø2.6 若太紧可用 M3 丝锥或 3.0 钻头轻扩。")
    A("")
    A("【装配顺序】")
    A("  1. 底盒朝上，把电源模块、DengFOC-Mini、ESP32-S3 排针朝下直接放进去（无卡槽，位置自由），")
    A("     让 ESP32 的 USB-C 对准 -X 侧壁开口；需要防滑就垫 2~3mm 泡棉。")
    A("  2. 开关装进 +X 侧壁开孔；12V 电源线从 Ø8 出线孔穿入，经开关到电源模块，")
    A("     模块输出再分给驱动板 VIN 与 ESP32；三相线 + 编码器线从顶盖 Ø9 过孔穿入。")
    A("  3. 【二选一】用 02 顶盖：4 根铜柱对准长槽插入，从盒内侧用 M3 螺母 + Ø10 垫片带紧（可滑动）。")
    A("     用 04 锁板：先把 M3 六角螺母按进板底 4 个六角沉腔，铜柱从上方穿过 4 个 Ø3.4 孔")
    A("     拧进螺母并锁紧；电机与锁板成为一体，再把锁板盖到底盒口沿上。")
    A("  4. 盖上顶盖 / 锁板：四条唇边对准内腔插入，底面压平在口沿与四个螺柱顶面上，"
      "四角拧入 M3x12 沉头螺钉。")
    A("     先不拧死、试合一次：顶盖应能整面落到底、四周无缝，若有顶手就检查"
      "螺柱顶面是否有毛刺或唇边是否被切片机加了支撑/大象脚。")
    A("  5. 白色转盘即现成旋钮；若要更大握持感，套上 03_knob.stl 并用 M3 紧定螺钉固定。")
    A("")
    A("【只要固定电机、不装外壳时】只打印 05_standalone_motor_plate.stl：")
    A("  1) 4 个 M3 六角螺母按进板底六角沉腔；2) 电机 4 根铜柱从板顶穿过 Ø3.4 孔，")
    A("  拧紧锁死；3) 三相线 / 编码器线从 Ø9 线束孔引出；4) 四角 Ø4.2 孔用 M4")
    A("  螺钉把整块板锁到桌面、支架或铝型材上。板本身不依附外壳，位置随意。")
    A("")
    A("【与固件的配合 / 安全】")
    A("  - 上电 initFOC() 会让电机正反各走一个电周期，务必让旋钮自由、别用手捏住。")
    A("  - 校准需 12V 与三相线都接好；失败会打印 Failed to notice movement 并卡住，按 RESET 重来。")
    A("  - 手扭住不放时电机持续堵转输出，MP6536 会发热，不用时发 T0 并断 12V。")
    A("  - 重烧固件前关闭上位机 / IDE 串口监视器，释放串口。")
    A("  - 机械件共三套独立方案：MountBracket 三板支架 / 01~04 整机外壳 / 05 独立小方板，")
    A("    按需要选一套打印即可；05 与外壳没有任何装配关系。")
    A("")
    A("【渲染图】")
    for name, size in zip(("01_assembled.png", "02_exploded.png",
                           "03_interior.png", "04_fit.png", "05_lip.png",
                           "06_lock_plate.png", "07_lock_underside.png",
                           "08_standalone_plate.png",
                           "09_standalone_underside.png"), renders):
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
