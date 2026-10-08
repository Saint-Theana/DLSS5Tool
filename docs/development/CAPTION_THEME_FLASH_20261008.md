# 标题栏切换按钮文字闪现（2026-10-08）

## 原因与修复

用户截图中标题栏模式按钮短暂显示「切换到本地媒体」的一部分。
原实现创建普通 Win32 `BUTTON`，保留模式切换文案作为可访问名称，
只接管 `WM_PAINT` / `WM_PRINTCLIENT` 图标绘制。
`SetWindowTextW` 更新模式名称时，标准按钮过程会同步重绘文字与按钮边框，
直到下一次自绘才恢复图标。模式切换同时反转主题，所以用户在换肤瞬间看到这次重绘。

改用 `BS_OWNERDRAW`，只处理属于本按钮的 `WM_DRAWITEM`，复用现有 GDI 图标绘制。
模式名称仍供可访问工具读取，悬停说明和模式切换功能保持可用。
主题更新也关闭旧的悬停说明，避免沿用上一主题颜色。
其他窗口与原生标题栏按钮的绘制不受这段处理影响。

Windows 自绘按钮的通知机制参见
[Microsoft 自定义控件文档](https://learn.microsoft.com/en-us/windows/win32/controls/user-controls-intro)。

## 验证

- 新增回归直接读取本应用按钮 HWND 的像素：更新模式文字后立即检查，不泵送下一轮绘制。
  修复前在浅色／实时模式出现多种系统文字和边框颜色，图标色与背景色缺失，测试失败。
  修复后明暗主题、两个模式均只出现预期图标与背景颜色，可访问名称仍正确。
- 按应用正常启动前置条件启用 DPI 感知后，`tests.test_caption_button` 共 11 项通过（6.326 秒）。
  包含按钮生命周期、窗口位置、最小化／全屏、点击、原有离屏图标检查与瞬时重绘检查。
- 应用级的标题栏点击切换、换肤中途不绘制半更新配色、连续模式切换三个已有回归通过
  （7.927 秒）；共 14 项相关测试通过，`git diff --check` 通过。

复用已有 `.venv`；TEMP/TMP 指向 `tmp/caption-theme-flash-20261008`。
开始可用空间 96,165,134,336 字节，新增峰值预算小于 10 MiB。
仅验证源码 UI，不创建发行包或复制运行依赖。
测试进程已结束，夹具已清理；核实精确任务路径与目录没有链接后删除任务目录，
剩余临时占用为 0，无保留文件。

```powershell
$env:TEMP='F:\project\DLSS5Tool\tmp\caption-theme-flash-20261008'
$env:TMP=$env:TEMP
$env:DLSS5TOOL_DISABLE_UPDATE_CHECK='1'
.venv/Scripts/python.exe -B -c "from dlss5tool import ui_theme; ui_theme.enable_dpi_awareness(); import unittest; unittest.main(module=None, argv=['unittest', 'tests.test_caption_button'])"
```
