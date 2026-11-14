/*
 * ESP32-C3（主控）+ DengFOC-Mini / MP6536 版（3PWM 驱动板，无主控）+ AS5600 + 无刷电机
 * 让电机第一次转起来（已按 MP6536 5~24V / 5.5A 峰值定稿）
 *
 * 用法：按 STAGE 分三步验证，每步只改一个数字，编译上传，串口 115200 观察。
 *   STAGE 1  只测 AS5600：手转电机轴，角度应在 0 ~ 6.28 rad 之间线性变化
 *   STAGE 2  开环速度：不依赖编码器，发 T6.28 应该正好 1 圈/秒
 *   STAGE 3  闭环 FOC：接上编码器，initFOC 自动校准，发 T10 等调速
 *
 * 环境：Arduino IDE 2.x + esp32 开发板包 3.x + SimpleFOC 库 2.3.4 以上（当前 2.4.0）
 *       开发板选 "ESP32C3 Dev Module"，USB CDC 按你的板子实际情况开关
 *
 * === 已确认硬件：DengFOC-Mini 的 MP6536 版，5~24V / 5.5A 峰值 ===
 *
 * MP6536 数据手册要点（这些决定了接线和限幅）：
 *   - VSP/VIN 供电 5~26V，板厂标 5~24V 留余量；欠压阈值约 4.4V，12V 最稳
 *   - 每相峰值限流 5.5A，是芯片内部逐周期限流，不是可持续电流
 *     （QFN-40 5x5 小板，连续 1~2A 就会明显发热，别长时间堵转）
 *   - 3PWM 输入：PWM 高 = 上管开，低 = 下管开，内部自带 10ns 死区
 *     → 正好对应 BLDCDriver3PWM，不需要 6PWM、不需要软件死区
 *   - PWM 逻辑高阈值仅 1.6~1.8V：ESP32-C3 的 3.3V GPIO 可直接驱动，无需电平转换
 *   - 芯片只有 VSP 一个电源脚，没有独立逻辑电源输入脚
 *   - SHDNB（关断，低有效）与 STBYB（待机，高有效且内部默认下拉）必须同时为高
 *     才有输出；DengFOC-Mini 把它们在板上并到 EN，所以 EN=3.3V 是硬前提
 *   - FAULTB 开漏低有效：过流 / 过温(160°C) / 欠压时拉低，故障灯亮 → 立即断电
 *
 * DengFOC-Mini 接口（以板上丝印为准）：
 *   IN1 / IN2 / IN3  三相 PWM 输入，是 3PWM 不是 6PWM
 *   EN               使能，高电平有效，接 GPIO6 或直接接 3.3V
 *   FAULT / 故障灯    开漏故障指示，可不接
 *   VCC              见下方判别，不要盲目灌电
 *   VIN / VM + GND   电机电源，接外部直流电源
 *   M1 / M2 / M3     电机三相线
 *
 * 接线（ESP32-C3，避开 GPIO2/8/9 启动脚、18/19 USB、20/21 串口）：
 *   GPIO3  -> 驱动板 IN1
 *   GPIO4  -> 驱动板 IN2
 *   GPIO5  -> 驱动板 IN3
 *   GPIO6  -> 驱动板 EN  (若把 EN 直接接 3.3V，删掉 driver 第 4 个参数)
 *   GPIO7  -> AS5600 SDA
 *   GPIO10 -> AS5600 SCL
 *   3V3    -> AS5600 VCC（只用 3.3V，别接 5V）
 *   GND    -> 驱动板 GND 与 AS5600 GND 必须共地
 *   ESP32-C3 单独用 USB 供电；驱动板 VIN/VM + GND 接外部电源，12V 起步并限流 1A
 *
 * VCC 脚判别（只接 VIN + GND、其他线都不接，用万用表量 VCC 对 GND）：
 *   已有 3.3V → 是板载 LDO 输出，别再灌电，可顺手给 AS5600 供电；
 *   0V       → 是输入/上拉参考，接 ESP32 的 3V3。
 *   两种情况芯片都能工作（因为逻辑电源不是必需的），但判别错了会倒灌烧 LDO。
 *
 * 安全边界（5.5A 这版尤其要守住）：
 *   1) 电源 12V + 限流 1A，VIN 端并 470µF；V_SUPPLY 绝不超过 24V（有编译期检查）。
 *   2) 相电流 ≈ voltage_limit / 相阻。相阻 10Ω 时 1V ≈ 0.1A，很安全；
 *      若换低阻航模电机（相阻 0.2Ω），1V 就是 5A，会直接撞上 5.5A 限流 → FAULT。
 *      换电机前先量相阻（任意两相阻值 ÷ 2），按 V_LIMIT ≤ 目标电流 × 相阻 反算，
 *      低阻电机从 0.5V 甚至更低起。
 *   3) FAULT 灯亮 = 过流 / 过温 / 欠压，立刻断电查相线与限幅；部分板会自锁，需重新上电。
 *   4) 灯哥配套例程默认 12V / 2208 云台电机 / 极对数 7，本文件沿用这组值。
 *
 * AS5600 正对轴端径向磁铁，间距 1~3mm，同心。
 */

#include <Arduino.h>
#include <Wire.h>
#include <SimpleFOC.h>

/* 编译期防呆：ESP32-C3 SuperMini 走原生 USB。若 Arduino IDE 里
 * 「工具 -> USB CDC On Boot」没设成 Enabled，Serial 会跑到 UART0(GPIO20/21)，
 * 电脑上看不到自检日志，T/L 指令也发不进去，现象很像「程序没跑」。
 * 与其烧出一个静默固件，不如直接编译失败并给出提示。
 * 命令行等价配置：FQBN=esp32:esp32:esp32c3:CDCOnBoot=cdc
 */
#if defined(ARDUINO_USB_CDC_ON_BOOT) && !ARDUINO_USB_CDC_ON_BOOT
#error "USB CDC On Boot is DISABLED -> Arduino IDE: Tools > USB CDC On Boot > Enabled, then compile/upload again."
#endif

/* ==================== 0. 只改这一区 ==================== */
#define STAGE        2      // 1=传感器自检  2=开环转动  3=闭环FOC
#define POLE_PAIRS   7      // 极对数：2208/2804 云台电机常见 7，按 STAGE 2 实测校准
#define V_SUPPLY     12.0f  // VIN/VM 实测电压 [V]，MP6536 版只允许 5~24V
#define V_LIMIT      1.0f   // 起转电压限幅 [V]，从 1V 起，用 L 命令逐步加
#define PHASE_R      10.0f  // 电机相阻 [Ω]：万用表量任意两相再 ÷2，云台电机约 5~10Ω

// 防呆：按 MP6536 版板厂标称边界卡死，填错电压直接编译失败而不是烧板
static_assert(V_SUPPLY >= 5.0f && V_SUPPLY <= 24.0f,
              "DengFOC-Mini MP6536: V_SUPPLY must be within 5..24V");
static_assert(V_LIMIT / PHASE_R < 5.5f,
              "V_LIMIT / PHASE_R exceeds the MP6536 5.5A peak limit; lower V_LIMIT");

#define PIN_A        3
#define PIN_B        4
#define PIN_C        5
#define PIN_EN       6
#define PIN_SDA      7
#define PIN_SCL      10
/* ==================================================== */

MagneticSensorI2C sensor = MagneticSensorI2C(AS5600_I2C);
BLDCMotor motor = BLDCMotor(POLE_PAIRS);
BLDCDriver3PWM driver = BLDCDriver3PWM(PIN_A, PIN_B, PIN_C, PIN_EN);
Commander command = Commander(Serial);

float target = 0;   // 目标速度 [rad/s]，上电保持 0，必须手动发指令才转

void doTarget(char* cmd) { command.scalar(&target, cmd); }

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
  Serial.println(F("=== DengFOC-Mini (MP6536) + ESP32-C3 ==="));
  Serial.print(F("STAGE ")); Serial.print(STAGE);
  Serial.print(F(" | pole_pairs ")); Serial.print(POLE_PAIRS);
  Serial.print(F(" | Vsupply ")); Serial.print(V_SUPPLY, 1);
  Serial.print(F(" V | Vlimit ")); Serial.print(V_LIMIT, 1);
  Serial.println(F(" V"));
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
  Serial.println(F("==========================================="));
}

void setup() {
  Serial.begin(115200);
  _delay(1000);                          // 等 USB 串口就绪，否则看不到开头日志
  SimpleFOCDebug::enable(&Serial);       // 打印 MOT:/SEN: 调试信息，非常关键

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

  driver.voltage_power_supply = V_SUPPLY;
  driver.voltage_limit = V_SUPPLY;
  driver.pwm_frequency = 20000;          // ESP32-C3 走 LEDC；MP6536 支持到 1MHz，
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
  motor.linkSensor(&sensor);

  motor.controller = MotionControlType::velocity;   // 闭环速度
  motor.PID_velocity.P = 0.2f;
  motor.PID_velocity.I = 5.0f;
  motor.PID_velocity.D = 0.0f;
  motor.LPF_velocity.Tf = 0.01f;
  motor.velocity_limit = 20.0f;
  motor.voltage_sensor_align = 1.0f;      // 校准时也要限流
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
    Serial.println(F("initFOC failed! Check pole pairs / sensor direction."));
    while (1) { _delay(1000); }
  }
#endif

  command.add('T', doTarget, "target velocity [rad/s], e.g. T6.28");
  command.add('L', doLimit,  "voltage limit [V], e.g. L2");
  Serial.println(F("Motor ready. Send T6.28 for 1 rev/s. Start with a small T!"));
  _delay(500);
}

void loop() {
#if STAGE == 1
  sensor.update();
  Serial.print(sensor.getAngle(), 4);
  Serial.print(F("\t"));
  Serial.println(sensor.getVelocity(), 4);
  _delay(100);
#else
  // SimpleFOC 2.4.0：真正写 PWM 的 setPhaseVoltage() 在 loopFOC() 里执行，
  // move() 只计算 current_sp。开环模式也必须调用 loopFOC()，
  // 否则三相电压恒为 0、电机完全不动。顺序：loopFOC() 在前、move() 在后。
  motor.loopFOC();                     // 必须尽可能快地循环
  motor.move(target);
  // motor.monitor();                   // 需要看曲线再打开，会明显拖慢循环
  command.run();
#endif
}
