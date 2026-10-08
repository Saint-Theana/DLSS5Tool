# Magpie / Veyra 联合参考与复用清单

日期：2026-10-03。本文保留联合参考清单和来源依据；现已进入全量实现与验收，不再是仅研究阶段。代码、GPLv3 迁移和合成窗口实测已经落地，逐项状态以实施台账为准。

后续决策：用户要求本次全量实施，下面的 P0/P1/P2 仅作依赖分组，不再作为缩小交付范围或延期的依据。实际进展与验收以[全量实施记录](REALTIME_IMPLEMENTATION_20261003.md)为准。

## 目标与结论

目标是直接增强本机正在运行的游戏或普通窗口，不以采集卡、串流或完整视频播放器为首期目标。

建议以 **Magpie 的窗口实时框架为主，吸收 Veyra 的画质处理与状态管理，保留 DLSS5Tool 的图片/视频工作流**。
用户已同意必要时采用 GPLv3 以减少重写工程量；许可证不再是排除源码复用的预设条件。

实施范围：同批接入 NR/SR/FG/HDR、显示器/GPU 选择及全部 19 项；不再采用早期的 SDR/单显示器简化首版建议。当前 SDR 虚拟桌面的合成实测不能替代 HDR、多显示器及游戏实机验收。
“任意窗口”是产品方向，不是所有程序均兼容的保证：独占全屏、受保护画面、反作弊、特殊鼠标输入和不同显示拓扑需要逐项验证。
这条路线处理的是已渲染画面，不能获得游戏引擎原生深度、运动矢量或独立 UI 图层，也不等于提高游戏本身的渲染帧率。

## 参考基线

- Magpie Experimental：`SAOG0721/Magpie`，固定提交 `2c017d4be8311fac8584e2ff6187b1f03383bde1`，下文链接均固定到该提交。
- Veyra：`Likely7/Veyra-NRVideo`，`v1.4.4` 已解析并固定为 `6851c2775c978b999e263a9c427ff43461688aa0`；下载归档 SHA256 和全部依赖固定在 [sources.lock.json](../../native/realtime/sources.lock.json)。下文标签链接保留研究出处，实际构建使用固定提交。
- DLSS5Tool：新增独立原生宿主和控制界面，已有真实 GPU 实验；尚无用户目标游戏并发测试。详见[全量实施记录](REALTIME_IMPLEMENTATION_20261003.md)。

Magpie 的窗口框架有较成熟的积累，但其 Experimental AI 路径不能据此视为全部生产可用。上游性能数字不作为本项目承诺。

## P0：实时链路基础（本次范围）

表中的“复用”均指完成文件级许可证核对后的源码复用；不是直接复制便携包里的 DLL。
工程量只作相对估计：小＝局部适配，中＝跨模块接入，大＝原生宿主/时序/兼容性工程，不代表工期。

| 待办 | 能力与用户收益 | 来源及采用方式 | 工程量 | 通过条件 |
| --- | --- | --- | --- | --- |
| [ ] P0-01 | 选择正在运行的窗口并持续增强，不需要采集卡 | 以 Magpie WGC 捕获、源窗口跟踪为主；其他捕获方式作为有证据的兼容回退 | 大 | 普通窗口、窗口化游戏可捕获；目标关闭、最小化、尺寸变化有明确处理；不把自己的增强输出再次捕获 |
| [ ] P0-02 | 增强后仍能正常点击、移动鼠标和切回游戏 | 成组复用 Magpie 输出窗口、焦点维护、光标绘制与坐标映射 | 大 | 不抢源窗口焦点；DPI/缩放坐标正确；Alt-Tab、停止及异常退出恢复光标与限位；相对鼠标输入单独验证 |
| [ ] P0-03 | 捕获→增强→显示保持 GPU 数据路径，减少每帧 CPU 往返 | 优先适配 Magpie D3D11/D3D12 共享纹理与 fence；接入我们现有 NR 设置/组件选择 | 大 | 不以 Python 逐帧传像素；同步所有权明确；无资源提前覆盖或释放；记录 GPU 拷贝和等待成本 |
| [ ] P0-04 | 负载升高时不不断累积延迟 | Magpie 最新帧消费与呈现调度为主，结合 Veyra 截止时间/有界队列设计 | 大 | 过期输入可丢弃；队列有上限；只有一处主导节拍；游戏并发负载下持续观察帧龄、P95/P99 与 GPU 争用 |
| [ ] P0-05 | 开关增强、调整参数、切换窗口和故障退出可控 | Magpie ScalingRuntime 生命周期；新增薄控制适配层，沿用我们的宿主替换失败回退思路 | 中～大 | 启停幂等；旧会话命令不能污染新会话；异常可回退源窗口；热键可立即停止 |
| [ ] P0-06 | 不因重复显示或短暂跳帧频繁闪烁，也不错误沿用旧历史 | 结合 Magpie 捕获时间戳与 Veyra ResetCoordinator；按真实连续性判定重置 | 中 | 区分重复呈现、跳过旧输入、场景切换、尺寸变化、运行时切换；重大不连续重置；短暂丢帧不机械重置 |
| [ ] P0-07 | 用户能确认增强效果和实际负载 | 参考 Magpie 对比/统计，复用我们的参数与对比交互设计 | 中 | 可快速原图/增强对比；分别显示新捕获帧、NR 处理、提交呈现速率与耗时；不以 Present 次数冒充真实帧率 |

### P0 的工程切分

优先复用一套连贯的原生实时核心，而不是分别重写捕获、鼠标、窗口和节拍。
建议由 DLSS5Tool 界面管理目标选择、参数和状态；原生实时宿主管理 GPU 纹理、增强与呈现。
初步控制接口包含：`start(target, options)`、`stop()`、`update_settings()`、`get_status()`；这是我们拟新增的接口，不是上游现成 API。

Magpie 的 `Magpie.Core` 当前是 C++ 静态库，并不是可直接交给 Python 使用的公开 SDK。
已检查的程序入口也不能证明存在稳定的 `--hwnd/--preset` 自动化契约。因此仍需控制适配层和构建整合，不能把源码复用估算为“调用一个现成 DLL”。
共享纹理路径仍可能包含 GPU 拷贝，不称为绝对“零拷贝”。

主要依据：[WGC 捕获][m-capture]、[光标管理][m-cursor]、[输出窗口][m-window]、[NR GPU 互操作][m-nr]、[运行时接口][m-runtime]、[静态库构建][m-project]、[帧同步说明][m-sync]。

## P1：让画面更稳、更好调

| 待办 | 能力与用户收益 | 来源及采用方式 | 工程量 | 验证重点 |
| --- | --- | --- | --- | --- |
| [ ] P1-01 | 降低增强细节在相邻帧间闪动 | 参考 Veyra NR 残差时域稳定：仅稳定“增强输出减原始基底”的差值，带运动重投影、拒绝和邻域限幅 | 中～大 | 高速运动、遮挡、场景切换、文字/HUD 不拖影；先作为默认关闭的实验开关 |
| [ ] P1-02 | 分别控制增强对亮度、暗部和颜色的影响 | 复用/适配 Veyra 残差合成 shader；从现有单一 output_mix 扩展 | 中 | 0 强度回到基底；高强度不硬切黑；颜色和亮度控制可预测；导出与预览一致 |
| [ ] P1-03 | 给字幕、HUD、边缘或指定区域保留原画面 | 参考 Veyra 保护遮罩与羽化机制；由我们补界面和区域规则 | 中 | 遮罩与残差有效性分离；边界无接缝；零残差不是“受保护”的同义词；不宣称自动识别所有游戏 UI |
| [ ] P1-04 | 提供更低成本的实时增强档位 | 参考 Veyra ResolutionPlan：较低分辨率计算 NR 残差，边缘感知合成回全分辨率基底 | 中～大 | 原图细节与文字保留；测速度、显存和画质取舍；明确属于性能档，不替代全分辨率质量档；不自动降低离线导出质量 |
| [ ] P1-05 | 一键切换画质风格，按应用记住参数 | 参考 Veyra 版本化预设白名单与 NR-only 预设；按应用绑定由我们补充 | 中 | NR 预设不误改 SR/FG/颜色等无关设置；设备/路径等不随外部预设注入；旧预设迁移可测 |
| [ ] P1-06 | 切换增强组件、运行时或尺寸失败后可恢复 | Veyra 事务式设置与会话代次；保留我们现有“新宿主创建成功后再替换”的基础 | 中 | 状态显示当前实际生效版本；失败保留可用配置；旧会话结果不能显示到新会话 |
| [ ] P1-07 | 将画质稳定性变成可回归验证的指标 | 参考 Veyra GPU 时域测试与 Magpie NR 时域测试，再加项目自己的对比样本 | 中 | 覆盖零残差、保护/羽化、缺失光流、异常间隔、越界、奇数尺寸、重置与数值有限性 |

Veyra 的时域 shader 标明派生自 Magpie 提交 `3841698348bfb246623d4acf791984c8b68a577b`，两者不是应当顺序叠加的两套独立“画质增益”。
引入时比较实现、选择一条历史稳定路径，并保留完整来源。Veyra 的历史处理使用过去帧，不是必须等待未来帧，但仍有计算和显存成本。

主要依据：[时域 shader][v-temporal]、[时域 pass][v-pass]、[残差合成][v-residual]、[分辨率计划][v-resolution]、[历史重置协调][v-reset]、[引擎控制][v-engine]、[预设][v-preset]、[GPU 回归测试][v-tests]。

## P2：高阶组合（同批实现，不延期）

| 待办 | 能力 | 取舍 |
| --- | --- | --- |
| [ ] P2-01 | GPU 光流路径优化与质量档 | 我们已有 RAFT/NVOFA 和相关互操作基础；结合两者调度经验做实测，不重复建设整套光流后端 |
| [ ] P2-02 | 本机实时 SR 与 FG 组合 | 参考 Magpie 的窗口链路、Veyra 的生成准入与输出限速；按实际需要生成，避免生成后再大量丢弃；区分真实帧/生成帧/提交帧 |
| [ ] P2-03 | 端到端 HDR | 参考两者颜色与浮点残差处理，延续我们的 HDR 合成；捕获、NR、合成、显示色彩空间必须一起验证，不能只开一个 HDR 标志 |
| [ ] P2-04 | 多显示器、混合 DPI、多 GPU、OBS 共存 | 按已通过的组合公布兼容范围；跨 GPU 拷贝和多显示器节拍单独测量，不默认继承上游所有支持 |
| [ ] P2-05 | 更完整的性能与节能策略 | 在 P0 指标之上增加持续采样、功耗观察和场景配置；提交速率不等于物理扫描输出或输入到光子的延迟 |

Veyra 对不同帧生成提供方/交换链的控制范围不相同；输出限速、严格准入不能不加区分地移植到所有后端。
主要依据：[帧同步说明][m-sync]、[引擎控制][v-engine]、[呈现设置][v-presentation]、[实时预览调度][v-scheduling]。

## 我们已有的优势：保留并扩展

| 现有基础 | 位置 | 接入原则 |
| --- | --- | --- |
| 时序连续的渲染缓存与预览/导出共享结果 | [render_cache.py](../../dlss5tool/render_cache.py)、[shared_render_preview.py](../../dlss5tool/shared_render_preview.py) | 保留文件工作流；实时窗口采用独立调度策略；新增画质参数纳入缓存键，防止读到旧效果 |
| 宿主进程隔离及先创建后替换 | [dlss_host_process.py](../../dlss5tool/dlss_host_process.py) | 复用恢复机制和设置契约；当前 GPU 输出入口仍有 CPU 输入，不能据此宣称实时输入已 GPU 常驻 |
| D3D12 NR 原生宿主 | [dlssnr_host_v2.cpp](../../native/host_v2/dlssnr_host_v2.cpp) | 保留离线通路；比较与 Magpie 实时核心的接口，再决定共用与隔离边界 |
| SDR/HDR 混合与完整离线导出 | [video_export.py](../../dlss5tool/video_export.py)、[frame_generation.py](../../dlss5tool/frame_generation.py) | 实时追新帧与导出保全帧是不同契约；不把实时丢帧/降分辨率策略直接套入导出 |
| 组件路径与运行时选择 | [mod_paths.py](../../dlss5tool/mod_paths.py) | 增加能力/版本/实际生效状态，不重造整套组件管理 |
| 图片处理、批量工作流、比较界面与更新器 | 当前主应用与发布流程 | 保持现有入口；新增实时模式，不将整个主应用替换成另一个播放器 |

## 不属于本机窗口增强任务的范围

- PS5 / RemotePlay / Chiaki、采集卡输入：不解决当前最重要的本机窗口目标，也增加协议、音频和许可证范围。
- 完整播放器、字幕与音频系统：只吸收与我们的现有工作流相关的修复，不搬整个产品。
- 不明来源的运行时、二进制补丁或未核准的 SDK 分发：上游提供下载不等于授予我们全部再分发权。
- 所有厂商 SR/FG 提供方：本次接入 DLSS SR/FG/NVOF 组合，不把未编译后端标为可用。HDR/多 GPU 入口在本次范围内，未具备对应硬件的组合仍须实机验收。
- 同时重写主 GUI、缓存、离线导出和更新器：会掩盖真正的实时链路风险。

## 许可证与发布前置条件

- [x] 建立固定来源和源码输入哈希清单、修改记录及 notices，见 [NOTICE.md](../../native/realtime/NOTICE.md) 和构建生成的 manifest。
- [x] 根许可证迁移 GPLv3，保留原始 MIT 声明及源码获取/构建脚本；现有 MIT 授权不被追溯撤销。公开发行材料仍须完成下述专有组件审查。
- [x] 所选 Veyra 画质 shader 的来源和许可证随模块保留；没有引入 RemotePlay/Chiaki 的 AGPLv3 代码。
- [ ] 分别核对 NVIDIA 运行时/SDK 的获取与再分发权，以及与 GPL 组合发布的兼容性。采用 GPLv3 不自动解决这些问题；进程隔离也不自动构成许可豁免。
- [x] 增加公开打包门禁：审查未完成时只允许显式本地候选，不静默删掉实时功能，也不宣称已经可公开再分发；本次没有对外发布。

以上是工程合规检查项，不是法律意见。依据：[Magpie 的第三方及再分发说明][m-license]、[GNU GPL 兼容性 FAQ][gpl-faq]。实施阶段应针对实际组件组合复核，而不是以两个项目已有发行包为证明。

## 建议执行顺序与验收门槛

1. **选定复用边界**：完成文件/依赖清单和最小构建方案，明确 Magpie 核心保留范围；避免先大规模移植再发现核心依赖不适合发行。
2. **建立实时闭环**：完成 P0，先验证不带增强的捕获/输入/显示，再接 NR；同步测“游戏单独运行 / 开捕获不增强 / 开 NR”三组。
3. **补画质与体验**：按 P1 做可关闭的增量功能，稳定性未通过不替换默认效果。
4. **完成高阶组合**：同批实现 P2；按既定硬件与负载基线逐项验收，不用配置入口存在冒充实际通过。

每阶段都要保留可回退基线，至少记录：

- 游戏/窗口与 GPU/驱动、输入/输出尺寸、参数、捕获方式；不要只测独立增强吞吐。
- 新帧率、处理耗时、捕获到提交的帧龄及 P95/P99、队列上限、显存、丢弃输入数和游戏自身帧率变化；硬件测量前不声称输入到光子的真实延迟。
- 长时间运行、Alt-Tab、最小化、源窗口关闭/缩放、运行时初始化失败及停止后的焦点/鼠标恢复。
- 运动、镜头切换、细线、文字和 HUD 样本的闪烁/拖影对比；标明质量档和性能档。
- 原有图片、视频、预览缓存、完整导出与更新流程无回归。

## 本次交付边界与仓库卫生

本文初稿是研究清单，后续用户已授权全量实现及 4 GiB 任务预算；不要再引用初稿的“未实现／临时占用为0”作为当前状态。
实现、已通过用例、未验收条件和清理结果见[全量实施记录](REALTIME_IMPLEMENTATION_20261003.md)。任务目录为 `tmp/realtime-integration-20261003/`，不清理既有依赖或用户数据。

[m-capture]: https://github.com/SAOG0721/Magpie/blob/2c017d4be8311fac8584e2ff6187b1f03383bde1/src/Magpie.Core/GraphicsCaptureFrameSource.cpp
[m-cursor]: https://github.com/SAOG0721/Magpie/blob/2c017d4be8311fac8584e2ff6187b1f03383bde1/src/Magpie.Core/CursorManager.cpp
[m-window]: https://github.com/SAOG0721/Magpie/blob/2c017d4be8311fac8584e2ff6187b1f03383bde1/src/Magpie.Core/ScalingWindow.cpp
[m-nr]: https://github.com/SAOG0721/Magpie/blob/2c017d4be8311fac8584e2ff6187b1f03383bde1/src/Magpie.Core/DLSSNRFilter.cpp
[m-runtime]: https://github.com/SAOG0721/Magpie/blob/2c017d4be8311fac8584e2ff6187b1f03383bde1/src/Magpie.Core/include/ScalingRuntime.h
[m-project]: https://github.com/SAOG0721/Magpie/blob/2c017d4be8311fac8584e2ff6187b1f03383bde1/src/Magpie.Core/Magpie.Core.vcxproj
[m-sync]: https://github.com/SAOG0721/Magpie/blob/2c017d4be8311fac8584e2ff6187b1f03383bde1/docs/FRAME_SYNC_GUIDE.md
[m-license]: https://github.com/SAOG0721/Magpie/blob/2c017d4be8311fac8584e2ff6187b1f03383bde1/docs/THIRD_PARTY_AND_REDISTRIBUTION.md
[v-temporal]: https://github.com/Likely7/Veyra-NRVideo/blob/v1.4.4/shaders/NrTemporal.hlsl
[v-pass]: https://github.com/Likely7/Veyra-NRVideo/blob/v1.4.4/src/pipeline/NrTemporalPass.cpp
[v-residual]: https://github.com/Likely7/Veyra-NRVideo/blob/v1.4.4/shaders/NrResidualComposite.hlsl
[v-resolution]: https://github.com/Likely7/Veyra-NRVideo/blob/v1.4.4/include/veyra/pipeline/ResolutionPlan.h
[v-reset]: https://github.com/Likely7/Veyra-NRVideo/blob/v1.4.4/include/veyra/pipeline/ResetCoordinator.h
[v-engine]: https://github.com/Likely7/Veyra-NRVideo/blob/v1.4.4/src/engine/EngineController.cpp
[v-preset]: https://github.com/Likely7/Veyra-NRVideo/blob/v1.4.4/include/veyra/engine/PresetStore.h
[v-tests]: https://github.com/Likely7/Veyra-NRVideo/blob/v1.4.4/tests/integration/NrTemporalGpuTests.cpp
[v-presentation]: https://github.com/Likely7/Veyra-NRVideo/blob/v1.4.4/include/veyra/engine/PresentationSettings.h
[v-scheduling]: https://github.com/Likely7/Veyra-NRVideo/blob/v1.4.4/include/veyra/engine/RealtimePreviewScheduling.h
[gpl-faq]: https://www.gnu.org/licenses/gpl-faq.en.html#WhatDoesCompatMean
