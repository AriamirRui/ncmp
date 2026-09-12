# ncmp

> 本项目基于 [ACAne0320/ncmp](https://github.com/ACAne0320/ncmp) 开发，在保留原版全部功能的基础上，采用 **Tauri + Rust 外壳 + Web 前端 + Python sidecar** 架构重写了桌面界面，并支持 Windows EXE 一键打包、任务实时进度显示与手动终止运行等功能。

ncmp(NetEase Cloud Music Partner/网易云音乐合伙人)

基于 Python 的网易云音乐-音乐合伙人任务脚本，支持本地运行和 GitHub Actions 自动执行。

## 功能特点

- 全自动完成音乐合伙人日常任务
  - 完成每日5个基础任务
  - 完成每日15个额外评分任务
- 便捷的部署方式
  - 支持本地手动运行（命令行）
  - 支持桌面应用：Tauri 外壳 + Web 界面（深色主题、实时日志、任务进度、可终止）
  - 支持浏览器模式（`python -m src.server` 直接使用同一套界面）
  - 支持一键打包为 Windows EXE（双击即用，无需安装 Python）
  - 支持 GitHub Actions 自动执行
- 完善的通知机制
  - Cookie 失效自动发送邮件提醒
- 一次配置持续使用
  - 支持自动登录账号并刷新Cookie，基于[NeteaseCloudMusicApi](https://github.com/Binaryify/NeteaseCloudMusicApi)

## 界面架构

```
┌──────────────────────────────────────────────┐
│  Tauri 外壳（Rust）                           │
│  · 窗口 / WebView2 容器                       │
│  · 启动并守护 Python sidecar，退出时回收进程     │
│  · 分配随机端口 + 访问令牌，交给前端             │
├──────────────────────────────────────────────┤
│  Web 前端（web/ 原生 HTML/CSS/JS，无需构建）    │
│  · 运行控制 / 配置 / 运行历史 / 关于            │
│  · SSE 实时日志与任务进度，一键终止任务          │
├──────────────────────────────────────────────┤
│  Python sidecar（ncmp-server，仅监听本机）      │
│  · HTTP API + SSE，复用原有评分任务逻辑          │
│  · 配置文件与运行日志读写（config/、data/）      │
└──────────────────────────────────────────────┘
```

- sidecar 只监听 `127.0.0.1`，并使用启动时随机生成的令牌鉴权（`X-NCMP-Token`）
- 配置、日志仍保存在程序目录下的 `config/`、`data/`，与原版保持一致

### 目录结构

```
ncmp/
├── main.py                  # 命令行入口（python main.py）
├── gui.py                   # Tkinter 界面入口（python gui.py，旧版界面）
├── sidecar_main.py          # Python 后端打包入口（PyInstaller）
├── src/
│   ├── core/                # 评分任务核心逻辑（与原版一致）
│   │   ├── pipeline.py      # 通用执行流程（命令行 / 界面 / 后端共用）
│   │   ├── bot.py           # 主流程编排
│   │   ├── signer.py        # 网易云加密与评分请求
│   │   ├── exceptions.py    # 终止任务异常与可中断等待
│   │   └── tasks/           # 每日任务 / 额外任务 / Cookie 刷新
│   ├── server/              # Web 后端（HTTP API + SSE）
│   ├── store/               # 运行历史读写
│   ├── ui/                  # Tkinter 旧版界面 + 运行器
│   ├── utils/               # 配置、日志、通知、路径
│   └── validators/          # Cookie 校验
├── web/                     # Web 前端（原生 HTML/CSS/JS，无构建步骤）
├── src-tauri/               # Tauri 外壳（Rust）
│   ├── src/main.rs          # 窗口 + sidecar 托管
│   ├── tauri.conf.json      # 应用配置
│   └── binaries/            # 放入 ncmp-server-<triple>.exe（由脚本生成）
├── assets/make_icon.py      # 生成 ico/png 图标（纯标准库）
├── build_sidecar.bat        # 构建 Python 后端
├── build_tauri.bat          # 构建 Tauri 桌面应用
├── build_exe.bat            # 构建 Tkinter 版单文件 EXE
├── ncmp-server.spec         # 后端 PyInstaller 配置
└── ncmp.spec                # Tkinter 版 PyInstaller 配置
```

### 构建桌面应用的前置条件

| 组件 | 用途 | 安装方式 |
| --- | --- | --- |
| Python 3.9+ | 后端与打包 | [python.org](https://www.python.org/downloads/) |
| Rust（stable-msvc） | 编译 Tauri 外壳 | [rustup.rs](https://rustup.rs/) |
| Node.js（可选） | 提供 Tauri CLI | [nodejs.org](https://nodejs.org/)（或用 `cargo install tauri-cli`） |
| Microsoft Edge WebView2 | 渲染界面 | Windows 10/11 通常已内置 |

## 使用前准备

如果你从来没有接触过GitHub Actions以及Cookies相关的网络知识，请戳[ncmp 使用指北](https://blog.nyaashino.com/post/ncmp_quickstart)。

### 获取网易云音乐 Cookie

1. 登录[网易云音乐网页版](https://music.163.com/)
2. 打开浏览器开发者工具（F12）
3. 切换到 Network（网络）选项卡
4. 刷新页面，在请求中找到 cookie 中的 `MUSIC_U` 和 `__csrf` 值

### Cookie自动刷新配置（可选）

为了让Cookie自动刷新功能正常工作，您需要创建一个具有特定权限的GitHub Personal Access Token (PAT)。以下是详细步骤：

#### 1. 创建GitHub Personal Access Token

1. 登录您的 GitHub 账号
2. 访问 [Token设置页面](https://github.com/settings/tokens)
3. 点击"Generate new token" > "Fine-grained tokens" or "Generate new token (classic)"
4. 在"Note"字段给您的Token起一个描述性名称，如"NCMP Cookie Refresh"
5. 设置 Token 有效期

#### 2. 选择正确的权限范围

您只需要为 Token 配置最小必要的权限。
如果使用 Fine-grained tokens (更精细的权限控制):

1. 选择只对您的ncmp仓库有效
2. 将 "secrets" 设为 "Read and write"

如果使用 Generate new token (classic):

**如果是公开仓库**，选择以下权限：

- `repo` > `public_repo` (仅访问公开仓库)
- `codespace` > `codespace:secrets`

**如果是私有仓库**，选择以下权限：

- `repo` (完整的仓库访问，包括私有仓库)
- `codespace` > `codespace:secrets`

#### 3. 保存Token

1. 滚动到页面底部，点击"Generate token"
2. **立即复制生成的token**（离开页面后将无法再次查看）
3. 将复制的token添加到您fork的ncmp仓库的GitHub Secrets中，命名为`GH_TOKEN`

#### 4. 添加额外的自动刷新Cookie所需Secrets

在仓库的Secrets中添加以下内容：

- `NETEASE_PHONE`: 您的网易云音乐账号手机号
- 网易云音乐账号密码（2选1，强烈建议使用MD5加密密码）
  - `NETEASE_PASSWORD`: 明文密码
  - `NETEASE_MD5_PASSWORD`: MD5加密密码
- `GH_TOKEN`: 刚才创建的GitHub Token

#### 5. 启用自动刷新工作流

- 确保仓库中`.github/workflows/refresh_cookie.yml`工作流已启用
- 您可以在Actions页面手动运行"Cookie Refresh"工作流测试配置是否正确

### 配置邮箱通知（可选）

支持所有提供 SMTP 服务的邮箱，以下是常见邮箱的配置示例：

1. Gmail (推荐)

   ```json
   {
     "notify_email": "your.email@gmail.com",
     "email_password": "YOUR_APP_SPECIFIC_PASSWORD",
     "smtp_server": "smtp.gmail.com",
     "smtp_port": 465
   }
   ```

   注意：Gmail 需要开启两步验证并使用应用专用密码

2. QQ邮箱

   ```json
   {
     "notify_email": "your_qq@qq.com",
     "email_password": "YOUR_AUTH_CODE",
     "smtp_server": "smtp.qq.com",
     "smtp_port": 465
   }
   ```

   注意：需要在QQ邮箱设置中开启SMTP服务并获取授权码

## 使用方法

### 方式一：本地手动执行

1. 克隆仓库到本地：

   ```bash
   git clone https://github.com/AriamirRui/ncmp.git
   cd ncmp
   ```

2. 安装依赖：

   ```bash
   pip install -r requirements.txt
   ```

3. 复制并编辑配置文件：

   ```bash
   cp config/setting.example.json config/setting.json
   ```

4. 编辑 `config/setting.json`，填写以下配置：

   ```json
   {
     "Cookie_MUSIC_U": "YOUR_MUSIC_U_COOKIE",
     "Cookie___csrf": "YOUR_CSRF_TOKEN",
     "notify_email": "your.email@gmail.com",
     "email_password": "YOUR_APP_SPECIFIC_PASSWORD",
     "smtp_server": "smtp.gmail.com",
     "smtp_port": 465,
     "wait_time_min": 15,
     "wait_time_max": 20,
     "score": 3  // 评分策略：1=1-2分，2=2-3分，3=3-4分（默认），4=固定4分
   }
   ```

5. 运行测试脚本确认配置正确：

   ```bash
   python tests/test_auto_score.py
   ```

6. 运行主程序：

   ```bash
   python main.py
   ```

### 方式二：桌面应用（Tauri，推荐）

Rust 外壳 + Web 前端 + Python sidecar。Windows 上一条命令完成构建：

```bash
build_sidecar.bat    # 1. 打包 Python 后端 (ncmp-server.exe) 并放入 src-tauri/binaries/
build_tauri.bat      # 2. 构建桌面应用（内部会自动调用上一步）
```

产物：

- 免安装可执行文件：`src-tauri/target/release/ncmp.exe`
- 安装包（NSIS）：`src-tauri/target/release/bundle/nsis/`

前端资源、Python 后端都会被打进应用，运行时不依赖本机 Python 环境。

**开发模式**（改前端即时生效，无需重新编译 Rust）：

```bash
# 终端 1：启动 Python 后端（随机端口，控制台会打印地址与令牌）
python -m src.server --open-browser

# 终端 2（可选）：直接调试 Tauri 外壳
npx tauri dev
```

### 方式三：浏览器模式（无需 Rust）

只想用界面、不想装 Rust 时，后端本身就带界面：

```bash
python -m src.server --open-browser
```

控制台会输出访问地址（含令牌），浏览器打开即为完整界面。手机上想远程查看时，可用
`python -m src.server --host 0.0.0.0 --port 8765 --print-token`（注意：会暴露到局域网，请自行评估风险）。

界面包含四个页面：

- **运行控制**：账号状态 / 用户昵称 / 每日与额外任务进度卡片、总进度条、实时日志（级别过滤、搜索、复制）、一键「验证 Cookie」「开始任务」「终止运行」「刷新 Cookie」
- **配置**：分组表单在线编辑全部配置项（Cookie、等待时间、评分策略、邮件通知、自动登录与 GitHub），敏感字段默认掩码显示，支持「保存并验证」
- **运行历史**：每次运行的结果与完整日志保存在 `data/history/`，可查看、删除、打开日志文件夹
- **关于**：架构说明、后端地址、数据目录、运行模式

### 方式四：打包为 Windows EXE（Tkinter 旧版界面）

原 Tkinter 界面仍保留可用，同样可打包为单文件 EXE：

```bash
build_exe.bat
```

或手动执行：

```bash
pip install -r requirements.txt pyinstaller
python assets/make_icon.py          # 生成应用图标（可选）
python -m PyInstaller ncmp.spec --noconfirm --clean
```

打包产物为 `dist/ncmp.exe`，双击即可运行，**无需安装 Python**。使用说明：

- 首次运行：把项目里的 `config` 文件夹（含 `setting.json`）复制到 exe 同目录后再运行，或直接在界面「配置」页签填写并保存
- 运行记录与日志保存在 exe 同目录的 `data/history/` 下
- exe 为单文件版，首次启动解压约需几秒，属正常现象

> Tkinter 界面源码位于 `src/ui/`，启动命令为 `python gui.py`；新功能（如终止运行）在两侧界面均已支持。

### 方式五：GitHub Actions 自动执行

1. Fork 本仓库到你的 GitHub 账号

2. 配置 GitHub Secrets：
   在你 fork 的仓库中，进入 Settings -> Secrets and variables -> Actions，添加以下配置：
   - `MUSIC_U`：网易云音乐 MUSIC_U Cookie
   - `CSRF`：网易云音乐 CSRF Token
   - `NOTIFY_EMAIL`：邮箱地址（可选）
   - `EMAIL_PASSWORD`：邮箱密码（可选）
   - `SMTP_SERVER`：smtp.gmail.com（可选）
   - `SMTP_PORT`：465（可选）
   - `WAIT_TIME_MIN`：最小等待时间（可选，默认15）
   - `WAIT_TIME_MAX`：最大等待时间（可选，默认20）
   - `SCORE`：评分策略（可选，默认3）

3. 启用 GitHub Actions：
   - 进入仓库的 Actions 页面
   - 点击 "I understand my workflows, go ahead and enable them"
   - Actions 将会按照预设时间自动运行（默认北京时间1点）

## 注意事项

- 目前仅对 Gmail/QQ邮箱 进行了验证，其他邮箱可能需要自行测试
- 邮箱密码为授权码，而非邮箱登录密码
- 任务提交默认添加了 15-20 秒的等待时间，避免被检测异常
- 建议使用 GitHub Actions 的定时任务功能，避免遗漏每日任务
- 网易云音乐的 Cookie 两周左右就会过期，建议配置邮箱以便及时收到失效通知
- Cookie 自动刷新使用了[ACAne0320/ncma](https://github.com/ACAne0320/ncma)的登陆API，如果害怕隐私泄露，可以自行fork该仓库并本地部署，将代码中刷新cookie的请求链接替换即可

## 声明

- 本项目仅供学习交流使用
- 不得用于商业用途
- 使用本脚本产生的一切后果由使用者自行承担

## 致谢

- [ncmp](https://github.com/ACAne0320/ncmp)
- [qinglong-sign](https://github.com/KotoriMinami/qinglong-sign)
- [CloudMusicBot](https://github.com/C20C01/CloudMusicBot)
- [NeteaseCloudMusicApi](https://github.com/Binaryify/NeteaseCloudMusicApi)
- [Tauri](https://tauri.app/)（Rust 外壳与 WebView 容器）
