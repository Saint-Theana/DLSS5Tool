# 主题切换打磨（2026-10-08）

范围：源码 UI；不打包、不升版本、不更改渲染算法或用户正式设置。

同日后续：工作区顶部提示已替换为底部状态栏常驻模式标记，见
[模式标记优化](MODE_BADGE_20261008.md)。下文保留前一轮换肤修复记录。

## 问题与修改

- 截图中的深浅拼块有对应的可复现路径：`_apply_ui_theme` 先更新 ttk／实时页面，随后调用
  `update_idletasks()`，本地 Canvas、自绘按钮、滑块和状态栏尚未更新时即执行绘制回调。
  新增测试在旧实现上捕捉到了新旧调色板混合状态。
- 移除换肤中途的 idle 刷新；所有客户区控件在同一事件循环回合更新，最后处理主窗口、
  分离预览窗口的原生标题栏与模式按钮。沿用启动阶段已有的标题栏重试，不强制泵送事件。
- 已处于 `clam` 时不再重复 `theme_use('clam')`；只配置颜色，减少额外的主题选择通知。
- 取消 180 ms 的整页滑动遮罩。模式提示始终固定在工作区顶部，文字／边框首尾各约
  160 ms 淡入淡出，总寿命仍为 900 ms；系统动画关闭时淡入淡出缩短为 120 ms。
  不截图、不调窗口透明度、不移动或重建工作区，不给视频内容加动画。
- 连续切换取消旧提示与定时器，并用代次标识拒绝旧回调；隐藏、悬停、关闭、创建失败、
  手动换色仍清理提示。`cover` 空字段和 `direction` 可选参数仅保留调用／探针兼容。
- 保留实际切换模式即反转当前主题、同模式不重复切换、创建失败回滚、媒体／队列／草稿保留、
  模式切换不自动启动或停止捕获等规则。

## 验证

复用 `.venv`；TEMP/TMP 指向 `tmp/theme-switch-20261008`，关闭自动更新检查。

- `tests.test_workbench_transition tests.test_workbench_ui`：35 项通过（82.291 s）。
  包含 6 项新增回归：idle 回调不可看到半更新、主／分离窗口标题栏最后换色、
  不重复选择 ttk 主题、常规动画也只显示静止提示、旧回调隔离、隐藏后不揭示提示。
- `tests.test_gui_player`：78 项通过（16.710 s）。
- `tests.test_realtime_ui`：独立进程 34 项通过（43.628 s）。
- `tests.test_caption_button`：按应用实际启动方式先执行 `ui_theme.enable_dpi_awareness()`，
  10 项通过（3.355 s）。直接运行该模块、未启用进程 DPI 感知时，当前桌面上原生边界相关
  用例出现 5 失败／1 错误；正常桌面重试亦如此，不能归因于沙箱。补齐应用已有的 DPI 启动
  前置条件后通过；未改标题栏产品代码、测试断言或系统显示设置。PNG 色彩配置警告不影响结果。
- 共 157 项相关测试通过，未声称全仓测试通过。
- 中文 10 秒隔离探针：`--mode realtime --theme dark --cycle`，结束为实时／浅色，
  `transition_finished=true`、`caption_visible=true`、`caption_error=null`、
  `callback_errors=[]`；载入 157 个效果／33 个参数控件，会话未运行，未提供捕获目标。
- 额外英文／减少动画的可见探针未获授权，未运行；对应静止提示行为已有自动回归，
  不将其等同于英文桌面视觉验收。最终视觉节奏仍由用户确认。
- `git diff --check` 通过。

重建命令（各模块可分进程运行）：

```powershell
$env:TEMP='F:\project\DLSS5Tool\tmp\theme-switch-20261008'
$env:TMP=$env:TEMP
$env:DLSS5TOOL_DISABLE_UPDATE_CHECK='1'
.venv/Scripts/python.exe -B -m unittest tests.test_workbench_transition tests.test_workbench_ui
.venv/Scripts/python.exe -B -m unittest tests.test_gui_player
.venv/Scripts/python.exe -B -m unittest tests.test_realtime_ui
.venv/Scripts/python.exe -B -c "from dlss5tool import ui_theme; ui_theme.enable_dpi_awareness(); import unittest; unittest.main(module=None, argv=['unittest', 'tests.test_caption_button'])"
.venv/Scripts/python.exe -B scripts/workbench_ui_probe.py --seconds 10 --mode realtime --theme dark --language zh_CN --cycle --work-dir tmp/theme-switch-20261008
```

## 空间与收尾

F 盘开始可用 96,315,387,904 字节（约 89.7 GiB）；新增峰值预算小于 10 MiB。
未构建、下载、复制依赖、生成大文件；测试夹具自动清理。
隔离探针的两份配置和扫描日志均可由上述命令重建，不含用户媒体。已确认测试／探针退出、
精确路径位于本任务目录内、目录与文件均非链接，且没有产品代码依赖后，删除这 3 个文件
及空的 native/logs 目录：文件共 27,195 字节，删除前后磁盘可用空间实测增加 28,672 字节。
仅保留小于 2 KiB 的 `TASK.md` 记录至 2026-10-15 复核；旧依赖、备份与非本任务文件不动。
