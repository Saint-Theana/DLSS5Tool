# 实时分界与滚动修正 · 2026-10-08

## 问题与处理

用户截图中的竖条是左侧内容滚动条，不是分界拖动手柄。原实现始终显示滚动条，
并把滚动范围直接设为内容边界；内容短于视口时，Tk 可在滚动或改变尺寸后保留负原点，
使内容上方留白，看起来无法有效滚动。

- 左侧及右侧各页仅在实际内容高度超过视口时显示滚动条；内容能完整显示时隐藏并回到顶部。
- 滚动范围至少覆盖视口，避免滚动／缩放后出现顶部空白；溢出时保留滚动位置与滚轮操作。
- 中间新增可拖动分界，使用与本地模式一致的左右调整光标；悬停或键盘聚焦时高亮。
- 双击分界恢复自动布局；Tab 聚焦后，左右方向键每次微调 16 个逻辑像素，Home 复位。
- 通常保留左侧至少 320、右侧至少 360 个逻辑像素；窗口过小时按可用空间安全限制。
- 手动宽度在本次打开期间保留，切换模式不重置；缩小窗口时暂时限制宽度，放大后恢复。
  未新增跨启动持久化设置，不改本地模式分界宽度。
- 拖动仅改变布局，不重建参数控件、不丢失未完成输入、不提交草稿或重启实际增强。

## 代码范围

- `dlss5tool/realtime_ui.py`：自动隐藏滚动条、视口原点归位、分界拖动及宽度限制。
- `locales/zh_CN.json`、`locales/en_US.json`：分界悬浮提示；不增加常驻帮助文字。
- `tests/test_realtime_layout.py`：新增五项滚动、拖动、限制、主题与保留草稿测试。
- `scripts/realtime_panel_probe.py`：可指定手动宽度、展开预设，报告滚动条、原点与分界状态。
- `docs/REALTIME_USER_GUIDE.md`：补充操作说明。

未修改原生渲染／捕获逻辑，未启动真实增强，未打包 EXE、提交或发布。

## 验证

布局测试 20 项通过；包含五项新增用例：
不溢出隐藏并顶对齐、溢出滚动后折叠／放大归位、真实 Tk 指针事件拖动且不提交、
极端拖动与缩窗保护、键盘调整／复位及深浅主题。

相关界面、启动检查、效果控件、工作台切换及中英文测试另 122 项通过，合计 142 项（不累计重复运行）。
Python AST、中英文 JSON、改动文件空白检查和 `git diff --check` 通过；既有 libpng 配置警告不影响结果。

隔离探针串行验看三种布局，均无回调错误、`native_started=false`：

| 场景 | 结果 |
| --- | --- |
| 中文深色 1920×1240 | 左右内容都完整显示；左侧滚动条隐藏，原点偏移 0，分界可见 |
| 英文浅色，展开预设并放大右侧 | 左侧需要滚动时显示滚动条；原点偏移 0，启停保留可见 |
| 中文深色，待重启并缩小右侧 | 两侧滚动正常，停止与重启确认可见 |

```powershell
$env:TEMP='F:\project\DLSS5Tool\tmp\realtime-splitter-20261008'
$env:TMP=$env:TEMP
$env:DLSS5TOOL_DISABLE_UPDATE_CHECK='1'
.venv\Scripts\python.exe -B -m unittest tests.test_realtime_layout
.venv\Scripts\python.exe -B -m unittest tests.test_realtime_ui tests.test_realtime_readiness tests.test_realtime_effects tests.test_workbench_ui tests.test_realtime_i18n tests.test_i18n
.venv\Scripts\python.exe -B scripts/realtime_panel_probe.py --work-dir tmp/realtime-splitter-20261008 --scenario idle --theme dark --geometry 1920x1240
.venv\Scripts\python.exe -B scripts/realtime_panel_probe.py --work-dir tmp/realtime-splitter-20261008 --scenario idle --theme light --language en_US --expand-presets --inspector-width 680
.venv\Scripts\python.exe -B scripts/realtime_panel_probe.py --work-dir tmp/realtime-splitter-20261008 --scenario restart --theme dark --inspector-width 440
```

截图仅来自探针自身窗口；模拟会话不代表实际游戏输出验收。
临时目录为 `tmp/realtime-splitter-20261008`，预算小于 20 MiB；复用 `.venv`，不复制依赖。

验收后已清理三个截图及两个隔离配置，共 424,005 字节；删除前核实确切路径、无链接、
无业务引用与相关测试进程已退出。F 盘可用空间从 96,297,418,752 增至 96,297,852,928 字节，
观测释放 434,176 字节。产物可由上述命令重建，不改真实用户配置。
剩余文件仅不足 2 KiB 的 `TASK.md`；另保留输入法产生的两个空子目录（无文件），
避免擅自清理第三方目录。登记用于追溯，2026-10-15 复核。

## 拖动卡顿定点诊断（未修改产品行为）

用户反馈拖动不流畅，并要求小改不再重复完整启动／模式切换验收。
只使用 `scripts/realtime_drag_probe.py` 中的单个模拟实时面板，没有创建完整 App、
启动实际增强、采集截图或运行全套回归。

最终一次测量（1280×800，固定模拟参数，12 步；仅冷路径附带 cProfile）：

| 路径 | 单步耗时中位数 | 单步最大值 |
| --- | ---: | ---: |
| 分界，首次经过这些宽度 | 491.67 ms | 676.88 ms |
| 分界，再次经过相同宽度 | 450.61 ms | 1027.10 ms |
| 左侧竖向滚动 | 16.82 ms | 41.68 ms |

这是此机器中包含 Tk `update_idletasks()` 的布局完成耗时，不是实际游戏帧率或通用性能承诺。
模拟客户端没有启动或发送命令。脚本最终正常退出；首轮诊断脚本在错误的 Tk owner 上取消计时器，
引发退出清理错误，已改为在注册计时器的 `ui.window` 上取消，不涉及产品代码。

当前 `_splitter_move` 每次鼠标移动都立即设置 inspector 宽度，两侧原生子窗口布局、
文字换行、滚动范围同步及自绘控件随之更新。冷路径 12 步中，按钮 Configure 回调 165 次、
按钮重绘 55 次、圆角绘制 121 次、折叠标题重绘 88 次；圆角绘制累计约 333 ms，
仅是 5672 ms 总耗时的一部分，不能把全部延迟归因于圆角或缓存。
重复宽度仍慢，说明仅靠现有图片缓存或鼠标事件节流不足以保证跟手。

最小范围建议：拖动期间只更新轻量分界预览线，释放时提交最终宽度并完成一次整块重排；
保留原宽度边界、键盘调整、双击复位与草稿。若要求两侧内容始终实时跟随缩放，
需要进一步优化原生布局和多类控件绘制，不能冒充仅加 16 ms 节流就已解决。

本轮仅诊断，产品代码未改；后续修正只需定点验证拖动、释放最终位置、宽度限制和关闭清理。
临时夹具已自动清理，无截图、配置或性能转储遗留；`tmp/realtime-drag-profile-20261008`
仅保留不足 2 KiB 的任务登记，2026-10-15 复核。可用以下命令重建测量：

```powershell
$env:TEMP='F:\project\DLSS5Tool\tmp\realtime-drag-profile-20261008'
$env:TMP=$env:TEMP
$env:DLSS5TOOL_DISABLE_UPDATE_CHECK='1'
.venv\Scripts\python.exe -B scripts/realtime_drag_probe.py
```

## 轻量预览优化已实施（用户确认后）

- 拖动时仅移动 `place` 覆盖的细预览线，不改变两侧控件尺寸、不参与父容器布局。
- 鼠标释放时采用最后的指针位置，一次提交宽度；仅点击不移动不改变自动布局。
- 预览与最终宽度使用同一限制。Esc、失焦、隐藏工作区、窗口尺寸变化或关闭时撤销未确认拖动并清理预览；释放后不会误提交已取消的拖动。
- 保留双击／Home 复位和左右方向键调整；深浅主题提示与用户指南已更新。没有修改公共控件绘制或原生增强。

遵照用户要求，只运行分界相关 6 项测试（`tests.test_realtime_layout -k splitter`），全部通过；
覆盖移动期间不提交宽度／不重建草稿、释放最终位置且只提交一次、边界／取消、隐藏及关闭清理、
原有缩窗限制／手动宽度恢复、键盘／复位／主题。语法及两个语言 JSON、空白检查通过。
未重跑完整 App 启动、模式切换、截图或整套回归。

同一个 1280×800 隔离探针复测（12 步，首次路径附带 cProfile）：

| 路径 | 中位耗时 | 最大耗时 |
| --- | ---: | ---: |
| 首轮预览线移动 | 2.59 ms | 14.98 ms |
| 再次移动 | 6.79 ms | 17.29 ms |
| 竖向滚动 | 7.74 ms | 13.77 ms |

移动期间两侧宽度保持不变；释放后的最终重排仍耗时 376.32 ms，只发生一次，
本次并未解决所有控件的重排成本。旧实现拖动中位 450～492 ms 与新测量使用相同模拟面板，
这些数字仅为本机定点结果，不代表所有硬件的保证。
模拟客户端仍为 `native_started=false`、发送命令 0。

复用上一节命令时将 TEMP/TMP 改为 `tmp/realtime-drag-preview-20261008`。
该目录预算 <1 MiB，夹具临时配置自动清理，无截图／性能转储，仅保留任务登记追溯，2026-10-15 复核。
