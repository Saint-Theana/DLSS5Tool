# 本地／实时复用落地记录（2026-10-10）

基于工作区起点 `851fb86`；不改变应用版本号，不打包、不推送、不发布。
这是实现与验收记录，不是 Release Notes。

**阶段勘误（2026-10-11）：** 本文早先引用了“实时功能路线”的 P0/P1/P2，
与用户截图中的“双模式复用清单”并非同一套编号。截图清单的最终 P0/P2 对账与验收见
[MODE_CONTRACT_CLOSEOUT_20261011.md](MODE_CONTRACT_CLOSEOUT_20261011.md)。以下旧阶段表仅保留历史记录，
不得据此推断截图项目已完成或仍欠缺。本文原 HDR 五项细调限制也已由该收尾更新。

2026-10-11 后续 P2 工程收尾及 HDR/双屏新增实测见 [P2_CLOSEOUT_20261011.md](P2_CLOSEOUT_20261011.md)。
下方阶段表保留本轮10月10日验收时的定位，不再用旧环境推断当前缺少HDR或双屏。

## 本轮验收与阶段定位

2026-10-10，用户确认本轮验收，并要求将双模式复用和后续调参响应优化合并为一次本地 Git 提交。
调参优化清单与测试见 [PARAMETER_RESPONSE_20261010.md](PARAMETER_RESPONSE_20261010.md)。
本次提交不更改版本号、不包含忽略的运行二进制/模型/临时备份，不代表完成发行包验收或分发许可审核。

当时误用于此处的是仓库 [实时功能 P0/P1/P2 台账](REALTIME_IMPLEMENTATION_20261003.md)：

| 分组 | 当前定位 |
| --- | --- |
| P0 实时基础链路 | 已实现并有基础实测；真实游戏输入、并发压力等原有验收缺口仍保留 |
| P1 画质与调参 | 已实现；本轮补齐本地残差/保护参数、双向互通及两边交互优化，用户确认本轮验收；实景时域画质不据此冒充通过 |
| P2 高阶组合 | 已进入实现与验收阶段；NVOF、SR/FG 有实测，纯 NVOFA 免 Torch 路线已落地；HDR 实机、多屏/混合 DPI/多 GPU/OBS、游戏长稳仍待对应环境验收 |

因此当前可表述为“做到 P2，实现和局部验收已落地，全面实机验收尚未闭环”，
不能写成 P0–P2 全部验收完成。跨模式共用 GPU 活跃会话/纹理、统一 GPU 合成及发行包依赖裁剪
尚未实现；本轮没有将这些能力计入已完成清单。

## 已落地

| 范围 | 实现 | 边界 |
| --- | --- | --- |
| 参数合同 | `appearance.py` 统一残差、全局合成、保护区默认值和校验 | 本地单次 NR 对应实时首个 NR 的第一通道，不复制多通道/采集/设备/快捷键 |
| 本地细调 | 残差倍数、阴影/结构、反射/辉光、饱和度、亮度五项；全局总量、压暗、提亮、颜色、亮度五项 | 阴影/反射按亮度变化分类，并非语义识别 |
| 保护区域 | 同一图像区域编辑器、最多四个归一化矩形、像素羽化、统一撤销/重置 | 保护 NR 变化，不撤销 SR；复制区域需显式勾选并按目标画面复核 |
| 互通操作 | 分组双向复制、通用 JSON 预设、保留 `撤销调参 + ···` | 实时复制仅改草稿，不自动启动/重启；清除旧排队提交，避免异步回执误应用新草稿 |
| 预览和导出 | 共享合成函数接入预览、图片、串行/并行视频、HDR、缓存派生与插帧入口 | 顺序为 SR → 原始 NR → 细调 → 全局/区域 → 旧输出混合 → FG → 对比/编码 |
| 缓存复用 | 原始 NR 缓存排除后处理参数，调参只重建派生输出和下游 FG | 配置深拷贝；对比侧保持真实原始素材，混合基底保持 NR 实际输入 |
| 实时全分辨率细调 | 新的显式开关复用原生残差资源，输入比例强制 100% | 原生 UI 可见性/中文标签同步；旧开关仍为 0，旧预设不会突然激活休眠值 |
| 纯 NVOFA 依赖 | 本地主程序可启动无 Torch 的隔离光流 worker | 不要求 inference addon；RAFT/深度仍走原附加包，不自动删依赖、不更改默认选择 |
| 运行协调 | 本地导出/队列和实时增强互斥；空闲实时启动同步 NR 组件路径并刷新 host/catalog | 不取消用户任务，运行中的会话和热键不被换路径打断 |
| 体积审计 | `scripts/runtime_footprint.py` 只读统计和同大小文件哈希审计 | 无经验证的安全删除项，因此没有裁剪现有 DLL/模型 |

设置新增 `nr_quality`、`nr_residual`。旧设置缺失时均为中性值；中性合成直接返回原输出。
通用预设为 `version: 1, kind: portable-appearance`，只允许明确的参数组，不携带路径或可执行内容。
本地扩展范围开关仍只作用于原有五个滑条，羽化和新残差控件不受它限制。

## 实际性能／体积含义

- 本地 NVOFA 和实时 NVOF 使用同类 NVIDIA 硬件光流能力，但仍分别经 CUDA 与 D3D11 路径，**没有跨进程共用活跃会话、GPU 纹理或历史帧**。
- 依赖收益是纯 NVOFA 使用者不再必须安装本机约 4.43 GiB 的 enhancement 附加包；不是宣称已从完整版删除 4.43 GiB。RAFT 的模型和 Torch 仍需保留。
- 本地残差合成目前为 NumPy CPU 向量实现，实时使用原生 GPU shader。复用了参数合同、操作组件和语义，**不是统一了两条 GPU 管线**。开启非中性参数会提前关闭 NR→编码器直接纹理通道，以保证参数不被绕过；仍可使用支持的 GPU 编码器。未承诺更高整段视频吞吐。
- 原始 NR 缓存复用是已验证的实际效率收益：只调后处理不重新执行 NR，缓存命中的导出不重复推理。
- 当前审计只发现 enhancement 内两处 `fbgemm.dll` 同哈希（5,721,600 bytes）。DLL 搜索路径未完成删除验证，均保留。未拆分/裁剪 FFmpeg 或 Torch 环境。

## HDR 与一致性边界

- HDR 的全局合成/保护区按线性光计算，支持 PQ、HLG 和有符号 scRGB；没有自动降成 SDR。
- HDR 的五项细调暂不支持非中性值。预览/导出明确报错；即时滑条反馈不会抛出未捕获的 Tk 异常。
- 数值互通不等于逐像素跨模式一致：实时多通道、降采样、时序处理、采集色彩路径与本地单次 NR 仍不同。
- 正式冻结安装包、长视频性能、真实游戏、各种 HDR 显示环境与多 GPU 组合未在本任务中完成全量验收。打包配置已纳入无 Torch worker 的入口，但不能用源码验收代替冻结发行验收。

## 验收证据

必要小型证据保存在 `mode-sharing-20261010/`（相对此文档目录）。不同批次有重叠，不应相加成独立测试总数。

- 核心回归：205 passed、3 skipped（需要 Torch 测试环境）、41 subtests；13 个 Tk 工作流用例改为独立进程执行。见 `core-results.xml`。
- UI/交互回归：120/120，按用例启动新进程，避免本机反复创建/销毁 Tcl 解释器时随机丢失资源文件的环境问题；包括参数、范围、工作台、启动、重载、热键和异步面板同步。结果见 `ui-results.json`。
- 效果工作流、区域编辑器、FG 及参数合同补充批次：71/71。见 `ui-extra-results.json`。末轮复制确认与运行路径协调补测见 `ui-last-results.json`。
- 原生 Release 构建通过；CTest 6/6，包括实际 D3D11 画质测试和 WARP 时序 shader 测试。D3D11 debug layer 未安装，该额外验证没有运行。见 `native-tests.txt`。
- 本地实际 GPU：320×192、4 帧合成源，NVOFA 附加包路径故意不存在；合成逐像素断言通过。改变总量后原始 NR 会话保持；实际视频导出 4 次缓存命中、0 新计算帧，重新解码为 4 帧。见 `local-gpu.json`。
- 实时实际 GPU：自有合成窗口，完整分辨率细调启用、输入缩放关闭、休眠比例设为 50%；日志确认 source/input 均 1198×674、实际比例 100%，持续提交至 487 帧，参数面板开关流程结束后正常退出。见 `realtime-probe.json` 和 `realtime.txt`。没有操作游戏或用户窗口。
- `git diff --check` 通过；已安装实时清单按所有输出文件的大小与 SHA-256 校验。

## 开发目录运行组件

已安装 `runtime/realtime/dlss5_realtime_host.exe`，大小 10,394,112 bytes。
SHA-256：`84364eca7afd1478a9a1db199803d004c2917f377e74ba065963ef1ac6702968`。

安装前确认无运行中的实时 host。与旧清单比较，只有 EXE 和 NR effect metadata 的内容发生变化；重建清单随后更新。
保留唯一回滚副本：`tmp/mode-sharing-20261010/rollback/`，含旧 EXE、旧 `build-manifest.json`、旧 `DLSSNR_AI_Filter.hlsl`，约 10.01 MiB。复核日期 2026-10-17，不自动删除。

回滚须先退出应用及实时 host，将旧 EXE/manifest 恢复到 `runtime/realtime/`，旧 effect 恢复到
`runtime/realtime/effects/DLSSNR/DLSSNR_AI_Filter.hlsl`，再运行 `validate_runtime(..., local_candidate=True)`。
不对回滚文件重新执行 provenance stage，否则会混入新 metadata。

运行组件继续标记 `local-validation-only`，GPL/NVIDIA 分发审查未因本任务而获得通过；本次没有发布动作。

## 重建与复验

先阅读仓库卫生守则、确认磁盘余量、登记新的任务目录。复用 `.venv` 和固定 third_party 依赖，不复制模型环境。

```powershell
.venv/Scripts/python.exe -B scripts/appearance_validation.py --output tmp/<task>/ui
.venv/Scripts/python.exe -B scripts/appearance_gpu_smoke.py --output tmp/<task>/local-gpu
.venv/Scripts/python.exe -B scripts/runtime_footprint.py --output tmp/<task>/footprint.json
```

UI 脚本默认重跑；仅源码未变化时使用 `--resume`。实际 GPU 探针只能使用新输出子目录。
原生构建使用 VS 2022 x64 CMake，`native/realtime` 为源目录，指定 `Python3_EXECUTABLE` 为 `.venv/Scripts/python.exe`，
`REALTIME_OUTPUT_DIR` 指向任务下唯一 candidate；Release build 后执行 CTest，并运行 `scripts.realtime_provenance.stage(candidate)`。
实时探针命令：`scripts/realtime_parameter_freeze_probe.py --effect NR --residual --host <candidate>/dlss5_realtime_host.exe --output <task>/probe --case full-resolution-panel`。

## 临时文件收尾

构建目录、候选目录、shader 中间文件、一次性媒体/截图和 pytest 临时输出均为本任务可重建产物；证据归档后清理。
本任务仅保留上述精确回滚副本和 `TASK.md`，不清理其他任务、持久依赖或模型。
清理 21 个明确目标后，F 盘可用空间差值增加 809,725,952 bytes（约 772.2 MiB）。剩余约 10.01 MiB，仅回滚副本及 `TASK.md`；具体记录见后者。
