# 03 · 本地 Web 上位机

`HapticConsole/` 是一个**零第三方依赖**的本地上位机：Python 标准库起 HTTP + SSE 服务，Windows 原生 API（`CreateFileW` / `SetCommState` / `ReadFile`，用 `ctypes` 调用）直接读写串口，**不需要 `pyserial`**。这样做是因为本机 pip 装 `pyserial` 失败过，顺带把依赖彻底去掉。

## 启动

```
双击 HapticConsole/start.bat        # 自动打开 http://127.0.0.1:8765
python HapticConsole/server.py --port 8766      # 换端口
python HapticConsole/server.py --nobrowser      # 不自动开浏览器
python HapticConsole/server.py --selftest --com COM6   # 不开服务，自检串口与 D 命令
```

`start.bat` 会优先找 `python`，找不到就找 `py -3`；端口 8765 被占用时自动往后找（最多试 10 个）。服务只监听本机，页面、遥测都在 `127.0.0.1`，不联网。

## 界面功能

- **实时状态**：连接端口、当前模式、target / shaft / err / vel / Uq、zero-speed silent 开关
- **角度 / Uq 曲线**：滚动时序列，用来直观对比「原点抖动」调参前后的差异
- **圆盘指针**：把 AS5600 角度画成旋钮指针
- **参数滑块**：`K` 刚度、`B` 阻尼、`Z` 死区，拖动即发串口命令
- **模拟手扭滑块**：给 `M1` 模式设目标偏置，观察回弹
- **快捷按钮**：`M0` / `M1` / `H` / `L` / `D` / `T`
- **串口日志**：所有下发命令与回显，便于对照 Arduino 串口监视器
- 主题切换（浅色 / 深色）

## 数据流

```
浏览器 ──POST /api/send──> server.py ──"D\n" / "K8\n"──> COMx @115200
浏览器 <──SSE /api/events── server.py <──8Hz 轮询 D 的解析结果── 固件
```

固件侧只需能响应 `D`（一行诊断输出）；`server.py` 里的 `parse_diag()` 把 `mode / home / shaft / err / vel / Kp / Kd / db / Uq / Ua,Ub,Uc / angle` 等字段解析成 JSON 推给前端。

## HTTP 接口

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/` | 返回 `index.html` |
| GET | `/api/ports` | 枚举本机串口（从注册表读 COM 口，含友好名称） |
| GET | `/api/status` | 当前连接状态、端口、模式与最近一次遥测 |
| GET | `/api/events` | SSE 长连接，推送遥测帧与串口日志 |
| POST | `/api/connect` | 打开指定串口，115200 8N1 |
| POST | `/api/disconnect` | 关闭串口，**烧录前必点** |
| POST | `/api/send` | 下发一条串口命令（如 `K8`、`T0`、`M1`） |
| POST | `/api/config` | 更新前端配置项 |

## 串口占用是最常见的故障

Windows 上 COM 口是独占的。Arduino IDE 的 `serial-monitor.exe` / `serial-discovery.exe`、上位机服务、`spin_test.ps1` 三者**只能有一个**拿着串口。

- 上位机连不上 → 关掉 IDE 串口监视器，确认没有旧的 `python server.py` 进程残留。
- 烧录报 `Could not open COMx, port is busy` 或 `PermissionError` → 先在上位机点「**断开**」，再关 IDE 监视器，然后双击 `flash_and_run.bat`。
- 不要靠 `taskkill /F /IM arduino-cli.exe` 抢端口：这会连 IDE 的编译守护进程一起杀掉，导致 IDE 报 `ECONNREFUSED 127.0.0.1:53078`。只处理 `serial-discovery.exe` / `serial-monitor.exe` 是安全的（烧录脚本已内置）。

`--selftest` 会打开指定 COM、发 `D`、打印解析出的全部字段，是排查「上位机没数据」最快的手段。
