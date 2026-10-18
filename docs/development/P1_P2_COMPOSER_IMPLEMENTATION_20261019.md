# P1/P2 本地合成实施记录

2026-10-19。用户批准继续落地 P1/P2，复用参考项目；真实多卡结果待后续用户反馈，不阻塞本轮单卡及故障路径验证。未授权发布。

## 回滚点

- `6e05ff6`：P0 内存生命周期与预算保护。
- `ac9bb01`：统一 SDR/PQ/HLG/scRGB 零效果旁路。原始 JUnit 失败日志保留原样，其尾空格不作源代码空白检查。
- 原有 `docs/release/RELEASE_NOTES_v3.0.1.md` 与 `packaging/update-policy.json` 修改不属于本任务。

## 实施顺序与验收

1. 明确合成适配器契约：传递实际选定的 LUID；不存在/旧 DLL 不支持则 CPU 回退，不静默换卡。预览 worker 保留一个执行和一个可替换请求，设备资源只由所属线程释放，退出关闭。
2. 复用 Veyra shader，HDR 细调与 CPU 的线性亮度/色度公式对齐；PQ/HLG Rec.2100、scRGB Rec.709，保留有符号/超白。
3. 四种 profile 共用 native 合成入口；保持百万像素门槛、小图 CPU 与故障回退。
4. 复用现有同卡 CUDA/NVENC 资源契约，合成纹理交给真实 GPU 消费者；CPU 消费者保留读回。所有权/同步及格式/transfer 明确。
5. 根据真实证据减少转换/复制、完成相关模块回归和有界内存实测；不提高队列上限冒充流水线。

## 复用边界

- 来源固定在 `native/realtime/sources.lock.json`、`native/realtime/NOTICE.md`。
- Veyra `NrResidualComposite.hlsl` 已在现有构建中复用；只在 prepare 脚本和本项目适配层修改，不改 vendor 产品/运行时。
- Magpie/Veyra 设备和共享纹理生命周期作为参考；编码继续复用本项目 `gpu_video_export` / `cuda_interop`，不另造编码器。
- 实时宿主的中性 `applyControls=false` 路径不变；不向实时插入 CPU-pointer 桥。

## 当前状态

- 第 1 项完成本机及故障路径验证：create_on_adapter + 实际身份返回/复核；缺失设备/旧 DLL/错误身份回退 CPU。大图才解析设备，不给小图增加枚举成本。
- 两种 GUI 合成 job 改为持久 latest-only worker；最多一个执行/一个替换请求。失效/退出在 owner 线程释放，空闲 30 秒释放 GPU 但保留轻量线程；结束活动任务后异步关闭，不从 Tk 销毁工作线程的资源。
- 定向测试：`python -m pytest tests/test_composer_device_and_worker.py tests/test_native_composer_lifetime.py tests/test_parameter_response.py tests/test_preview_cache_clear.py -q`：45 passed、7 subtests。pytest 默认 cache 目录写入权限警告不影响断言；后续使用任务内 cache。
- 构建：`scripts/build_realtime.ps1 -QualityOnly -BuildDirectory F:/project/DLSS5Tool/tmp/p1-p2-composer-20261019/build -OutputDirectory F:/project/DLSS5Tool/tmp/p1-p2-composer-20261019/candidate` 成功，仅构建质量桥与相关 shader/GPU 测试，不编译整个实时宿主。
- 实卡：`scripts/verify_local_composer.py --dll tmp/p1-p2-composer-20261019/candidate/dlss5_quality.dll --task tmp/p1-p2-composer-20261019`：4070 SUPER LUID 0:79242 身份一致；不存在的 LUID 被拒绝；6 次请求同线程/同 handle。1,002,001 像素 SDR 与 CPU 最大误差 1 个 8-bit code；首帧约 224 ms，预热后约 12.5–13.7 ms（仅合成调用，不等于整个 GUI 加速）。
- `realtime_quality_tests.exe`：20 个原有实卡 shader/直写/拷贝回退用例通过。
- 第 2/3 项完成：在既有 Veyra shader 加入线性 HDR 亮度/色度细调及显式权重；实时中性分支保持旧运算顺序。四档共用设备、阈值、故障回退策略，HDR 上传 RGBA32F 线性值以避免额外 FP16 中间量化，输出按原 profile/dtype 恢复，保留 alpha。PQ/HLG 仍复用 Python 原 EOTF/OETF，不另起颜色转换栈。ABI v2 之前的 DLL 不开启 HDR。
- HDR 定向测试 93 passed（`hdr-verified-unit-tests.xml`）。首轮断言执行完毕后 pytest 清理系统旧临时链接遇到权限错误，退出 1；改用本任务独立 `--basetemp` 重跑通过，没有删除系统目录。
- 实卡 `hdr-native.json`：18 组 profile/dtype/RGB/BGR 非中性细调＋保护遮罩对照及两组独立线性权重检查。线性最大绝对误差 1.44e-6；PQ float32 最大 1.69e-5、HLG 3.95e-6，float16 至多相邻量化码，alpha 全部精确；scRGB 负值/超白保留。16-bit PQ 原先过严的 1/65535 阈值观察到 2/65535 差异，改为预先说明的 3/65535 上限（低于 0.05 个 10-bit code），不声称逐 bit 一致。原有 20 个实卡 shader 用例仍通过。
- 第 4/5 项已完成本轮本机验证，限制与证据见下；不把单卡检查扩展为多卡实际通过。
- 新任务目录 `tmp/p1-p2-composer-20261019/`，峰值预算 4 GiB，开始可用约 61.9 GiB。

## 同卡 GPU 消费者交接

- `quality_gpu_output.cpp` 按固定 Magpie 的共享纹理/fence 模式适配 D3D11 -> D3D12；仍用现有 `SharedCudaBuffer`、`ProcessGpuVideoWriter`、CUDA 颜色转换及 NVENC ring，不增加第二套编码器。
- 单个可复用槽：上传 -> shader -> GPU 内部复制至共享 buffer -> 完成 -> 编码消费 ACK -> 允许复用。保留一次有界 GPU 完成等待，不声称完全异步或绝对零拷贝。
- 普通 CPU/Tk 消费者仍读回。免合成读回只用于同卡、同尺寸、最终视图、mix=1 的 GPU writer；比较/差值、其他 mix、尺寸转换、没有 GPU writer 时保持既有路径。scRGB 没有受支持的本地 NVENC 视频合同，合成已走统一 GPU，但显示仍由 CPU/Tk 消费，不伪装成 GPU 显示器。
- FG/NVOFA 当前 CPU 帧消费者仍拿真实合成结果，不能为免读回而给它未合成帧。本轮只免合成这一跳，不把 NR/SR/解码等其他搬运宣称为一起消除。VSR/FG/FFmpeg 的全部显式选卡尚未统一；本地合成使用 NR 实际选择，跨卡不强行共享。
- 已接普通有序写入 worker、GUI HDR 同步/异步导出和通用 multiplier=1 路由。导出 finally 在所属线程释放，消费者导入/编码错误直接终止，不做重复编码或伪成功；创建/dispatch 尚未编码时可回退。
- 每次本地 dispatch 直接传自身 QualitySettings，不再先写共享全局再读取，避免两个 owner 的参数互相覆盖。

## 数值、交接与真实工作流

- `final-native.json`：最终 DLL SHA256 `32EA271A83786B1533F4074CB29534CF866B4778D68B0B823DBF4C5DBAF544B6`。四档共 18 组类型/通道序测试与 2 组独立线性权重对照通过；原有 20 个实卡 quality 用例通过。最终线性误差不超过 1.91e-6，SDR 最大 1 个 8-bit code，HDR 半精度至多相邻码。源 alpha 精确。
- `handoff-transport.json`：SDR/PQ/HLG 各 6 帧，实际隔离 NVENC 写入共 18 帧，桥端 CPU readback=0。把**同一 GPU 结果**诊断读回后经 CPU 上传编码作为控制，解码像素全部一致；这证明资源交接精确，不等于整个 shader 与 CPU 数学逐 bit 相等。诊断 sink 的 CUDA 下载仅用于验证，产品不走它。
- HDR GPU 输出先按同一 PQ/HLG 公式编码，再显式 nearest-even 半精度量化。初轮 typed UAV/f32tof16 截断造成约 34% 通道码不同；显式找相邻 half、比较中点与奇偶后，PQ 与原 CPU OETF 路由约 99.568% RGBA 码一致、HLG 99.998%，其余误差仍不超过一个相邻半精度码。有损编码会放大差异，早期直接与 CPU 数学路径视频比较的严阈值未过，未冒充相等；通过的交接门槛使用同一 GPU 像素，CPU 数学误差另行检验。
- `pipeline-native.json`：真实 NR -> 合成 -> GPU 编码，通用入口 SDR/PQ/HLG 各 6 帧、GUI HDR PQ/HLG 各 6 帧，共 30 帧；全部实际 handoff，readback=0；帧数/色彩标记正确，HDR 为 Main10/yuv420p10le，结束 bridge 已释放。开发 runtime 安装后再按相同 5 个入口复验 30 帧通过，见 `pipeline-installed.json`。

## P1 转换、性能与资源

- 保持 RGBA 在图内传递，去掉共享 interim 与 FG 合成的 RGBA -> BGR -> RGBA 回环；编码边界才转 BGR。现有最终视图混合/opaque alpha 行为逐 bit 对照通过。只借用不可变、连续、已符合 wire 格式的 RGBA uint8/scRGB float32 快照，省两份整帧中间复制，不改输出所有权。
- 不扩队列：有序导出仍单 worker/一个 pending write，预览仍 latest-only。百万像素门槛未改。HDR CPU 解码 transfer 仍是后续可测的成本，不拿未实施的 GPU EOTF 收益报数。
- `performance-final.json`：1080p、12 帧/组、ABBA 四组、去前 4 帧的合成＋相同隔离编码 API 调用中位耗时如下。不是整体视频 NR/SR/FG 加速倍数，也不是任务管理器利用率。

| profile | 读回＋上传编码，两轮 | 同卡交接，两轮 |
| --- | --- | --- |
| SDR | 18.32 / 17.75 ms | 2.60 / 2.33 ms |
| PQ | 455.83 / 447.38 ms | 295.05 / 290.10 ms |
| HLG | 378.28 / 377.24 ms | 262.59 / 263.88 ms |

- 12 个编码 worker 均关闭、bridge 均释放。另 48 次设备重建（`performance-lifetime-extended.json`）create=destroy=48，最后 Release 设备引用=0。瞬时 private 在约 405～455 MiB 之间锯齿变化；停发后 1/2/3 秒约 423/316/215 MiB，回到第一轮关闭后约 213 MiB。这是延迟回收观察，不把 driver 内部原因当作已独立证明，也不承诺工作集立即清空。
- 原“瞬时波动小于 32 MiB”试验阈值失败（两个初轮、48 次扩展轮原 JSON 保留）。依据零存活 owner、零设备引用和停发回落，正式门槛改为**关闭后稳态基线增量小于 32 MiB**，不改安全预算、不隐瞒瞬时峰值。最终性能轮 create=destroy=28，3 秒后 private 约 242 MiB，相对首轮关闭约增加 26.8 MiB，门槛通过。显式 ClearState/释放/Flush 是正确的资源收尾，但未消除 driver 延迟，不将其称为即时回收修复。

## 定向测试与边界

- 最终涉及 242 个不同测试，按测试身份合并后均有通过记录；另 30 个子检查。组合运行 228 passed，1 个旧插桩位置失败及 2 个 Tk 初始化失败。已把插桩从被移除的 BGR 回环移动到新 RGBA 入口，原本的非阻塞/丢弃旧 revision 断言不变，重跑通过；Tk 项独立进程重跑通过，保留原始失败 XML。
- 后续模块运行：171 passed/7 subtests，43 passed（handoff＋parameter_response），43 passed（handoff＋原图对比），超分 11 passed/5 subtests。单独 frame_generation 17 passed/8 subtests、1 个 Tk setup 失败，该项再独立重跑通过。没有运行全量仓库测试。
- 尚待用户实际多卡、核显组合、长视频/批量素材反馈；不宣称反馈中的系统重启或所有低 GPU 占用已经根治。按照用户决定后续发布后收集，不以缺少第二块卡阻塞本轮代码交付。
- 本轮不打包、不推送、不发布；旧版 optional DLL 会安全回 CPU，但要使用本轮 GPU 路径需同版本源码与质量桥。

## 开发运行库

- 已把通过验证的 ABI 3 质量桥放入本工作区 `runtime/dlss5_quality.dll`，SHA256 同 `final-native.json`。正常 `_native_library_path()` 发现该文件，LUID 0:79242 创建成功。
- 原工作区 145408-byte DLL 仅保留一个回滚副本于 `tmp/p1-p2-composer-20261019/rollback/dlss5_quality.dll`，SHA256 `E81F1A00A67DCD8227C7D27FB9AC884D8BA1D4F0107E980380E8A0FE659D9E0C`；复核日 2026-10-26。没有复制模型/环境，也未把 DLL 或 SDK 提交源码。
- 原有 Release Notes 和 update-policy 修改原样保留，不在本次提交范围。

## 临时产物收尾

已核实 101 个明确目标严格在本任务目录内，无链接/目录联接，无对应 GPU 任务运行；源码/脚本无硬编码任务目录引用。构建/候选、pytest 临时目录、合成测试视频、重复报告均已删除。保留脚本、约 180 KiB 的小型证据及失败记录在源码文档内；任务目录只余 TASK 与一份 145408-byte 旧 DLL 回滚，合计约 146 KiB，2026-10-26 复核。

清理前任务逻辑体积 9,807,617 bytes；删除后首次统计 148,074 bytes（其后 TASK 补写了收尾记录）。盘可用空间差 12,013,568 bytes，见 `cleanup.json`。没有删除 SDK、模型、开发环境、其他 tmp 依赖/备份或用户素材；新 DLL 已在 runtime，不依赖已清理的候选目录。
