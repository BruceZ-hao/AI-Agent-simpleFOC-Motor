/*
 * ESP32S3_TFT_HWTEST.ino — 1.83" ST7789P3 硬件隔离诊断（本地临时工程，不入库）
 *
 * 目的：把「屏幕亮一会就灭」拆成两类，一次分清：
 *   A. 屏幕供电 / 背光硬件问题 -> 心跳继续但屏幕变黑
 *   B. 软件刷新 / SPI 速率 / 厂商初始化表问题 -> 静态画面能一直保持
 *
 * 与正式固件的差别（每个都是刻意剥掉的变量）：
 *   - 不加载 SimpleFOC / Commander / Wire，电机完全不碰，不需要 12V
 *   - BLK(GPIO16) 用普通 GPIO 常高驱动，完全不用 LEDC / PWM
 *   - SPI 降到 1MHz，只发最简初始化序列（不发厂商扩展寄存器表）
 *   - 开机只画一帧静态图案，之后永远不再碰 SPI 总线
 *   - 没有 core 0 刷屏任务、没有动画、没有每秒重绘
 *   - 每 2 秒打印一次心跳，用来判断 ESP32 是否仍在运行
 *
 * 串口 115200 命令：
 *   R  重新初始化屏幕并重画（若屏控芯片掉电，这条应能救回来）
 *   B  翻转 BLK 高低（判断背光是有源高还是有源低）
 *   C  换下一种纯色（判断 SPI 是否还在工作）
 *   H  立即打印一次心跳
 */

#include <Arduino.h>
#include <SPI.h>
#include "TFT_ST7789P3.h"

#define TFT_SCK   12
#define TFT_MOSI  11
#define TFT_MISO  13
#define TFT_CS    10
#define TFT_DC    14
#define TFT_RST   15
#define TFT_BL    16
#define TFT_HZ    1000000UL

// 最后一个参数 -1 = 驱动不要接管背光（不 ledcAttach），由本文件用普通 GPIO 拉高
static ST7789P3 tft(TFT_SCK, TFT_MOSI, TFT_MISO,
                    TFT_CS, TFT_DC, TFT_RST, -1);

static const uint16_t COLORS[] = {
  TFT_WHITE, TFT_RED, TFT_GREEN, TFT_BLUE, TFT_CYAN, TFT_YELLOW
};
static const char* COLOR_NAMES[] = {
  "WHITE", "RED", "GREEN", "BLUE", "CYAN", "YELLOW"
};
static uint8_t  colorIdx = 0;
static bool     blHigh   = true;
static uint32_t lastHb   = 0;

static void paint() {
  tft.fillScreen(COLORS[colorIdx]);
  // 中间放一块高对比图案：能看见橙块 = 真的有图像，不是只有背光
  tft.fillRect(50,  90, 140, 104, TFT_BLACK);
  tft.fillRect(62, 102, 116,  80, TFT_ORANGE);
  tft.fillRect(90, 220,  60,  24, TFT_BLUE);
}

static void heartbeat() {
  Serial.print(F("HB t="));
  Serial.print(millis());
  Serial.print(F("ms  bl="));
  Serial.print(blHigh ? F("HIGH") : F("LOW"));
  Serial.print(F("  pinRead="));
  Serial.print(digitalRead(TFT_BL));
  Serial.print(F("  color="));
  Serial.println(COLOR_NAMES[colorIdx]);
}

void setup() {
  Serial.begin(115200);
  delay(1200);

  pinMode(TFT_BL, OUTPUT);
  digitalWrite(TFT_BL, HIGH);          // 背光常亮，无 PWM

  tft.begin(TFT_HZ, 240, 284, 0, 0, true, true, false);
  paint();

  Serial.println(F("========== TFT HW ISOLATION TEST =========="));
  Serial.println(F("BLK=GPIO16 plain HIGH (NO ledc/PWM), SPI=1MHz, simple init"));
  Serial.println(F("ONE static frame then NO SPI traffic at all"));
  Serial.println(F("Cmds: R=re-init+redraw  B=toggle BLK  C=next color  H=heartbeat"));
  Serial.println(F("If screen dies while HB keeps printing -> VCC/backlight HW issue"));
  Serial.println(F("==========================================="));
  heartbeat();
  lastHb = millis();
}

void loop() {
  // 每轮重申背光电平，防止任何外设把 GPIO16 改回去
  digitalWrite(TFT_BL, blHigh ? HIGH : LOW);

  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == 'R' || c == 'r') {
      tft.begin(TFT_HZ, 240, 284, 0, 0, true, true, false);
      paint();
      Serial.println(F("CMD R: display re-initialized + redrawn"));
    } else if (c == 'B' || c == 'b') {
      blHigh = !blHigh;
      digitalWrite(TFT_BL, blHigh ? HIGH : LOW);
      Serial.print(F("CMD B: BLK now "));
      Serial.println(blHigh ? F("HIGH") : F("LOW"));
    } else if (c == 'C' || c == 'c') {
      colorIdx = (colorIdx + 1) % 6;
      paint();
      Serial.print(F("CMD C: color = "));
      Serial.println(COLOR_NAMES[colorIdx]);
    } else if (c == 'H' || c == 'h') {
      heartbeat();
    }
  }

  if (millis() - lastHb >= 2000UL) {
    lastHb = millis();
    heartbeat();
  }
  delay(20);
}
