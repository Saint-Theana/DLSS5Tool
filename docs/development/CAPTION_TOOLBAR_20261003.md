# 标题栏切换入口与播放器布局

日期：2026-10-03。范围：源码 UI 优化，不构建发行包、不启动游戏捕获、不变更渲染算法。

## 当前设计

- 移除第一版工作台独立的顶部模式栏。最小化按钮左侧显示双向箭头，单击立即切换「本地媒体 ↔ 实时增强」，不再弹出选择菜单；实时模式增加强调色标识。悬停说明当前模式和目标模式。
- 不替换 Windows 窗框或原生最小化／最大化／关闭按钮。按钮使用归主窗口所有的微型原生 BUTTON 绘制表面，不额外出现在任务栏／Alt-Tab 中、不置顶、不激活，无独立工作台。全屏、最小化、主窗口隐藏／禁用或无安全空间时隐藏；保留 `Ctrl+Tab` 和「更多 → 工作模式」。
- 实时状态及停止按钮移入现有底部状态栏，只在会话有效时显示；在本地模式仍可停止实时会话。切换本身不启动或停止捕获，不清除媒体、队列或参数草稿。
- 播放器按控件自然宽度计算单行所需空间，取消固定 1000 像素断点。空间够时恢复单行，窄窗口分组换行，不删控件或缩小字体；主预览和分离预览共用逻辑。

## 实现与回归保护

- `dlss5tool/caption_button.py`：DWM 标题按钮边界、DPI、负坐标、Win32 subclass 生命周期、客户端绘制。原生回调只绘制／入队，Tk 主循环处理直接切换及提示；Tk 全屏切换重建 HWND 后重新挂载。
- 回调通过弱引用访问对象，避免 ctypes 回调强引用环导致 Tk 对象在工作线程回收。早期全量测试曾出现 Tcl 线程退出异常，修正后全量通过。
- 标题栏不再创建菜单。按下／释放仅在有效点击时排入一次切换，拖出按钮后松开不切换；保留标准按钮的可访问性调用入口。
- 播放器只测量方向不变的子组，避免换行后尺寸反过来导致布局反复切换；Configure 合并到一次 idle 调整。
- 新增 `tests/test_caption_button.py`，扩展播放器和工作台测试。涵盖原生 HWND 安装／清理、最大化／最小化／全屏往返、菜单与快捷键、会话保持、窄宽布局往返。

## 首版验证记录（已被用户截图揭示不足）

- 首版全量 `unittest discover -s tests`：781 项，10 项跳过，141.254 秒，通过；包含当时的菜单生命周期回归。此前弱引用修正后另一次全量 780 项亦通过。此结果只证明逻辑和 HWND 生命周期，不证明 DWM 最终显示。
- 隔离浅色本地界面运行 10 秒：`caption_installed=true`、`caption_rect=[841,0,887,30]`、`caption_error=null`、`callback_errors=[]`，正常关闭；无可选捕获目标，设置和队列隔离。
- 探针所在桌面的默认最大宽度将请求的 1260 像素限制为 1028，播放器正确采用两行；自动测试显式设置足够 maxsize，在 1260 主窗口／930 分离预览验证单行，在 600 分离预览验证换行。
- `git diff --check` 通过。
- 桌面检查工具初始化失败（kernel assets 路径错误，重置后重试仍失败），未完成图标像素外观、实际鼠标点击或拖拽验收；没有将 HWND 或合成消息测试当作截图／真实点击验收。

## 复现与空间

### 用户空白截图后的修正

- 用户反馈第一版新增标题栏位置只显示空白。旧实现使用 `GetWindowDC` 写入 Windows 管理的非客户区并周期重画，无法仅凭 HWND 安装成功证明最终合成显示；该路径已全部移除。微软的 [DWM 绘制建议](https://learn.microsoft.com/en-us/windows/win32/dwm/bestpractices-ovw)也建议避免在非客户区直接绘制。
- 新按钮用 `WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE` 的 owned BUTTON 表面，在客户端 `WM_PAINT` 中画完整背景和矢量箭头；不修改主窗 DWM 绘制策略，不拦截其标题栏绘制／命中测试。owner 的位置消息同步按钮位置；不通过全局置顶来维持位置。窗口归属与合成方式参考 [Window Features](https://learn.microsoft.com/en-us/windows/win32/winmsg/window-features)。
- 按最新要求，标题栏点击改为直接切换，不弹菜单；`更多 → 工作模式` 保留为可读文字入口。切换仍不启动捕获、不清空工作状态。
- 新增验证：实际收到 `WM_PAINT`；将自身 `WM_PRINTCLIENT` 输出画入内存 DIB，断言浅／深主题、本地／实时及悬停组合均有前景像素而不是空白，并核对背景像素；核对 popup owner、非激活／非任务栏／非置顶样式；检查移动、隐藏、禁用、全屏恢复及释放到按钮外不会切换。
- 首轮针对性 20 项通过；补充主窗口禁用测试后全量 785 项、10 项跳过，145.921 秒通过。一次事件切换一次、两次切换返回本地、不会弹菜单和自动捕获均有回归测试。
- 浅色本地工作台隔离运行 10 秒正常退出：`caption_installed=true`、`caption_surface=true`、`caption_visible=true`、`caption_error=null`、`callback_errors=[]`。未提供捕获目标，未操作用户正在运行的实例。
- computer-use 技能指定的桌面工具重新初始化／重置后仍报 `failed to write kernel assets`（路径错误），没有绕过工具抓取桌面。离屏绘制测试不是最终桌面合成截图，也不是实际鼠标点击验收；真实视觉仍待用户重启后确认。

### 任务空间

复用已有 `.venv`，先将当前进程的 TEMP/TMP 指向 `tmp/caption-display-fix-20261003`：

```powershell
.venv/Scripts/python.exe -B -m unittest discover -s tests
.venv/Scripts/python.exe -B scripts/workbench_ui_probe.py --seconds 10 --mode local --theme light --geometry 1000x680+0+0 --work-dir tmp/caption-display-fix-20261003
```

任务登记见 `tmp/caption-toolbar-20261003/TASK.md`；预算 30 MiB，复核日 2026-10-10。
开始时 F 盘约 89.66 GiB 可用、tmp 约 29.285 GiB，已超过预警线；不复制依赖、不生成大文件、不清理其他任务目录。

交付清理：隔离探针正常退出后，核实路径、引用及非链接属性，删除本任务两份可重建配置
`probe-settings.json`／`probe-queue.json`（共 2802 字节）；F 盘前后可用空间增加 4096 字节。
测试临时目录自行回收，本任务目录只保留不足 2 KiB 的 `TASK.md` 供复核；其他任务资产未清理。

空白修复另登记在 `tmp/caption-display-fix-20261003/TASK.md`，同样预算 30 MiB、2026-10-10 复核。
本轮两份隔离配置也已删除（2802 字节，可重建），磁盘实测释放 4096 字节；仅留不足 2 KiB 的登记。
