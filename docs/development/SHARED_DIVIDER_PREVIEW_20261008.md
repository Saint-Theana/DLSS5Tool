# 本地／实时共享分界预览 · 2026-10-08

## 范围与处理

本地模式采用与实时模式一致的轻量拖动：按下后显示预览线，移动期间不调整面板宽度，
释放时采用最后的指针位置，一次调整并保存。保留原有 320～480 逻辑像素限制及 DPI 换算。
Esc、失焦、隐藏工作区、工作区尺寸变化或关闭时取消；原地点按不保存。
没有修改画面内原图／增强对比分界，也没有新增本地模式键盘调宽或双击复位操作。

实时模式原来的普通 Tk 子 Frame 在嵌套 Canvas／ttk 子窗口上移动时，底层旧位置可能
没有补画，留下多条竖线。两种模式现共用 `dlss5tool/divider_preview.py`：Windows 使用
分层子窗口合成预览线；分层不可用时，仅对旧条带覆盖的嵌套控件发送局部 Expose 重绘。
不增加 Toplevel、全局置顶或鼠标抓取，不重排整个界面、不提交增强参数。

实现参考：[微软分层窗口说明](https://learn.microsoft.com/en-us/windows/win32/winmsg/window-features#layered-windows)、
[SetLayeredWindowAttributes](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setlayeredwindowattributes)。

## 定点验收

- `tests.test_divider_preview`：5 项通过，7.199 秒。使用未初始化完整 App 的小型夹具，
  检查移动期间宽度不变、释放最终位置且只保存一次、边界／取消／隐藏、DPI 换算。
- 像素用例覆盖分层与强制非分层后备路径，深浅主题、Canvas 和嵌套 ttk 控件。
  先确认采样点属于测试自身窗口，再读取实际合成像素；不使用会重新绘制的 PrintWindow。
  检查当前线实际可见、历史位置无残留、隐藏后恢复原像素、键盘焦点不变。
- `tests.test_realtime_layout -k splitter`：6 项通过，18.444 秒。保留实时释放／取消、
  宽度限制、草稿、键盘调整／复位及主题行为。独立用例合计 11 项，不累计重复运行。
- 4 个 Python 文件 AST、2 个语言 JSON、新文件空白及 `git diff --check` 通过；
  既有换行格式警告未处理，不修改无关文件。

同一实时面板探针中，首次／再次移动预览线的中位耗时为 1.62／1.53 ms，最大值为
5.50／4.26 ms。移动期间面板宽度不变，释放后的最终重排仍需 351.67 ms，只发生一次。
这是本机模拟面板测量，不是通用性能承诺；没有宣称解决全部控件重排成本。
模拟客户端 `native_started=false`、发送命令 0。

```powershell
$env:TEMP='F:\project\DLSS5Tool\tmp\shared-divider-20261008'
$env:TMP=$env:TEMP
$env:DLSS5TOOL_DISABLE_UPDATE_CHECK='1'
.venv\Scripts\python.exe -B -m unittest tests.test_divider_preview
.venv\Scripts\python.exe -B -m unittest tests.test_realtime_layout -k splitter
.venv\Scripts\python.exe -B scripts/realtime_drag_probe.py
```

遵照用户要求未重跑完整 App 启动／模式切换或全套回归，未运行真实捕获／增强，未打包 EXE。
复用 `.venv`；临时配置由夹具自动清理，没有保存截图或性能转储。
`tmp/shared-divider-20261008` 仅保留不足 2 KiB 的任务登记用于追溯，2026-10-15 复核。
没有手动删除其他临时内容，未计量或声称磁盘释放量。
