/*
 * ESP32-S3-DevKitC-1（板上焊 ESP32-S3-WROOM-1 模组）第一份验证程序：点亮 LED
 *
 * 硬件说明：
 *   板载 WS2812 RGB 在 GPIO48。默认板型的 LED_BUILTIN / RGB_BUILTIN 已指向它，
 *   digitalWrite(LED_BUILTIN, HIGH) 会被 arduino-esp32 内部自动转成
 *   rgbLedWrite() 输出白光（亮度 RGB_BRIGHTNESS = 64）——普通 Blink 写法即可点亮，
 *   不需要额外装 NeoPixel 库，也不需要自己写 WS2812 时序。
 *
 *   若你手上是裸模组 / 没有板载灯的最小系统板：把 ENABLE_EXT_LED 改成 1，
 *   在 EXT_LED_PIN（默认 GPIO4）串 220~330Ω 电阻接一颗普通 LED 到 GND。
 *
 *   已知坑：个别 DevKitC-1 批次 GPIO48 驱动电压偏低，板载 RGB 不亮或很暗。
 *   这时用外接 LED 那一路验证（ENABLE_EXT_LED = 1），或换 GPIO 接外置 WS2812。
 *
 * WROOM-1 引脚禁忌（别用这些脚接 LED）：
 *   GPIO26~32        内部 Flash / PSRAM 占用，绝对不能用
 *   GPIO33~37        部分八线 PSRAM 版本占用
 *   GPIO19 / 20      原生 USB D- / D+
 *   GPIO0/3/45/46    strapping 启动脚，上电电平会影响启动
 *   GPIO43 / 44      默认 UART0 TX / RX
 *   推荐空闲脚：4~18、21、47、48（本例用 4）
 *
 * Arduino IDE 板型设置（工具菜单）：
 *   开发板：ESP32S3 Dev Module
 *   用板上「原生 USB」口看串口 -> USB CDC On Boot = Enabled
 *   用「USB-TTL / UART」口看串口 -> USB CDC On Boot = Disabled（Serial 走 UART0）
 *   看不到串口日志不影响 LED 闪烁，别据此判断程序没跑。
 */
#include <Arduino.h>

/* ==================== 只改这一区 ==================== */
#define BLINK_MS       500   // 亮 / 灭各 500 ms
#define EXT_LED_PIN    4     // 外接 LED 的 GPIO，须串 220~330Ω 限流电阻
#define ENABLE_EXT_LED 0     // DevKitC-1 有板载 RGB，默认 0；裸模组改 1 并接 LED
/* =================================================== */

#ifndef LED_BUILTIN
  #define LED_BUILTIN 48    // 兜底：极少数板型未定义时直接指到 GPIO48
#endif

static uint32_t blinkCount = 0;

void setup() {
  Serial.begin(115200);
  delay(300);

  pinMode(LED_BUILTIN, OUTPUT);       // 若核心定义了 RGB_BUILTIN，内部会自动重映射到 GPIO48
#if ENABLE_EXT_LED
  pinMode(EXT_LED_PIN, OUTPUT);
#endif

  Serial.println(F("=== ESP32-S3-WROOM-1 : LED blink ==="));
  Serial.print(F("Chip  : ")); Serial.println(ESP.getChipModel());
  Serial.print(F("CPU   : ")); Serial.print(ESP.getCpuFreqMHz()); Serial.println(F(" MHz"));
  Serial.print(F("Flash : ")); Serial.print(ESP.getFlashChipSize() / 1024 / 1024); Serial.println(F(" MB"));

#if defined(RGB_BUILTIN)
  Serial.println(F("Onboard LED : WS2812 RGB on GPIO48 (digitalWrite -> rgbLedWrite)"));
#else
  Serial.print(F("Onboard LED GPIO : ")); Serial.println((int)LED_BUILTIN);
#endif

#if ENABLE_EXT_LED
  Serial.print(F("External LED : GPIO")); Serial.print(EXT_LED_PIN);
  Serial.println(F(" (220-330 ohm in series to GND)"));
#endif
  Serial.println(F("Blinking every 500 ms. If no output here, check USB CDC setting."));
  Serial.println(F("======================================="));
}

void loop() {
  digitalWrite(LED_BUILTIN, HIGH);    // 板载：RGB 白光 / 普通 LED 亮
#if ENABLE_EXT_LED
  digitalWrite(EXT_LED_PIN, HIGH);    // 外接：亮
#endif
  delay(BLINK_MS);

  digitalWrite(LED_BUILTIN, LOW);
#if ENABLE_EXT_LED
  digitalWrite(EXT_LED_PIN, LOW);
#endif
  delay(BLINK_MS);

  if (++blinkCount % 10 == 0) {       // 每 10 次报一次活，确认程序没跑飞
    Serial.print(F("alive, blinks = ")); Serial.println(blinkCount);
  }
}
