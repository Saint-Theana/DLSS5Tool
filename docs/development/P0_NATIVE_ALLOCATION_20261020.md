# P0：进程归属与原生分配调用栈 · 2026-10-20

## 当前结论

**统计中的增长属于本次测试进程，不包含无关后台应用自身的私有内存。进一步采样在 NVIDIA 用户态显卡驱动 `nvwgf2umx.dll` 中找到了持续分配调用栈。**

本机最小对照仅调用 CUDA 初始化、创建 D3D11 设备、提交一次空计算，随后空闲 60 秒，默认原生堆已分配量仍增加约 **70.15 MiB**；该进程未加载项目 `runtime/` 下的任何 DLL。带调用栈追踪的同类对照抓到与项目合成器相同的驱动模块偏移序列。

这使“其他应用多占了内存、误把整机总量算成项目增长”无法解释当前测量，也说明项目帧缓存、NR/VSR 推理和合成器不是复现这一增长的必要条件。**当前定位到的是本机 CUDA/D3D 组合触发的驱动进程内分配路径，尚未证明是驱动独立缺陷、覆盖层等注入模块影响，或二者的交互。P0 仍为部分完成。** 原用户 32 GiB 故障也不能直接以本机结论替代。

完整汇总见 [allocation-summary.json](p0-native-allocation-20261020/raw/allocation-summary.json)，进程/退出证据见 [verification-summary.json](p0-native-allocation-20261020/verification-summary.json)。

## 为什么不是误读后台应用占用

`scripts/verify_p0_stability.py` 使用 Toolhelp 识别本次工作进程及其后代，按 PID 和创建时间验证身份，持有进程句柄避免 PID 重用。`GetProcessMemoryInfo` 的 `PrivateUsage` 仅统计这些身份的私有提交；它不是整机 RAM 总量，也不等于物理驻留量或独立显存。微软定义见 [PROCESS_MEMORY_COUNTERS_EX](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters_ex)。

上一轮 VSR 的同一个工作进程 PID 45820、创建时间 134369009883572229，在首帧后空闲约第 10→300 秒的私有提交约为 431.36→806.13 MiB。父 Python 约 38 MiB 稳定；按同一 worker 身份比较已排除临时 `nvngx_update.exe` 出现/退出的干扰。原始证据保留在 [上一轮比较](p0-overlay-off-20261020/raw/comparison.json)。

进程内的 SDK、驱动和注入 DLL 也会计入这个进程。后台应用自己的私有内存不会混入计数，但仍可能通过注入、驱动状态、资源竞争等间接影响增长。全局系统余量和 `nvidia-smi` 整卡快照只用于环境观察及安全停止，不能替代逐进程归属。

## 新增六组受控对照

均为现有本地环境，用户已关闭 NVIDIA 浮窗开关；每组只初始化/处理一次后空闲约 60 秒，之后正常退出。`map` 只查询内存区域元数据和默认堆汇总，`heap` 另在该隔离进程中临时追踪既有 IAT 引用的原生堆调用。

| 用例 | PID | 默认堆已分配量增量 | 观察 |
| --- | ---: | ---: | --- |
| 独立合成器 `native-composer-map` | 30228 | **70.61 MiB** | 匿名私有提交约增 78.15 MiB；映射/映像私有提交不变 |
| 合成器调用栈 `native-composer-heap` | 47668 | **40.08 MiB** | 主要观测分配栈在 NVIDIA 驱动；跟踪改变了速度 |
| D3D11 空计算＋时间戳查询 `native-device11-timing-map` | 40336 | **0.071 MiB** | 没有复现同等规模增长；私有提交略回落 |
| 仅枚举适配器 `native-adapters-map` | 14308 | **0.075 MiB** | 调用项目枚举接口和 CUDA 身份查询，未初始化 NGX；未复现同等规模增长 |
| CUDA 初始化＋D3D11 空计算 `native-device11-cuda-map` | 48696 | **70.15 MiB** | 无项目原生运行库；匿名私有提交约增 75.45 MiB |
| 上述组合＋调用栈 `native-device11-cuda-heap` | 13332 | **19.89 MiB** | 抓到相同驱动分配栈；栈表饱和，仅用于路径证据 |

所有六组处理/退出检查完成，未触发安全停止或 supervisor 回收，观察过的精确进程身份均已退出。`passed` 只表示处理和退出，所有 `long_term_memory_plateau_verified` 继续为 false。各组仅一次顺序实验，短窗口和追踪后的斜率不外推为小时级占用。

## 已抓到的分配路径

本机驱动 DLL 文件版本为 **32.0.16.1742**（显示驱动 617.42）。合成器与最小 CUDA/D3D11 对照中的主要捕获序列均为：

```text
nvwgf2umx.dll + 0xee0dec
nvwgf2umx.dll + 0xeaebdf
nvwgf2umx.dll + 0xeaee79
nvwgf2umx.dll + 0xeaf2a2
nvwgf2umx.dll + 0xfff1a
ntdll.dll ...
```

合成器调用栈追踪的同一条栈在约 20、40、60 秒分别记录到未配对释放的请求量 **14,806,848 / 28,250,624 / 41,761,008 bytes**。最后为 226,962 笔、每笔 184 bytes，约 **39.83 MiB**，占本次追踪观测净保留量约 99.16%；同期 `HeapSummary` 的实际默认堆已分配量增加约 40.08 MiB，二者规模接近。该组合证据比单看 DLL 是否加载更能支持分配来源定位。

**“观测未配对释放”不是完整泄漏审计：**探针不覆盖所有缓存函数指针、随后加载模块的导入或原生分配方式。漏记释放可高估保留量，失败释放和并发重分配也可能影响配对计数；真实堆增量为独立读数。没有 NVIDIA 私有符号，偏移不能擅自命名为某项具体驱动功能，也不能证明所有后续帧/GUI 增量都来自同一处。

合成器追踪的对象/栈表均未丢条目。最小组合的跟踪因 Python 检查点产生大量不同栈而达到 8,192 栈容量，最终丢弃 1,298,308 次新栈记录；已有驱动栈仍持续记录到约 20.47 MiB。**该轮只能确认同一分配路径，不能据此计算完整来源比例或拿斜率与非追踪运行比较。** 该饱和现象和原始记录均保留。

## 探针验证和边界

- `scripts/inspect_native_allocations.py` 使用 [VirtualQueryEx 同类页面查询语义](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-virtualqueryex)、[QueryVirtualMemoryInformation](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-queryvirtualmemoryinformation) 和 [HeapSummary](https://learn.microsoft.com/en-us/windows/win32/api/heapapi/nf-heapapi-heapsummary)，仅读取自身进程元数据，无内存内容转储。映射/映像中的写时复制私有提交也纳入分类。
- HeapSummary 只查询默认进程堆，不遍历第三方 DLL 可能并发销毁的私有堆。地址扫描不是原子快照，部分轮次有 1 个并发失效区域查询失败，数量已逐检查点保存，未把失败当成零分配。
- 地址分类自检准确识别 16 MiB VirtualAlloc 提交并确认释放；调用栈探针自检准确记录 16→24 MiB 分配/扩容及释放后归零，66 个 IAT 引用全部恢复。
- 第一次调用栈自检因优化后的客户端尾调用省略了客户端帧，断言失败；原始 16 MiB 分配实际已记录。将自检客户端改为 `/Od` 后验证通过，未据失败记录得出模块归因。失败和成功原始材料均保留。
- 两组调用栈追踪均恢复了运行中临时拦截引用；合成器 238/238，最小组合 221/221。探针 DLL 及固定大小表仅留在隔离进程至其退出，不替换项目运行库。
- 本轮没有修改生产代码、全局 NVIDIA/Windows 设置、注册表、用户安装程序，没有安装新工具或重启。没有重复跑全量/233 项关联回归；本轮验证为探针自检、五份诊断 Python 语法/CLI 检查及六组有限实测。

## 下一步与验收口径

优先复用最小 CUDA/D3D11 对照检查驱动与注入环境，而不必反复跑完整项目负载。重启后核对注入状态、或改变驱动/相关全局设置，均应作为单独明确的环境对照；当前未执行这些操作，不能用“关闭浮窗后仍有 DLL”证明开关无效。

确认环境触发条件并修复后，再回到 VSR/NR、GUI 图片和连续视频，验证预热平台、重复任务基线及清理退出。原有失败所有者重试和内存余量保护仍有价值，但不等于这条原生分配路径已经修复。

## 重建与仓库卫生

任务目录 `tmp/p0-native-allocation-20261020/`，2026-10-20 建立、2026-10-27 复核；初始 F 盘约 59.45 GiB，预算低于 128 MiB。复用既有 `.venv` 和运行库。

设置 `PYTHONDONTWRITEBYTECODE=1`、TEMP/TMP 到登记任务目录，设置 `DLSS5TOOL_P0_MEMORY_MAP=1`。普通合成器/显卡对照不需编译；只有显式设置 `DLSS5TOOL_P0_HEAP_TRACE=1` 才加载任务内 `native_heap_trace.dll`。编译命令、自检客户端/脚本、各组参数、模块清单、源码/运行库哈希、原始采样及清理核验保留在关联证据目录中。

```powershell
.venv/Scripts/python.exe -B scripts/inspect_native_allocations.py --self-check
.venv/Scripts/python.exe -B scripts/verify_p0_stability.py --task tmp/<registered-task> --case native-device11 --device-compute --device-cuda --frames 32 --idle-seconds 60 --timeout 150 --label cuda-map
.venv/Scripts/python.exe -B scripts/summarize_native_heap_trace.py --task tmp/<registered-task> --output tmp/<registered-task>/allocation-summary.json
```

归档的源码/运行库清单记录本轮收尾状态，不能替代每轮执行前的完整源码快照；实验间只增加诊断分支/采样，不改生产代码或运行库。清理只处理本任务可重建输出；最终校验及剩余临时占用见证据目录内 `archive-verification.json`、`cleanup.json` 和任务登记。

收尾已核验 80 份原始文件、18 个精确进程身份退出、路径/祖先/条目无重解析点、源码无任务临时目录引用及逐文件独占打开。Win32_Process 命令行查询被系统拒绝访问，未据此得出无进程结论。删除 87 个本任务可重建文件、13 个子目录，共 18,330,443 逻辑 bytes；F 盘可用空间前后增加 **18,472,960 bytes（约 17.62 MiB）**，该全盘差值可能包含并发磁盘活动。只保留 TASK.md 供 2026-10-27 复核，必要报告、脚本/构建命令及分配证据均已保留。
