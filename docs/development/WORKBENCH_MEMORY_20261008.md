# 工作区模式与主题记忆（2026-10-08）

## 范围与结论

- 用户反馈的左侧示意图是归一化保护区域编辑器，不是源窗口实时预览。
  拖动会写入最多四个矩形并提交 quality；原生 `host.cpp` 将这些坐标传给残差合成器。
  `NrProtection.hlsli` 计算固定区域/向内羽化，`NrResidualComposite.hlsl` 在完全保护处输出
  NR 合成前的 base，羽化处降低 NR 改变量。它不自动识别或跟踪字幕/HUD，也不屏蔽其他效果。
- 因为没有源画面底图，定位不直观、默认占据主区域过大。建议移入「保护」页按需展开；
  本次只核实用途，未改该布局，未新增捕获、截图或预览管线，未执行 GPU 画质验收。
- 主题原本已保存，但启动硬编码为 local；用户切回 realtime 又触发现有主题反转，
  因而无法恢复退出前的模式/主题组合。

## 实现

- 设置新增 `workbench_mode`，默认 local，合法值 local/realtime；旧配置及非法值回退 local。
- 在共享 UI 构建完成后恢复工作区，沿用保存的 `ui_theme`，不反色、不重绘整套主题、
  不播放切换高亮、不因恢复动作额外保存设置；标题栏按钮与常驻状态标记同步。
- 手动切换的主题反转、同模式不重复切换、草稿/媒体保留规则不变。
- 模式与主题沿用设置的原子写入、300 ms 防抖和正常关闭时立即保存。
  恢复实时页仅初始化其 UI/目录查询，不自动开始捕获或增强；创建失败保留本地页和保存的主题。
- 恢复实时模式时，记忆的分离预览窗口创建后保持隐藏；提示条位于工作区容器中，
  仅本地模式显示。修复在本地布局已隐藏时插入提示条导致的 Tk pack 错误。
- 用户指南补充启动记忆，并校准当前模式标记的说明；不改版本号、不打包、不动用户正式配置。

## 验证与复现

复用 `.venv`；隔离设置/队列/实时会话，模拟原生客户端，无真实增强会话。

```powershell
$env:TEMP='F:\project\DLSS5Tool\tmp\workbench-memory-20261008'
$env:TMP=$env:TEMP
$env:DLSS5TOOL_DISABLE_UPDATE_CHECK='1'
.venv/Scripts/python.exe -B -m unittest tests.test_workbench_memory tests.test_workbench_transition
.venv/Scripts/python.exe -B -m unittest tests.test_workbench_ui
.venv/Scripts/python.exe -B -m unittest tests.test_gui_player
.venv/Scripts/python.exe -B -m unittest tests.test_realtime_ui
```

新测试覆盖四种模式/主题组合退出重开、防抖结束前关闭、首次/旧版/非法配置、
可见启动无反色高亮/无额外设置保存、实时页创建失败回退、分离预览与提示条隐藏/恢复。

- `tests.test_workbench_memory tests.test_workbench_transition`：17 项通过（23.536 s）。
- `tests.test_workbench_ui`：26 项通过（51.078 s）。
- `tests.test_gui_player`：78 项通过（10.024 s）。
- `tests.test_workbench_memory tests.test_realtime_ui`：44 项通过（64.897 s）；
  含再次执行的 8 项启动记忆测试及最后补充的标题栏模式同步断言。
- 合计 157 项不重复测试通过；`git diff --check` 通过。既有 libpng 色彩配置警告仍存在。
  最终运行没有 Tk 回调错误；未声称全仓测试或 GPU 保护效果验收通过。

## 空间与收尾

F 盘开始可用 96,299,069,440 字节（约 89.69 GiB），预算 < 30 MiB；复用 `.venv`，
没有下载、打包或复制大依赖。测试夹具由 TemporaryDirectory 自动回收，没有额外手工删除。
自动回收未逐项计量磁盘释放量，不把其他进程导致的磁盘波动作为清理收益。
任务目录仅保留不足 2 KiB 的 `TASK.md` 作为用途/复现记录，2026-10-15 复核；旧依赖和备份不动。

重新通过 `run.bat` 启动源码后生效。旧配置尚无工作模式字段时仍首次进入本地，选择一次模式后
即开始记忆；已运行的旧进程不会热加载修改。未重新构建 EXE。
