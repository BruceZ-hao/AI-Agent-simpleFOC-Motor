#pragma once
/*
 * TFT_UI.h — 240x284 竖屏仪表盘
 *
 * 设计要点：SPI 刷屏是阻塞操作，绝不能放进 loop()（会打断 loopFOC 的
 * 高频电流环）。因此所有绘制只发生在 core 0 的独立 FreeRTOS 任务里，
 * loop() 只把几个 float 写进 DisplayState 快照（32 位对齐读写是原子的）。
 * 串口命令也只置标志位，由该任务在帧首统一应用，避免双核同时抢 SPI。
 */

#include <stdio.h>
#include <math.h>
#include "TFT_ST7789P3.h"

/* loop() 写、显示任务读的快照。全部是 32 位以内的标量，无需加锁。 */
struct DisplayState {
  volatile float angle;        // 相对 home 的机械角 [rad]
  volatile float velocity;     // [rad/s]
  volatile float target;       // 回中模式=相对原点[rad]，速度模式=[rad/s]
  volatile float uq;           // 当前输出电压 [V]
  volatile float kp, kd, db;   // 弹簧刚度 / 阻尼 / 死区
  volatile float vlimit;       // 电压限幅 [V]，力矩条满量程
  volatile uint8_t mode;       // 0=速度环 1=弹簧回中 2=传感器自检
  volatile bool sensorOk, silent, enabled;
  volatile uint16_t fps;       // 由显示任务回写
};

enum : uint8_t {
  TFT_REQ_TEST      = 1 << 0,
  TFT_REQ_INVERT    = 1 << 1,
  TFT_REQ_BGR       = 1 << 2,
  TFT_REQ_OFFSET    = 1 << 3,
  TFT_REQ_BACKLIGHT = 1 << 4
};

/* 不用 printf 的 %f（有些 newlib-nano 会裁掉浮点格式化），自己拼整数 */
static void tftFmt(char* out, float v, uint8_t dec, bool plus) {
  bool neg = (v < 0.0f);
  if (neg) v = -v;
  long scale = 1;
  for (uint8_t i = 0; i < dec; i++) scale *= 10;
  long n   = (long)(v * scale + 0.5f);
  long ip  = n / scale;
  long fp  = n % scale;
  char* p  = out;
  if (neg)       *p++ = '-';
  else if (plus) *p++ = '+';
  char rev[12]; uint8_t m = 0;
  if (ip == 0)   rev[m++] = '0';
  else { long t = ip; while (t > 0) { rev[m++] = (char)('0' + t % 10); t /= 10; } }
  while (m > 0) *p++ = rev[--m];
  if (dec) {
    *p++ = '.';
    char d[8];
    for (int i = dec - 1; i >= 0; i--) { d[i] = (char)('0' + fp % 10); fp /= 10; }
    for (uint8_t i = 0; i < dec; i++) *p++ = d[i];
  }
  *p = '\0';
}

class TFTDashboard {
 public:
  TFTDashboard(DisplayState* s, int8_t sck, int8_t mosi, int8_t miso,
               int8_t cs, int8_t dc, int8_t rst, int8_t bl)
      : _tft(sck, mosi, miso, cs, dc, rst, bl), _s(s), _w(240), _h(284),
        _req(0), _reqX(0), _reqY(0), _test(false), _needRebuild(true),
        _needleValid(false), _oldX(0), _oldY(0),
        _testX(10), _testDir(1), _frames(0), _fpsT0(0) {}

  bool begin(uint32_t hz, uint16_t w, uint16_t h,
             uint8_t ox, uint8_t oy, bool inv, bool bgr) {
    _w = w; _h = h;
    return _tft.begin(hz, w, h, ox, oy, inv, bgr, false);
  }

  /* 只在 setup()（core 1、尚无显示任务）调用 */
  void showSplash() {
    _tft.fillScreen(TFT_BLACK);
    _tft.drawRect(6, 6, _w - 12, _h - 12, TFT_DIM);
    _tft.text(24, 108, "SIMPLEFOC", TFT_CYAN,  TFT_BLACK, 3);
    _tft.text(48, 150, "1.83 TFT",  TFT_WHITE, TFT_BLACK, 2);
    _tft.text(40, 182, "240 x 284", TFT_GRAY,  TFT_BLACK, 2);
  }

  /* core 1 只置位，真正生效在 core 0 的帧首，保证 SPI 单核独占 */
  void request(uint8_t bit)            { _req |= bit; }
  void requestOffsets(uint8_t x, uint8_t y) { _reqX = x; _reqY = y; _req |= TFT_REQ_OFFSET; }

  /* 由 core 0 的 tftTask 每帧调用一次 */
  void renderFrame() {
    const uint8_t r = _req;
    _req = 0;
    bool cfg = false;
    if (r & TFT_REQ_BACKLIGHT) _tft.toggleBacklight();
    if (r & TFT_REQ_BGR)    { _tft.setBGR(!_tft.bgr());       cfg = true; }
    if (r & TFT_REQ_INVERT) { _tft.setInvert(!_tft.invert()); cfg = true; }
    if (r & TFT_REQ_OFFSET) { _tft.setOffsets(_reqX, _reqY);  cfg = true; }
    if (r & TFT_REQ_TEST)   { _test = !_test;                 cfg = true; }
    if (cfg || _needRebuild) {
      if (_test) drawTest(); else drawStatic();
      _needRebuild = false;
      _needleValid = false;
    }
    if (_test) testAnimation(); else drawDynamic();
    countFps();
  }

 private:
  ST7789P3 _tft;
  DisplayState* _s;
  uint16_t _w, _h;
  volatile uint8_t _req, _reqX, _reqY;
  bool _test, _needRebuild, _needleValid;
  int16_t _oldX, _oldY, _testX, _testDir;
  uint32_t _frames, _fpsT0;

  static const int16_t CX = 120, CY = 112, RING = 42, NEEDLE = 31;
  static const int16_t BX = 8, BY = 170, BW = 224, BH = 12;
  static const int16_t ROW_Y = 186, ROW_H = 16;

  void countFps() {
    _frames++;
    const uint32_t now = millis();
    if (now - _fpsT0 >= 1000UL) {
      _s->fps = (uint16_t)(_frames * 1000UL / (now - _fpsT0));
      _frames = 0;
      _fpsT0  = now;
    }
  }

  void drawTest() {
    char l1[28], l2[28];
    snprintf(l1, sizeof(l1), "240X284 ST7789P3");
    snprintf(l2, sizeof(l2), "OFS %u,%u %s %s",
             (unsigned)_tft.colOfs(), (unsigned)_tft.rowOfs(),
             _tft.invert() ? "INV" : "NOINV", _tft.bgr() ? "BGR" : "RGB");
    _tft.testPattern(l1, l2);
    _testX = 10; _testDir = 1;
  }

  void testAnimation() {
    _tft.fillRect(_testX, 100, 20, 16, TFT_BLACK);
    _testX += 4 * _testDir;
    if (_testX > _w - 30) { _testX = _w - 30; _testDir = -1; }
    if (_testX < 10)      { _testX = 10;      _testDir =  1; }
    _tft.fillRect(_testX, 100, 20, 16, TFT_ORANGE);
  }

  void drawStatic() {
    static const char* labels[6] = { "MODE", "TGT", "VEL", "UQ", "K/Z", "SENS" };
    _tft.fillScreen(TFT_BLACK);
    _tft.text(6, 4, "SIMPLEFOC", TFT_CYAN, TFT_BLACK, 2);
    _tft.fillRect(0, 25, _w, 2, TFT_DIM);
    _tft.text(196, 58, "DEG", TFT_GRAY, TFT_BLACK, 1);

    _tft.drawCircle(CX, CY, RING, TFT_DIM);
    _tft.drawCircle(CX, CY, RING - 1, TFT_DIM);
    _tft.drawLine(CX, CY - RING, CX, CY - RING + 7, TFT_ORANGE);   // 原点标记
    _tft.drawLine(CX + RING - 6, CY, CX + RING, CY, TFT_GRAY);
    _tft.drawLine(CX - RING + 6, CY, CX - RING, CY, TFT_GRAY);
    _tft.drawLine(CX, CY + RING - 6, CX, CY + RING, TFT_GRAY);
    _tft.text(CX - 6, CY + RING + 4, "0", TFT_GRAY, TFT_BLACK, 1);

    _tft.text(8, 158, "Uq", TFT_GRAY, TFT_BLACK, 1);
    _tft.drawRect(BX - 2, BY - 2, BW + 4, BH + 4, TFT_DIM);

    for (uint8_t i = 0; i < 6; i++) {
      const int16_t y = ROW_Y + i * ROW_H;
      _tft.fillRect(0, y, _w, 1, TFT_DARK);
      _tft.text(6, y, labels[i], TFT_DIM, TFT_BLACK, 2);
    }
    _tft.fillRect(0, _h - 1, _w, 1, TFT_DIM);
  }

  void rowValue(uint8_t i, const char* s, uint16_t color) {
    const int16_t y = ROW_Y + i * ROW_H;
    _tft.fillRect(70, y, 170, ROW_H, TFT_BLACK);
    _tft.text(72, y, s, color, TFT_BLACK, 2);
  }

  void drawDynamic() {
    const char* tag = (_s->mode == 1) ? "HAPTIC"
                    : (_s->mode == 2) ? "SENSOR"
                    : (_s->mode == 0) ? "VELOC" : "TEST";

    /* 顶部模式标签 */
    _tft.fillRect(130, 2, 108, 20, TFT_BLACK);
    _tft.text(132, 4, tag, TFT_YELLOW, TFT_BLACK, 2);

    /* 大号角度（相对原点，单位度） */
    char a[20], num[16];
    tftFmt(num, _s->angle * 57.29578f, 1, true);
    snprintf(a, sizeof(a), "%s deg", num);
    _tft.fillRect(4, 30, 232, 28, TFT_BLACK);
    _tft.text(6, 32, a, TFT_WHITE, TFT_BLACK, 3);

    /* 表盘指针：先用底色擦上一帧，再画新指针 */
    if (_needleValid) _tft.drawLine(CX, CY, _oldX, _oldY, TFT_BLACK);
    const float th = fmodf(_s->angle, 6.2831853f) - 1.5707963f;
    const int16_t nx = CX + (int16_t)(cosf(th) * NEEDLE);
    const int16_t ny = CY + (int16_t)(sinf(th) * NEEDLE);
    _tft.drawLine(CX, CY, nx, ny, TFT_CYAN);
    _tft.fillRect(CX - 2, CY - 2, 5, 5, TFT_WHITE);
    _oldX = nx; _oldY = ny; _needleValid = true;

    /* 力矩条：中点为 0，左右分别表示负/正 Uq */
    _tft.fillRect(BX, BY, BW, BH, TFT_DARK);
    _tft.fillRect(BX + BW / 2, BY, 1, BH, TFT_GRAY);
    const float vmax = (_s->vlimit > 0.1f) ? _s->vlimit : 3.0f;
    int16_t len = (int16_t)(fabsf(_s->uq) / vmax * (BW / 2 - 2));
    if (len > BW / 2 - 2) len = BW / 2 - 2;
    if (len > 0) {
      const uint16_t col = (_s->uq >= 0.0f) ? TFT_ORANGE : TFT_MAGENTA;
      const int16_t x = (_s->uq >= 0.0f) ? (BX + BW / 2 + 1)
                                         : (BX + BW / 2 - 1 - len);
      _tft.fillRect(x, BY + 2, len, BH - 4, col);
    }

    /* 6 行状态 */
    char f1[16], f2[16], f3[16], v[28];
    snprintf(v, sizeof(v), "%s %s", tag, _s->silent ? "S1" : "S0");
    rowValue(0, v, TFT_YELLOW);

    tftFmt(f1, _s->target, 2, true);
    snprintf(v, sizeof(v), "%s %s", f1, (_s->mode == 1) ? "rad" : "r/s");
    rowValue(1, v, TFT_WHITE);

    tftFmt(f1, _s->velocity, 2, true);
    snprintf(v, sizeof(v), "%s r/s", f1);
    rowValue(2, v, TFT_WHITE);

    tftFmt(f1, _s->uq, 2, true);
    snprintf(v, sizeof(v), "%s V", f1);
    rowValue(3, v, TFT_CYAN);

    tftFmt(f2, _s->kp, 1, false);
    tftFmt(f3, _s->db, 3, false);
    snprintf(v, sizeof(v), "K%s Z%s", f2, f3);
    rowValue(4, v, TFT_GRAY);

    snprintf(v, sizeof(v), "%s %s %uFPS",
             _s->sensorOk ? "OK" : "--", _s->silent ? "S1" : "S0", (unsigned)_s->fps);
    rowValue(5, v, _s->enabled ? TFT_GREEN : TFT_RED);
  }
};
