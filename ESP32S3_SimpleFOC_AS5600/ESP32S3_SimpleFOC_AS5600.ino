/*
 * ESP32-S3-DevKitC-1（主控）+ DengFOC-Mini / MP6536 版（3PWM 驱动板，无主控）
 * + AS5600 + 无刷电机：让电机第一次转起来
 *
 * 由 ESP32-C3 版移植而来，参数与调试流程不变，只换了主控引脚与 PWM 后端。
 *
 * 用法：按 STAGE 分步验证，每步只改一个数字，编译上传，串口 115200 观察。
 *   STAGE 0  只测 1.83" TFT：不初始化电机/驱动/编码器，纯屏幕自检
 *   STAGE 1  只测 AS5600：手转电机轴，角度应在 0 ~ 6.28 rad 之间线性变化
 *   STAGE 2  开环速度：不依赖编码器，发 T6.28 应该正好 1 圈/秒
 *   STAGE 3  闭环 FOC：上电 initFOC 自动对齐（务必让轴空转！），
 *             看串口 "PP check: OK!" 校极对数。
 *             默认进入「弹簧回中」：手扭开、松手即弹回上电位置。
 *               M1 回中 / M0 切速度环(T2 起转) / K 刚度 / B 阻尼
 *               / Z 死区 / H 重设原点 / D 诊断
 *             原点抖动治理：单环 PD + 原点死区，不再用库自带的级联位置环
 *             速度环零速抖动治理：T0 时纯阻尼电刹车 + 速度死区，绕开 PID_velocity
 *               S1/S0 静音开关、G 阻尼、J 速度死区
 *
 * 环境：Arduino IDE 2.x + esp32 开发板包 3.x + SimpleFOC 库 2.3.4 以上（当前 2.4.0）
 *   开发板选     "ESP32S3 Dev Module"
 *   USB CDC On Boot = Enabled   （原生 USB 口，否则串口一片空白）
 *   Upload Speed    = 115200    （避开 Windows usbser.sys 切速时的错误 31）
 *   命令行等价 FQBN：esp32:esp32:esp32s3:CDCOnBoot=cdc,UploadSpeed=115200
 *
 * === 与 C3 版的两处本质差别 ===
 * 1) S3 有 MCPWM，SimpleFOC 默认走 MCPWM（三相同步时基），不是 C3 的 LEDC。
 *    BLDCDriver3PWM 用法完全一样，只是底层不同；S3 的 MCPWM 经 GPIO 矩阵
 *    任意映射，任意可用 GPIO 都能当 PWM，没有引脚组限制。
 *    若某些库版本组合下 MCPWM 异常，可加编译宏 SIMPLEFOC_ESP32_USELEDC
 *    强制退回 LEDC（arduino-cli: --build-property
 *    "compiler.cpp.extra_flags=-DSIMPLEFOC_ESP32_USELEDC"）。
 * 2) 引脚禁区完全不同，C3 的 3/4/5/6、7/10 不能照抄 S3 的接线参考。
 *    S3 禁止占用：GPIO0/3/45/46（strapping）、GPIO19/20（原生 USB D-/D+）、
 *    GPIO26~32（Flash/PSRAM，WROOM-1 模组内部占用）、GPIO33~37（部分
 *    WROOM-1 批次为 octal PSRAM）、GPIO43/44（默认 UART0 TX/RX）、
 *    GPIO48（板载 WS2812 RGB）。
 *    本例选用的 4/5/6/7/8/9 全部是安全的普通 GPIO，且 8/9 正是 S3 默认
 *    硬件 I2C 的 SDA/SCL，AS5600 时序最稳。
 *
 * === 已确认硬件：DengFOC-Mini 的 MP6536 版，5~24V / 5.5A 峰值 ===
 * MP6536 数据手册要点（决定了接线和限幅）：
 *   - VSP/VIN 供电 5~26V，板厂标 5~24V 留余量；欠压阈值约 4.4V，12V 最稳
 *   - 每相峰值限流 5.5A，是芯片内部逐周期限流，不是可持续电流
 *     （QFN-40 5x5 小板，连续 1~2A 就会明显发热，别长时间堵转）
 *   - 3PWM 输入：PWM 高 = 上管开，低 = 下管开，内部自带 10ns 死区
 *     → 正好对应 BLDCDriver3PWM，不需要 6PWM、不需要软件死区
 *   - PWM 逻辑高阈值仅 1.6~1.8V：S3 的 3.3V GPIO 可直接驱动，无需电平转换
 *   - 芯片只有 VSP 一个电源脚，没有独立逻辑电源输入脚
 *   - SHDNB（关断，低有效）与 STBYB（待机，高有效且内部默认下拉）必须同时为高
 *     才有输出；DengFOC-Mini 把它们在板上并到 EN，所以 EN=3.3V 是硬前提
 *   - FAULTB 开漏低有效：过流 / 过温(160°C) / 欠压时拉低，故障灯亮 → 立即断电
 *
 * === 接线（ESP32-S3 DevKitC-1 → DengFOC-Mini / AS5600）===
 *   GPIO4  -> 驱动板 IN1
 *   GPIO5  -> 驱动板 IN2
 *   GPIO6  -> 驱动板 IN3
 *   GPIO7  -> 驱动板 EN   (若把 EN 直接接 3.3V，删掉 driver 构造第 4 个参数)
 *   GPIO8  -> AS5600 SDA
 *   GPIO9  -> AS5600 SCL
 *   3V3    -> AS5600 VCC（只用 3.3V，别接 5V）
 *   GND    -> 驱动板 GND 与 AS5600 GND 必须共地
 *   ESP32-S3 单独用板上的原生 USB 口供电；驱动板 VIN/VM + GND 接外部
 *   12V 电源（先限流 1A，VIN 端并 470µF）。电机三相线接 M1/M2/M3。
 *   AS5600 正对轴端径向充磁磁铁，间距 1~3mm，同心。
 *
 * VCC 脚判别（只接 VIN + GND、其他线都不接，万用表量 VCC 对 GND）：
 *   已有 3.3V → 是板载 LDO 输出，别再灌电，可顺手给 AS5600 供电；
 *   0V       → 是输入/上拉参考，接 S3 的 3V3。
 *   判别错了会倒灌烧 LDO。FAULT / 故障灯可不接。
 *
 * 安全边界（5.5A 这版尤其要守住）：
 *   1) 电源 12V + 限流 1A；V_SUPPLY 绝不超过 24V（有编译期检查）。
 *   2) 相电流 ≈ voltage_limit / 相阻。相阻 10Ω 时 1V ≈ 0.1A，很安全；
 *      若换低阻航模电机（相阻 0.2Ω），1V 就是 5A → 直接撞 5.5A 限流报 FAULT。
 *      换电机前先量相阻（任意两相阻值 ÷2），低阻电机从 0.5V 甚至更低起。
 *   3) FAULT 灯亮 = 过流 / 过温 / 欠压，立刻断电查相线与限幅；部分板需重新上电。
 *   4) 灯哥配套例程默认 12V / 2208 云台电机 / 极对数 7，本文件沿用这组值。
 *
 * 烧录注意事项（S3 特有）：
 *   普通 esptool "hard-reset" 结束时会把芯片留在 ROM 下载模式，应用不启动，
 *   现象是串口打出 "waiting for download"、灯不亮、程序像没跑。
 *   → 必须用 --after watchdog-reset，或烧完按一下板上 RESET 键 / 重插 USB。
 *   本目录的 flash_and_run.bat 已内置该处理。
 *
 * === 板载 RGB 灯为什么可能「常亮」 ===
 *   DevKitC-1 的 GPIO48 是 WS2812，属于锁存型器件：只要 3V3 不断电，
 *   就会一直保持最后一次收到的颜色帧。Blink 固件刚好停在「亮」时被复位
 *   换成 SimpleFOC 固件，而旧版 SimpleFOC 代码完全不碰 GPIO48，于是灯
 *   保持常亮白光 —— 不是死机，也不是烧坏。断电重插即可熄灭。
 *   本版已接管这颗灯，用状态指示消除歧义：
 *     待机(target=0)  → 每 1.5s 短闪 80ms（心跳，证明程序在跑）
 *     有目标速度      → 常亮（表示正在驱动电机）
 * === 扩展：1.83" TFT / ST7789P3 / 240x284 / 4 线 SPI ===
 * 8 针模块：GND VCC SCL SDA RES DC CS BLK（没有 MISO）。
 *   GPIO12 SCL / GPIO11 SDA / GPIO10 CS / GPIO14 DC / GPIO15 RES / GPIO16 BLK
 *   3V3 + GND 供电。10~16 全部空闲，不与电机 4~7、AS5600 8/9 冲突。
 * 刷屏是阻塞式 SPI 传输，绝不能放进 loop() 打断 loopFOC()，因此显示单独
 * 钉在 core 0 的 FreeRTOS 任务里，loop() 只写一个 DisplayState 快照。
 * 驱动零依赖（TFT_ST7789P3.h），不用装 TFT_eSPI / Arduino_GFX。
 * 屏幕校准：STAGE 0 = 只测屏（完全不初始化电机）；运行时命令
 *   V 测试图 / I 反色 / C RGB-BGR / N 背光 / O<col>,<row> 显存偏移 /
 *   Q<MHz> 换 SPI 速率 / P 冻结成单帧静态图（A/B 定位刷新问题）/
 *   W<px> 圆角屏半径（手表屏四角遮罩，0=关闭）。
 * 屏幕玻璃是圆角（R≈4mm，像手表屏），GRAM 仍是完整矩形：UI 每帧把
 * 四角刷成底色并让标题避开圆角，测试图里用红线标出遮罩边界供 W 校准。
 * 驱动修复记录：setWindow() 发完 RAMWR 必须把 DC 拉回高电平，否则全部
 *   像素字节会被当作命令 -> 花屏，且像素里偶发 0x28/0x10 会关屏变黑。
 * 把 USE_TFT 改成 0 即可完全退回原来的纯串口固件。
 */

/* 显示扩展总开关：0 = 不编译任何 TFT 代码，1 = 启用仪表盘 */
#define USE_TFT      1

#include <Arduino.h>
#include <Wire.h>
#include <SimpleFOC.h>
#if USE_TFT
#include <SPI.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include "TFT_ST7789P3.h"
#include "TFT_UI.h"
#endif

/* 编译期防呆：S3 DevKitC-1 走原生 USB Serial/JTAG。若 Arduino IDE 里
 * 「工具 -> USB CDC On Boot」没设成 Enabled，Serial 会跑到 UART0(GPIO43/44)，
 * 电脑上看不到自检日志，T/L 指令也发不进去，现象很像「程序没跑」。
 */
#if defined(ARDUINO_USB_CDC_ON_BOOT) && !ARDUINO_USB_CDC_ON_BOOT
#error "USB CDC On Boot is DISABLED -> Arduino IDE: Tools > USB CDC On Boot > Enabled, then compile/upload again."
#endif

/* ==================== 0. 只改这一区 ==================== */
#define STAGE        3      // 0=只测TFT(不碰电机) 1=传感器 2=开环 3=闭环FOC
#define POLE_PAIRS   7      // 极对数：2208/2804 云台电机常见 7，看串口 PP check 结果校准
#define V_SUPPLY     12.0f  // VIN/VM 实测电压 [V]，MP6536 版只允许 5~24V
#define V_LIMIT      3.0f   // 电压限幅 [V]：STAGE 2 实测 1V 带不动、3V 才转，故闭环默认 3V
#define PHASE_R      10.0f  // 电机相阻 [Ω]：万用表量任意两相再 ÷2，云台电机约 5~10Ω

/* === 弹簧回中 v2：单环 PD + 原点死区（解决「在原点不停抖动」）===
 * 为什么不用库自带的 MotionControlType::angle 级联位置环：
 *   angle 环 = P_angle(位置误差) → 速度指令 → PID_velocity(速度误差)。
 *   AS5600 只有 12 bit，速度是角度差分，静止时噪声不小；这个噪声被两级
 *   增益放大，位置误差在零点反复翻符号，输出 Uq 在 ±0.1V 之间高频来回，
 *   电机就在原点「嗡嗡」抖。实测 K10 时轴摆幅 0.017 rad，降到 K3 反而
 *   更松、漂移更大 —— 单纯降增益治不了根。
 * 现在的做法：torque/voltage 模式下自己算 Uq，只有一层增益：
 *     Uq = Kp * soft_deadband(err) - Kd * lowpass(velocity)
 *   死区内把 Uq 直接清零，连阻尼项一起关掉，PWM 仍是 50%/50%/50%，
 *   电机既没有回正力也没有噪声驱动，彻底静止；一旦偏出死区立刻恢复弹簧。
 *   速度环不再参与，I 一律为 0（积分会累积、放手后冲过头）。
 * HOME_KP  刚度 [V/rad]，越大越硬，建议 4~12
 * HOME_KD  阻尼 [V/(rad/s)]，抑制回弹过冲；太大手感发涩、也可能重新引入噪声
 * HOME_DB  死区 [rad]，0.012 rad ≈ 0.7°；还抖就发 Z0.03 加大
 * HOME_VTF 速度低通时间常数 [s]，越大越平滑、响应略慢
 * HOME_DS  move() 下采样：每 (DS+1) 次算一次控制，拉长角度差分间隔降噪
 * 实测（本台电机）：K3/Z0.025 静止不抖，但回中卡在静摩擦处、残差 3.8°；
 *   K8/Z0.012/B0.2 回弹到位、静止摆幅 0.0046 rad、残差约 1.3°，故取后者。
 */
#define HOME_KP      8.0f
#define HOME_KD      0.20f
#define HOME_DB      0.012f
#define HOME_VTF     0.05f
#define HOME_DS      3

/* === 速度环零速静音（解决「M0 速度模式 T0 停转时抖动」）===
 * 库的 velocity 环是 current_sp = PID_velocity(target - shaft_velocity)。
 * 静止时 AS5600 的角度差分噪声不小，I=5 会把它积分成缓慢摆动的力矩，
 * 输出在零点反复翻符号，电机就在「停住」的位置嗡嗡抖；而且速度模式里
 * LPF_velocity.Tf 只有 0.01、motion_downsample=0，噪声比回中模式更大。
 * 做法：|target| 小于 VEL_STOP_EPS 时绕开 PID，切到 torque 模式自己算
 *     Uq = -G * soft_deadband(lowpass(velocity))
 * 只有纯阻尼、没有积分、没有位置保持：速度低于 J 死区时 Uq 直接归零，
 * 三相全在 50% 中点，彻底静音；高于死区则柔和刹住惯性滑行。
 * 非零指令仍用库原来的 velocity 环，T2 的转动表现完全不变。
 * S1/S0 可实时开关（S0 = 恢复原始库 PID，用于 A/B 对比），G/J 可实时调。
 */
#define VEL_STOP_EPS  0.05f   // |target| 低于它视为停车指令 [rad/s]
#define VEL_BRAKE_KD  0.20f   // 停车阻尼 [V/(rad/s)]，G 命令可调
#define VEL_BRAKE_DB  0.20f   // 速度死区 [rad/s]，J 命令可调；还抖就加大
#define VEL_BRAKE_VTF 0.05f   // 停车阻尼用的速度低通时间常数 [s]

// 防呆：按 MP6536 版板厂标称边界卡死，填错电压直接编译失败而不是烧板
static_assert(V_SUPPLY >= 5.0f && V_SUPPLY <= 24.0f,
              "DengFOC-Mini MP6536: V_SUPPLY must be within 5..24V");
static_assert(V_LIMIT / PHASE_R < 5.5f,
              "V_LIMIT / PHASE_R exceeds the MP6536 5.5A peak limit; lower V_LIMIT");

#define PIN_A        4      // IN1  （S3 安全 GPIO，避开 0/3/19/20/26-37/43/44/45/46/48）
#define PIN_B        5      // IN2
#define PIN_C        6      // IN3
#define PIN_EN       7      // EN
#define PIN_SDA      8      // AS5600 SDA（S3 默认硬件 I2C）
#define PIN_SCL      9      // AS5600 SCL

/* === 1.83" TFT / ST7789P3 / 240x284 / 4 线 SPI ===
 * 8 针：GND VCC SCL SDA RES DC CS BLK（屏幕不回读，MISO 只是占一个空闲脚）
 * 12/11/13/10 正好是 esp32 core 给 S3 定义的默认 SCK/MOSI/MISO/SS，
 * 走默认 FSPI 时序最稳；10~16 全部避开了电机 4~7、I2C 8/9 与 S3 引脚禁区。
 */
#define TFT_SCK      12
#define TFT_MOSI     11
#define TFT_MISO     13
#define TFT_CS       10
#define TFT_DC       14
#define TFT_RST      15
#define TFT_BL       16     // PWM 背光；不需要调光可直接把 BLK 接 3V3
#define TFT_SPI_HZ   4000000UL  // 4MHz：整屏约 0.27s。DC 修复后可稳跑；长线噪多发 Q2/Q1 降级
#define TFT_BL_PWM   0          // 0=GPIO 常高（无 PWM 纹波，推荐）；1=LEDC 5kHz PWM 调光
#define TFT_UI_CORE  0          // 刷屏任务所在核；排查 SPI 跨核问题时可改 1
#define TFT_W        240
#define TFT_H        284
#define TFT_COL_OFS  0      // 画面整体偏移时改这里，或运行时发 O<col>,<row>
#define TFT_ROW_OFS  0
#define TFT_INVERT   1      // IPS 模组多数需 INVON；黑白反了发 I 切换
#define TFT_BGR      1      // 红蓝互换发 C 切换
#define TFT_FPS_MS   150    // ~6 FPS：4MHz 下每帧约 0.2s 的 GRAM 写入，别让屏幕一直处于半刷新状态
/* 圆角屏（手表屏）四角遮罩半径 [px]。
 * 可视区约 30.5mm / 240px ≈ 0.127 mm/px -> R4mm ≈ 31px，取 30。
 * 规格里的 "R0.4" 若指 0.4mm（几乎看不出圆角）就改成 3；
 * 不用重编译：串口发 W<px> 实时调，W0 关闭，对齐后把值写回这里。 */
#define TFT_CORNER_PX 30
/* ==================================================== */

#if STAGE == 0 && !USE_TFT
#error "STAGE 0 (TFT self-test) requires USE_TFT = 1"
#endif

MagneticSensorI2C sensor = MagneticSensorI2C(AS5600_I2C);
BLDCMotor motor = BLDCMotor(POLE_PAIRS);
BLDCDriver3PWM driver = BLDCDriver3PWM(PIN_A, PIN_B, PIN_C, PIN_EN);
Commander command = Commander(Serial);

float target = 0;        // 速度模式 [rad/s]；回中模式 = 目标绝对角度 [rad]
bool  hapticMode = false;
float homeAngle  = 0;    // 弹簧回中的原点（上电位置，或 H 命令重设）
float springKp = HOME_KP;   // 弹簧刚度 [V/rad]，K 命令实时调
float springKd = HOME_KD;   // 阻尼 [V/(rad/s)]，B 命令实时调
float springDb = HOME_DB;   // 原点死区 [rad]，Z 命令实时调
float springUq = 0.0f;      // 最近一次算出的 Uq [V]，供 D 诊断（速度环下填库 PID 输出）
float velFilt  = 0.0f;      // 对 shaft_velocity 再做一层一阶低通
bool  velSilent = true;     // S1/S0：速度环零速静音刹车开关
float brakeKd  = VEL_BRAKE_KD;  // 停车阻尼，G 命令实时调
float brakeDb  = VEL_BRAKE_DB;  // 速度死区，J 命令实时调
float brakeUq  = 0.0f;      // 最近一次电刹车输出 [V]
bool  focReady = true;      // initFOC() 是否成功；失败时禁用电机但保留串口/屏幕调试

#if USE_TFT
/* loop() 写、显示任务读的快照；全部为 32 位以内标量，双核读写无需加锁 */
DisplayState dispState;
TFTDashboard dashboard(&dispState, TFT_SCK, TFT_MOSI, TFT_MISO,
                       TFT_CS, TFT_DC, TFT_RST, TFT_BL);

/* 显示任务钉在 core 0。loop()/loopFOC() 跑 core 1，SPI 阻塞传输不会
 * 打断电流环；优先级 1 与 loopTask 同级，不会饿死系统服务。 */
void tftTask(void*) {
  uint32_t n = 0;
  for (;;) {
    dashboard.renderFrame();
    // 每 100 帧打印一次，用来确认刷屏任务确实在 core 0 跑（而非卡死）
    if (++n % 100 == 0) {
      Serial.print(F("TFT: UI frames=")); Serial.println((unsigned long)n);
    }
    vTaskDelay(pdMS_TO_TICKS(TFT_FPS_MS));
  }
}

/* 显示命令只置标志位，真正的 SPI 操作由 core 0 在帧首统一执行，
 * 避免 core 1 的命令回调和刷屏任务同时抢 SPI 总线。 */
void doTftTest(char*)   { dashboard.request(TFT_REQ_TEST);      Serial.println(F("TFT: test pattern toggle")); }
void doTftInvert(char*) { dashboard.request(TFT_REQ_INVERT);    Serial.println(F("TFT: invert toggle")); }
void doTftBGR(char*)    { dashboard.request(TFT_REQ_BGR);       Serial.println(F("TFT: RGB/BGR toggle")); }
void doTftBL(char*)     { dashboard.request(TFT_REQ_BACKLIGHT); Serial.println(F("TFT: backlight toggle")); }
/* Q<MHz>：不重新编译就能逐级提速。发 Q2 / Q4 / Q8 看哪档能稳定出图。 */
void doTftSpeed(char* cmd) {
  long mhz = atol(cmd);
  if (mhz < 1 || mhz > 40) { Serial.println(F("TFT: use Q1..Q40 (MHz), e.g. Q4")); return; }
  dashboard.requestSpeed((uint32_t)mhz * 1000000UL);
  Serial.print(F("TFT: SPI -> ")); Serial.print(mhz);
  Serial.println(F(" MHz, reinit + redraw"));
}
void doTftOffset(char* cmd) {
  int x = 0, y = 0;
  if (sscanf(cmd, "%d,%d", &x, &y) == 2) {
    if (x < 0) x = 0;  if (x > 80) x = 80;
    if (y < 0) y = 0;  if (y > 80) y = 80;
    dashboard.requestOffsets((uint8_t)x, (uint8_t)y);
    Serial.print(F("TFT: offset = ")); Serial.print(x);
    Serial.print(F(",")); Serial.println(y);
  } else {
    Serial.println(F("Usage: O<col>,<row>   e.g. O0,20"));
  }
}
/* P：把 UI 冻结成「只画一帧静态图、之后不再写 GRAM」。
 * 花屏/黑屏时先用它做 A/B：冻结后画面稳定 = 持续刷新路径有问题；
 * 冻结后仍花屏 = 初始化或硬件问题。V/I/C/O 在冻结态仍会重画静态帧。 */
void doTftFreeze(char*) {
  const bool f = !dashboard.frozen();
  dashboard.setFrozen(f);
  Serial.println(f ? F("TFT: UI FROZEN - one static frame, no further GRAM writes")
                   : F("TFT: UI RESUMED - dynamic dashboard"));
}
/* W<px>：圆角屏四角遮罩半径，单位像素。发 V 进测试图后，红线就是当前
 * 遮罩边界，调到刚好贴住玻璃圆角即可；W0 关闭遮罩（直角模式）。
 * 与 Q/P 一样只置标志位，真正的重画在 core 0 帧首执行。 */
void doTftCorner(char* cmd) {
  long px = atol(cmd);
  if (px < 0 || px > 80) { Serial.println(F("TFT: use W0..W80 (px), e.g. W30")); return; }
  dashboard.requestCorner((uint16_t)px);
  Serial.print(F("TFT: rounded corner R = ")); Serial.print(px);
  Serial.println(F(" px (0 = square corners)"));
}
#endif

/* ==================== 弹簧回中（触觉旋钮）====================
 * torque + voltage 模式下 move(uq) 会让 current_sp = uq，loopFOC() 里
 * voltage.q = constrain(current_sp, -voltage_limit, voltage_limit)，
 * 也就是我们完全掌控输出电压，绕过库里两级 PID 的噪声放大。
 * 切换模式时清掉 PID 状态、恢复滤波与下采样参数，避免模式互串。
 */
void setHapticMode(bool on) {
  hapticMode = on;
  motor.P_angle.reset();
  motor.PID_velocity.reset();
  velFilt  = 0.0f;
  springUq = 0.0f;
  brakeUq  = 0.0f;
  if (on) {
    motor.controller = MotionControlType::torque;   // 电压模式：target 就是 Uq
    motor.LPF_velocity.Tf = HOME_VTF;              // 库内速度低通也调强
    motor.motion_downsample = HOME_DS;             // 降低控制频率，差分噪声更小
    homeAngle = motor.shaft_angle;                 // 以上电时的位置为原点
    target = homeAngle;                            // 注意是累积多圈的机械角，不是 0~6.28
    Serial.println(F("HAPTIC ON (quiet): K<stiffness> / B<damping> / Z<deadband> / H re-zero / M0 velocity."));
  } else {
    motor.controller = MotionControlType::velocity;   // 零速时 loop 会临时切 torque
    motor.LPF_velocity.Tf = 0.03f;   // 比原来的 0.01 更平滑，转动时噪声更小
    motor.motion_downsample = 0;
    motor.PID_velocity.P = 0.2f;
    motor.PID_velocity.I = 5.0f;
    motor.PID_velocity.D = 0.0f;
    motor.PID_velocity.limit = V_LIMIT;  // 积分输出不许超过电压限幅，防起转冲击
    motor.updateVelocityLimit(20.0f);
    target = 0.0f;
    Serial.println(F("HAPTIC OFF: velocity mode. T<rad/s> to spin; T0 stops silently."));
    Serial.println(F("           S1/S0 silent brake, G<damping>, J<speed deadband>."));
  }
}

void doMode(char* cmd) {
  float v = 1.0f;
  command.scalar(&v, cmd);
  setHapticMode(v > 0.5f);
}

void doHome(char* cmd) {
  (void)cmd;
  if (!hapticMode) { Serial.println(F("Not in haptic mode. Send M1 first.")); return; }
  homeAngle = motor.shaft_angle;
  target = homeAngle;
  Serial.print(F("New home = ")); Serial.println(homeAngle, 4);
}

/* K：弹簧刚度 [V/rad]。数值越大越硬，回正越急；太大容易在死区边缘来回弹。 */
void doStiffness(char* cmd) {
  command.scalar(&springKp, cmd);
  if (springKp < 0.0f)  springKp = 0.0f;
  if (springKp > 12.0f) springKp = 12.0f;   // 再大也只会撞 V_LIMIT 饱和
  Serial.print(F("spring Kp = ")); Serial.print(springKp, 3); Serial.println(F(" V/rad"));
}

/* B：阻尼 [V/(rad/s)]。回弹发飘/过冲就加大；手感发涩或有嗡嗡声就减小。 */
void doDamping(char* cmd) {
  command.scalar(&springKd, cmd);
  if (springKd < 0.0f) springKd = 0.0f;
  if (springKd > 1.0f) springKd = 1.0f;
  Serial.print(F("spring Kd = ")); Serial.print(springKd, 3); Serial.println(F(" V/(rad/s)"));
}

/* Z：原点死区 [rad]。还抖就加大（Z0.04 / Z0.06）；想要更跟手就减小（Z0.01）。
 * 死区不损失回弹行程：偏出死区后按 (|err|-DB) 计算，力是连续的。
 */
void doDeadband(char* cmd) {
  command.scalar(&springDb, cmd);
  if (springDb < 0.0f)  springDb = 0.0f;
  if (springDb > 0.3f)  springDb = 0.3f;
  Serial.print(F("deadband = ")); Serial.print(springDb, 4); Serial.println(F(" rad"));
}

/* === 速度环零速静音：S 开关 / G 阻尼 / J 速度死区 ===
 * S0 用于 A/B 对比：恢复库原始 PID（会重现抖动），S1 回静音刹车。
 */
void doSilent(char* cmd) {
  float v = 1.0f;
  command.scalar(&v, cmd);
  velSilent = (v > 0.5f);
  motor.PID_velocity.reset();
  Serial.print(F("zero-speed silent brake = "));
  Serial.println(velSilent ? F("ON (quiet)") : F("OFF (raw SimpleFOC PID, buzzes at T0)"));
}

void doBrakeKd(char* cmd) {
  command.scalar(&brakeKd, cmd);
  if (brakeKd < 0.0f) brakeKd = 0.0f;
  if (brakeKd > 1.0f) brakeKd = 1.0f;
  Serial.print(F("stop brake Kd = ")); Serial.print(brakeKd, 3);
  Serial.println(F(" V/(rad/s)"));
}

void doBrakeDb(char* cmd) {
  command.scalar(&brakeDb, cmd);
  if (brakeDb < 0.0f) brakeDb = 0.0f;
  if (brakeDb > 2.0f) brakeDb = 2.0f;
  Serial.print(F("stop velocity deadband = ")); Serial.print(brakeDb, 3);
  Serial.println(F(" rad/s"));
}

/* 板载 RGB 状态灯：只在状态翻转时通过 RMT 写一帧，
 * 平时不产生任何开销，不会拖慢 loopFOC()。
 */
void updateStatusLed() {
#if defined(RGB_BUILTIN) && defined(LED_BUILTIN)
  static bool lit = false;
  const bool idle = hapticMode || (target == 0.0f);
  const bool want = idle ? ((millis() % 1500UL) < 80UL) : true;
  if (want != lit) {
    lit = want;
    digitalWrite(LED_BUILTIN, want ? HIGH : LOW);  // 核心自动转 rgbLedWrite()
  }
#endif
}

/* T：速度模式下是目标速度 [rad/s]；回中模式下是「相对 home 的偏移」[rad]，
 * T0 即回到原点。这样两种模式共用一条指令，不会把轴甩到绝对 0 位。
 */
void doTarget(char* cmd) {
  float v = 0.0f;
  command.scalar(&v, cmd);
  target = hapticMode ? (homeAngle + v) : v;
}

/* 诊断命令 D：把软件链路的关键状态打印出来，用于定位「指令生效但电机不动」。
 * 只读取状态、不改任何控制量；AS5600 角度可直接判断轴到底有没有动。
 */
bool diagSensorReady = false;

void doDiag(char* cmd) {
  Serial.println(F("--- DIAG ---"));
  Serial.print(F("target=")); Serial.print(target, 2);
  Serial.print(F(" vlimit=")); Serial.print(motor.voltage_limit, 2);
  Serial.print(F(" drv_vlimit=")); Serial.print(driver.voltage_limit, 2);
  Serial.print(F(" enabled=")); Serial.print(motor.enabled);
  Serial.print(F(" status=")); Serial.print(static_cast<int>(motor.motor_status));
  Serial.print(F(" mode=")); Serial.println(hapticMode ? F("HAPTIC") : F("VELOCITY"));
  Serial.print(F("home=")); Serial.print(homeAngle, 4);
  Serial.print(F(" shaft=")); Serial.print(motor.shaft_angle, 4);
  Serial.print(F(" err=")); Serial.print(target - motor.shaft_angle, 4);
  Serial.print(F(" vel=")); Serial.println(motor.shaft_velocity, 3);
  Serial.print(F("spring Kp/Kd/db=")); Serial.print(springKp, 2);
  Serial.print(F("/")); Serial.print(springKd, 3);
  Serial.print(F("/")); Serial.println(springDb, 4);
  Serial.print(F("Uq(out)=")); Serial.print(springUq, 3);
  Serial.print(F(" velFilt=")); Serial.println(velFilt, 3);
  Serial.print(F("Ua/Ub/Uc=")); Serial.print(motor.Ua, 2);
  Serial.print(F("/")); Serial.print(motor.Ub, 2);
  Serial.print(F("/")); Serial.println(motor.Uc, 2);
  if (diagSensorReady) {
    Serial.print(F("angle=")); Serial.println(sensor.getAngle(), 4);
  } else {
    Serial.println(F("angle=(AS5600 not initialized)"));
  }
  // 仅供参考：GPIO 输入回环未必能读回 MCPWM 输出，恒 0 不代表没有 PWM
  unsigned int hi = 0;
  const int N = 1500;
  for (int i = 0; i < N; i++) hi += digitalRead(PIN_A);
  Serial.print(F("GPIO4 readback high%=")); Serial.println(100.0f * hi / N, 1);
  Serial.print(F("zero-speed silent=")); Serial.print(velSilent ? 1 : 0);
  Serial.print(F(" brake Kd/db=")); Serial.print(brakeKd, 3);
  Serial.print(F("/")); Serial.print(brakeDb, 3);
  Serial.print(F(" brakeUq=")); Serial.println(brakeUq, 3);
  Serial.println(F("--- end ---"));
}

void doLimit(char* cmd) {
  command.scalar(&motor.voltage_limit, cmd);
  // 运行时第二道保险：L 命令也卡在「相阻 × 峰值电流的一半」与电源电压之内，
  // 手滑发 L20 不会让 MP6536 撞上 5.5A 逐周期限流而报 FAULT。
  const float halfPeak = 5.5f * PHASE_R * 0.5f;
  const float safeMax  = (V_SUPPLY < halfPeak) ? V_SUPPLY : halfPeak;
  if (motor.voltage_limit > safeMax) {
    motor.voltage_limit = safeMax;
    Serial.print(F("L clamped to ")); Serial.print(safeMax, 2);
    Serial.println(F(" V (MP6536 5.5A peak guard)"));
  }
  if (motor.voltage_limit < 0.0f) motor.voltage_limit = 0.0f;
}

bool sensorPresent() {
  Wire.beginTransmission(0x36);          // AS5600 的 I2C 地址
  return (Wire.endTransmission() == 0);  // AS5600L 是 0x40，需改这里和配置
}

void printConfig() {
  Serial.println(F("=== DengFOC-Mini (MP6536) + ESP32-S3 DevKitC-1 ==="));
  Serial.print(F("STAGE ")); Serial.print(STAGE);
  Serial.print(F(" | pole_pairs ")); Serial.print(POLE_PAIRS);
  Serial.print(F(" | Vsupply ")); Serial.print(V_SUPPLY, 1);
  Serial.print(F(" V | Vlimit ")); Serial.print(V_LIMIT, 1);
  Serial.println(F(" V"));
#if defined(SOC_MCPWM_SUPPORTED) && !defined(SIMPLEFOC_ESP32_USELEDC)
  Serial.println(F("PWM backend: MCPWM (3 synced channels, GPIO matrix)"));
#else
  Serial.println(F("PWM backend: LEDC"));
#endif
  Serial.println(F("Chip MP6536: VIN 5-24V, 5.5A PEAK per phase (not continuous)."));
  Serial.print(F("Est. phase current at startup: "));
  Serial.print(V_LIMIT / PHASE_R, 2);
  Serial.print(F(" A  (Vlimit / PHASE_R=")); Serial.print(PHASE_R, 1);
  Serial.println(F(" ohm; measure your motor and update PHASE_R)"));
  Serial.print(F("IN1/2/3 GPIO ")); Serial.print(PIN_A); Serial.print(F("/"));
  Serial.print(PIN_B); Serial.print(F("/")); Serial.print(PIN_C);
  Serial.print(F(" | EN GPIO ")); Serial.println(PIN_EN);
  Serial.print(F("I2C SDA/SCL GPIO ")); Serial.print(PIN_SDA);
  Serial.print(F("/")); Serial.println(PIN_SCL);
  Serial.print(F("AS5600 @0x36: "));
  if (sensorPresent()) Serial.println(F("OK"));
  else Serial.println(F("NOT FOUND (check wiring; AS5600L is 0x40)"));
  Serial.println(F("3PWM + EN: EN drives SHDNB & STBYB high. 3.3V PWM is OK."));
  Serial.println(F("FAULT LED on = overcurrent/overtemp/UVLO -> POWER OFF NOW."));
  Serial.println(F("No motion? Check EN=HIGH, VIN polarity, common GND, VCC pin, then raise L."));
  Serial.println(F("Onboard RGB: 1.5s heartbeat when idle, solid when target != 0."));
  Serial.println(F("Diagnostics: send D to print target/limits/Ua,Ub,Uc/AS5600 angle."));
  Serial.println(F("Haptic v2: single-loop PD + deadband. M1/M0, K stiffness, B damping,"));
  Serial.println(F("           Z deadband, H re-zero. If buzzing at home, try Z0.03 / B0.10."));
  Serial.println(F("Velocity idle: silent brake S1/S0, G<damping>, J<speed deadband>; T0 quiet."));
#if USE_TFT
  Serial.print(F("TFT ST7789P3 ")); Serial.print(TFT_W);
  Serial.print(F("x")); Serial.print(TFT_H);
  Serial.print(F(" @ ")); Serial.print(TFT_SPI_HZ / 1000);
  Serial.print(F(" kHz, BL=")); Serial.print(TFT_BL_PWM ? F("PWM") : F("GPIO"));
  Serial.print(F(", UI core ")); Serial.print(TFT_UI_CORE);
  Serial.print(F(", corner R=")); Serial.print(TFT_CORNER_PX);
  Serial.println(F(" px (rounded screen)"));
  Serial.print(F("TFT GPIO SCK/MOSI/CS/DC/RST/BL = "));
  Serial.print(TFT_SCK); Serial.print(F("/")); Serial.print(TFT_MOSI);
  Serial.print(F("/"));  Serial.print(TFT_CS);  Serial.print(F("/"));
  Serial.print(TFT_DC);  Serial.print(F("/"));  Serial.print(TFT_RST);
  Serial.print(F("/"));  Serial.println(TFT_BL);
  Serial.println(F("TFT cmds: V test / I invert / C RGB-BGR / N backlight / O<col>,<row> / Q<MHz> speed / P freeze / W<px> corner"));
#endif
  Serial.println(F("====================================================="));
}

void setup() {
  Serial.begin(115200);
#if defined(RGB_BUILTIN) && defined(LED_BUILTIN)
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);        // 清掉上一份固件留下的 WS2812 锁存亮度
#endif
  _delay(1000);                          // 等 USB 串口就绪，否则看不到开头日志
  SimpleFOCDebug::enable(&Serial);       // 打印 MOT:/SEN: 调试信息，非常关键

#if USE_TFT
  // 屏幕初始化放在最前面：就算后面 initFOC() 失败或 AS5600 没接，
  // 开机画面也已经亮起，能立刻判断是屏的问题还是电机的问题。
  dashboard.begin(TFT_SPI_HZ, TFT_W, TFT_H, TFT_COL_OFS, TFT_ROW_OFS,
                  TFT_INVERT != 0, TFT_BGR != 0);
  dashboard.setCorner(TFT_CORNER_PX);          // 圆角屏四角遮罩
  dashboard.showSplash();
  Serial.println(F("TFT: splash drawn (WHITE bg + ORANGE block + rounded corners)"));
  command.add('V', doTftTest,   "V toggle TFT test pattern");
  command.add('I', doTftInvert, "I toggle display inversion");
  command.add('C', doTftBGR,    "C toggle RGB/BGR color order");
  command.add('N', doTftBL,     "N toggle backlight");
  command.add('O', doTftOffset, "O<col>,<row> set CASET/RASET offset");
  command.add('Q', doTftSpeed,  "Q<MHz> set SPI speed (1..40)");
  command.add('P', doTftFreeze, "P freeze/resume UI (single-frame A/B test)");
  command.add('W', doTftCorner, "W<px> rounded-screen corner radius (0=square)");
  Serial.print(F("TFT: ST7789P3 ready, BL="));
  Serial.print(TFT_BL_PWM ? F("PWM") : F("GPIO"));
  Serial.print(F(", UI core "));
  Serial.print(TFT_UI_CORE);
  Serial.print(F(", corner R=")); Serial.print(TFT_CORNER_PX);
  Serial.println(F(" px"));
  /* 先让开机画面完整停留 2.5s，期间 core 0 完全不碰 SPI。
   * 之前任务在这之前就启动，第一帧 drawStatic() 会立刻把开机画面刷成黑底，
   * 用户根本分不清「开机画面有没有画对」。 */
  _delay(2500);
  xTaskCreatePinnedToCore(tftTask, "TFT_UI", 6144, NULL, 1, NULL, TFT_UI_CORE);
  Serial.println(F("TFT: UI task started; send P to freeze at one static frame"));
#endif

#if STAGE == 0
  // 只测屏幕：完全不初始化 Wire / driver / motor，电机不会上电、不会校准。
  Serial.println(F("=== STAGE 0: TFT self-test. Motor/driver/sensor NOT initialized. ==="));
  Serial.println(F("V test / I invert / C RGB-BGR / N backlight / O<col>,<row> / Q<MHz> / P freeze / W<px> corner"));
  dispState.mode = 3;
  dashboard.request(TFT_REQ_TEST);
  return;
#endif

  Wire.begin(PIN_SDA, PIN_SCL);          // 必须在 sensor.init() 之前
  Wire.setClock(400000);                 // 读数跳就降到 100000
  printConfig();                         // 上电先打印配置 + AS5600 在线状态

#if STAGE == 1
  if (!sensorPresent()) {
    Serial.println(F("AS5600 not found at 0x36! Check SDA/SCL/VCC/GND."));
    while (1) { _delay(1000); }
  }
  sensor.init();
  Serial.println(F("Sensor ready. Turn the shaft by hand."));
  Serial.println(F("Angle should sweep 0 .. 6.28 rad per revolution."));
  return;
#endif

#if STAGE == 2
  // 仅供 D 诊断命令回读角度：初始化 AS5600 但不 linkSensor，
  // 开环控制仍然完全不依赖编码器。
  if (sensorPresent()) {
    sensor.init();
    diagSensorReady = true;
  }
#endif

  driver.voltage_power_supply = V_SUPPLY;
  driver.voltage_limit = V_SUPPLY;
  driver.pwm_frequency = 20000;          // S3 走 MCPWM；MP6536 支持到 1MHz，
                                         // 20kHz 避开音频且内部 10ns 死区已自动处理
  if (!driver.init()) {
    Serial.println(F("Driver init failed!"));
    while (1) { _delay(1000); }
  }
  motor.linkDriver(&driver);

  motor.voltage_limit = V_LIMIT;         // 电流 ≈ 电压 / 相阻，这行是保险丝

#if STAGE == 3
  if (!sensorPresent()) {
    Serial.println(F("AS5600 not found at 0x36! Check SDA/SCL/VCC/GND."));
    while (1) { _delay(1000); }
  }
  sensor.init();
  diagSensorReady = true;                 // 让 D 命令在闭环下也能回读 AS5600 角度
  motor.linkSensor(&sensor);

  motor.controller = MotionControlType::velocity;   // 闭环速度
  motor.PID_velocity.P = 0.2f;
  motor.PID_velocity.I = 5.0f;
  motor.PID_velocity.D = 0.0f;
  motor.LPF_velocity.Tf = 0.05f;
  motor.velocity_limit = 20.0f;
  motor.voltage_sensor_align = 3.0f;      // 与 V_LIMIT 一致：1V 带不动，3V 才转得动
#else
  motor.controller = MotionControlType::velocity_openloop;  // 开环，不需要编码器
#endif

  motor.useMonitoring(Serial);
  if (!motor.init()) {
    Serial.println(F("Motor init failed!"));
    while (1) { _delay(1000); }
  }

#if STAGE == 3
  // 校准时电机会轻微正反各转一下，务必让它空转、别捏着轴
  if (motor.initFOC() != 1) {
    // 不在这里 while(1)：否则 command.run() 永远不执行，屏幕校准命令 V/I/C/N/O/Q/P/W
    // 和串口诊断全部失效。常见原因是 12V 没接 / 三相线松 / 轴被卡住。
    focReady = false;
    motor.disable();                   // 未校准时禁止输出，避免按错误电角度乱加电压
    Serial.println(F("initFOC failed! Check pole pairs / sensor direction."));
    Serial.println(F("Motor outputs DISABLED. Check 12V / 3 phases / EN / free shaft."));
    Serial.println(F("Press RESET to retry. Serial + TFT cmds (V/I/C/N/O/Q/P/W) stay live."));
  }
#endif

  command.add('T', doTarget, "T<rad/s> velocity mode / T<offset rad> haptic mode");
  command.add('L', doLimit,  "voltage limit [V], e.g. L2");
  command.add('D', doDiag,   "diagnostics: target/limits/Ua,Ub,Uc/AS5600 angle");
#if STAGE == 3
  command.add('M', doMode,      "M1=spring-to-home (haptic), M0=velocity mode");
  command.add('H', doHome,      "set the current shaft position as the new home");
  command.add('K', doStiffness, "spring stiffness [V/rad], e.g. K2 / K5");
  command.add('B', doDamping,   "spring damping [V/(rad/s)], e.g. B0.15 / B0.4");
  command.add('Z', doDeadband,  "home deadband [rad], e.g. Z0.05 to stop buzzing");
  command.add('S', doSilent,   "S1=silent zero-speed brake (default), S0=raw velocity PID");
  command.add('G', doBrakeKd,  "stopping brake damping [V/(rad/s)], e.g. G0.3");
  command.add('J', doBrakeDb,  "zero-speed velocity deadband [rad/s], e.g. J0.3");
  setHapticMode(true);       // 上电默认就是弹簧回中，烧完直接用手扭即可试
  Serial.println(F("HAPTIC READY (quiet). Twist the shaft by hand and let go -> snaps back."));
#else
  Serial.println(F("Motor ready. Send T6.28 for 1 rev/s. Start with a small T!"));
#endif
  _delay(500);
}

/* 计算弹簧回中的输出电压 Uq：单环 PD + 软死区。
 * err = 目标角 - 当前轴角；死区内 e=0 且 Uq=0（连阻尼一起关，杜绝噪声驱动）。
 * 速度反馈先过 motor.LPF_velocity (Tf=0.05)，这里再过一层一阶低通，
 * 阻尼项才不会把 AS5600 的差分噪声变成高频力矩。
 */
/* 共用的一阶速度低通：弹簧阻尼与停车刹车都吃这路滤波后的速度，
 * 避免 AS5600 的角度差分噪声直接变成力矩。每帧只调用一次。
 */
float filteredVelocity(float tf) {
  static uint32_t lastUs = 0;
  const uint32_t now = micros();
  float dt = (lastUs == 0) ? 0.001f : (now - lastUs) * 1.0e-6f;
  lastUs = now;
  if (dt < 0.0002f) dt = 0.0002f;                 // 防止除零 / 首帧异常
  if (dt > 0.05f)   dt = 0.05f;
  const float alpha = dt / (tf + dt);
  velFilt += alpha * (motor.shaft_velocity - velFilt);
  return velFilt;
}

float computeSpringUq() {
  const float err = target - motor.shaft_angle;
  float e = 0.0f;
  if (err > springDb)       e = err - springDb;   // 软死区：出区后力连续
  else if (err < -springDb) e = err + springDb;
  const float v = filteredVelocity(HOME_VTF);
  if (e == 0.0f) return 0.0f;                    // 死区内完全静音
  return springKp * e - springKd * v;
}

/* 速度环零指令时的「静音电刹车」：只有纯阻尼，没有积分、没有位置保持。
 * 速度低于死区就把 Uq 直接归零（三相 50% 中点），彻底消除零速抖动；
 * 出死区后阻尼连续增长，柔和刹住惯性滑行。
 */
float computeBrakeUq() {
  const float v = filteredVelocity(VEL_BRAKE_VTF);
  float e = 0.0f;
  if (v > brakeDb)       e = v - brakeDb;
  else if (v < -brakeDb) e = v + brakeDb;
  if (e == 0.0f) return 0.0f;
  return -brakeKd * e;
}

void loop() {
  updateStatusLed();                     // 非阻塞，不占用 loopFOC 的时间预算
#if STAGE == 0
  command.run();                         // 屏幕自检：只处理 V/I/C/N/O/Q/P/W，电机不参与
  _delay(20);
  return;
#endif
#if STAGE == 1
  sensor.update();
  Serial.print(sensor.getAngle(), 4);
  Serial.print(F("\t"));
  Serial.println(sensor.getVelocity(), 4);
#if USE_TFT
  dispState.angle    = sensor.getAngle();
  dispState.velocity = sensor.getVelocity();
  dispState.mode     = 2;
  dispState.sensorOk = true;
  dispState.enabled  = true;
#endif
  _delay(100);
  command.run();
#else
  command.run();                       // 命令始终可用，即使 FOC 校准失败
  if (!focReady) {
#if USE_TFT
    dispState.uq      = 0.0f;
    dispState.enabled = false;
    dispState.mode    = 4;             // 屏幕显示 FOC FAIL，但 V/I/C/N/O/Q/P/W 仍可校准
#endif
    _delay(20);
    return;                            // 跳过 loopFOC()/move()，驱动已 disable
  }
  // SimpleFOC 2.4.0 的关键点：setPhaseVoltage()（真正写 PWM）在 loopFOC() 里执行，
  // move() 只计算 current_sp。开环模式也必须调用 loopFOC()，否则三相电压恒为 0、
  // 电机完全不动（曾据此误判为硬件故障）。顺序必须 loopFOC() 在前、move() 在后。
  motor.loopFOC();                     // 必须尽可能快地循环
  if (hapticMode) {
    if (motor.controller != MotionControlType::torque) motor.controller = MotionControlType::torque;
    springUq = computeSpringUq();
    springUq = constrain(springUq, -motor.voltage_limit, motor.voltage_limit);
    brakeUq  = 0.0f;
    motor.move(springUq);              // torque/voltage：target 就是 Uq
  } else if (velSilent && fabsf(target) < VEL_STOP_EPS) {
    // 零指令：绕开库的 PID_velocity（I 项把速度噪声积分成周期性力矩 → 抖）
    if (motor.controller != MotionControlType::torque) {
      motor.controller = MotionControlType::torque;
      motor.PID_velocity.reset();      // 清积分，避免下次起转时输出冲击
    }
    brakeUq = computeBrakeUq();
    brakeUq = constrain(brakeUq, -motor.voltage_limit, motor.voltage_limit);
    springUq = brakeUq;                // D 诊断 / 上位机看到的是真实输出电压
    motor.move(brakeUq);
  } else {
    if (motor.controller != MotionControlType::velocity) {
      motor.controller = MotionControlType::velocity;
      motor.PID_velocity.reset();
    }
    motor.move(target);
    springUq = motor.current_sp;       // 库 PID 输出（电压模式下就是 Uq）
    brakeUq  = 0.0f;
  }
  // motor.monitor();                   // 需要看曲线再打开，会明显拖慢循环
#if USE_TFT
  /* 只写几个标量（core 0 读），不做任何 SPI 操作，不影响 loopFOC() 频率 */
  dispState.angle    = motor.shaft_angle - homeAngle;
  dispState.velocity = motor.shaft_velocity;
  dispState.target   = hapticMode ? (target - homeAngle) : target;
  dispState.uq       = springUq;
  dispState.kp       = springKp;
  dispState.kd       = springKd;
  dispState.db       = springDb;
  dispState.vlimit   = motor.voltage_limit;
  dispState.mode     = hapticMode ? 1 : 0;
  dispState.silent   = velSilent;
  dispState.enabled  = motor.enabled;
  dispState.sensorOk = diagSensorReady;
#endif
  // command.run() 已在 loop 开头执行（校准失败时也能响应）
#endif
}
