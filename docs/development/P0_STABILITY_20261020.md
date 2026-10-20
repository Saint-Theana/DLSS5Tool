# P0 真实负载验证与运行期保护 · 2026-10-19～20

## 当前结论

**P0 部分完成，仍未满足内存平台验收。** 本轮补齐失败关闭时的所有权和重试，增加 NR/VSR 运行中及空闲等待时的 RAM/系统提交余量检查，完成本地合成样本的处理、取消、清理和退出验证。

本地样本同时确认了尚未解决的增长：VSR、NR 以及独立原生合成器在首帧后空闲时，私有提交仍增加；图片切换的 GUI 主进程也有原生侧增长。Python 堆、Tk 图像数量、已知缓存账目不能解释其规模。分配来源尚未定位到具体 SDK、驱动或注入模块，不能把 P0 勾选为全部解决。

原始证据、逐进程采样、失败记录、源码/运行库 SHA256 和测试去重结果见 [verification-summary.json](p0-stability-final-20261020/verification-summary.json)。探针的 `status=passed` 表示处理和进程树退出完成；内存观察单独报告，`long_term_memory_plateau_verified` 保持 false。

## 已修复

| 范围 | 修复 |
| --- | --- |
| GUI NR/VSR 预览 | close 失败保留所有者，允许重试；缓存和上一预览帧仍清理。成功关闭后才清除引用。 |
| 宿主替换 | 保留关闭失败的旧会话；下一次替换先重试退休，避免继续堆积模型。当前会话也独立尝试关闭。半关闭代理拒绝新分配。 |
| RenderCache | 各层按身份去重、逐一关闭，成功的移除，失败的保留；单层失败不会跳过其他层。 |
| 后台缓存退休 | 保存失败 manager；重叠退休先等待上一线程；线程启动失败可重试；未完成退休时阻止新建模型。 |
| 取消/退出/重载 | 导出取消仍完成 UI 收尾；清理失败进入重试列表；退出失败保留窗口和所有者；缓存关闭失败不再显示清理完成；热重载的二次关闭失败仍发布结果。 |
| 运行期压力 | NR/VSR 父进程在复制帧前检查余量；子进程处理命令和空闲等待均检查，空闲轮询间隔 0.5 秒。停止命令仍可执行。 |
| 压力退出 | 实测 VSR 在压力错误后可能卡住 NGX shutdown；压力路径改由隔离进程退出回收原生资源，沿用 NR 的既有策略。保留压力错误，避免只显示进程不可用。 |

核心文件：`gui.py`、`dlss_host_process.py`、`render_cache.py`、`shared_render_preview.py`、`memory_budget.py`、`super_resolution.py`。

余量沿用已有规则：为系统保留 `max(2 GiB, RAM/8)`，同时检查物理 RAM 和系统提交余量。检查不提供全应用硬配额，也不能限制一次已经进入原生代码的突发分配；GUI 原生侧增长仍需继续解决。没有自动降低画质、分辨率或精度，也没有定期重启 NR 会话改变连续历史。

## 定向回归

新增 **23 项**：失败所有权/退休 12 项、运行期压力 10 项、重载二次关闭失败 1 项。按测试身份合并，本轮 **233 项不同关联用例均有通过记录**。

| 批次 | 结果 |
| --- | --- |
| 资源、GUI、缓存关联 | 125 passed、87 subtests |
| 加入运行期压力的关联组合 | 155 passed、94 subtests；1 项在 Tk 初始化阶段失败 |
| 该 Tk 用例独立重跑 | 1 passed |
| 压力和所有权补验 | 95 passed；最终相关模块 58 passed，均有 7 subtests，批次重叠 |
| FG/HDR 关联 | 74 passed、8 subtests；1 项在 Tk 初始化阶段失败 |
| 该 Tk 用例独立重跑 | 1 passed |

两个 Tk 失败都发生在测试主体之前读取本机 Tcl 文件时，独立重跑通过。原始失败 XML 保留；不将组合批次描述为一次全绿。未执行全仓回归。

## 真实本机处理与退出

环境：64 GiB RAM、RTX 4070 SUPER 12 GiB，复用 `.venv`、FFmpeg 和现有运行库。各媒体输入为探针在登记目录生成的合成样本。峰值为观察到的**任务进程树私有提交之和**。

| 场景 | 实际执行 | 峰值 GiB | 结果 |
| --- | --- | ---: | --- |
| 连续 SR+NR 视频 | 960×540 → 1920×1080，1,800 帧；源 60 秒，处理 135.754 秒 | 2.244 | 帧数、尺寸、处理和退出完成；预热后仍有增长 |
| 缓存导出 | 同尺寸 128 帧，RenderCache 128 MiB | 2.428 | 编码完成、各层关闭、无残留 |
| 图片预览与导出 | 三种尺寸轮换 12 次，暂停、清缓存、退出 | 2.467 | 导出尺寸正确、清理账目归零、窗口销毁、无残留；基线增长另列下节 |
| 取消后重开 | 实际处理到第 16 帧取消，随后完成 32 帧 | 2.226 | 取消输出不冒充完整文件；重开成功 |
| GUI 退出 | 预览后重新请求精细画面，再退出 | 1.252 | 退出完成、无 Tk 回调错误和残留进程 |
| HDR/PQ | 128 帧 SR+NR；输入输出均断言 PQ/BT.2020/10-bit | 2.829 | 保留 HDR，128 帧进入本地 GPU 合成，处理和退出完成 |
| SR+NR+2× FG | 48 个源帧 → 96 个 60 fps 输出帧 | 3.431 | 包括 47 个生成帧及 1 个端点保持，退出完成 |
| 纯 SR | 128 帧，关闭增强，仍使用 2× 超分 | 1.142 | 输出与退出完成 |
| 真 VSR 的模拟低余量 | 首帧后仅替换子进程内的内存快照 | 0.458 | 修复后约 3.828 秒完成，先确认子进程自行退出再关闭父所有者 |
| 真 NR 的模拟低余量 | 同上，无真实 RAM 加压 | 1.009 | 约 9.016 秒完成，退出及错误报告正确 |

所有记录的任务进程树最终为空，supervisor 未触发按 PID/创建时间的兜底回收。普通关闭路径仍可使用已有的有界进程终止回退；上述统计不能证明每一次 SDK shutdown 都自然完成。

安全界限为本次进程树私有提交 8 GiB，以及物理/提交余量各保留 8 GiB，另有超时和精确进程身份检查。全局 `nvidia-smi` 快照没有逐进程显存归属，不能据此声称测齐独显/共享显存。64 GiB 本机验证也不能替代原用户 32 GiB 机器和整机异常验收。

## 尚未解决的原生增长

### 空闲与组件对照

下表斜率使用首帧后空闲窗口：排除最初 10 秒，对前后各 1/5 样本取中位数，并除以两个中位时间点的间隔。数值只描述这一观察窗口。

| 对照 | 观察 |
| --- | --- |
| VSR 首帧后空闲 300 秒 | 前后中位提交差约 202.5 MiB，等效约 52.4 MiB/分钟，尚未进入平台；Python heap 基本稳定。 |
| NR 首帧后空闲 60 秒 | 中位差约 28.9 MiB，等效约 43.3 MiB/分钟；后续处理还出现过工作区回落，不能将所有增长算为帧缓存。 |
| 独立原生合成器，无 SR/NR | 首帧后空闲 60 秒仍增长，中位差约 37.9 MiB，约 56.9 MiB/分钟。结束时 created/destroyed=1/1、retained device refs=0。 |
| 单独 D3D12 / D3D11 设备 | 在 60～90 秒窗口内基本稳定。 |
| 单独 CUDA 初始化 | 约数 MiB 的启动/分配器波动，没有复现上述规模的增长。 |
| 最小 D3D11 绘制/计算/读回 | 分别执行清屏、空 compute dispatch、1080p staging Copy/Map/Unmap，再空闲；没有复现同等增长。没有加载项目合成 DLL 或 SR/NR 模型。 |

这将问题范围缩小到实际原生处理路径，尚不能据此指定某个 SDK、驱动、覆盖层或项目原生函数为根因。

### GUI 图片切换

补做 6 轮带 tracemalloc、GC、Tk 图像计数和缓存账目的 GUI 对照。相同大图尺寸的第 1→4 轮：私有提交约 **300.64→398.35 MiB**，Python heap 约 **34.18→36.04 MiB**，Tk 图像数均为 **296**。

第一张小图后的 60 秒空闲期间 GUI 主进程约 111 MiB，较稳定；子进程继续增长。进入实际原生合成后主进程也抬高。已知帧缓存、Python 活跃数组与 Tk 图像数量没有解释约 98 MiB 的差额；重复图片基线的平台验收仍未通过。

### 已尝试的诊断

- 进程内 `ProcessExtensionPointDisablePolicy` 没有阻止 `nvspcap64.dll` 加载，无法形成覆盖层关闭的有效 A/B。此策略仅用于探针。
- 文档化的 LFH cache decommit 成功，但只减少约 0.27 MiB，未解释 VSR 的增长。此操作没有进入产品。
- 编译了一个任务内 VSR 日志出口候选，使用现有 SDK 和静态库，保持正式运行库原样。候选初始化超时，没有有效输出，**排除为修复候选，也不用于内存比较**。补丁、构建命令和哈希已归档。
- 首轮 `continuous-hdr` 夹具实际缺少 PQ 标记，完成的是 SDR 处理，该记录已排除为 HDR 验收。修正 x265 VUI 参数、增加输入输出元数据断言后，`continuous-hdr-verified` 通过。
- 首次 VSR 模拟压力暴露 shutdown 阻塞，保留失败结果；`native-sr-pressure-fixed` 验证修复后的及时退出。

Microsoft API 依据：[进程扩展点策略](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-process_mitigation_extension_point_disable_policy)、[HeapSetInformation](https://learn.microsoft.com/en-us/windows/win32/api/heapapi/nf-heapapi-heapsetinformation)、[D3D11CreateDevice](https://learn.microsoft.com/en-us/windows/win32/api/d3d11/nf-d3d11-d3d11createdevice)。NGX 日志候选按本地 RTX Video SDK 1.1 的 `nvsdk_ngx_defs.h` 约束实现，未修改模型参数。

## 继续验收的条件

- [x] 失败所有权、取消 UI 收尾、重试与本机完整进程树退出。
- [x] 本地 SDR/HDR、缓存、图片、FG、纯 SR 及模拟低余量路径的有限负载验证。
- [ ] 定位并消除首帧后空闲增长，以及 GUI 图片切换后的原生基线抬高。
- [ ] 形成覆盖层关闭的有效环境对照；当前仅观察到 DLL 加载，尚无因果结论。关闭 NVIDIA 全局覆盖层会影响其他应用，需要维护者操作后再测。
- [ ] 使用固定设置继续验证原生内存平台、重复批次及小时级负载；原用户 32 GiB 场景、实际素材和整机异常仍保留待回验。

维护者在本轮收尾选择先交付当前修复，并请求临时关闭覆盖层的操作说明；本轮不继续修改环境。关闭覆盖层后的对照留待维护者操作后继续。

后续：维护者随后提供关闭主开关的截图并授权复测，[五组关闭后观察](P0_OVERLAY_COMPARISON_20261020.md) 已完成。原生增长仍复现，且新进程仍加载覆盖层 DLL；该轮没有取得“模块完全不加载”的对照，P0 状态不变。

本轮源码基于 `acf3ac2`，新增修复尚在工作区。未改正式运行库、用户安装程序、系统/NVIDIA 全局设置或原有发布文案；没有打包、推送或上传。

## 重建

先按仓库卫生守则登记一个新的 `tmp/<任务>-<日期>/TASK.md`，并检查 F 盘空间。以下从仓库根运行，替换 `<task>`，每次使用新 label：

```powershell
$env:TEMP = 'F:\project\DLSS5Tool\tmp\<task>'
$env:TMP = $env:TEMP
$env:PYTHONDONTWRITEBYTECODE = '1'
.venv/Scripts/python.exe -B scripts/verify_p0_stability.py --task tmp/<task> --case continuous --frames 1800 --timeout 480 --label sdr
.venv/Scripts/python.exe -B scripts/verify_p0_stability.py --task tmp/<task> --case cached --frames 128 --timeout 240 --label cache
.venv/Scripts/python.exe -B scripts/verify_p0_stability.py --task tmp/<task> --case continuous --hdr --frames 128 --timeout 300 --label hdr
.venv/Scripts/python.exe -B scripts/verify_p0_stability.py --task tmp/<task> --case images --cycles 6 --trace-gui --idle-seconds 60 --timeout 360 --label gui
.venv/Scripts/python.exe -B scripts/verify_p0_stability.py --task tmp/<task> --case native-sr --native-width 960 --frames 512 --idle-seconds 300 --timeout 390 --label idle
.venv/Scripts/python.exe -B scripts/verify_p0_stability.py --task tmp/<task> --case native-sr --native-width 960 --frames 32 --simulate-pressure --timeout 60 --label pressure
.venv/Scripts/python.exe -B scripts/verify_p0_stability.py --task tmp/<task> --case native-composer --frames 32 --idle-seconds 60 --timeout 120 --label composer
```

其他场景、帧数、耗时及输出元数据见归档 worker/result JSON；新增脚本的 `--help` 包含全部受控参数。归档脚本 `collect_p0_stability.py` 会拒绝重解析点，压缩原始采样并逐一比对 SHA256，保留失效对照的排除原因。

## 仓库卫生

唯一临时任务为 `tmp/p0-stability-20261019/`，开始可用空间 63,833,038,848 bytes（约 59.45 GiB）。新增峰值预算低于 512 MiB；复用环境、模型及 SDK，日志候选新增预算低于 32 MiB。小型报告和证据已归档，媒体、编译候选和测试夹具可重建。

收尾清理、剩余占用及磁盘前后差值以同目录的 `cleanup.json` 为准；保留任务归属记录，复核日期为 2026-10-26。旧依赖和发行基线不参与本任务清理。

收尾已核实全部观察到的任务进程退出、功能源码无临时目录引用、目标路径及条目无重解析点，逐文件独占打开后清理 51 个明确目标。共删除 916 个文件、215,967,607 逻辑 bytes；F 盘可用空间实测增加 **217,505,792 bytes（约 207.43 MiB）**。任务目录仅保留 **3487 bytes** 的 TASK.md，记录归属、重建与后续原生增长对照，2026-10-26 复核。最终证据保留 215 个校验过的原始文件；旧版报告的摘要/登记快照已迁入 prior-summaries 后才删除重复副本。
