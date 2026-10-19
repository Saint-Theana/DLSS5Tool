# P0 失败回滚、错误持帧与内存准入修复 · 2026-10-19

## 状态

用户在 [P0/P1 复核](P0_P1_AUDIT_20261019.md) 后授权先修 P0。本轮三个缺口均已完成源码修复和定向验收；基于 v3.0.2 / `ab6ffc3` 的工作区继续开发，尚未打包或提交。
P1 的全链路选卡与 HDR 转换保持原待办。用户完整长视频、批量原始图片及整机异常仍需实际负载回验，不据小型探针宣称全部根因已消除。

## 1. 部分初始化回滚

- `ProcessSuperResolution` 在资源分配前初始化所有权字段；共享内存、NumPy view、Pipe、Process 创建、启动及握手均处于同一回滚区。
- 未交接的子 Pipe 端点也由父所有者负责关闭。清理先收敛子进程，再断开帧 view、关闭/解除共享内存，并释放 Process 对象的系统句柄。
- 关闭时 BrokenPipe 不再跳过等待/终止；子进程确认仍存活时保留帧所有权并报告失败，允许重试关闭。
- 普通 `_HostSession` 同时补齐未启动进程不能 join 的边界和子 Pipe 回滚，避免把同类缺口留在 NR 路径。

新用例覆盖输入/输出分配、view 创建、Pipe/Process 创建、start 和握手分别失败；失败异常栈保留期间也要求资源已释放。
另覆盖幂等关闭、broken pipe、终止/kill、尚未退出时禁止提前释放，以及 **6 次真实 spawn/Pipe/共享内存事务**（SDR/HDR 各三次）。后者使用模拟缩放 worker，不加载原生 DLL；各次退出码均为 0，父进程释放相应句柄和共享段。

## 2. 延迟错误不再拥有原始帧

新增 `deferred_error.ErrorSnapshot`，只保存错误类型、消息和文本 traceback，不保存原异常的 args、cause/context、定制属性或执行帧。

- `RenderSession.error` 对外每次返回一个新异常；失败线程结束时即可回收其帧，关闭 session 后清空错误数据。
- `LatestPreviewJob` 和共享预览准备线程使用同一错误数据；每次消费构造新异常，避免反复 raise 给缓存中的同一个对象重新附加 UI 调用栈。
- 保留错误消息和诊断文本，共享预览消费完一次性结果后清空邮箱。既有 ZeroDivisionError 等普通错误类型行为通过原有回归；需要结构化构造参数的错误可转为保持原消息的 RuntimeError。

weakref 验收包含异常 cause、异常自定义属性和局部数组：失败后即回收，关闭后不再残留；重复消费、12 轮持久预览错误及共享准备失败也不持帧。错误消息和文本诊断仍可读取。

## 3. 已知余量不足时提前拒绝

- `select_in_flight()` 保留 0 的拒绝结果；GUI HDR 导出不会把它重新变成一个槽。
- `memory_budget.require_memory_headroom()` 同时检查物理 RAM 和提交余量，沿用已有系统保留值；系统快照未知时保持既有策略。
- 普通 NR/HDR 会话在共享内存和子进程创建前检查已知帧缓冲需求，MemoryError 不触发另一后端重试。
- SDR 超分、HDR GUI 导出和通用 SR/NR/FG 入口在创建相应 reader/writer/worker 前检查工作量估算；分层缓存输入不会把既有超分尺寸再次乘倍率。
- HDR reader 在启动及逐帧读取前检查解码/浮点转换暂存需求；隔离 GPU writer 在临时事务、共享内存和进程创建前检查输入缓冲需求。
- 中英文内存不足提示说明释放预览缓存或关闭其他任务后重试。保护不改变保存的参数、分辨率、处理精度或图像算法。

这些是已知缓冲的准入和既有余量策略，不是全进程硬配额；驱动/模型工作区与其他程序的突发分配仍需实际负载观察。

## 原故障探针对照

原始复核：[修复前 JSON](p0-p1-audit-20261019/diagnostics-detailed.json)；本轮：[修复后 JSON](p0-boundaries-fix-20261019/diagnostics-final.json)。

| 检查 | 修复前 | 修复后 |
| --- | --- | --- |
| 第二块共享内存分配失败，首块 close/unlink | 0 / 0，映射仍开着 | 1 / 1，映射已关闭 |
| 半初始化所有者 close | AttributeError | 成功，重复调用无副作用 |
| 错误局部帧是否仍被 session 持有 | 关闭后仍存活 | 失败后即回收，关闭后也无残留 |
| 一帧预算返回 0 时，选出的槽 | 1 | 0 |
| 零余量下 NR 是否到达共享内存分配 | 是 | 否 |

真实分配故障注入只使用 256-byte 段；其他压力条件通过模拟快照验证，没有制造真实 OOM。

## 回归记录

新增 **38 项 P0 回归**。按测试身份合并本轮相关批次，**268 项不同用例均有通过记录**，不存在未解决的断言失败。

| 批次 | 结果 | 原始证据 |
| --- | --- | --- |
| 核心资源/缓存/宿主 | 130 passed、14 subtests | [core-tests.xml](p0-boundaries-fix-20261019/core-tests.xml) |
| 导出路由/HDR/预览/文案 | 137 passed、10 subtests；1 项 Tk 初始化失败 | [consumer-tests.xml](p0-boundaries-fix-20261019/consumer-tests.xml) |
| 该 Tk 用例独立重跑 | 1 passed | [tk-rerun.xml](p0-boundaries-fix-20261019/tk-rerun.xml) |
| 错误消息和重复消费补验 | 3 passed | [error-text-tests.xml](p0-boundaries-fix-20261019/error-text-tests.xml) |

Tk 失败发生在 `tk.Tk()` 读取 `init.tcl` 阶段，未执行测试主体；原始失败记录保留，不将混跑批次描述为一次全绿。
[去重统计](p0-boundaries-fix-20261019/verification-summary.json) 包含各批次计数。没有执行全仓回归或构建。

复用 `.venv`，先按卫生守则登记新的任务目录，并把以下 `<task>` 替换为该目录名：

```powershell
$env:TEMP='F:\project\DLSS5Tool\tmp\<task>'
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
.venv/Scripts/python.exe -B scripts/audit_p0_p1.py --output tmp/<task>/diagnostics.json
.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider --basetemp=tmp/<task>/core --junitxml=tmp/<task>/core.xml tests/test_p0_memory_boundaries.py tests/test_memory_budget.py tests/test_super_resolution.py tests/test_host_queue.py tests/test_shared_cache_budget.py tests/test_render_cache.py tests/test_dlss_host_process.py tests/test_composer_device_and_worker.py tests/test_native_composer_lifetime.py tests/test_preview_cache_clear.py
.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider --basetemp=tmp/<task>/consumers --junitxml=tmp/<task>/consumers.xml tests/test_frame_generation.py tests/test_gpu_export_routing.py tests/test_gpu_export_integration.py tests/test_hdr_pipeline.py tests/test_hdr_image_sequence.py tests/test_parameter_response.py tests/test_preview_feedback.py tests/test_i18n.py
```

源码程序重启后使用本轮修复；现有冻结 EXE 不会热更新，分发时另按正式打包流程交付。

## 仓库卫生与收尾

- 唯一任务目录 `tmp/p0-boundaries-fix-20261019/`，开始 F 盘可用约 59.45 GiB；新增磁盘预算低于 32 MiB，实际临时逻辑体积约 2.30 MB。
- 复用环境与合成夹具，未复制模型、依赖或运行库；有价值的脚本与小型证据已在 scripts/docs，归档文件逐一 SHA256 一致。
- 等待诊断与测试命令全部结束；检查删除目标严格位于本任务内、无重解析点、无持久源码引用，逐文件独占打开后清理 11 个明确目标，共 176 个文件、2,294,940 逻辑 bytes。
- 删除时磁盘可用空间增加 **2,457,600 bytes**，原始路径及盘差值见 [cleanup.json](p0-boundaries-fix-20261019/cleanup.json)。保留数 KiB TASK.md 作归属记录，2026-10-26 复核。
- 原有发行说明修改、此前复核证据、旧 tmp 依赖、备份与发行包均保留。
