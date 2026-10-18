# P1：SDR / HDR 统一零效果优化 · 2026-10-19

## 已落地

在 P0 提交 `6e05ff6` 和 [P1 基线](P1_BASELINE_20261019.md) 上，实现了同一套零效果调度，覆盖 SDR、PQ、HLG、scRGB；不是只给 SDR 加一个临时开关。没有修改 native DLL、位深、编码参数、队列上限或发行配置。

- 外观残差确定为零，或最终视图的输出混合为零时，不创建 NR 宿主／共享帧缓冲／guidance，会话走有所有权的轻量输出。
- 四个基础参数全部为零且自动遮罩关闭时，使用与现有宿主零参数输出一致的快路径。不将“一个参数是零”或“接近零”当作关闭增强。
- 本地预览、普通导出、HDR 严格导出、共享缓存／超分／插帧、并行导出 worker 使用同一判定。原生 GPU 直出也在初始化前检查是否真的需要 NR，不能从一个不存在的增强会话请求 GPU 纹理。
- 零残差合成直接返回输入，不再做 D3D 创建／shader、整帧转换或 HDR 传递函数往返。PQ 近黑和 scRGB 负值／超白在这个源帧分支精确保留。
- 缓存身份区分正常 NR、源帧旁路、宿主零参数旁路；恢复效果时换回新 NR 会话／生产者，从正确时序重置，不把旁路帧当作增强结果。普通非零外观编辑仍复用原始 NR 和超分缓存。
- 保持一个同步旁路结果，不引入额外异步队列；异常后清除对输入帧的引用。显式光流／深度查看仍执行真实 guidance，使用临时会话并正确关闭，不伪造零光流。

核心策略在 `dlss5tool/appearance.py`；接入点为 `dlss_host_process.py`、`frame_generation.py`、`render_cache.py`、`parallel_export_worker.py`，以及 GUI 的缓存身份／旁路边界失效。合成入口为 `residual_composition.py` 和 `video_export.py`。

## 为什么分两种零效果，而不是分 SDR / HDR

| 公共判定 | 输出语义 | 色彩处理 |
| --- | --- | --- |
| `source` | 外观总量为 0；亮／暗同时为 0；颜色／亮度同时为 0；或最终视图混合为 0 | 原样保留合成输入，不裁剪、不量化、不做 EOTF/OETF |
| `native-zero` | intensity、local_tone、local_struct、skin_struct 全为 0，自动遮罩关闭 | 模拟现有零参数宿主；浮点 RGB 限制到 0～1，alpha 不变，保留浮点位深 |
| 不旁路 | 其他情况，包括差值／对比视图仅混合为 0、有效增强、未知自定义运行库的基础参数归零 | 沿用正常增强与合成链 |

真实宿主对照发现：scRGB 的基础参数归零并不等于原样返回，宿主会裁剪负值和超白。若像 SDR 合成实验那样一律返回输入，会改变既有画面。这里集中保留该数值契约，而不是在各个 HDR 入口各打一个补丁。去除宿主原有裁剪是另一个有画面行为变化的任务，本轮不擅自更改。

`native-zero` 只对默认／内置运行库启用；明确选择自定义 `dlss_runtime` 时保守地继续调用 NR。外观零残差是合成公式上的恒等式，不依赖某个模型版本，仍可旁路。

输出混合为零不能覆盖差值或左右对比视图需要的增强结果；外观残差归零则在所有视图下都不需要 NR。视图仍由原有格式化步骤生成，不删除分界线或差值图。

## 验证

必要的小型证据在 [p1-zero-path-20261019/](p1-zero-path-20261019/)。全部使用可重建合成素材，没有用户媒体。

### 定向测试

- 285 项不同用例及 59 个 subtest，覆盖四种色彩配置、精确零与近零、HDR 近黑／负值／超白、alpha、帧所有权、正常外观缓存复用、旁路切换／恢复、失败恢复、未消费队列保护、超分输入与原始对比源分离、插帧前合成、直接／缓存／GUI HDR／并行导出、P0 内存预算及原生上下文生命周期。
- 最后一次组合运行为 283 通过、2 项在 Tk 初始化阶段报错；两项各自独立进程重跑均通过。错误指向 Tk 脚本读取，具体原因未定，未通过修改生产代码掩盖它们。早先一次 Tk 初始化错误和一次导入对话框超时也在独立重跑中通过。
- 保留组合运行与独立重跑 XML，不把“285 项分别验证通过”写成“一次运行全部通过”。未运行全量回归。

### 真实宿主零参数对照

复用 `.venv`、现有 runtime，RTX 4070 SUPER / 617.42；不复制或安装模型、Torch 或 CUDA。探针直接使用 `_HostSession`，故不会被新 `ProcessLive` 旁路自身绕过。

- v2：SDR、PQ、HLG、scRGB × 三种 style × 三帧，共 36 帧。
- legacy：SDR × 三种 style × 三帧，共 9 帧。
- **45/45** 与零参数快路径逐位一致，alpha 精确；scRGB 测试输入包含负值与最高约 5.5 的超白。
- 初次另外 12 帧对照保留，作为发现 scRGB 裁剪行为的原始证据。

### 真实超分＋插帧链

256×256 / 30 fps / 8 源帧，生产 `frame_generation.export_video`：VSR 2× → 光流／FG 2× → NVENC，输出 512×512 / 60 fps / 16 帧。每种 profile 各运行纯超分＋插帧、外观总量 0、四个基础参数 0，GPU 任务严格顺序运行。

| Profile | 三组编码前输出 | NR 宿主创建 | 实际处理／编码格式 | 色彩标记 |
| --- | --- | --- | --- | --- |
| SDR | 16/16 帧一致，MP4 哈希也一致 | 0 | uint8 / H.264 | SDR |
| PQ | 16/16 帧一致，MP4 哈希也一致 | 0 | float16 / HEVC Main 10 | BT.2020 / SMPTE 2084 |
| HLG | 16/16 帧一致，MP4 哈希也一致 | 0 | float16 / HEVC Main 10 | BT.2020 / ARIB STD-B67 |

两种 HDR 的首帧通道均有 1024 个不同值，不是套上 HDR 名称的 8-bit SDR 处理。使用 ffprobe 完整读取 12 个输入／输出文件，帧数、尺寸、帧率、像素格式和色彩标记均正确。

首轮自生成 HEVC 素材未保留传递函数／色度标记，实际按 SDR 处理。该轮 `zero-pipeline.json` **不计为 HDR 验收**，作为负面证据归档。脚本修正为向 x265 明确写入 VUI，并在进入管线前和编码后强制验证 profile、float16 及 Main10；有效结论只取 `zero-verified-pipeline.json`。

小型整链证明旁路、精度与顺序，不代表用户长视频、所有硬件／运行库、HDR 元数据扩展或音频时间线均已验收；scRGB 验证为原生帧接口和数组／缓存测试，不冒充一个已有的 scRGB 视频编码入口。整链短任务启动／收尾占比很高，不给出固定百分比提速承诺。

## 复现

先检查空间并登记 `tmp/p1-zero-path-20261019/TASK.md`。现有报告／媒体不可覆盖；重复运行用新 label，测试用新的 basetemp。

```powershell
$env:TEMP='F:\project\DLSS5Tool\tmp\p1-zero-path-20261019'
$env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -B scripts/verify_zero_nr_contract.py --task tmp/p1-zero-path-20261019 --label all-styles
.\.venv\Scripts\python.exe -B scripts/verify_zero_nr_contract.py --task tmp/p1-zero-path-20261019 --backend legacy --label legacy
.\.venv\Scripts\python.exe -B scripts/verify_zero_pipeline.py --task tmp/p1-zero-path-20261019 --label verified
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_enhancement_bypass.py tests/test_appearance.py tests/test_hdr_pipeline.py tests/test_render_cache.py tests/test_frame_generation.py tests/test_dlss_host_process.py tests/test_gpu_export_routing.py tests/test_parameter_response.py tests/test_original_comparison.py tests/test_preview_interaction_continuity.py tests/test_preview_feedback.py tests/test_hdr_image_sequence.py tests/test_native_composer_lifetime.py tests/test_memory_budget.py tests/test_workbench_memory.py --basetemp=tmp/p1-zero-path-20261019/pytest-verified -o cache_dir=tmp/p1-zero-path-20261019/pytest-cache --tb=short
# 两项 Tk 初始化失败的独立重跑：
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_parameter_response.py::TestLocalResponse::test_unchanged_collect_is_read_only --basetemp=tmp/p1-zero-path-20261019/pytest-tk-readonly -o cache_dir=tmp/p1-zero-path-20261019/pytest-cache
.\.venv\Scripts\python.exe -B -m pytest -q tests/test_parameter_response.py::TestLocalResponse::test_tk_heartbeat_and_controls_work_during_slow_composition --basetemp=tmp/p1-zero-path-20261019/pytest-tk-heartbeat -o cache_dir=tmp/p1-zero-path-20261019/pytest-cache
```

## 收尾与后续边界

本轮任务新增峰值预算 <256 MiB，实测临时文件仅约 11 MiB。原始小型证据归档后，删除本任务明确生成的测试目录、合成媒体及日志，保留任务登记；具体路径核实和磁盘前后值见 `cleanup.json`。

未修改用户既有发行说明和更新策略，未打包、提交、推送或上传。选卡统一、预览常驻 worker、GPU 常驻输出仍是后续任务；本轮不把“零效果旁路完成”扩大为“所有 P1 问题已解决”。
