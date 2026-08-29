"""ncmp 桌面图形界面主窗口（Tkinter）。

界面包含三个页签：
  1. 运行：账号状态/任务统计卡片、进度条、启动按钮、实时日志控制台
  2. 配置：在线编辑 config/setting.json 的全部配置项（敏感项默认隐藏）
  3. 历史：查看每次运行的记录与完整日志
"""
import json
import os
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk

from .history import PROJECT_ROOT, RunHistory
from .runner import RunManager
from ..core.exceptions import CANCELLED_REASON

VERSION = "1.1.2"

# ----------------------------------------------------------------------
# 主题常量（深色 + 网易红）
# ----------------------------------------------------------------------
BG = "#1b1b22"
PANEL = "#26262e"
PANEL2 = "#2f2f3a"
TEXT = "#e8e8ea"
MUTED = "#9a9aa5"
ACCENT = "#ec4141"
ACCENT_DARK = "#c83434"
GREEN = "#5cb85c"
WARN = "#ffb300"
ERR = "#ef5350"
BORDER = "#3a3a45"

LOG_BG = "#14141a"

FONT = "Microsoft YaHei UI"
MONO = "Consolas"

CONFIG_PATH = os.path.join(PROJECT_ROOT, "config", "setting.json")
EXAMPLE_PATH = os.path.join(PROJECT_ROOT, "config", "setting.example.json")
HISTORY_FOLDER = os.path.join(PROJECT_ROOT, "data", "history")
CONFIG_FOLDER = os.path.join(PROJECT_ROOT, "config")

SCORE_LABELS = ["1-2分", "2-3分", "3-4分（默认）", "固定4分"]

# (field_key, 显示名, 控件类型, 附加参数)
# 控件类型: entry=普通输入 long=长输入 cookie=长输入(默认隐藏) password=密码
#           spin=数字微调 combo=下拉
CONFIG_SECTIONS = [
    ("网易云账户 Cookie（必需）", [
        ("Cookie_MUSIC_U", "MUSIC_U Cookie", "cookie"),
        ("Cookie___csrf", "__csrf Token", "cookie"),
    ]),
    ("任务设置", [
        ("wait_time_min", "最短等待时间（秒）", "spin", (1, 300)),
        ("wait_time_max", "最长等待时间（秒）", "spin", (1, 300)),
        ("score", "评分策略", "combo"),
    ]),
    ("邮件通知（可选）", [
        ("notify_email", "通知邮箱", "entry"),
        ("email_password", "邮箱密码 / 授权码", "password"),
        ("smtp_server", "SMTP 服务器", "entry"),
        ("smtp_port", "SMTP 端口", "spin", (1, 65535)),
    ]),
    ("自动登录 & GitHub（可选，用于 Cookie 自动刷新）", [
        ("netease_phone", "网易云音乐手机号", "entry"),
        ("netease_password", "密码（明文，二选一）", "password"),
        ("netease_md5_password", "密码（MD5，推荐，二选一）", "password"),
        ("gh_token", "GitHub Personal Access Token", "password"),
        ("gh_repo", "GitHub 仓库（username/repo）", "entry"),
    ]),
]


class NcmpApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"网易云音乐合伙人 v{VERSION}")
        self.geometry("1020x720")
        self.minsize(900, 640)
        self.configure(bg=BG)

        self.manager = RunManager()
        self.busy = False
        self.last_result_text = ""
        self.auto_scroll = tk.BooleanVar(value=True)

        self._setup_fonts()
        self._setup_style()
        self._build_menu()
        self._build_header()
        self._build_body()
        self._build_footer()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._poll_events)
        self.after(600, self._auto_check)

    # ------------------------------------------------------------------
    # 初始化：字体与样式
    # ------------------------------------------------------------------
    def _setup_fonts(self):
        global FONT
        try:
            families = set(tkfont.families(self))
            for candidate in ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
                              "Noto Sans CJK SC", "SimHei"):
                if candidate in families:
                    FONT = candidate
                    break
        except Exception:
            pass

    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab",
                        background=PANEL, foreground=MUTED,
                        padding=(22, 10), font=(FONT, 10))
        style.map("TNotebook.Tab",
                  background=[("selected", PANEL2)],
                  foreground=[("selected", TEXT)])

        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT, font=(FONT, 10))
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT, font=(FONT, 10))
        style.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=(FONT, 9))

        style.configure("TButton",
                        background=PANEL2, foreground=TEXT, font=(FONT, 10),
                        padding=(14, 7), borderwidth=0, focusthickness=0)
        style.map("TButton", background=[("active", "#3a3a48"), ("disabled", "#23232b")],
                  foreground=[("disabled", "#5a5a66")])
        style.configure("Accent.TButton",
                        background=ACCENT, foreground="#ffffff", font=(FONT, 11, "bold"),
                        padding=(18, 8), borderwidth=0)
        style.map("Accent.TButton", background=[("active", ACCENT_DARK), ("disabled", "#5f2b2b")])
        style.configure("Danger.TButton",
                        background="#b03535", foreground="#ffffff", font=(FONT, 10, "bold"),
                        padding=(14, 7), borderwidth=0)
        style.map("Danger.TButton", background=[("active", "#c44a4a"), ("disabled", "#5f2b2b")])

        style.configure("TEntry",
                        fieldbackground="#1f1f27", foreground=TEXT,
                        insertcolor=TEXT, bordercolor=BORDER, lightcolor=BORDER)
        style.configure("TCombobox",
                        fieldbackground="#1f1f27", background=PANEL2,
                        foreground=TEXT, arrowcolor=TEXT, bordercolor=BORDER)
        style.map("TCombobox", fieldbackground=[("readonly", "#1f1f27")],
                  foreground=[("readonly", TEXT)])
        style.configure("TSpinbox",
                        fieldbackground="#1f1f27", background=PANEL2,
                        foreground=TEXT, arrowcolor=TEXT, bordercolor=BORDER)
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT, font=(FONT, 9))

        style.configure("Treeview",
                        background="#1f1f27", fieldbackground="#1f1f27",
                        foreground=TEXT, rowheight=27, borderwidth=0)
        style.configure("Treeview.Heading", background=PANEL2, foreground=TEXT,
                        font=(FONT, 9, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", "#3d3d4d")])

        style.configure("TLabelframe", background=PANEL, foreground=TEXT)
        style.configure("TLabelframe.Label", background=PANEL, foreground=MUTED,
                        font=(FONT, 9, "bold"))

        style.configure("Run.Horizontal.TProgressbar",
                        troughcolor="#1f1f27", background=ACCENT,
                        bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT)
        style.configure("TScrollbar", troughcolor=PANEL, background=PANEL2,
                        arrowcolor=TEXT, bordercolor=PANEL)

    # ------------------------------------------------------------------
    # 菜单
    # ------------------------------------------------------------------
    def _build_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="打开配置文件", command=self._open_settings_file)
        file_menu.add_command(label="打开配置文件夹", command=self._open_config_folder)
        file_menu.add_command(label="打开日志文件夹", command=self._open_history_folder)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self._on_close)
        menubar.add_cascade(label="文件", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="关于", command=self._show_about)
        menubar.add_cascade(label="帮助", menu=help_menu)

        self.config(menu=menubar)

    def _open_folder(self, folder, name):
        try:
            if sys.platform == "win32":
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            messagebox.showerror("错误", f"无法打开{name}: {e}")

    def _open_config_folder(self):
        self._open_folder(CONFIG_FOLDER, "配置文件夹")

    def _open_history_folder(self):
        os.makedirs(HISTORY_FOLDER, exist_ok=True)
        self._open_folder(HISTORY_FOLDER, "日志文件夹")

    def _open_settings_file(self):
        if not os.path.exists(CONFIG_PATH):
            messagebox.showinfo(
                "提示", f"配置文件不存在：\n{CONFIG_PATH}\n\n"
                        "请先在「配置」页签填写并保存。")
            return
        try:
            os.startfile(CONFIG_PATH)  # type: ignore[attr-defined]
        except Exception as e:
            messagebox.showerror("错误", f"无法打开配置文件: {e}")

    def _show_about(self):
        mode = "exe 打包版" if getattr(sys, "frozen", False) else "源码运行版"
        messagebox.showinfo(
            "关于 · 网易云音乐合伙人",
            f"网易云音乐合伙人 v{VERSION}\n"
            f"当前模式：{mode}\n\n"
            "基于 Python 的网易云音乐-音乐合伙人任务脚本\n"
            "支持本地运行、图形界面与 GitHub Actions 自动执行\n\n"
            "本工具仅供学习交流使用，使用产生的一切后果由使用者自行承担。"
        )

    # ------------------------------------------------------------------
    # 顶部标题栏
    # ------------------------------------------------------------------
    def _build_header(self):
        header = tk.Frame(self, bg="#20202a", height=58)
        header.pack(fill=tk.X, side=tk.TOP)
        header.pack_propagate(False)

        logo = tk.Label(header, text="●", bg="#20202a", fg=ACCENT,
                        font=(FONT, 20, "bold"))
        logo.pack(side=tk.LEFT, padx=(14, 6), pady=10)

        title_box = tk.Frame(header, bg="#20202a")
        title_box.pack(side=tk.LEFT, pady=8)
        tk.Label(title_box, text="网易云音乐合伙人", bg="#20202a", fg=TEXT,
                 font=(FONT, 14, "bold")).pack(anchor="w")
        tk.Label(title_box, text="网易云音乐每日评分任务 · 自动执行",
                 bg="#20202a", fg=MUTED, font=(FONT, 9)).pack(anchor="w")

        self.lamp = tk.Label(header, text="● 空闲", bg="#20202a", fg=GREEN,
                             font=(FONT, 10, "bold"))
        self.lamp.pack(side=tk.RIGHT, padx=16)

        tk.Label(header, text=f"v{VERSION}", bg="#20202a", fg=MUTED,
                 font=(FONT, 9)).pack(side=tk.RIGHT, padx=8)

    # ------------------------------------------------------------------
    # 主体布局
    # ------------------------------------------------------------------
    def _build_body(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.tab_run = ttk.Frame(self.notebook)
        self.tab_config = ttk.Frame(self.notebook)
        self.tab_history = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_run, text="  运行  ")
        self.notebook.add(self.tab_config, text="  配置  ")
        self.notebook.add(self.tab_history, text="  历史  ")

        self._build_run_tab()
        self._build_config_tab()
        self._build_history_tab()

    # --------------------------- 运行页签 ---------------------------
    def _build_run_tab(self):
        # 统计卡片
        info = tk.Frame(self.tab_run, bg=PANEL, highlightbackground=BORDER,
                        highlightthickness=1)
        info.pack(fill=tk.X, padx=12, pady=(12, 8))
        for col in range(4):
            info.columnconfigure(col, weight=1, uniform="info")

        self.lbl_account = self._info_card(info, 0, "账号状态")
        self.lbl_account["text"] = "未检测"
        self.lbl_nickname = self._info_card(info, 1, "用户昵称")
        self.lbl_nickname["text"] = "-"
        self.lbl_daily = self._info_card(info, 2, "每日评分任务")
        self.lbl_daily["text"] = "-"
        self.lbl_extra = self._info_card(info, 3, "额外评分任务")
        self.lbl_extra["text"] = "-"

        # 进度条
        progress_row = tk.Frame(self.tab_run, bg=BG)
        progress_row.pack(fill=tk.X, padx=12, pady=(0, 6))
        self.progress = ttk.Progressbar(progress_row, style="Run.Horizontal.TProgressbar",
                                        mode="determinate", maximum=100)
        self.progress.pack(fill=tk.X)

        # 操作按钮
        btn_bar = tk.Frame(self.tab_run, bg=BG)
        btn_bar.pack(fill=tk.X, padx=12, pady=(2, 8))
        self.btn_validate = ttk.Button(btn_bar, text="验证 Cookie", command=self._on_validate)
        self.btn_validate.pack(side=tk.LEFT, padx=(0, 10))
        self.btn_run = ttk.Button(btn_bar, text="▶ 开始任务", style="Accent.TButton",
                                  command=self._on_run)
        self.btn_run.pack(side=tk.LEFT, padx=(0, 10))
        self.btn_refresh = ttk.Button(btn_bar, text="刷新 Cookie", command=self._on_refresh)
        self.btn_refresh.pack(side=tk.LEFT)
        self.btn_stop = ttk.Button(btn_bar, text="■ 终止运行", style="Danger.TButton",
                                   command=self._on_stop, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=(10, 0))
        tk.Label(btn_bar, text="（刷新需配置手机号、密码和 GitHub 信息）",
                 bg=BG, fg=MUTED, font=(FONT, 9)).pack(side=tk.LEFT, padx=6)

        # 日志工具栏
        tool_bar = tk.Frame(self.tab_run, bg=BG)
        tool_bar.pack(fill=tk.X, padx=12, pady=(0, 4))
        tk.Label(tool_bar, text="实时日志", bg=BG, fg=TEXT,
                 font=(FONT, 10, "bold")).pack(side=tk.LEFT)
        ttk.Button(tool_bar, text="清空", width=6,
                   command=self._clear_log).pack(side=tk.RIGHT)
        ttk.Button(tool_bar, text="复制", width=6,
                   command=self._copy_log).pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Checkbutton(tool_bar, text="自动滚动", variable=self.auto_scroll,
                        command=self._on_autoscroll_toggle).pack(side=tk.RIGHT, padx=(0, 10))

        # 日志控制台
        log_frame = tk.Frame(self.tab_run, bg=LOG_BG, highlightbackground=BORDER,
                             highlightthickness=1)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 6))

        self.log_text = tk.Text(log_frame, bg=LOG_BG, fg=TEXT, insertbackground=TEXT,
                                font=(MONO, 10), wrap="word", borderwidth=0,
                                highlightthickness=0, state=tk.DISABLED, padx=10, pady=8)
        scrollbar = tk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.log_text.tag_configure("time", foreground="#5f5f6e")
        self.log_text.tag_configure("info", foreground=TEXT)
        self.log_text.tag_configure("warn", foreground=WARN)
        self.log_text.tag_configure("err", foreground=ERR)
        self.log_text.tag_configure("ok", foreground=GREEN)
        self.log_text.tag_configure("sys", foreground=MUTED)

        self._append_log("sys", f"网易云音乐合伙人 v{VERSION} 图形界面已启动\n")

    def _info_card(self, parent, col, title):
        card = tk.Frame(parent, bg=PANEL)
        card.grid(row=0, column=col, sticky="nsew", padx=10, pady=10)
        tk.Label(card, text=title, bg=PANEL, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        value = tk.Label(card, text="-", bg=PANEL, fg=TEXT, font=(FONT, 12, "bold"))
        value.pack(anchor="w", pady=(2, 0))
        return value

    def _clear_log(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _copy_log(self):
        content = self.log_text.get("1.0", tk.END)
        self.clipboard_clear()
        self.clipboard_append(content.strip())
        self.status_bar.configure(text="✅ 日志已复制到剪贴板")

    def _on_autoscroll_toggle(self):
        if self.auto_scroll.get():
            self.log_text.see(tk.END)

    # --------------------------- 配置页签 ---------------------------
    def _build_config_tab(self):
        outer = tk.Frame(self.tab_config, bg=BG)
        outer.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        self._config_canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        vs = tk.Scrollbar(outer, orient="vertical", command=self._config_canvas.yview)
        self._config_canvas.configure(yscrollcommand=vs.set)
        vs.pack(side=tk.RIGHT, fill=tk.Y)
        self._config_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        form = tk.Frame(self._config_canvas, bg=BG)
        self._config_canvas.create_window((0, 0), window=form, anchor="nw")

        form.bind("<Configure>",
                  lambda e: self._config_canvas.configure(
                      scrollregion=self._config_canvas.bbox("all")))
        self._config_canvas.bind("<Configure>",
                                 lambda e: self._config_canvas.itemconfig(1, width=e.width))
        self._config_canvas.bind("<MouseWheel>",
                                 lambda e: self._config_canvas.yview_scroll(
                                     int(-e.delta / 120), "units"))

        self.form_vars = {}
        self._masked_widgets = {}   # section_index -> list[(entry, var, is_cookie)]

        for idx, (title, fields) in enumerate(CONFIG_SECTIONS):
            lf = tk.LabelFrame(form, text=title, bg=PANEL, fg=MUTED,
                               font=(FONT, 9, "bold"),
                               bd=1, relief="groove", padx=10, pady=8)
            lf.pack(fill=tk.X, pady=(0, 10))

            has_mask = any(f[2] in ("cookie", "password") for f in fields)
            cookie_in_section = any(f[2] == "cookie" for f in fields)
            for row, field in enumerate(fields):
                key, label, kind = field[0], field[1], field[2]
                extra = field[3] if len(field) > 3 else None

                tk.Label(lf, text=label, bg=PANEL, fg=TEXT, font=(FONT, 10), width=24,
                         anchor="w").grid(row=row, column=0, sticky="w", pady=3)

                var = tk.StringVar()
                self.form_vars[key] = var

                if kind in ("entry", "long", "cookie", "password"):
                    width = 66 if kind in ("long", "cookie") else 52
                    show = "*" if kind in ("cookie", "password") else ""
                    widget = ttk.Entry(lf, textvariable=var, width=width,
                                       show=show,
                                       font=(MONO, 9) if kind in ("long", "cookie")
                                       else (FONT, 10))
                    widget.grid(row=row, column=1, sticky="we", pady=3, padx=(6, 0))
                    if kind in ("cookie", "password"):
                        self._masked_widgets.setdefault(idx, []).append(
                            (widget, var, kind == "cookie"))
                elif kind == "spin":
                    low, high = extra
                    widget = ttk.Spinbox(lf, from_=low, to=high, textvariable=var,
                                         width=12, font=(FONT, 10))
                    widget.grid(row=row, column=1, sticky="w", pady=3, padx=(6, 0))
                elif kind == "combo":
                    widget = ttk.Combobox(lf, values=SCORE_LABELS, state="readonly",
                                          width=20, font=(FONT, 10))
                    widget.grid(row=row, column=1, sticky="w", pady=3, padx=(6, 0))
                    widget.bind("<<ComboboxSelected>>",
                                lambda e, w=widget: self._on_score_changed(w))
                    self._score_combo = widget

            lf.columnconfigure(1, weight=1)

            if has_mask:
                show_var = tk.BooleanVar(value=False)
                text = "显示 Cookie" if cookie_in_section else "显示密码"
                ttk.Checkbutton(lf, text=text, variable=show_var,
                                command=lambda v=show_var, i=idx: self._on_toggle_mask(i, v)
                                ).grid(row=len(fields) + 1, column=1, sticky="w", pady=(2, 0))

        # 底部操作栏
        action = tk.Frame(self.tab_config, bg=BG)
        action.pack(fill=tk.X, padx=12, pady=(4, 12))
        ttk.Button(action, text="保存配置", style="Accent.TButton",
                   command=self._on_save).pack(side=tk.LEFT)
        ttk.Button(action, text="保存并验证", command=self._on_save_and_validate).pack(
            side=tk.LEFT, padx=(10, 0))
        ttk.Button(action, text="重新加载", command=self._load_config_form).pack(
            side=tk.LEFT, padx=(10, 0))
        ttk.Button(action, text="用记事本打开", command=self._open_settings_file).pack(
            side=tk.LEFT, padx=(10, 0))
        self.config_hint = tk.Label(action, text="", bg=BG, fg=GREEN, font=(FONT, 9))
        self.config_hint.pack(side=tk.LEFT, padx=12)

    def _on_toggle_mask(self, idx, show_var):
        show = "" if show_var.get() else "*"
        for widget, _var, _is_cookie in self._masked_widgets.get(idx, []):
            widget.configure(show=show)

    def _on_score_changed(self, combo):
        try:
            index = SCORE_LABELS.index(combo.get())
            self.form_vars["score"].set(str(index + 1))
        except ValueError:
            pass

    # --------------------------- 历史页签 ---------------------------
    def _build_history_tab(self):
        left = tk.Frame(self.tab_history, bg=BG)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(12, 6), pady=12)

        head = tk.Frame(left, bg=BG)
        head.pack(fill=tk.X)
        ttk.Button(head, text="刷新", command=self._refresh_history).pack(side=tk.LEFT)
        ttk.Button(head, text="删除所选", command=self._delete_selected).pack(
            side=tk.LEFT, padx=(8, 0))
        ttk.Button(head, text="打开日志文件夹",
                   command=self._open_history_folder).pack(side=tk.LEFT, padx=(8, 0))

        columns = ("time", "kind", "result", "summary")
        self.history_tree = ttk.Treeview(left, columns=columns, show="headings", height=20)
        self.history_tree.heading("time", text="时间")
        self.history_tree.heading("kind", text="类型")
        self.history_tree.heading("result", text="结果")
        self.history_tree.heading("summary", text="摘要")
        self.history_tree.column("time", width=130, anchor="w")
        self.history_tree.column("kind", width=76, anchor="w")
        self.history_tree.column("result", width=60, anchor="center")
        self.history_tree.column("summary", width=170, anchor="w")
        self.history_tree.pack(fill=tk.Y, expand=True, pady=(8, 0))
        self.history_tree.bind("<<TreeviewSelect>>", self._on_history_select)

        h_scroll = tk.Scrollbar(left, orient="vertical", command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=h_scroll.set)
        h_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        right = tk.Frame(self.tab_history, bg=LOG_BG, highlightbackground=BORDER,
                         highlightthickness=1)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 12), pady=12)

        self.history_log = tk.Text(right, bg=LOG_BG, fg=TEXT, insertbackground=TEXT,
                                   font=(MONO, 9), wrap="word", borderwidth=0,
                                   highlightthickness=0, state=tk.DISABLED, padx=8, pady=8)
        h_scroll2 = tk.Scrollbar(right, command=self.history_log.yview)
        self.history_log.configure(yscrollcommand=h_scroll2.set)
        h_scroll2.pack(side=tk.RIGHT, fill=tk.Y)
        self.history_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._refresh_history()

    def _refresh_history(self):
        self.history_tree.delete(*self.history_tree.get_children())
        for record in RunHistory.load_all():
            result = "✅" if record.get("success") else "❌"
            self.history_tree.insert(
                "", "end", iid=record.get("id", ""),
                values=(record.get("time", ""), record.get("kind", ""),
                        result, record.get("summary", ""))
            )

    def _on_history_select(self, _event=None):
        selection = self.history_tree.selection()
        if not selection:
            return
        run_id = selection[0]
        content = RunHistory.load_log(run_id)
        self.history_log.configure(state=tk.NORMAL)
        self.history_log.delete("1.0", tk.END)
        self.history_log.insert("1.0", content or "（该记录没有日志文件）")
        self.history_log.configure(state=tk.DISABLED)

    def _delete_selected(self):
        selection = self.history_tree.selection()
        if not selection:
            return
        run_id = selection[0]
        if messagebox.askyesno("删除历史", "确定删除这条运行记录及其日志吗？"):
            RunHistory.delete(run_id)
            self._refresh_history()

    # ------------------------------------------------------------------
    # 底部状态栏
    # ------------------------------------------------------------------
    def _build_footer(self):
        footer = tk.Frame(self, bg=PANEL, highlightbackground=BORDER,
                          highlightthickness=1)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_bar = tk.Label(footer, text="就绪", anchor="w",
                                   bg=PANEL, fg=TEXT, font=(FONT, 9),
                                   padx=12, pady=5)
        self.status_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(footer, text="仅供学习交流使用", bg=PANEL, fg=MUTED,
                 font=(FONT, 9)).pack(side=tk.RIGHT, padx=12)

    # ------------------------------------------------------------------
    # 配置读取/保存
    # ------------------------------------------------------------------
    def _read_config(self) -> dict:
        path = CONFIG_PATH if os.path.exists(CONFIG_PATH) else EXAMPLE_PATH
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            messagebox.showerror("读取配置失败", f"{path}\n\n{e}")
            return {}

    def _load_config_form(self):
        data = self._read_config()
        for key, var in self.form_vars.items():
            value = data.get(key, "")
            if key == "score":
                try:
                    var.set(str(int(value)))
                except (TypeError, ValueError):
                    var.set("3")
            else:
                var.set(str(value if value is not None else ""))
        try:
            score = int(self.form_vars["score"].get())
        except ValueError:
            score = 3
        score = max(1, min(4, score))
        self._score_combo.set(SCORE_LABELS[score - 1])
        self.config_hint.configure(
            text="已加载 " + ("config/setting.json" if os.path.exists(CONFIG_PATH)
                              else "setting.example.json（保存后将创建 setting.json）"),
            fg=MUTED)

    def _collect_and_validate(self):
        """校验并收集表单数据，返回 (data, error_msg)"""
        data = self._read_config()
        if not data:
            return None, "无法读取配置文件模板"

        music_u = self.form_vars["Cookie_MUSIC_U"].get().strip()
        csrf = self.form_vars["Cookie___csrf"].get().strip()
        if not music_u or not csrf:
            return None, "MUSIC_U Cookie 与 __csrf Token 为必填项。"

        try:
            wait_min = float(self.form_vars["wait_time_min"].get())
            wait_max = float(self.form_vars["wait_time_max"].get())
            score = int(self.form_vars["score"].get())
            smtp_port = int(self.form_vars["smtp_port"].get())
        except ValueError:
            return None, "请在任务设置与邮件通知中输入合法数字。"

        if wait_min <= 0 or wait_max <= 0:
            return None, "等待时间必须大于 0。"
        if wait_min > wait_max:
            return None, "最短等待时间不能大于最长等待时间。"
        if score not in (1, 2, 3, 4):
            return None, "评分策略必须为 1-4。"
        if not (1 <= smtp_port <= 65535):
            return None, "SMTP 端口必须在 1-65535 之间。"

        data["Cookie_MUSIC_U"] = music_u
        data["Cookie___csrf"] = csrf
        data["wait_time_min"] = wait_min
        data["wait_time_max"] = wait_max
        data["score"] = score
        data["smtp_port"] = smtp_port
        for key in ("notify_email", "email_password", "smtp_server",
                    "netease_phone", "netease_password", "netease_md5_password",
                    "gh_token", "gh_repo"):
            data[key] = self.form_vars[key].get()
        return data, None

    def _on_save(self):
        data, error = self._collect_and_validate()
        if error:
            messagebox.showwarning("配置格式错误", error)
            return
        self._write_config(data)
        self.config_hint.configure(text=f"✅ 已保存到 {CONFIG_PATH}", fg=GREEN)
        self._append_log("sys", f"✅ 配置已保存到 {CONFIG_PATH}\n")
        self.status_bar.configure(text="✅ 配置已保存")

    def _on_save_and_validate(self):
        data, error = self._collect_and_validate()
        if error:
            messagebox.showwarning("配置格式错误", error)
            return
        self._write_config(data)
        self.config_hint.configure(text=f"✅ 已保存到 {CONFIG_PATH}", fg=GREEN)
        self._append_log("sys", f"✅ 配置已保存到 {CONFIG_PATH}\n")
        self.notebook.select(self.tab_run)
        self._on_validate()

    def _write_config(self, data: dict) -> None:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # 操作：验证 / 运行 / 刷新
    # ------------------------------------------------------------------
    def _on_validate(self):
        # 表单为空时自动从配置文件加载，保证任何时机点击都可用
        if not self.form_vars["Cookie_MUSIC_U"].get().strip():
            self._load_config_form()
        music_u = self.form_vars["Cookie_MUSIC_U"].get().strip()
        csrf = self.form_vars["Cookie___csrf"].get().strip()
        if not music_u or not csrf:
            messagebox.showwarning("配置不完整",
                                   "请先在「配置」页签填写 MUSIC_U 与 __csrf 并保存。")
            self.notebook.select(self.tab_config)
            return
        self.lbl_account.configure(text="检测中...", fg=WARN)
        self.lamp.configure(text="● 检测中", fg=WARN)
        if not self.manager.validate_async(music_u, csrf):
            messagebox.showinfo("提示", "已有一个任务正在运行或验证中，请稍候再试。")
            return
        self._set_busy(True, "正在验证 Cookie...")

    def _on_run(self):
        if self.manager.busy:
            return
        # 表单为空时自动从配置文件加载，保证任何时机点击都可用
        if not self.form_vars["Cookie_MUSIC_U"].get().strip():
            self._load_config_form()
        music_u = self.form_vars["Cookie_MUSIC_U"].get().strip()
        if not music_u:
            messagebox.showwarning("配置不完整",
                                   "请先在「配置」页签填写 Cookie 并保存。")
            self.notebook.select(self.tab_config)
            return
        if not self.manager.start_pipeline():
            messagebox.showinfo("提示", "已有一个任务正在运行或验证中，请稍候再试。")
            return
        self._append_log("sys", "—— 开始执行每日任务 ——\n")
        self._set_busy(True, "任务运行中...")

    def _on_refresh(self):
        if self.manager.busy:
            return
        if not self.manager.start_refresh():
            messagebox.showinfo("提示", "已有一个任务正在运行或验证中，请稍候再试。")
            return
        self._append_log("sys", "—— 开始刷新 Cookie ——\n")
        self._set_busy(True, "Cookie 刷新中...")

    def _on_stop(self):
        """终止正在运行的任务。"""
        if not self.manager.busy:
            return
        if not messagebox.askyesno(
                "终止运行",
                "确定要终止当前任务吗？\n"
                "正在进行的评分操作会在当前请求完成后停止。"):
            return
        self.manager.request_cancel()
        self.btn_stop.configure(state=tk.DISABLED)
        self.status_bar.configure(text="正在终止任务...")
        self.lamp.configure(text="● 终止中", fg=WARN)
        self._append_log("sys", "—— 收到终止请求，正在停止任务 ——\n")

    def _set_busy(self, busy: bool, status_text: str = ""):
        self.busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        self.btn_validate.configure(state=state)
        self.btn_run.configure(state=state)
        self.btn_refresh.configure(state=state)
        # 运行中才允许"终止运行"
        self.btn_stop.configure(state=tk.NORMAL if busy else tk.DISABLED)
        if busy:
            self.lamp.configure(text="● 运行中", fg=ACCENT)
            # 先停掉旧动画再启动，避免残留回调继续推进 value
            self.progress.stop()
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)
        else:
            # 注意：Python 3.14 的 Tkinter 中 widget["mode"] 返回 Tcl_Obj，
            # 必须用 str() 转换后再比较，否则恒为 False
            was_indeterminate = str(self.progress["mode"]) == "indeterminate"
            keep_value = float(self.progress["value"])
            self.progress.stop()
            if was_indeterminate:
                # 从未产生真实进度时归零；否则保留最后一次真实进度
                self.progress.configure(mode="determinate", maximum=100, value=0)
            else:
                self.progress["value"] = keep_value
            self.lamp.configure(text="● 空闲", fg=GREEN)
        if status_text:
            self.status_bar.configure(text=status_text)

    # ------------------------------------------------------------------
    # 事件轮询（从 worker 线程队列读取）
    # ------------------------------------------------------------------
    def _poll_events(self):
        while True:
            try:
                event = self.manager.queue.get_nowait()
            except Exception:
                break
            self._handle_event(event)

        # 同步忙碌状态与按钮状态
        busy_now = self.manager.busy
        if busy_now != self.busy:
            self._set_busy(busy_now)
            if not busy_now:
                status_text = getattr(self, "last_result_text", "") or "就绪"
                self.status_bar.configure(text=status_text)

        self.after(100, self._poll_events)

    def _handle_event(self, event: dict):
        etype = event.get("type")

        if etype == "log":
            self._append_log(event.get("level", "INFO"), event.get("line", ""))
            return

        if etype == "progress":
            self.status_bar.configure(text=event.get("text", ""))
            return

        if etype == "stats":
            self._handle_stats(event.get("stage"), event.get("payload") or {})
            return

        if etype == "validate":
            ok = bool(event.get("success"))
            message = event.get("message", "")
            if ok:
                self.lbl_account.configure(text="✅ Cookie 有效", fg=GREEN)
                self.last_result_text = "✅ Cookie 验证通过"
            else:
                self.lbl_account.configure(text="❌ Cookie 无效", fg=ERR)
                self.last_result_text = f"❌ Cookie 验证失败：{message}"
            self.status_bar.configure(text=self.last_result_text)
            self._append_log("sys",
                             f"Cookie 验证结果：{'✅ ' + message if ok else '❌ ' + message}\n")
            return

        if etype == "account":
            self.lbl_nickname.configure(text=event.get("username") or "-")
            return

        if etype == "done":
            record = event.get("record", {})
            ok = bool(record.get("success"))
            summary = record.get("summary", "")
            if not ok and summary == CANCELLED_REASON:
                result_text = "⏹ 任务已被用户终止"
            else:
                result_text = ("✅ 上次运行成功" if ok else "❌ 上次运行失败") + f"：{summary}"
            self.last_result_text = result_text
            self.status_bar.configure(text=result_text)
            if ok:
                # 先停动画再显示 100%（ttk 的 stop() 会清零 value）
                self.progress.stop()
                self.progress.configure(mode="determinate", maximum=100)
                self.progress["value"] = 100
            self._append_log("sys", f"—— 运行结束：{result_text} ——\n")
            self._refresh_history()
            return

    def _set_progress(self, maximum: int, value: int):
        """更新进度条：必须先 stop()（ttk 会清零 value），再切模式并设值。"""
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=max(maximum, 1))
        self.progress["value"] = max(0, min(max(value, 0), max(maximum, 1)))

    def _handle_stats(self, stage: str, payload: dict):
        if stage == "account":
            self.lbl_nickname.configure(text=payload.get("username") or "-")
        elif stage == "daily":
            count = int(payload.get("count", 0) or 0)
            completed = int(payload.get("completed", 0) or 0)
            self.lbl_daily.configure(text=f"{completed}/{count}", fg=TEXT)
            if count:
                self._set_progress(count, completed)
        elif stage == "extra_meta":
            completed = int(payload.get("completed", 0) or 0)
            maximum = int(payload.get("max", 15) or 15)
            self.lbl_extra.configure(text=f"{completed}/{maximum}", fg=TEXT)
            self._set_progress(maximum, completed)
        elif stage == "extra_progress":
            done = int(payload.get("done", 0) or 0)
            maximum = int(payload.get("max", 15) or 15)
            self.lbl_extra.configure(text=f"{done}/{maximum}", fg=TEXT)
            self._set_progress(maximum, done)

    def _append_log(self, level: str, line: str):
        self.log_text.configure(state=tk.NORMAL)
        at_bottom = self.log_text.yview()[1] >= 0.999

        if level == "SYS":
            tag = "sys"
        elif level == "ERROR" or "❌" in line:
            tag = "err"
        elif level == "WARNING" or "⚠️" in line:
            tag = "warn"
        elif "✅" in line:
            tag = "ok"
        elif level == "DEBUG":
            tag = "time"
        else:
            tag = "info"

        self.log_text.insert(tk.END, line + "\n", tag)
        if self.auto_scroll.get() and (at_bottom or self.log_text.yview()[1] >= 0.995):
            self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # 启动/关闭
    # ------------------------------------------------------------------
    def _auto_check(self):
        """启动时自动检测一次 Cookie（若有配置）。"""
        data = self._read_config()
        music_u = str(data.get("Cookie_MUSIC_U") or "")
        csrf = str(data.get("Cookie___csrf") or "")
        if music_u.startswith("YOUR") or not music_u:
            self._append_log("sys", "未检测到有效配置，请前往「配置」页签填写后保存。\n")
            return
        self._load_config_form()
        self.lbl_account.configure(text="检测中...", fg=WARN)
        self.lamp.configure(text="● 检测中", fg=WARN)
        if self.manager.validate_async(music_u, csrf):
            self._set_busy(True, "正在检测 Cookie...")

    def _on_close(self):
        if self.manager.busy and not messagebox.askyesno(
                "确认退出", "任务正在运行中，确定要退出吗？\n（运行中的任务将被中断）"):
            return
        self.destroy()
