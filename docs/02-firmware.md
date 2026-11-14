# 02 · 固件、校准与控制算法

主固件：`ESP32S3_SimpleFOC_AS5600/ESP32S3_SimpleFOC_AS5600.ino`。所有可调项集中在文件顶部「只改这一区」。

## 编译与烧录设置

| 项 | 值 |
| --- | --- |
| IDE | Arduino IDE 2.x（实测 2.3.10）+ esp32 包 3.x（实测 3.3.10-cn）+ Simple FOC 2.4.0 |
| 开发板 | `ESP32S3 Dev Module` |
| USB CDC On Boot | **Enabled**（原生 USB 口；关掉会串口全空，代码里有 `#error` 防呆） |
| Upload Speed | **115200**（避开 Windows `usbser.sys` 切速时报错误 31） |
| FQBN | `esp32:esp32:esp32s3:CDCOnBoot=cdc,UploadSpeed=115200` |

一键脚本 `flash_and_run.bat` 用 esptool 把 4MB `merged.bin` 写到 `0x0`，参数要点：`--baud 115200`（全程不切速）+ `--after watchdog-reset`。S3 若用普通 `hard-reset`，芯片会留在 ROM 下载模式，串口打出 `waiting for download`、程序像没跑。脚本会自动从 `%LOCALAPPDATA%\Arduino15\packages\esp32\tools\esptool_py\*` 找 `esptool.exe`，也可用环境变量 `ESPTOOL_PATH` 指定。

> 烧录前关闭 Arduino IDE 串口监视器、在上位机点「断开」释放串口；保持 12V 与三相线接好、轴空转。

## 三个 STAGE

改 `#define STAGE`，重新编译上传，串口 115200 观察。

| STAGE | 做什么 | 通过标准 |
| --- | --- | --- |
| `1` | 只测 AS5600 | 手转一圈，角度在 0~6.28 rad 之间线性变化，速度有正负 |
| `2` | 开环速度，不依赖编码器 | `L3` 后发 `T6.28` 应该正好 1 圈/秒（7 对极下别直接 `T2`，容易失步，先 `T0.5` 起步） |
| `3` | 闭环 FOC（**当前默认**） | 上电 `initFOC()` 对齐，打印 `PP check: OK!`、`Motor ready.` |

校准日志里的 `ERR-MOT: No current sense.` 是**无害提示**：本驱动板没有电流采样，SimpleFOC 自动退到电压模式。若 `PP check: fail - estimated pp: N`，把 `POLE_PAIRS` 改成 N 再编译。

`loop()` 的结构必须保持：

```cpp
void loop() {
  command.run();
  updateStatusLed();
#if STAGE == 1
  // 只打印传感器
#else
  motor.loopFOC();   // STAGE 2 和 STAGE 3 都必须调用！
  motor.move(target);
#endif
}
```

早期「电机不转」的真实原因就是 `loopFOC()` 被写进了 `#if STAGE == 3` 里，开环阶段没有电流环更新。

## 弹簧回中（默认 `M1`）

**不用**库自带的 `MotionControlType::angle` 级联位置环，而是在 `torque/voltage` 模式下自己算 `Uq`：

```
err = soft_deadband(target - shaft_angle, HOME_DB)
vel = lowpass(shaft_velocity, HOME_VTF)
Uq  = HOME_KP * err - HOME_KD * vel
```

死区内 `Uq` 直接清零（**连阻尼项一起关掉**），三相 PWM 回到 50%/50%/50%，电机既没有回正力也没有噪声驱动；一旦偏出死区立刻恢复弹簧。控制量只在单环上，速度环与积分项完全不参与，`motion_downsample`（`HOME_DS`）拉长角度差分间隔进一步降噪。

原因：AS5600 只有 12 bit，速度是角度差分，静止时噪声不小。级联 `angle` 环会把这个噪声经两级增益放大，位置误差在零点反复翻符号，`Uq` 在 ±0.1V 之间高频来回 → 原点「嗡嗡」抖。实测单纯降增益治不了根（K10 摆幅 0.017 rad，K3 更松且漂移更大）。

默认值（可串口热调）：`K8` / `B0.2` / `Z0.012`（≈0.7°）/ 速度低通 0.05s / 下采样 3。

## 速度环零速静音刹车（`M0` + `T0`）

`T0` 时目标速度为零，库里 `PID_velocity` 的积分项（`I=5`）会累积 AS5600 噪声，让轴在停转后小幅来回摆（实测 `S0` 可复现约 4.84° 摆幅）。处理方式：

```
if (mode == velocity && |target| < 0.05 && silentBrake) {
    // 临时切 torque：纯阻尼电刹车，绕开 PID_velocity
    Uq = -brakeKd * soft_deadband(lowpass(shaft_velocity), brakeDb);
} else {
    // 非零目标仍走库的 PID_velocity，转动性能不变
    motor.loopFOC(); motor.move(target);
}
```

`S1` 默认开启；`S0` 关掉可复现原抖动做对比；`G` 调刹车阻尼、`J` 调速度死区。实测 `S1` 后静止角度 0.0000 rad，`T2` 连续转动 2.5s 走 4.73 rad 不受影响。注意：速度环停止**没有位置保持**，轴是自由滑停的；要位置保持用 `M1`。

## 命令与诊断

命令表见 [README](../README.md#串口命令)。`D` 输出一行诊断，字段包括 `mode / home / shaft / err / vel / Kp / Kd / db / zero-speed silent / brakeUq / Uq(out) / Ua,Ub,Uc / AS5600 angle / GPIO4 duty`，上位机正是解析这行做遥测。

`spin_test.ps1` / `spin_test.bat` 会发 `T0 → L3 → T0.5`，连读 `D` 并按 AS5600 角度解卷绕，判断 `SPINNING` / `NOT MOVING`，可当无人值守的转动自检。

## 板载 RGB 状态灯

DevKitC-1 的 GPIO48 是 WS2812 **锁存型**器件，只要 3V3 不断电就会保持最后一帧颜色。Blink 固件停在「亮」时被复位换成旧版固件、而旧固件完全不碰 GPIO48，就会出现「灯常亮但不是死机」的误会。本版接管这颗灯：`setup()` 先清一次，之后 **待机每 1.5s 短闪 80ms（心跳）**、**有目标速度时常亮**。
