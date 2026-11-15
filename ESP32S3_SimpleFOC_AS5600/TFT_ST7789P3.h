#pragma once
/*
 * TFT_ST7789P3.h — 零依赖驱动：1.83" IPS 240x284 / ST7789P3 / 4 线 SPI
 *
 * 为什么不用 TFT_eSPI / Arduino_GFX / Adafruit_ST7789：
 *   - 本机 Arduino 库目录里只有 Simple_FOC，装新库容易踩版本/网络坑；
 *   - 240x284 属于非标准尺寸，很多库的 init(240,284) 偏移对不上，
 *     这里把 CASET/RASET 偏移做成可运行时修改的参数（O 命令）；
 *   - 只用到纯色矩形 / 线 / 5x7 英文字，几百行就能自给自足。
 *
 * 8 针模块常见丝印：GND VCC SCL SDA RES DC CS BLK
 *   SCL=SPI 时钟, SDA=MOSI, RES=复位, DC=命令/数据, CS=片选, BLK=背光
 *   模块没有 MISO：本驱动从不读屏，MISO 只是占一个空闲脚避免和默认脚冲突。
 *
 * 依赖：仅 <Arduino.h> + <SPI.h>（Arduino-ESP32 3.x 自带）。
 */

#include <Arduino.h>
#include <SPI.h>

/* RGB565 换色，另附几个常用常量 */
static inline uint16_t tftRGB565(uint8_t r, uint8_t g, uint8_t b) {
  return ((uint16_t)(r & 0xF8) << 8) | ((uint16_t)(g & 0xFC) << 3) | (uint16_t)(b >> 3);
}
#define TFT_BLACK   0x0000
#define TFT_WHITE   0xFFFF
#define TFT_RED     tftRGB565(255, 60, 60)
#define TFT_GREEN   tftRGB565( 60, 230, 90)
#define TFT_BLUE    tftRGB565( 70, 130, 255)
#define TFT_YELLOW  tftRGB565(255, 215, 60)
#define TFT_CYAN    tftRGB565( 60, 220, 235)
#define TFT_MAGENTA tftRGB565(240, 80, 220)
#define TFT_ORANGE  tftRGB565(255, 150, 40)
#define TFT_DARK    tftRGB565( 20, 24, 32)
#define TFT_GRAY    tftRGB565( 95, 105, 120)
#define TFT_DIM     tftRGB565( 55, 62, 75)

/* 经典 5x7 列式字模，0x20..0x7F，每字节 bit0=最上一行 */
static const uint8_t TFT_FONT5X7[96][5] PROGMEM = {
  {0x00,0x00,0x00,0x00,0x00}, {0x00,0x00,0x5F,0x00,0x00},
  {0x00,0x07,0x00,0x07,0x00}, {0x14,0x7F,0x14,0x7F,0x14},
  {0x24,0x2A,0x7F,0x2A,0x12}, {0x23,0x13,0x08,0x64,0x62},
  {0x36,0x49,0x55,0x22,0x50}, {0x00,0x05,0x03,0x00,0x00},
  {0x00,0x1C,0x22,0x41,0x00}, {0x00,0x41,0x22,0x1C,0x00},
  {0x08,0x2A,0x1C,0x2A,0x08}, {0x08,0x08,0x3E,0x08,0x08},
  {0x00,0x50,0x30,0x00,0x00}, {0x08,0x08,0x08,0x08,0x08},
  {0x00,0x60,0x60,0x00,0x00}, {0x20,0x10,0x08,0x04,0x02},
  {0x3E,0x51,0x49,0x45,0x3E}, {0x00,0x42,0x7F,0x40,0x00},
  {0x42,0x61,0x51,0x49,0x46}, {0x21,0x41,0x45,0x4B,0x31},
  {0x18,0x14,0x12,0x7F,0x10}, {0x27,0x45,0x45,0x45,0x39},
  {0x3C,0x4A,0x49,0x49,0x30}, {0x01,0x71,0x09,0x05,0x03},
  {0x36,0x49,0x49,0x49,0x36}, {0x06,0x49,0x49,0x29,0x1E},
  {0x00,0x36,0x36,0x00,0x00}, {0x00,0x56,0x36,0x00,0x00},
  {0x00,0x08,0x14,0x22,0x41}, {0x14,0x14,0x14,0x14,0x14},
  {0x41,0x22,0x14,0x08,0x00}, {0x02,0x01,0x51,0x09,0x06},
  {0x32,0x49,0x79,0x41,0x3E}, {0x7E,0x11,0x11,0x11,0x7E},
  {0x7F,0x49,0x49,0x49,0x36}, {0x3E,0x41,0x41,0x41,0x22},
  {0x7F,0x41,0x41,0x22,0x1C}, {0x7F,0x49,0x49,0x49,0x41},
  {0x7F,0x09,0x09,0x01,0x01}, {0x3E,0x41,0x41,0x51,0x32},
  {0x7F,0x08,0x08,0x08,0x7F}, {0x00,0x41,0x7F,0x41,0x00},
  {0x20,0x40,0x41,0x3F,0x01}, {0x7F,0x08,0x14,0x22,0x41},
  {0x7F,0x40,0x40,0x40,0x40}, {0x7F,0x02,0x04,0x02,0x7F},
  {0x7F,0x04,0x08,0x10,0x7F}, {0x3E,0x41,0x41,0x41,0x3E},
  {0x7F,0x09,0x09,0x09,0x06}, {0x3E,0x41,0x51,0x21,0x5E},
  {0x7F,0x09,0x19,0x29,0x46}, {0x46,0x49,0x49,0x49,0x31},
  {0x01,0x01,0x7F,0x01,0x01}, {0x3F,0x40,0x40,0x40,0x3F},
  {0x1F,0x20,0x40,0x20,0x1F}, {0x7F,0x20,0x18,0x20,0x7F},
  {0x63,0x14,0x08,0x14,0x63}, {0x03,0x04,0x78,0x04,0x03},
  {0x61,0x51,0x49,0x45,0x43}, {0x00,0x00,0x7F,0x41,0x41},
  {0x02,0x04,0x08,0x10,0x20}, {0x41,0x41,0x7F,0x00,0x00},
  {0x04,0x02,0x01,0x02,0x04}, {0x40,0x40,0x40,0x40,0x40},
  {0x00,0x01,0x02,0x04,0x00}, {0x20,0x54,0x54,0x54,0x78},
  {0x7F,0x48,0x44,0x44,0x38}, {0x38,0x44,0x44,0x44,0x20},
  {0x38,0x44,0x44,0x48,0x7F}, {0x38,0x54,0x54,0x54,0x18},
  {0x08,0x7E,0x09,0x01,0x02}, {0x08,0x14,0x54,0x54,0x3C},
  {0x7F,0x08,0x04,0x04,0x78}, {0x00,0x44,0x7D,0x40,0x00},
  {0x20,0x40,0x44,0x3D,0x00}, {0x00,0x7F,0x10,0x28,0x44},
  {0x00,0x41,0x7F,0x40,0x00}, {0x7C,0x04,0x18,0x04,0x78},
  {0x7C,0x08,0x04,0x04,0x78}, {0x38,0x44,0x44,0x44,0x38},
  {0x7C,0x14,0x14,0x14,0x08}, {0x08,0x14,0x14,0x18,0x7C},
  {0x7C,0x08,0x04,0x04,0x08}, {0x48,0x54,0x54,0x54,0x20},
  {0x04,0x3F,0x44,0x40,0x20}, {0x3C,0x40,0x40,0x20,0x7C},
  {0x1C,0x20,0x40,0x20,0x1C}, {0x3C,0x40,0x30,0x40,0x3C},
  {0x44,0x28,0x10,0x28,0x44}, {0x0C,0x50,0x50,0x50,0x3C},
  {0x44,0x64,0x54,0x4C,0x44}, {0x00,0x08,0x36,0x41,0x00},
  {0x00,0x00,0x7F,0x00,0x00}, {0x00,0x41,0x36,0x08,0x00},
  {0x08,0x08,0x2A,0x1C,0x08}, {0x00,0x00,0x00,0x00,0x00}
};

class ST7789P3 {
 public:
  ST7789P3(int8_t sck, int8_t mosi, int8_t miso,
           int8_t cs, int8_t dc, int8_t rst, int8_t bl)
      : _sck(sck), _mosi(mosi), _miso(miso), _cs(cs), _dc(dc), _rst(rst), _bl(bl),
        _w(240), _h(284), _colOfs(0), _rowOfs(0), _invert(true), _bgr(true),
        _blDuty(210), _ready(false) {}

  bool begin(uint32_t spiHz, uint16_t w, uint16_t h,
             uint8_t colOfs, uint8_t rowOfs, bool invert, bool bgr,
             bool fullInit = false) {
    _w = w; _h = h; _colOfs = colOfs; _rowOfs = rowOfs;
    _invert = invert; _bgr = bgr;

    pinMode(_dc, OUTPUT);
    pinMode(_cs, OUTPUT);
    pinMode(_rst, OUTPUT);
    digitalWrite(_cs, HIGH);
    digitalWrite(_dc, HIGH);
    digitalWrite(_rst, HIGH);
    if (_bl >= 0) {
      ledcAttach(_bl, 5000, 8);        // Arduino-ESP32 3.x API
      ledcWrite(_bl, _blDuty);
    }

    // 用默认 FSPI 引脚（S3: SCK=12 MOSI=11 MISO=13 SS=10），
    // 显式传入可避免不同核心版本默认脚不一致。
    SPI.begin(_sck, _miso, _mosi, _cs);
    _settings = SPISettings(spiHz, MSBFIRST, SPI_MODE0);

    // 硬件复位 + 软件复位
    digitalWrite(_rst, LOW);  delay(60);
    digitalWrite(_rst, HIGH); delay(120);
    txBegin(); writeCmd(0x01); txEnd(); delay(150);   // SWRESET
    txBegin(); writeCmd(0x11); txEnd(); delay(120);   // SLPOUT

    if (fullInit) writeInitTable();                 // 可选：厂商扩展寄存器

    txBegin();                                      // COLMOD: RGB565 / 16bit
    writeCmd(0x3A); writeData(0x55);
    txEnd(); delay(10);

    applyOrientation();                            // MADCTL + INVON/INVOFF
    txBegin(); writeCmd(0x13); txEnd(); delay(10); // NORON
    txBegin(); writeCmd(0x29); txEnd(); delay(120);// DISPON

    _ready = true;
    return true;
  }

  uint16_t width()  const { return _w; }
  uint16_t height() const { return _h; }
  uint8_t  colOfs() const { return _colOfs; }
  uint8_t  rowOfs() const { return _rowOfs; }
  bool     invert() const { return _invert; }
  bool     bgr()    const { return _bgr; }

  /* 这些函数只改内部变量 / 发一条命令，调用方须保证不会和刷屏任务并发。
   * 主固件里统一由 core 0 的 TFT 任务在 renderFrame() 开头执行。 */
  void setOffsets(uint8_t x, uint8_t y) { _colOfs = x; _rowOfs = y; }
  void setInvert(bool on) { _invert = on; applyOrientation(); }
  void setBGR(bool on)    { _bgr = on;    applyOrientation(); }
  void setBacklight(uint8_t duty) {
    _blDuty = duty;
    if (_bl >= 0) ledcWrite(_bl, duty);
  }
  void toggleBacklight() { setBacklight(_blDuty > 0 ? 0 : 210); }

  /* 自愈：长杜邦线 / 20MHz 下偶发毛刺可能把 0x2C(RAMWR) 打歪成
   * 0x28(DISPOFF)，屏幕会一直黑到下次硬复位。显示任务每 2 秒重申
   * 一次 DISPON；面板本来就在显示状态时这条命令是无害的空操作。
   * 只由 core 0 的刷屏任务调用，不与其它 SPI 访问并发。 */
  void assertDisplayOn() {
    txBegin();
    writeCmd(0x29);                 // DISPON
    txEnd();
  }

  void fillScreen(uint16_t c) { fillRect(0, 0, _w, _h, c); }

  void fillRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t c) {
    if (w <= 0 || h <= 0) return;
    if (x < 0) { w += x; x = 0; }
    if (y < 0) { h += y; y = 0; }
    if (x + w > _w) w = _w - x;
    if (y + h > _h) h = _h - y;
    if (w <= 0 || h <= 0) return;
    uint8_t tile[128];                  // 64 像素，避免逐点开窗口
    for (uint8_t i = 0; i < 64; i++) {
      tile[2 * i] = (uint8_t)(c >> 8);
      tile[2 * i + 1] = (uint8_t)c;
    }
    txBegin();
    setWindow(x, y, w, h);
    uint32_t total = (uint32_t)w * h;
    while (total >= 64) { SPI.writeBytes(tile, 128); total -= 64; }
    if (total) SPI.writeBytes(tile, total * 2);
    txEnd();
  }

  void drawRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t c) {
    fillRect(x, y, w, 1, c);
    fillRect(x, y + h - 1, w, 1, c);
    fillRect(x, y, 1, h, c);
    fillRect(x + w - 1, y, 1, h, c);
  }

  void drawPixel(int16_t x, int16_t y, uint16_t c) {
    txBegin(); putPixel(x, y, c); txEnd();
  }

  void drawLine(int16_t x0, int16_t y0, int16_t x1, int16_t y1, uint16_t c) {
    int16_t dx = (x1 > x0) ? (x1 - x0) : (x0 - x1);
    int16_t dy = (y1 > y0) ? (y1 - y0) : (y0 - y1);
    int8_t sx = (x0 < x1) ? 1 : -1;
    int8_t sy = (y0 < y1) ? 1 : -1;
    int16_t err = dx - dy;
    txBegin();
    for (;;) {
      putPixel(x0, y0, c);
      if (x0 == x1 && y0 == y1) break;
      int16_t e2 = 2 * err;
      if (e2 > -dy) { err -= dy; x0 += sx; }
      if (e2 <  dx) { err += dx; y0 += sy; }
    }
    txEnd();
  }

  void drawCircle(int16_t cx, int16_t cy, int16_t r, uint16_t c) {
    int16_t x = r, y = 0, err = 1 - r;
    txBegin();
    while (x >= y) {
      putPixel(cx + x, cy + y, c); putPixel(cx + y, cy + x, c);
      putPixel(cx - x, cy + y, c); putPixel(cx - y, cy + x, c);
      putPixel(cx - x, cy - y, c); putPixel(cx - y, cy - x, c);
      putPixel(cx + x, cy - y, c); putPixel(cx + y, cy - x, c);
      y++;
      if (err < 0) err += 2 * y + 1;
      else { x--; err += 2 * (y - x) + 1; }
    }
    txEnd();
  }

  /* 只支持 ASCII 0x20..0x7F，size 1..4；每个字符一次窗口 + 一次整块写。
   * 底色 bg 会把字符整个 6*size × 8*size 方框刷掉，所以不需要额外擦除。 */
  void text(int16_t x, int16_t y, const char* s,
            uint16_t fg, uint16_t bg, uint8_t size = 2) {
    if (!s || size == 0) return;
    if (size > 4) size = 4;
    const uint8_t cw = 6 * size, ch = 8 * size;
    while (*s) {
      drawChar(x, y, *s++, fg, bg, size, cw, ch);
      x += cw;
    }
  }

  /* 校准用测试图：四角定位块 + 1px 白边（缺边即说明偏移不对）+ 彩条 + 文字 */
  void testPattern(const char* l1, const char* l2) {
    const uint16_t bars[8] = {
      TFT_WHITE, TFT_RED, TFT_GREEN, TFT_BLUE,
      TFT_CYAN, TFT_MAGENTA, TFT_YELLOW, TFT_BLACK
    };
    fillScreen(TFT_BLACK);
    for (uint8_t i = 0; i < 8; i++)
      fillRect(i * (_w / 8), 10, _w / 8, 36, bars[i]);
    drawRect(0, 0, _w, _h, TFT_WHITE);            // 四边白框：一眼看出裁切
    fillRect(2, 2, 10, 10, TFT_RED);
    fillRect(_w - 12, 2, 10, 10, TFT_GREEN);
    fillRect(2, _h - 12, 10, 10, TFT_BLUE);
    fillRect(_w - 12, _h - 12, 10, 10, TFT_YELLOW);
    drawLine(_w / 2, 60, _w / 2, _h - 20, TFT_DIM);
    drawLine(10, _h / 2, _w - 10, _h / 2, TFT_DIM);
    for (uint8_t i = 0; i < 6; i++)
      fillRect(0, 60 + i * 30, (i % 2) ? 8 : 14, 1, TFT_GRAY); // 左侧刻度
    text(8, _h - 46, l1, TFT_WHITE, TFT_BLACK, 2);
    text(8, _h - 26, l2, TFT_CYAN,  TFT_BLACK, 2);
  }

 private:
  int8_t _sck, _mosi, _miso, _cs, _dc, _rst, _bl;
  uint16_t _w, _h;
  uint8_t _colOfs, _rowOfs;
  bool _invert, _bgr;
  uint8_t _blDuty;
  bool _ready;
  SPISettings _settings;
  uint8_t _buf[24 * 32 * 2];                       // 单个字符最大 24x32 像素

  void txBegin() { SPI.beginTransaction(_settings); digitalWrite(_cs, LOW); }
  void txEnd()   { digitalWrite(_cs, HIGH); SPI.endTransaction(); }
  void writeCmd(uint8_t c)  { digitalWrite(_dc, LOW);  SPI.write(c); }
  void writeData(uint8_t d) { digitalWrite(_dc, HIGH); SPI.write(d); }

  void applyOrientation() {
    uint8_t mad = _bgr ? 0x08 : 0x00;              // 0x08 = BGR 顺序
    txBegin();
    writeCmd(0x36); writeData(mad);                // MADCTL：竖屏、不镜像
    writeCmd(_invert ? 0x21 : 0x20);              // IPS 模组多数需要 INVON
    txEnd();
  }

  /* 可选：ST7789 常见厂商扩展寄存器。默认不发，避免覆盖面板出厂参数。 */
  void writeInitTable() {
    static const uint8_t pv[] PROGMEM = {
      0xD0,0x04,0x0D,0x11,0x13,0x2B,0x3F,0x54,0x4C,0x18,0x0D,0x0B,0x1F,0x23 };
    static const uint8_t nv[] PROGMEM = {
      0xD0,0x04,0x0C,0x11,0x13,0x2C,0x3F,0x44,0x51,0x2F,0x1F,0x1F,0x20,0x23 };
    static const uint8_t por[] PROGMEM = { 0x0C, 0x0C, 0x00, 0x33, 0x33 };
    txBegin();
    writeCmd(0xB2); for (uint8_t i = 0; i < sizeof(por); i++) writeData(pgm_read_byte(&por[i]));
    writeCmd(0xB7); writeData(0x35);
    writeCmd(0xBB); writeData(0x19);
    writeCmd(0xC0); writeData(0x2C);
    writeCmd(0xC2); writeData(0x01);
    writeCmd(0xC3); writeData(0x12);
    writeCmd(0xC4); writeData(0x20);
    writeCmd(0xC6); writeData(0x0F);
    writeCmd(0xD0); writeData(0xA4); writeData(0xA1);
    writeCmd(0xE0); for (uint8_t i = 0; i < sizeof(pv); i++) writeData(pgm_read_byte(&pv[i]));
    writeCmd(0xE1); for (uint8_t i = 0; i < sizeof(nv); i++) writeData(pgm_read_byte(&nv[i]));
    txEnd();
    delay(10);
  }

  void setWindow(int16_t x, int16_t y, int16_t w, int16_t h) {
    int16_t x0 = x + _colOfs, x1 = x + w - 1 + _colOfs;
    int16_t y0 = y + _rowOfs, y1 = y + h - 1 + _rowOfs;
    writeCmd(0x2A);
    writeData((uint8_t)(x0 >> 8)); writeData((uint8_t)x0);
    writeData((uint8_t)(x1 >> 8)); writeData((uint8_t)x1);
    writeCmd(0x2B);
    writeData((uint8_t)(y0 >> 8)); writeData((uint8_t)y0);
    writeData((uint8_t)(y1 >> 8)); writeData((uint8_t)y1);
    writeCmd(0x2C);                                // RAMWR
  }

  void putPixel(int16_t x, int16_t y, uint16_t c) {
    if (x < 0 || y < 0 || x >= _w || y >= _h) return;
    setWindow(x, y, 1, 1);
    uint8_t b[2] = { (uint8_t)(c >> 8), (uint8_t)c };
    SPI.writeBytes(b, 2);
  }

  void drawChar(int16_t x, int16_t y, char c, uint16_t fg, uint16_t bg,
                uint8_t size, uint8_t cw, uint8_t ch) {
    if (c < 0x20 || c > 0x7F) c = ' ';
    const uint8_t* g = TFT_FONT5X7[(uint8_t)(c - 0x20)];
    const uint32_t n = (uint32_t)cw * ch;
    for (uint32_t i = 0; i < n; i++) {
      _buf[2 * i]     = (uint8_t)(bg >> 8);
      _buf[2 * i + 1] = (uint8_t)bg;
    }
    for (uint8_t col = 0; col < 5; col++) {
      const uint8_t bits = pgm_read_byte(&g[col]);
      for (uint8_t row = 0; row < 7; row++) {
        if (!(bits & (1 << row))) continue;
        for (uint8_t dy = 0; dy < size; dy++) {
          for (uint8_t dx = 0; dx < size; dx++) {
            const uint16_t px = col * size + dx;
            const uint16_t py = row * size + dy;
            const uint32_t k = ((uint32_t)py * cw + px) * 2;
            _buf[k]     = (uint8_t)(fg >> 8);
            _buf[k + 1] = (uint8_t)fg;
          }
        }
      }
    }
    txBegin();
    setWindow(x, y, cw, ch);
    SPI.writeBytes(_buf, n * 2);
    txEnd();
  }
};
