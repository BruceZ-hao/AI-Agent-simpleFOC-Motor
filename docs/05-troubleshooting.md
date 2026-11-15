# 05 · 排坑记录

这份文档是本项目实际踩过的坑，按「现象 → 原因 → 解法」整理。调固件前建议先扫一遍。

## 编译 / 上传

| 现象 | 原因 | 解法 |
| --- | --- | --- |
| `SimpleFOC.h: No such file or directory` | 库没装 | Arduino 库管理器装 **Simple FOC 2.4.0**（2.3.4+ 均可） |
| `#error "USB CDC On Boot is DISABLED"` | 菜单没开 CDC（代码里的防呆） | `工具 > USB CDC On Boot > Enabled`，再编译 |
| 串口一片空白、发 `T/L` 没反应 | `CDCOnBoot=default` 时 `Serial` 跑到 UART0(GPIO43/44 / C3 的 20/21) | 同上；S3 用**原生 USB 口**，不要用 UART 口 |
| `PermissionError(13, ..., 错误 31) Cannot configure port` | Windows `usbser.sys` 在 esptool 把波特率从 115200 提到 921600 的 `SetCommState` 失败 | `工具 > Upload Speed > 115200`，全程不切速；`flash*.bat` 已固定 115200 |
| 烧录成功但串口 `waiting for download`、灯不亮 | S3 普通 `hard-reset` 把芯片留在 ROM 下载模式 | esptool 用 `--after watchdog-reset`，或烧完按一下 RESET / 重插 USB |
| C3 刷到一半 USB 掉线、串口无输出 | bootloader 区被擦，**不是变砖**，ROM 下载模式仍可用 | 物理重插 / 按住 BOOT 上电，用 `flash.bat` 重刷 4MB `merged.bin` |
| IDE 报 `ECONNREFUSED 127.0.0.1:53078` | 编译守护进程被 `taskkill /F /IM arduino-cli.exe` 误杀 | 完全退出 Arduino IDE（确认进程全结束）再重开；清串口只处理 `serial-discovery.exe` / `serial-monitor.exe` |
| `Could not open COMx, port is busy` | IDE 串口监视器 / 上位机 / 测试脚本抢占 COM | 关监视器、上位机点「断开」，再烧录 |
| 板载 RGB 灯常亮白光 | GPIO48 WS2812 是锁存型，3V3 不断电就保持最后一帧；旧固件不碰它 | 断电重插即灭；本版 `setup()` 先清灯并接管成心跳/常亮状态指示 |

## 电机不转 / 转得不对

| 现象 | 原因 | 解法 |
| --- | --- | --- |
| STAGE 2 发了 `T2`、`L2` 都不转 | `loop()` 里 `motor.loopFOC()` 被写进 `#if STAGE == 3` 分支，开环没有电流环更新 | **STAGE 2 和 3 都必须调 `loopFOC()`**，见 `docs/02-firmware.md` |
| 有 `Ua/Ub/Uc` 但轴不动 | EN 没拉高 / VIN 没上电 / 没共地 / VCC 脚判别错 / 限幅太低 | 按 `docs/01-wiring.md` 的检查顺序逐条过；实测 `L3` 才带得动 |
| `T2` 一给就失步、啸叫 | 7 对极下电角速度过快 | 先 `L3` + `T0.5` 低速起步，再逐步加 |
| `PP check: fail - estimated pp: N` | 极对数不对 | 把 `POLE_PAIRS` 改成 N 重编译；正常应打印 `PP check: OK!` |
| `ERR-MOT: No current sense.` | 驱动板无电流采样，库退回电压模式 | **无害**，忽略 |
| FAULT 灯亮 / 电机发烫 | 过流 / 过温 / 欠压，或 `voltage_limit / 相阻` 太大 | 立刻断电；查相线与限幅，低阻电机从 0.5V 起 |
| 上电校准失败 | 校准时 12V 没开、三相没接、轴被捏住 | 保持供电与接线、轴空转，按 RESET 重来 |

## 抖动（两个不同的原因）

| 现象 | 原因 | 解法 |
| --- | --- | --- |
| **原点**不停「嗡嗡」抖 | SimpleFOC 级联 `angle` 环：`P_angle` → 速度指令 → `PID_velocity`，把 AS5600 12bit 角度差分的噪声两级放大，`Uq` 在 ±0.1V 高频翻符号 | 改 `torque` **单环 PD** + 原点软死区（死区内 `Uq=0`，连阻尼一起关）+ 速度低通 + `motion_downsample`；默认 `K8 / B0.2 / Z0.012`，还抖就 `Z0.03` |
| 速度环 `T0` **停止时**抖 | `PID_velocity` 的 `I=5` 累积速度噪声 | `S1`（默认）在目标速度 <0.05 时临时切 `torque` 做纯阻尼电刹车 + 速度死区；`S0` 可复现原抖动（实测约 4.84° 摆幅），`S1` 后静止 0.0000 rad，`T2` 转动性能不变 |
| 弹簧偏软 / 回不到原点 | 刚度不足或稳态误差 | `K` 加大（4~12），过冲用 `B` 调；换原点用 `H` |

## 上位机

| 现象 | 原因 | 解法 |
| --- | --- | --- |
| `pip install pyserial` 装不上 | 本机 pip 环境受限 | 项目已改为 Win32 原生串口 API（`ctypes`），**不依赖任何第三方包** |
| 页面没遥测数据 | USB CDC 无回显 / COM 被占 / 旧服务进程残留 | `python server.py --selftest --com COMx` 自检；关 IDE 监视器、重烧固件、重启服务 |
| SSE 拿到的是旧数据 | 旧服务进程还占着端口 | 关掉旧的 `python server.py`；服务端口占用会自动从 8765 递增 |

## Blender / STL

| 现象 | 原因 | 解法 |
| --- | --- | --- |
| 首版外壳主体被削空、旋钮 STL 0 个三角 | 多个重叠 cutter **合并后**做 Exact Boolean，绕数互相抵消 | `boolean()` 改成逐个 cutter 单独应用（本项目已修） |
| STL 头部三角数与实际不一致 / 退化面 / 4 条未配对边 | 导出时过滤了三角形、圆角轮廓用直角近似 | `recalc()` 用 bmesh 清退化面、导出不再过滤；内腔与唇边改成真正的圆角轮廓 |
| 渲染太暗、标签倒置/遮挡 | 灯光与相机角度、文字朝向 | 调材质 / 世界背景 / 三点光、文字朝向、相机倾角与标签位置 |
| 无头渲染在集显上报错 | 不支持 Vulkan 会回退 | EEVEE 回退后仍能出图，约 70s，可忽略 |
| **上盖与底盒结合处不匹配、盖不下去** | 用 `BEVEL` 削整个薄板：6mm 圆角被 clamp 成上下斜切，盒口外轮廓（104.2×70.2）反而比内腔开口（105.2×71.2）小，侧壁在 z=36 被切穿，顶盖底面也不是平面；定位唇边又是一整块 104.4×70.4 实心板，正好压在四角螺柱（顶面 z=36）上 | 外形改用精确圆角棱柱 `prism(rounded_rect_poly(...))`，盒口留 2.4mm 平齐口沿、螺柱顶面与口沿共面；顶盖底面整面压合；唇边改 4 条直条、两端避开螺柱；用 `verify_fit.py` 自动校验 |

`python verify_stl.py` 独立复验三角数、退化面、边配对与法线；`python verify_fit.py` 独立复验结合处（口沿存在、外轮廓一致、唇边不越界、与螺柱不干涉、共面）。当前 3 个外壳 STL 全部 PASS（0 非流形 / 0 边界 / 0 法线异常），配合校验 11/11 PASS。底盒 2 个零面积三角形不影响切片。

## 一句口诀

**先接线（EN + VIN + 共地 + CDC），再低速（L3 + T0.5），最后闭环（PP check OK）；抖在原点调 Z，抖在停转开 S1；烧录前先放开串口。**
