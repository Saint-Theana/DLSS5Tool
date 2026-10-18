# 本地 GPU 残差合成后续 TODO

日期：2026-10-16。当前版本：v3.0.1。原始交接状态：当时未开始。

2026-10-19 更新：维护者已在新对话授权实施与提交，本文件下文“暂不实施/不提交”是历史边界，不再覆盖最新授权。
四项已完成本轮本机落地和定向验证，详见 [P1/P2 实施记录](P1_P2_COMPOSER_IMPLEMENTATION_20261019.md)。
已完成精确 LUID、HDR 公式与三档 HDR GPU 入口、真实同卡编码交接；CPU/Tk、比较/差值、mix≠1、尺寸转换和 CPU FG 消费者仍保留必要读回。真实多卡与用户长视频反馈尚待验收，不扩大本机证据。

本文是下一步交接，记录当时核对过的缺口和验收口径。写本文时用户明确要求先存档、暂不实施。没有新的实施指令时，不要把本文当成改代码、改默认路径或重新打包的授权。

已落地的测量和边界见 [本地媒体 GPU 残差合成](LOCAL_GPU_COMPOSITION_20261016.md)。本文不重复那份测量。

## 目的

本地导出和预览的大尺寸残差合成，继续走已经在用的 `dlss5_quality.dll`，并补上四件还没接上的事：

1. 合成用本轮导出已经选中的那块 GPU。
2. 有符号 HDR 的 shader 公式先和 CPU 对齐。
3. 再把 PQ、HLG、scRGB 接进现有 GPU 入口。
4. 下一步编码或显示仍在这块 GPU 上时，结果留在显存里。

实时宿主的主路径保持现状。实时帧已经在 GPU 上，合成时 `applyControls=false`，细调在低分辨率阶段做过。不要把 `dlss5_quality.dll` 的 CPU 指针桥塞进实时宿主。

## 已有能力（不要从零重做）

- `native/realtime/quality.cpp` 的 `ResidualComposite` 已复用 Veyra compute shader。输出纹理带 `D3D11_BIND_UNORDERED_ACCESS` 时直接写 UAV；否则走 staging 加 `CopyResource`。同尺寸走单像素读取。
- `native/realtime/quality_bridge.cpp` 已接受 `format_id = 0`（RGBA8 UNORM）和 `format_id = 1`（RGBA16F）。本地调用是 `Draw(..., hdr, true, false)`，也就是在 shader 里施加细调。
- `dlss5tool/residual_composition.py` 的 `compose()` 只在 `profile == 'srgb'`、`uint8`、像素数达到 `NATIVE_COMPOSITION_MIN_PIXELS`（1,000,000）时调用 DLL。失败、缺 DLL，或设置了 `DLSS5TOOL_DISABLE_NATIVE_COMPOSER`，都回到 NumPy。
- HDR 的 CPU 对照在 `compose()` 里：PQ/HLG 先 EOTF、线性光合成、再 OETF，权重 Rec.2100 `(0.2627, 0.6780, 0.0593)`；scRGB 保持线性浮点，权重 Rec.709 `(0.2126, 0.7152, 0.0722)`，允许超出 0–1。细调函数是 `hdr_fine_controls()`。
- 本机导出侧的 DLSS 设备已经按请求的 LUID 选适配器，见 `native/host_v2/dlssnr_host_v2.cpp` 的 `OpenAdapterByLuid`。质量桥还没有用这个 LUID。

## 实施顺序

按 1 → 2 → 3 → 4 做。第 2 项完成前不要打开 HDR 的 GPU 开关。第 1 项完成前不要做免读回，否则结果可能落在另一块适配器上。

### 1. 本地桥使用本轮导出的 GPU

现状：`quality_bridge.cpp` 的 `Bridge::Initialize()` 调用 `D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, ...)`，设备落在默认适配器。导出已经按 LUID 选过 DLSS 设备，两边可能不是同一块 GPU。

做法：把本轮导出选中的适配器 LUID 传进桥。枚举到的适配器与该 LUID 一致才创建合成设备。对不上、设备创建失败或 dispatch 失败时，回到现有 CPU 路径。

完成标准：指定 GPU 时，合成发生在该 LUID 上。指定的 LUID 在机器上不存在时，不静默落到默认适配器再报成功。

注意：同一张 RTX 上 DXGI 可能列出多个逻辑 LUID。用导出已经选定的那一个，不要把这些逻辑 LUID 当成多张物理卡。

### 2. 先补齐有符号 HDR 的 shader 公式

现状：`scripts/prepare_realtime_build.py` 注入的 `NrApplyFine` 在 `signedHdr > 0.5` 时跳过 `saturate`，也跳过饱和度/亮度那一段 HSL。方向分类的亮度权重写死为 Rec.709 `(0.2126, 0.7152, 0.0722)`。

CPU 的 `hdr_fine_controls()` 不是这条路径。它按亮度/色度拆开残差，再乘 `residualLightness` 和 `residualSaturation`。PQ/HLG 用 Rec.2100 权重；scRGB 用 Rec.709。数值可以落在 0–1 之外。

本地桥在 `applyControls=true` 时会把这些非中性细调送进 shader。实时宿主合成时 `applyControls=false`，用的是中性 `QualitySettings`，细调已经在低分辨率阶段做过。改公式时，实时中性路径的结果保持不变。

完成标准：同一组线性输入下，shader 与 `hdr_fine_controls()` 的差异只来自量化。scRGB 仍用 Rec.709；PQ/HLG 用 Rec.2100；0–1 之外的值保留。

### 3. 把本地 HDR 接到现有 GPU 入口

现状：DLL 已经能收 `format_id = 1`。Python 在 `profile != 'srgb'` 时不调用 `_native_compose()`。`_native_quality_values()` 把 `signedHdr` 写成 `0.0`，`dlss5_quality_compose` 的 format 参数写成 `0`。只改 format 而不做第 2 项，PQ/HLG 的结果会对不上 CPU。

做法：第 2 项对齐之后再接。

- scRGB：上传线性 float，合成后仍是线性 float。
- PQ/HLG：先解码到线性光，合成，再编码回原来的传递函数。传递函数继续用现有 `_pq_eotf` / `_pq_oetf`、`_hlg_eotf` / `_hlg_oetf`。
- 失败、缺 DLL，或像素数低于 1,000,000，继续走现在的 CPU 路径。

完成标准：`hdr10_pq`、`hdr10_hlg`、`scrgb` 三档在达到像素门槛时走 GPU，并与现有 CPU 结果一致（差异只来自量化）。SDR `uint8` 大图仍走 DLL。

### 4. 导出和预览不再整帧读回 CPU

现状：`quality_bridge.cpp` 的 `Compose()` 对每一帧都是上传、dispatch、再 `Map` staging 纹理把整帧拷回 CPU。读回纹理没有 UAV。

做法：第 1 项选定的 GPU 上，如果接下来的编码或显示仍用这块设备，合成结果留在该设备的纹理上，交给下一步消费。下一步必须读 CPU 指针时，保留现在的读回。

完成标准：大尺寸导出在编码或显示仍在同一块 GPU 上时，不再为合成做这次整帧 staging 读回。读回路径仍能在失败时回到 CPU。

## 本轮保持不变

- `NATIVE_COMPOSITION_MIN_PIXELS = 1_000_000` 继续作为 CPU/GPU 搬运门槛。1280×720 仍走 CPU，1920×1080 仍走 GPU。这是故意的截止，不是遗漏。
- 不把 fence、`CopyResource`、publish 从 `quality_gpu_ms_p95` 里再拆出来。现有计时只包住 `Dispatch`。
- 不新增按组件硬性断言 LUID。实时侧 DLSS、合成、光流、插帧已经共用 Magpie `DeviceResources` 选定的适配器。本清单第 1 项只补本地质量桥。
- 不改实时宿主的 UAV 直写、同尺寸单像素读取，以及 `applyControls=false` 的调用方式。
- 不改发行说明，不重新打包，不提交。

## 每项自带的检查

- 第 1 项：指定一个存在的 LUID 时，合成设备就是该适配器；指定不存在的 LUID 时走 CPU，而不是默认适配器。
- 第 2 项：非中性 `residualSaturation` / `residualLightness` 下，scRGB 与 PQ/HLG 的线性结果分别对齐 `hdr_fine_controls()` 的两种权重。实时中性参数的输出不变。
- 第 3 项：大尺寸 SDR `uint8` 仍选 DLL。PQ、HLG、scRGB 接上后与 CPU 结果一致。缺 DLL 和 dispatch 失败仍回 NumPy。
- 第 4 项：同一 GPU 上的大尺寸导出不再出现合成用的整帧 staging 读回。必须落回 CPU 的调用方仍能拿到帧。

现有 `tests/test_mode_contract.py` 覆盖的是 CPU `hdr_fine_controls()`。仓库里还没有“只有大尺寸 SDR `uint8` 才选 DLL”的断言。上述检查随对应项一起加，不要提前写成已经通过。
