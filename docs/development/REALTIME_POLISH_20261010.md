# 实时工作台细节与任务栏图标（2026-10-10）

## 范围

按用户确认的建议落地，继续保留已有工作树。左栏默认宽度、拖动与手动宽度记忆不改。
不修改 shader、参数范围、预设格式、原生增强引擎或版本号；不打包、提交、推送或发布。

## 用户可感知变化

- 分隔线改为 1 像素细线，悬停／拖动／键盘聚焦时 2 像素高亮；拖动热区仍至少 6 逻辑像素。
- 待机运行工具折成一行，输出确认后自动展开；手动收起不会被同次运行的遥测反复打开。
  启动中、停止中或恢复中仍禁用输出工具，停止操作仍固定可达。
- 输出设置入口与标题同排，常规说明移到帮助；不兼容选项自动调整时仍明确告知。
- 手动检查移到「高级 → 运行库与诊断」，开始／确认重启仍自动检查；问题显示在左栏并可定位。
- 未选择来源时禁用开始按钮。待机不显示两段性能说明，当前会话有数据后再显示运行详情；
  新会话不会把上次详情当作当前数据，指标含义保留在帮助中。
- 运行工具明确命名为原图对比、画面内调参、画面内统计、保存增强截图，并补充用途帮助。
- 普通快捷键冲突改为短提示＋详情，完整信息继续写日志；紧急停止不可用单独提示。
  实时日志为四行紧凑高度，原开关记忆／持续记录不变，原生错误与快捷键警告分色。
- 常用参数首次默认展开，保留手动收起；多遍标题去掉与开关重复的状态文字。
  「N 项非默认」与待应用分离，撤销操作显示作用范围。

## 图标原因与修复

原 Windows 分支只调用 WM_SETICON，跳过 Tk 的默认图标注册；即使调用
`apply_app_icon(root, default=True)`，默认／窗口类图标仍未同步。
现在每个解释器只向根窗口注册一次 `iconbitmap(default=...)`，同时保留原有清晰的分尺寸图标。
窗口重新映射后补设原生图标；按 DPI 缓存原生句柄，根窗口关闭时统一释放，避免主题刷新销毁
分离窗口正在借用的图标。不会对每个子窗口重复加载整组 Tk 默认图标。

机制依据：[Tk wm 文档](https://www.tcl-lang.org/man/tcl8.6/TkCmd/wm.htm) 的默认图标语义，
以及 [Tk Windows 窗口管理实现](https://github.com/tcltk/tk/blob/core-8-6-branch/win/tkWinWm.c) 中
`WinSetIcon` 对默认窗口类图标和单窗口图标的区分。

验证不只检查返回值：新进程实际读取默认大小图标句柄，确认注册后已替换默认图标，后建窗口
继承相同窗口类图标；另检查最小化恢复、主题切换、25 次分离窗口创建／销毁的资源占用。
没有清除用户图标缓存、修改固定快捷方式或终止用户正在运行的应用。

## 验证

复用 `.venv`，不生成字节码，TEMP/TMP 使用本轮任务目录：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:TEMP='F:\project\DLSS5Tool\tmp\realtime-polish-20261010'
$env:TMP=$env:TEMP
.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_realtime*.py' -v -f
.venv\Scripts\python.exe -m unittest -v -f tests.test_workbench_ui tests.test_workbench_memory tests.test_app_icon tests.test_i18n
.venv\Scripts\python.exe -m unittest -v -f tests.test_app_icon
```

- 工作台／设置记忆／国际化／图标组合：64 项通过，203.615 秒（此时图标用例 14 项）。
- 新增真实窗口类默认图标断言后，图标完整 15 项通过，最终 4.735 秒。
- 细节／启动检查／撤销命名定向复测：27 项通过，87.736 秒。
- 完整实时回归：264 项通过，532.608 秒，退出码 0。
- 最终不同测试用例共 329 项（264＋64＋新增的 1 项图标用例）；27 项定向及其余图标复测不重复累计。
- Python AST、重复方法、双语 JSON 重复键检查通过；`git diff --check` 通过。
  原有 CRLF 文件只提示正常换行归一化。

前置图标断言在修复前失败（默认注册调用次数为 0），修复后通过。
首轮实时回归在旧版「撤销必须是纯图标」断言处停止，已改为验证图标＋作用范围文字。
对应分隔线色块、手动检查位置的旧布局断言也按明确需求更新，安全／同步断言保留。

## 可视检查

使用 computer-use 查看隔离模拟窗口；引擎、窗口枚举与截图作业均替换为模拟实现。
通过 `--no-screenshot` 禁用探针自身的截图，由界面工具返回有界窗口图像：

```powershell
.venv\Scripts\python.exe scripts/realtime_panel_probe.py --work-dir tmp/realtime-polish-20261010 --language zh_CN --theme dark --geometry 1280x960 --full-catalog --no-screenshot --hold-seconds 240 --startup-timeout 30
.venv\Scripts\python.exe scripts/realtime_panel_probe.py --work-dir tmp/realtime-polish-20261010 --language en_US --theme light --scenario running --geometry 1280x960 --full-catalog --no-screenshot --hold-seconds 180 --startup-timeout 30
```

隔离执行环境的窗口不在当前桌面窗口列表内；终止两次本任务的隔离探针后，获准在桌面启动
模拟窗口，再完成中文深色待机与英文浅色运行页的实际截图检查。两次可见探针退出码均为 0，
`callback_errors=[]`、`native_started=false`，分界与开始／停止区域可达，产品标题栏图标可见。
待机左栏无滚动溢出；英文运行时左栏按需滚动，固定底部不被挤走。

截图在会话中返回，未另存本地图片。未进行真实游戏捕获、原生增强／GPU 兼容验证；
未重新构建 EXE，也没有单独捕获 Windows 任务栏，因此不声称已验收用户固定快捷方式的缓存。

## 临时目录

`tmp/realtime-polish-20261010/`：开始可用 94,811,103,232 字节，预计峰值 <100 MiB。
配置／队列仅由本轮模拟探针生成，可用上述命令重建。已确认探针和回归进程退出、目标无链接、
脚本与源码不依赖生成配置后，仅删除 `settings.json`（2,824 字节）与 `queue.json`（35 字节）。
这两个文件不经过回收站，可按探针命令重新生成；用户设置、旧任务目录和持久依赖未动。

清理前 F 盘可用 94,810,533,888 字节，清理后 94,810,537,984 字节，实测增加 4,096 字节。
测试临时目录已自行清理；仅保留不足 2 KiB 的 `TASK.md` 审计记录，以及工具运行期间出现的
`sogou_log_temp/APP`、`sogou_log_temp/IME` 空目录（无文件，0 字节文件内容）。
这些输入法命名目录的归属不明确，未擅自删除。复核日期为 2026-10-17，不是自动删除日期。
