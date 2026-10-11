# 本机实时增强：全量实施记录

用户于 2026-10-03 明确要求一次完成，不以简化首版作为终点。原 [联合参考清单](MAGPIE_VEYRA_REUSE_CHECKLIST_20261003.md) 的全部 19 项均纳入本次；P0/P1/P2 只表示依赖顺序，不表示推迟到其他版本。

2026-10-10 后续：分量/残差、区域保护及预设互通已扩展到本地预览和导出，
详见 [双模式复用记录](MODE_SHARING_20261010.md) 与 [调参响应优化](PARAMETER_RESPONSE_20261010.md)。
下文“仅属于实时链路”描述为 10 月 3 日历史边界，已被该扩展更新；其余尚未满足的实机验收
条件不因本轮用户确认调参体验而自动变为通过。

2026-10-11 P2 收尾：新增设备/后端启动门禁与隔离验收工具，五档 NVOF、四档 SR/FG、
三分钟持续性及自有 FP16/scRGB HDR、同 DPI 双屏均有新证据。当前环境已非下文的旧虚拟桌面，
最新逐项状态、未验收条件及证据以 [P2 收尾记录](P2_CLOSEOUT_20261011.md) 为准。

## 验收台账

未验收不标记完成；有配置项、接口或测试替身不等于真实功能已交付。

| 项目 | 当前状态 | 证据 |
| --- | --- | --- |
| P0-01 窗口捕获与跟踪 | 已接入，合成窗口实测 | WGC 窗口/全屏、GDI、DWM 出帧；resize/minimize/restore。当前虚拟桌面 DD 不交付帧，明确回退 WGC 已出帧，不记 DD 成功 |
| P0-02 光标、输入与焦点 | 原生框架已接入，普通点击实测；游戏输入待验收 | computer-use 实点增强画面后源 Canvas 收到点击；Ctrl+Alt+F10 退出并恢复原窗口；无进程注入。游戏相对鼠标和混合 DPI 尚未实测 |
| P0-03 GPU 捕获/增强/显示 | 已接入并实测 | NR/SR/FG、共享纹理/fence；Python 协议不传像素。GDI 本身是兼容性 CPU 捕获，不能称其为全 GPU |
| P0-04 有界队列与节拍 | 已接入，压力/游戏并发待验收 | 复用 Magpie 有界呈现环与消费确认；命令64、事件1024、统计512；WGC 旧帧丢弃计数；尚无真实游戏并发帧龄结论 |
| P0-05 生命周期、控制与快捷键 | 已实现，协议与生命周期实测 | 旧 run_id 拒绝、宿主代次隔离、EOF/quit 清理、快捷键占用检测、紧急停止缺失时拒绝全屏 |
| P0-06 历史连续性与重置 | 已接入，GPU/WARP 回归 | 使用单套 Magpie 捕获序列/资源代次/时间戳/输入修订；静止合成参数刷新不增加真实帧和 NR 评估计数 |
| P0-07 对比与实时指标 | 已实现，计数实测 | 对比、截图、参数/统计浮层；捕获/NR/真实/生成/提交分别统计；取帧→提交 P50/P95/P99、NR GPU P95 |
| P1-01 残差时域稳定 | 已接入，合成与时域测试 | Magpie temporal（Veyra 同源路线不重复叠加）；NR50%+NVOF+antiFlicker=2+SR+FG 实际出帧；真实游戏拖影主观验收仍需完成 |
| P1-02 分量增强调节 | 已实现，GPU 测试通过 | Veyra 合成在全部 NR/temporal 之后执行；total/darken/brighten/color/luminance；零强度精确基底、暗部过驱及有符号 HDR |
| P1-03 区域保护与羽化 | 已实现，GPU 测试通过 | 四矩形、归一化坐标、拖动/数值编辑、羽化；全保护/边界/有效零残差测试；不宣称自动识别 HUD |
| P1-04 低成本 NR 与全分辨率合成 | 已实现并实测 | NR50%残差在 GPU 边缘引导重建回完整基底；全局增益不重复应用；奇数尺寸测试；离线路径不自动降质 |
| P1-05 命名及按应用预设 | 已实现，单元测试通过 | 原子保存、版本白名单、大小限制、NR-only/整链/应用绑定、JSON导入导出；运行库路径本地隔离 |
| P1-06 事务切换与回退 | 已实现，真实故障注入通过 | 首个成功提交后才持久化 known-good；失败重建宿主一次并恢复画面/保存配置；浮层保存三方合并与回执；参数按实际 applied 确认 |
| P1-07 画质回归 | 已实现，GPU/WARP 通过 | 10个实际GPU残差用例、上游 temporal 回归；高运动实景素材主观评估未替代为合成通过 |
| P2-01 GPU 光流与质量档 | NVOF 已实现并实测 | 系统驱动 API5、双向光流、质量档；temporal隐式光流走已编译 NVOF；AMD OF 未编译，显式拒绝 |
| P2-02 实时 SR/FG 及准入限速 | 已实现，完整组合实测 | NR→DLSS SR 1.5x→DLSS FG2x 出帧；真实/生成帧分开；复用后端准入/节拍/反压。其他厂商原生后端未纳入本构建 |
| P2-03 端到端 HDR | 10月11日补齐自有HDR源实机功能测试，视觉验收仍待确认 | FP16/scRGB源→WGC→NR及NR/SR/FG在HDR主屏出帧，原生确认FP16且无回退；保留色彩元数据推断告警，未做色度/亮度校准 |
| P2-04 多显示器/DPI/GPU/OBS | 同DPI双屏与跨屏移动已实测，其他组合未验收 | 两屏均150%，主HDR/副SDR；物理坐标移动后持续出帧。五个同名DXGI项不是五张物理卡；混合DPI/双卡/OBS仍待验 |
| P2-05 性能与节能策略 | 四档组合与三分钟合成持续性通过；游戏性能未验收 | 整卡采样、真实/生成/提交分别记录，持续样本提交12372帧、NR失败0；不将整卡功耗当本进程开销、不外推游戏性能 |

## 环境与边界

- VS 2022 Build Tools 17.14.30，Windows SDK 10.0.26100.0 已存在；复用仓库 SDK。
- D3D11 调试层未安装，因此上游 temporal 用例中的调试层检查跳过；实际 shader/WARP 数值断言通过，不据此宣称调试层零警告。
- 当前主应用 Tkinter，既有图片/视频缓存与导出保留；实时像素处理放原生宿主，不经 Python 每帧搬运。
- 用户允许必要时采用 GPLv3；逐文件来源与专有运行库再分发仍须分别记录。开发接入不是公开发行授权。
- 当前未发布、未上传、未推送。临时目录和 4 GiB 任务预算见 `tmp/realtime-integration-20261003/TASK.md`。

## 已确认的实现边界

- 本次不是占位界面；本机已有实际原生 NR/SR/FG 输出及截图。入口已整合为主界面标题栏双向箭头按钮，单击直切「本地媒体 / 实时增强」，详见[双模式工作台记录](WORKBENCH_UI_20261003.md)及[标题栏与播放器布局更新](CAPTION_TOOLBAR_20261003.md)。本台账中的原生验收不等于本次 UI 的截图或游戏验收。
- 不使用采集卡、串流、播放器/音频或 RemotePlay。没有复制完整 Veyra 程序或已有 Torch/CUDA 环境。
- 原有离线图片、视频、缓存和完整导出走原链路；本次残差保护配置仅属于实时链路及其实时截图，没有偷换离线导出质量。
- 157 个目录效果定义不等于157个硬件后端可用；未编译的 XeSS/FSR2/3/4 native、RTXVideo、AMD OF 明确拒绝，普通 shader FSR/NIS 等仍可使用。
- SR/FG 测试只读取既有 Veyra experimental runtime 目录；未下载、修改或再分发专有 DLL。
- 根 LICENSE 已改为 GPLv3，旧 MIT 声明保留。固定提交、归档哈希、文件级 notices、429 个源码输入哈希及204个运行文件清单随构建生成；公共打包默认阻止未审核的组合。此许可处理不等于厂商同意再分发。

## 测试与报告

可重建报告在 `tmp/realtime-integration-20261003/probe-*.json`；11组小型归纳和原报告 SHA256 已保存为[验收证据 JSON](REALTIME_ACCEPTANCE_20261003.json)，由 `scripts/realtime_acceptance_summary.py` 重建。较早探针未记录二进制哈希，汇总保留 null，不能追溯冒充来自最新宿主。测试只选择本任务创建的合成窗口，不选择用户游戏或私人窗口。

| 用例 | 结果 |
| --- | --- |
| `nr-sr-fg-nvof` | NR50%、保护区、NVOF、antiFlicker2、SR1.5x、FG2x：真实121、生成117、提交238，NR失败0，正常退出 |
| `nr-sr-fg-final` | 最新宿主90秒，指定GPU0、非置顶、Reflex节拍；真实1079/生成1078/提交2157，NR失败0，正常退出；intensity=.65 实际applied确认；唯一报错为故意过期run_id的预期拒绝 |
| `nr-static-quality-final` | 最新宿主静止后强度修改：捕获33/NR33保持不变，提交33→34；quality revision2已应用，生成帧仍0 |
| `input-hotkey` | 实际点击得到源Canvas坐标(369,259)，点击数0→1；Ctrl+Alt+F10 后状态Scaling→Stopping→Idle，原窗口恢复；正常退出且0错误 |
| `gdi-windowed` / `dwm-windowed` / `wgc-fullscreen` | 有真实帧、正常退出、无原生错误 |
| `dd-fullscreen` / `dd-diagnostic` | OS AcquireNextFrame 持续超时，不伪装出帧 |
| `dd-explicit-wgc-fallback` | 5秒无首帧后提示切到 WGC，实际输出与退出正常 |
| `hdr-preflight-fixed` | 当前SDR显示环境拒绝HDR，未生成虚假HDR输出；早期 `hdr-preflight` 是发现flag被覆盖的失败证据，已被修复用例取代 |
| `probe-ui-rollback` | 真实宿主拒绝不可用后端，控制器重建后恢复Bilinear输出，saved_known_good=true |
| `nr-protocol-lifecycle` | 过期run_id故意拒绝（预期1项错误），对比切换及窗口resize/minimize/restore |
| 控制/构建/界面测试 | `tests.test_realtime`、`test_realtime_build`、`test_realtime_ui` 最终28项通过；覆盖旧状态不能提前确认新启动、quality命令回执与GPU revision一致、运行中错误回退、外部预设设备隔离 |
| 原生测试 | CTest 三项通过：实际GPU残差10用例、WARP temporal、CPU计数/环形缓冲；Release也保留断言；重复真实提交不计FG，会话重置清除旧取帧样本 |
| 原有工作流回归 | 图片/视频缓存、HDR、编码、FG、GUI更新器、updater、delta_update等124项通过；首次在C盘临时目录触发空间限制，转到本任务F盘目录后通过 |
| 完整测试集 | 最终清理后 unittest discovery 757项执行、747通过、10项环境条件跳过、0失败（120.293秒）。首次完整回归暴露打包布局fixture缺少实时清单，已补真实哈希清单fixture，不绕过发布门禁 |

合成Tk窗口在当前虚拟桌面更新约13帧/秒；它只能证明链路和指标契约，不能用来宣称60/120FPS游戏性能。组合链路短样本取帧→提交P95约70ms，90秒样本末段约85ms；后者与完整测试集同时运行，是功能持续性探针而非隔离性能基准。其中包含当前环境/初始化/时序影响，不是输入到光子延迟。必须进一步做目标游戏并发A/B与长稳。

## 复核命令

```powershell
./scripts/build_realtime.ps1
.venv/Scripts/python.exe -B -m unittest tests.test_realtime tests.test_realtime_build tests.test_realtime_ui -v
.venv/Scripts/python.exe -B scripts/realtime_window_probe.py --case nr-static-quality --effect NR --windowed --flow 2 --static-quality --seconds 14 --quiet
.venv/Scripts/python.exe -B scripts/realtime_rollback_probe.py
```

更完整GPU和工程回归应先把该进程的 TEMP/TMP 指向已登记任务子目录，不修改系统环境变量。UI验收使用 computer-use 查看实际窗口，已据此修复底部操作栏挤出和设置页溢出；不把widget单元测试代替视觉验收。

## 尚未满足的验收条件（不是已完成勾选）

真实游戏目标与反作弊兼容、相对鼠标、长时间并发性能、HDR实机、多物理显示器/混合DPI/多GPU、OBS共存及高速运动主观画质仍需在对应环境验收。当前1024×768 SDR虚拟桌面不能提供这些证据。功能入口未因此删除，不能把19项全部写成已验收。

## 仓库卫生收尾

已校验最终运行文件清单，再清理本任务的原生 `build` 中间目录与13个固定来源下载ZIP；永久删除，均可通过源码获取/构建脚本重建。没有删除旧依赖、模型、备份、用户改动或 `var/` 数据。

F盘清理前后可用空间 95,447,003,136 → 96,272,801,792 字节，实际增加825,798,656字节（约0.77 GiB）。本任务临时目录剩余约1.37 MiB，用于小型原始验收报告、失败诊断和最终CTest日志，2026-10-10复核。固定上游源码与可运行宿主是持久构建输入/产物，分别留在 `third_party/realtime` 和 `runtime/realtime`，不必为使用功能重新构建。

旧 `tmp/` 仍主要由既有依赖和备份占用（guidance-cuda-env约7.16 GiB，三个既有组件/备份目录各约4.43 GiB，guidance-probe-env约3.20 GiB）；没有将这些内容计作本次可删除缓存。已把本任务意外生成的0字节根日志移入任务日志目录，并修复原生直接启动的状态路径。
