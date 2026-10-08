# 双模式诊断导出与效果说明（2026-10-04）

## 本次范围

- 统一本地／实时诊断导出，默认轻量快照；原有本地 GPU 检测保留为显式「深度检测并导出」。
- 效果候选新增用途分类、用途搜索、当前候选与链内效果说明，中英文同步。不删除效果，不修改原生渲染行为。
- 核查并显示现有 NR DLL 选择来源；没有实现显卡代际自动匹配、DLL 下载、试加载排名或自动替换。
- 未构建、打包、发版或上传；保留本任务开始前的所有工作树修改。

## 诊断行为

`support_diagnostics.py` 负责两种模式共用的报告写入。本地「更多」「关于」及嵌入式实时工作台委托同一入口；独立实时 UI 保留自己的按钮并复用写入器。

- 主线程只获取界面快照，后台线程读取限量原生日志并写报告。轻量模式不调用旧 GPU 探针，也不创建共享引导缓存池。
- 实时草稿与运行配置分开保存：即使数值框尚未填完，也不通过 `collect()` 验证或应用草稿。
- 错误、生命周期、普通日志独立限量保留，遥测只留最新值。报告显示省略数量；不把内存环形记录当作完整历史日志。
- 固定读取 `realtime.log` 及 `.1/.2/.3` 的尾部，各最多 256 KiB；不递归扫描日志目录，拒绝被检查路径中的链接／目录联接。
- 默认路径脱敏与已知窗口标题隐藏，不包含画面、不上传；保留文件名和错误码，仍提示分享前人工检查自定义文本。
- `.json` 使用结构化输出；`.log/.txt` 为本地化标题及结构化内容。通过同目录临时文件和原子替换保存；失败时保留原报告并清理自身临时文件。
- 深度检测须确认，且在确认／保存对话框前后检查导出、队列、后端切换、实时会话是否繁忙；检测期间阻止启动实时增强。它验证的是原有本地媒体后端，不是目标游戏捕获兼容性。

## DLL 核查结论

共同决策点为 `dlss5tool/mod_paths.py::runtime_info/runtime_path`：显式内置 → 有效手动路径 → 模块目录标准文件 → 唯一的已识别候选 → 内置回退；多个候选不猜选。返回值另包含缺失手动路径回退及多候选标志。

- 本地引擎 `dlss5tool/dlss_engine.py` 已调用同一 `runtime_path`，并非本次才得到的实时专属能力。
- 实时 `RealtimeClient.launch` 把 NR 路径传入 `DLSS5_REALTIME_NR_PATH`，特性目录另经 `DLSS5_REALTIME_RUNTIME_ROOT` 传入。新增报告记录这些启动时参数，但明确不将它们当作模块实际加载成功的证据。
- `scripts/prepare_realtime_build.py` 及 `third_party/realtime/magpie/src/Magpie.Core/DLSSNRFilter.cpp` 对应路径转交／加载，没有按 RTX 代际、驱动和版本综合选择兼容 DLL 的决策器。
- 实时工作台持有首次打开时的本地设置快照；本次如实提示修改本地 NR 选择后需重启应用，没有偷偷改动会话热切换行为。

## 效果说明依据

分类覆盖已安装效果目录及未分类第三方效果，保留 native ID。大量选项是 Anime4K、CuNNy、RAVU、NNEDI3 等算法家族的模型／质量变体，不是同数量的 DLSS 功能。

`FrameRate_Filter.hlsl` 是原生节拍控制入口，不能当作插帧；`DLSS_SR.hlsl` 的输入为捕获色彩，不具备游戏引擎原生深度。`native/realtime/host.cpp::unavailableReason` 仍限制本构建未提供的 XeSS、RTXVideo、FSR2/3/4 等后端。分类与帮助不改变这些限制；列入候选不证明 GPU、DLL 或目标游戏兼容。

## 定向验证

复用 `.venv`，`TEMP/TMP` 指向 `tmp/diagnostics-effects-20261004/`，Python 使用 `-B`。未执行全量回归，未实际启动深度 GPU 探针；涉及 native 的单元测试使用替身。

1. 67 项通过（35.689 秒）：

   ```powershell
   .venv\Scripts\python.exe -B -m unittest tests.test_support_diagnostics tests.test_realtime_inspector tests.test_realtime_ui tests.test_realtime_i18n tests.test_i18n
   ```

2. 90 项通过（34.382 秒）：

   ```powershell
   .venv\Scripts\python.exe -B -m unittest tests.test_workbench_ui tests.test_gui_player.WidgetSmokeTests.test_one_click_diagnostic_exports_in_background tests.test_about_dialog tests.test_support_diagnostics tests.test_diagnostics tests.test_realtime_i18n tests.test_mods_guidance tests.test_realtime
   ```

3. 收尾 7 项通过（7.363 秒）：`RealtimeInspectorTests` 的分类筛选不改链、非法草稿诊断无命令两个测试；`WorkbenchUiTests` 的保存对话框后复查忙碌、深度后台执行及解除保护、取消／失败恢复、隐藏实时会话快照、深度检测入口保护五个测试。后两项是改动后的复测；以上批次含重复测试，不作为唯一用例数相加。

覆盖后台线程、双模式快照、不触发 GPU 探针、日志限量与错误保留、脱敏、原子保存失败、深度检测复用和保护、中英文说明、现有 DLL 文件发现与 UI 交互。已跟踪修改文件通过 `git diff --check`（仅有既有 CRLF 转 LF 提示）。未声称完成像素截图验收、HDR／多 GPU 或真实游戏兼容性验证。

## 空间与清理

开始时 F 盘可用 89.66 GiB，既有 `tmp/` 约 29.45 GiB；本任务新增峰值预算 30 MiB，未复制依赖或模型。

收尾逐项验证任务目录内的 `npm-cache`、`node-compile-cache`，检查源码／脚本引用、活动进程及目录联接后，仅删除这两处本任务生成的可重建缓存；没有删除用户报告或既有依赖。删除逻辑体积 1,327,774 字节，盘可用空间前后净增 2,658,304 字节（包含文件系统分配差异），清理后 F 盘可用 96,270,893,056 字节。缓存不经回收站，可重新生成；任务目录只保留数 KiB 的 `TASK.md` 追溯记录，2026-10-11 复核。既有约 29.45 GiB 的临时目录依赖及备份未动。
