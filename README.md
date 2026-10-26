# 天天象棋自动下棋（Windows）

面向「天天象棋」客户端的自动对弈助手：屏幕截取棋盘 → 视觉识别局面 → Pikafish 引擎算招 → 模拟鼠标落子。

**技术栈**：Python · OpenCV / CNN 棋子分类 · Pikafish (UCI) · mss 截屏 · 鼠标 / PostMessage 点击

> 仅供学习计算机视觉与象棋引擎对接。自动代打可能违反游戏用户协议，存在封号风险，请自行判断。

## 功能概览

- **棋盘校准**：框选棋盘区域，保存格子坐标
- **双识别后端**：模板匹配，或 CNN 分类（ONNX Runtime）
- **引擎对接**：下载并驱动 Pikafish，可调思考时间 / 深度
- **自动走子**：支持 click / drag / PostMessage，适配 DPI 缩放
- **热键控制**：F8 暂停、F9 退出

## 架构

```
截屏(mss) → 识别 FEN（template / CNN）→ Pikafish(UCI) → 鼠标落子
```

## 环境

- Windows 10/11
- Python 3.10+
- 天天象棋（窗口完整可见，不要遮挡棋盘）

```powershell
cd d:\A_Project\chess
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 快速开始

先看进度：

```powershell
python main.py status
```

一键引导（会等待你打开天天象棋，再校准 + 采模板）：

```powershell
python main.py setup
```

### 1. 下载 Pikafish

```powershell
python main.py download
```

若 GitHub 很慢，打开 [pikafish.com](https://www.pikafish.com/) 用百度网盘下载「纯引擎」`.7z`，然后：

```powershell
python main.py download --from-file D:\Downloads\Pikafish.xxxx.7z
```

查看进度：

```powershell
python main.py status
```

把 `pikafish.exe` 和 `*.nnue` 放到 `engine/` 亦可（脚本会统一命名）。

### 2. 校准棋盘区域

打开天天象棋，摆出棋盘后执行：

```powershell
python main.py calibrate
```

拖拽框选**棋盘最外圈交叉点**的外接矩形，按 Enter 保存到 `data/calib.json`。

### 3. 采集棋子模板

```powershell
python main.py templates
```

按提示依次点击 14 种棋子中心并 Enter 保存。模板写入 `data/templates/R.png` 等。

### 4. 预览识别

```powershell
python main.py preview
```

确认格子与棋子字母基本正确后，再开自动下棋。

### 5. 自动下棋

```powershell
python main.py play
# 或指定颜色 / 思考时间
python main.py play --side red --movetime 1000
```

| 热键 | 功能 |
|------|------|
| F8 | 暂停 / 继续（需安装 `keyboard`） |
| F9 | 退出（需安装 `keyboard`） |
| Ctrl+C | 退出 |

## 常用命令

```powershell
python main.py analyse --side red --movetime 1500
python main.py templates --force
```

## 配置

见 `config.yaml`：

- `engine.movetime_ms`：思考时间
- `screen.dpi_scale`：点击偏移时按系统缩放调整（125%→1.25）
- `vision.match_threshold`：模板匹配阈值
- `bot.side`：`auto` / `red` / `black`

## 目录

```
xiangqi_bot/
  board.py      # FEN / 坐标
  engine.py     # Pikafish UCI
  bot.py        # 主循环
  vision/       # 截屏、校准、template / CNN 识别
  control/      # 鼠标
  train_cls.py  # 棋子分类训练
config.yaml
main.py
engine/         # pikafish.exe + nnue（需自行下载）
data/
  models/       # piece_cls.onnx 等
  templates/    # 模板匹配用棋子图
```

## 排查

**识别不准**：重新 `templates --force`；保证校准框贴合交叉点；调低 `match_threshold`。

**点击偏了**：改 `screen.dpi_scale`；确认没开游戏内额外缩放；以管理员运行有时能改善坐标。

**引擎报错**：确认 `engine/pikafish.exe` 与 nnue 同目录；先 `python main.py analyse` 单测。

**找不到窗口内容**：用前台可见窗口；全屏/多屏时改 `screen.monitor`。
