# DLSS5Tool 内存策略审查与修补方案

日期：2026-10-22。源码基线：GitHub main 归档内提交标识 `7835104bfab3e66d9fb08c3fd5171bc97b9aba9a`。已读取用户上传的 `DLSS5Tool-local-diagnostic-20261022-061054.log`（从原聊天附件恢复）。用户程序版本为 v3.0.3；日志没有源码提交号，不能保证用户二进制与此提交完全相同。

**结论：内存保护的应用方式偏保守、过于一刀切，但不能认定保护本身多余。更应修复缓存与工作内存的协调、压力后的恢复，以及导出对预览缓存的依赖。导出已经流式处理，简单切短视频不是这次第 0 帧失败的直接解法。**

已在源码副本实现一个范围有限的补丁：拒绝申请前重新读取一次系统内存，错误保留同一时刻的原始数值。没有修改安全阈值、图像处理、编码或音频代码。它能消除一种可复现的过期快照拒绝，帮助定位现场；没有宣称根治当前用户错误或原生内存增长。

## 1. 日志确实证明了什么

| 日志字段 | 实际值与含义 |
| --- | --- |
| 源视频 | 864×480，24 fps，158 帧，6.583333 秒，SDR |
| 超分 | 2×，实际目标 1728×960；此路径优先使用倍数，非设置中的固定 1920×1080 |
| 插帧 | `frame_generation_multiplier=1`，即没有实际插帧；预览开关 true 不等于启用 2× 插帧 |
| HDR | 开关 true，但 `hdr_active=false`，不能按本次 HDR 内存翻倍分析 |
| 最近失败 | 导出 `frames=0`，错误为全精度帧对无法放入缓存 |
| 多次先前失败 | 预计需要约 13 MiB，预算可用 0 MiB；还有一次两者四舍五入后都是 13 MiB |
| 另一次独立失败 | 磁盘余量不足“预计峰值＋15 GiB”，不是 RAM 错误 |
| 成功记录 | 关闭超分后的 864×480 导出成功，host 为 `bypass`，原音轨直通；不能据此断言真正 NR 运算正常 |

诊断快照的精确字节数及换算：

| 项目 | 字节 | GiB |
| --- | ---: | ---: |
| 物理内存总量 | 34181894144 | 31.8344 |
| 可用物理内存 | 14868754432 | 13.8476 |
| 可用提交额度 | 6649380864 | 6.1927 |
| 当前代码预留 `max(2 GiB, RAM/8)` | 4272736768 | 3.9793 |
| 按快照计算的剩余处理额度 | 2376644096 | 2.2134 |

**同一份快照按当前公式不会拒绝 13 MiB。** 新增单元测试已验证此计算。错误发生时内存可能更低，子进程退出后又恢复；也可能涉及不同版本或不同阶段。日志没有每次拒绝的原始内存值、进程私有提交曲线或完整调用栈，不能把这些可能性当成已定位根因。

日志“风险较低、空闲约 5.2 GiB”属于显存风险提示；它不是系统 RAM／提交额度的通过证明。物理空闲很多也不代表 Windows 可以继续承担同样多的提交量。这里没有测得用户分页文件设置，不能推定其关闭或不足。

## 2. 已核查的源码路径

以下链接固定在被审查的提交，不随 main 更新。

### 内存策略与宿主

- [`memory_budget.py`](https://github.com/banbanzhige/DLSS5Tool/blob/7835104bfab3e66d9fb08c3fd5171bc97b9aba9a/dlss5tool/memory_budget.py)：`system_memory()` 缓存 Windows 快照 250 ms；`memory_headroom_bytes()` 取物理空闲、提交空闲的较小值，再减统一预留。
- `cache_limit_bytes()` 使用 `max(0, min(用户上限, RAM/4, 已缓存量 + 空闲下限 - 预留))`。缓存已占内存得到一次抵扣，因此不是每次调用都累计扣掉 4 GiB。用户的 26000 MiB 设置是请求上限，实际并不必然分配 26 GB；本机 RAM/4 上限约 7.96 GiB，压力下还会更小。
- `bounded_frame_count()` 仅让一个队列使用剩余额度的四分之一。零容量会拒绝；这不是跨所有线程／进程的真实原子内存预订。
- `require_memory_headroom()` 把同一预留用在处理申请上。`receive_worker_command()` 空闲每 0.5 秒也检查两个帧的额度，非关闭命令收到后再检查。小额工作或空闲宿主也会被统一门槛终止，缺少先协调缓存回收的阶段。
- [`dlss_host_process.py`](https://github.com/banbanzhige/DLSS5Tool/blob/7835104bfab3e66d9fb08c3fd5171bc97b9aba9a/dlss5tool/dlss_host_process.py)：`_HostSession.__init__()` 以 `frame_bytes*(4+2*slots)` 做预检，再创建两个共享帧；`copy_input()` 又检查两个帧，虽然实际 `np.copyto` 目标已经存在；`_host_worker_main()` 使用上述空闲／运行检查。这些调用不是每次真的新分配这么多，也不应描述为把 reserve 连续相加，但会反复触发同一门槛。
- [`super_resolution.py`](https://github.com/banbanzhige/DLSS5Tool/blob/7835104bfab3e66d9fb08c3fd5171bc97b9aba9a/dlss5tool/super_resolution.py)：`ProcessSuperResolution.__init__()` 用带 512 MiB 裕量的 `recommended_ram_bytes` 预检，默认估算还包含增强阶段；`process()` 检查两个目标帧，VSR worker 同样检查。1728×960 RGBA8 一帧为 **6.328125 MiB**，两帧为 **12.65625 MiB**，与错误显示的 13 MiB吻合。这只能定位一组候选检查点，不能仅凭数值指定是哪一次调用抛错。

### 预览、预取和预渲染

- [`shared_render_preview.py`](https://github.com/banbanzhige/DLSS5Tool/blob/7835104bfab3e66d9fb08c3fd5171bc97b9aba9a/dlss5tool/shared_render_preview.py) 的 `_uses_shared_render()` 将超分、插帧及相关 HDR 预览送入共享渲染；`_shared_display()`／`_shared_tick()` 控制预取。
- [`render_cache.py`](https://github.com/banbanzhige/DLSS5Tool/blob/7835104bfab3e66d9fb08c3fd5171bc97b9aba9a/dlss5tool/render_cache.py) 的 `RenderCache.session()` 创建 spatial（SR）、base（NR）、必要时 output（外观／FG）层。各层 `RenderSession` 会持有处理结果、原图对照，base 在相关路径还持有 SR 混合输入；`sink()` 复制数组。不能只按“源视频帧字节”估算成本。
- `RenderSession._produce()` 的 `gate()` 和 `sink()` 已有背压和淘汰，并不是整段视频无限解码入内存。但可缓存多层全精度帧，且“放不下一对帧”会成为致命错误；导出也会遭此错误。
- `set_prefetch_ahead()` 将共享预览传入值限制在 2～48，故用户设置 120 不等于共享预览真的前取 120 帧。新建普通 session 的默认值仍是 120；`encode_cached()` 只开启 prefetch，没有主动统一设成较短的导出窗口，因此新建导出会话与已用于预览的会话可能有不同前取长度。
- [`shared_cache_budget.py`](https://github.com/banbanzhige/DLSS5Tool/blob/7835104bfab3e66d9fb08c3fd5171bc97b9aba9a/dlss5tool/shared_cache_budget.py) 的 `SharedCacheBudget` 协调已缓存字节和需求，但不等于全应用工作集预算。渲染层“检查额度→复制数组→发布用量”也不构成跨层原子预订。
- [`gui.py`](https://github.com/banbanzhige/DLSS5Tool/blob/7835104bfab3e66d9fb08c3fd5171bc97b9aba9a/dlss5tool/gui.py) 的 `_start_prefetch()` 在共享渲染路径直接返回，所以不能把旧预览队列与共享渲染前取简单叠加。旧路径涉及 `_start_paused_prerender()`、`_prerender_target_frames()`、`_evict_preview_cache_accounted()`；预渲染确实可能按容量扩大。
- `preview_decoder.py::PreviewDecoder` 默认最多 4 个解码结果；`preview_jobs.py::LatestPreviewJob` 是一个运行任务、一个可替换请求、一个当前结果。它们有界，不能凭名字认定存在无界队列。

### 导出与音频

本次 GUI 导出主路径是：

```text
App._export_video_source()
  → _export_frame_generated_video()  # 只有超分、倍率1也走这里
  → RenderCache.session()
  → spatial → base → 可选 output/FG
  → encode_cached() 按帧等待并编码
  → writer.finish() → 音频封装
```

`App._export_sdr_upscaled_video()` 看起来像超分入口，但当前 GUI 的 SR 分支先进入上述共享路径，修复只放在这个旧辅助函数会错过现场。

[`frame_generation.py::export_video()`](https://github.com/banbanzhige/DLSS5Tool/blob/7835104bfab3e66d9fb08c3fd5171bc97b9aba9a/dlss5tool/frame_generation.py#L373) 已经逐帧执行：解码→SR→NR／合成→FG→写入。FG 保留前后端点及运动输入；结尾补端点保持，场景切换使用保持帧，不能在批次边界重复补尾。当前 GUI 共享路径内部会强制单帧 host 队列；用户保存的 workers=4、host_in_flight=3 不代表本次真的启动四份模型或三槽流水线。

[`parallel_export.py::export_parallel()`](https://github.com/banbanzhige/DLSS5Tool/blob/7835104bfab3e66d9fb08c3fd5171bc97b9aba9a/dlss5tool/parallel_export.py#L80) 已有 2～4 进程分段；每段各自启动模型，默认 warmup=8。这是吞吐方案，不是低内存方案。当前 SR／FG 路由不会因更改这个函数就自动获得分段支持。`parallel_export_worker.py::main()` 从段前预热并 reset，有限预热不能证明结果与完整时序相同。

[`video_export.py`](https://github.com/banbanzhige/DLSS5Tool/blob/7835104bfab3e66d9fb08c3fd5171bc97b9aba9a/dlss5tool/video_export.py) 的 `FFmpegVideoWriter.finish()` 在全部视频完成后调用 `mux_source_audio()`；后者复制视频，尽可能原音频直通，不兼容时可能转成 AAC 192 kbps。已有逻辑是“保留音频”，并不无条件保证音频位流无损。若要求原音轨绝不重编码，应增加严格复制模式：不兼容就明确提示选择容器，不静默走 AAC fallback。

## 3. 分段方案怎样才不牺牲画质

| 方案 | 可行性与限制 |
| --- | --- |
| 每次消费 8／16 帧，保留同一模型会话和同一编码器 | 推荐。只是调度批次，不切模型历史；内存由窗口和工作峰值决定，FG 跨批次保留所需前后端点。批次长度须由字节预算计算，8／16 仅是初始测试值 |
| 完成帧后立即写入，减少共享预览缓存 | 推荐优先改造。导出无需保留已消费的全片对照缓存；正确移交所有权后可以即时释放 |
| 无损磁盘缓存已算好的帧 | 能减少重算但占磁盘；必须保存原 dtype、色彩元数据及时间戳，不能用 JPEG 或普通 8-bit 图片替代 HDR 中间结果 |
| 每段重启 SR／NR／FG 子进程 | 能释放其资源，但可能丢失时序状态。没有已验证的状态导入导出接口；warmup=8 不是等价证明。不得默认启用并宣称无画质变化 |
| 空间切块后拼图 | 本次不是超大单帧问题；还涉及感受野、运动／深度和边界融合，不能把通用 tile 当作安全修复 |

如果增长来自活着的驱动／SDK 会话，保持会话的逻辑分块不会自动修复泄漏。作者在同仓库 [`P0_COMPLETION_20261020.md`](https://github.com/banbanzhige/DLSS5Tool/blob/7835104bfab3e66d9fb08c3fd5171bc97b9aba9a/docs/development/P0_COMPLETION_20261020.md) 中记录了测试机 VSR／NR 空闲增长仍存在。它是作者特定环境的测试证据，未在用户机器复现，不能据此认定用户驱动有相同问题。

## 4. 具体补丁路线

### P0：已完成的最小补丁

修改 `memory_budget.py::system_memory(refresh=False)` 和 `require_memory_headroom()`：

1. 正常检查继续使用 250 ms 缓存，避免增加每帧常态系统查询。
2. 若即将拒绝，绕过 TTL 重新查询一次；只有新快照通过原门槛才允许继续。
3. 新查询失败时保留先前拒绝，不把“未知”作为已知内存不足的绕过手段。
4. 错误附带同一快照的 required、available、physical_free、commit_free、reserve 精确字节数及刷新状态，解决“13 MiB 对 13 MiB”的显示歧义。这些文本能经过现有 worker 错误字符串传递。
5. 中英目录增加一个诊断文本键；增加独立 CPU 单元测试。

范围限制：仅覆盖 `require_memory_headroom()` 调用；VSR 构造函数的独立检查、RenderSession 缓存报错、队列零容量报错尚未统一。因此这不是所有拒绝路径的完整诊断改造，也不回收缓存、不解决驱动增长。

### P1：压力协调，先回收，再拒绝

- `memory_budget.py`：把“硬安全余量”和“缓存可用额度”明确区分；缓存软预算再减去下一步工作峰值及恢复缓冲。先保持现有硬安全阈值，依据真实测量再讨论调参。
- `shared_cache_budget.py::SharedCacheBudget`：新增工作峰值／待分配租约，与已缓存字节分开；检查与登记在短锁内原子完成，失败／取消归还。锁内不能执行 IPC、模型推理、长等待或分配大图。
- `render_cache.py::RenderSession._allowance/_trim/_produce`：内存压力先停前取、淘汰已消费和非必要帧；保护正在被消费的帧及 FG 端点；以最小可前进窗口继续。协调所有层，避免一个层等待另一个层释放，而另一个层又等待它消费。
- `dlss_host_process.py::_HostSession.__init__/copy_input` 与 `super_resolution.py::ProcessSuperResolution.__init__/process`：按真正新增的峰值记账，区分已分配共享帧与未来复制／native 工作区。不能只删 `copy_input()` 的检查；要有对应的模型增长监测和硬停止。
- `memory_budget.py::receive_worker_command`、两种 worker 循环：软压力先通知父进程回收缓存并限时重试；硬压力依旧退出。禁止无限等待，禁止默默重建时序模型；关闭命令始终可用。
- `gui.py` 的预取／预渲染入口和 `shared_render_preview.py`：导出取得资源后冻结不相关预览生产者；只有确认旧任务退出才能释放共享内存。保持现有 generation／取消机制。
- 诊断记录增加阶段、PID、帧号、尺寸／dtype、模型初始化前后提交量、各层 cached／pending／active 字节。只记录统计，不采集画面。

### P2：将导出变成有界消费

- `gui.py::App._export_frame_generated_video()` 增加明确的导出消费模式；在创建本次任务时选择，不对已部分写出的文件自动换路径。
- `render_cache.py::encode_cached()` 在 `writer.write()` 同步消费完成后通知 session 释放不再使用的帧；把上游前取窗口按总字节和倍率限制。数组若仍被异步消费者引用，必须等完成信号，不能仅删字典就当作实际释放。
- `RenderSession._produce()` 给导出使用 1～若干帧的有界通道／租约，把可复用历史缓存设为可选；预览继续保留按需重算语义。现有单帧对缓存测试可作为起点。
- 也可考虑由 `frame_generation.export_video()` 直接流向 writer，绕开多层预览缓存；先验证与分层路径的 SR→NR→外观→FG 顺序、原图对照、output_mix、HDR/VFR 语义一致，再接入 GUI。
- 无 FG 时评估去除无用的 previous/proxy 全尺寸副本；`sr.process()` 已返回独立 copy，`export_video()` 中再次 `.copy()` 是可核查的冗余复制候选。所有权回归测试通过后再删，尤其不能把共享缓冲直接借给跨帧消费者。
- 保持一个编码器运行到结束。逻辑批次不调用 `finish()`、不重复补 FG 尾帧、不切音频。最后只封装一次原音轨；严格无损音频要求独立明确处理。

### P3：若确认为 native 持续增长

在独立进程记录预热后长期曲线，分别测 SR-only、NR-only、FG-only、组合及空闲。Python heap 平台不等于整个进程平台。持续增长应查资源生命周期或 SDK／驱动；需要重启模型的分段方案只能作为明确注明时序影响的选择，不能替代根治并宣称画质不变。

## 5. 测试、交付和验收边界

本次实际执行 **13 项测试，全部通过**：新增 11 项 admission／刷新／错误数值／worker 关闭和压力测试，加原有 2 项语言目录一致性与格式化测试。包括用用户精确快照计算 2.2134 GiB，并验证其可通过约 13 MiB 申请。

在源码根目录执行：

```text
python -B -m unittest tests.test_memory_admission_refresh tests.test_i18n.LocalizationTests.test_language_catalogs_have_identical_nonempty_keys tests.test_i18n.LocalizationTests.test_translation_formats_named_values_and_falls_back_safely -v
```

本机复用了现有 Python 3.12.14，没有下载模型、编译 DLL 或生成大视频。没有可用的完整项目 GPU 测试环境；OpenCV／pytest 不在复用环境内，未运行 `test_memory_budget.py`、`test_p0_memory_boundaries.py` 等依赖完整环境的测试，也未复现用户视频的实际 GPU 导出。13 项通过不能替代上述回归或 GPU 验收。

P1/P2 合并前至少补齐：

| 验收项 | 判定要求 |
| --- | --- |
| 158 帧用户同参数用例 | 从首帧到最终封装完成；记录每阶段峰值，禁止用关闭 SR 替代通过 |
| 预算边界 | 低物理内存、低 commit、零容量仍可靠拒绝；可回收缓存先回收；缓存禁用而最小工作集可用时能流式前进 |
| 并发租约／取消 | 两层同时申请不超订；失败回滚；等待期间可取消，无死锁、残留进程或共享内存提前释放 |
| 1／2／8／16 帧窗口 | 相同像素顺序／dtype／reset 序列；所有渲染帧与不分批基线一致，不能只比压缩文件字节 |
| FG 2×／3×／4× | 跨窗口端点、切镜保持、最终尾帧正确；总帧数和时间戳正确，无重复拼接、缺帧或时长改变 |
| HDR／VFR／外观 | PQ、HLG 精度和元数据不变；倍率1保留源时间戳；当前不支持的 VFR 插帧仍明确拒绝 |
| 音频 | 同容器兼容格式做包负载校验，音轨数／起始时间／同步不变；严格模式不允许静默 AAC 转码 |
| 长视频稳定性 | 窗口缓存有界，预热后进程树提交量进入平台；只因保护触发而停止不算通过 |

关联原有测试：`tests/test_render_cache.py`（单帧对预算、重放、取消、缓存复用）、`tests/test_memory_budget.py`、`tests/test_p0_memory_boundaries.py`、`tests/test_super_resolution.py`、`tests/test_frame_generation.py`，以及相应音频／VFR writer 测试。修改完成后按影响范围执行，不需要无差别跑全仓库。

交付 `memory-admission-refresh.patch`、可审查的源码小包和本报告。补丁基于上述固定提交；应先 `git apply --check` 再应用。源码小包不是可执行升级包，不能直接替换 v3.0.3 的 exe。未修改用户安装、用户设置或分页文件，未上传代码／日志，未创建 PR。

临时资源：保留约 83 MiB 的源码副本以便后续核查及继续实现；源码归档在补丁验证后删除。未复制 Torch/CUDA 或模型。保留目录复核日期为 2026-10-29，不设置自动删除任务。
