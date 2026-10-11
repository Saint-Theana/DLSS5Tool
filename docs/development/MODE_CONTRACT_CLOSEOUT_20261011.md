# 双模式复用清单：P0 / P2 收尾（2026-10-11）

基线 `main@df74d1e`。以用户截图“调整后的落地清单”为准，**不使用实时功能路线的阶段编号**。
本轮完成下表五项的实现、回归与本机合成源验证；不代表所有游戏/显示器/冻结发行包已验收。
2026-10-11 用户确认将本轮代码、测试和验收证据一并提交到本地 Git。
未更改版本号、未推送、未打包或发布；忽略的运行二进制、模型与临时回滚不入库。

## 截图逐项对账

| 优先级 / 工作包 | 落地结果 | 保留的执行边界 |
| --- | --- | --- |
| P0 统一参数定义 | `parameter_contract.py` 集中维护共享名称、范围、默认值、分组、能力、生效和失效规则；接入本地设置、两侧参数行、校验、互拷、诊断 | 原生 catalog/实时更新模式回执仍决定实际能力。保留历史默认差异（本地肤色强度 1、原生 0）及用户已有值；范围取共享合同与安装后端交集，不放宽后端限制 |
| P2 单次 NR 残差细调 | 五项 SDR/HDR 细调均可用；HDR 增加独立线性残差实现、原生能力握手和实机验证；本地 HDR NR-only 预览接入高精度共享渲染，不再先转 SDR 后细调 | 实时首个 NR 的单次细调；需要显式启用残差资源。HDR 保持 100% 输入分辨率，不支持时阻止启动，不自动降低画质 |
| P2 分组预设与互拷 | 基础 NR、残差细调、全局合成、保护区可分组选取；通用 JSON 往返、旧设置中性默认、局部复制及撤销验证；补齐目标后端残差范围校验 | 不复制窗口、设备、路径、多通道、快捷键；区域显式勾选；拒绝不支持/越界项且不部分写入；实时复制只改草稿，不自动启动 |
| P2 统一操作与能力反馈 | 共用数值校验和参数行、状态语义；保持原有应用/撤销/恢复事务；新增本地待渲染/更新中/已生效/失败反馈，实时区分待重启与当前不支持；对比使用共同语义名 | 旧完成事件不能确认新草稿；无效草稿不进渲染。两边展示与执行适配器不合并，实时热更新以匹配会话的回执为准 |
| P2 缓存、重置与诊断 | 统一基础参数→NR/合成/FG、外观参数→合成/FG的失效层级；合成版本只进入派生身份；本地和实时报告共用 schema/state/generation/capabilities/runtime/last_invalidation 字段 | 原始 NR 缓存不因细调/全局/保护区重建；运行库“配置选择”和“已加载”不混称；两边 GPU 会话、历史帧和缓存仍独立 |

P1 全局合成、保护区、预览/导出贯通沿用已落地能力，本次补验 HDR、原始对比侧和缓存复用。
P3 光流/安装体积和资源协调仍是独立清单；本轮不将其算作新的完成项，不裁剪 DLL/Torch/模型。

## HDR 的具体语义

- SDR 保持原始存储 RGB/HSL 算法；五项中性值为 1，不改写旧画面。
- HDR 先在线性光域计算 `processed - original`，按整像素亮度差选择阴影/高光倍率，
  再分别调整亮度差和颜色差。PQ/HLG 使用 Rec.2020 权重；实时 scRGB 使用 Rec.709 权重。
  scRGB 保留负值及高于 1 的高光，不做 SDR 白位裁切。区域保护随后作用，旧输出混合仍独立。
- 本地 HDR 预览在高精度处理完成后才做显示用 tone mapping；导出保留 HDR。
  修复旧输出混合将 scRGB 误按 HLG 解码的问题。
- 实时宿主广播 `appearance_hdr_residual_version=1`；旧/未知/过期代次宿主不能冒充支持。
  未启用的旧预设休眠细调值不会因此被改写或阻止启动。开启 HDR 并要求非 100% NR 输入时，
  Python 启动检查和原生启动入口均明确拒绝。
- 相同数值不保证跨模式逐像素相同：采集、色域、时域、NR 调用路径仍有差异；不是把 SDR HSL 强套到 HDR。

## 验收证据

小型证据归档于同目录 `mode-contract-closeout-20261011/`。各批次有重叠，不把执行次数相加成独立测试数。

- 核心纯逻辑回归：97 passed、34 subtests，见 `core.xml`。包含参数合同、往返、HDR 数学、
  预览路由、原始画面保持、缓存身份、原生生成规则、启动能力检查。
- 界面回归：`ui.json` 145/145；末轮异步/诊断及 HDR 能力代次补测 `ui-closeout.json` 48/48。
  HDR 序列与参数范围测试另按独立进程运行，`ui-hdr-range.json` 53/53；三批去重共 199 项全部通过。
  独立进程用于隔离 Tcl 生命周期；
  先前合并执行的 150 项虽全部通过，但有一次 Tk 析构线程警告，因此不以那批作为最终无警告证据。
- 原生 Release 构建、CTest 8/8，见 `native-tests.txt`。新增 HDR shader 在 WARP 和真实 D3D11 GPU
  上分别通过 7 组单项/组合参数，含奇数尺寸、零残差、有符号值、高光与 alpha 的标量参考比对。
- 本地真实 GPU：SDR 和 HDR10/PQ 各 320×192、4 帧自建源。渲染缓存与参考合成逐像素相同；
  调整全局量后原始 NR 会话保持，导出 4 帧缓存命中、0 新推理，重新解码 4 帧。
  HDR 输出为 `yuv420p10le / bt2020 / smpte2084`。见 `local-sdr.json`、`local-hdr.json`。
- 实时真实 GPU：自建 SDR/scRGB 窗口，五项细调均 live，状态回执确认所有目标值；全局量修改确认生效，
  NR 错误 0，正常退出。最终候选 HDR 日志确认 FP16、DirectFP16、HDR 显示、输入分辨率 100%。
  见 `realtime-sdr.json`、`realtime-hdr.json`、`realtime-hdr.txt`（原始宿主日志，仅清理行尾空格）。
- 初次沙箱 WGC 返回 `0x80070424`，未计为渲染通过；获准使用正常桌面后完成。
  首次 HDR 测试素材编码没有保留传递函数标签，探针断言失败；改用带明确 PQ 元数据的合成素材，
  并增加源标签断言后重验通过，未更改生产代码绕过验证。
- `git diff --check`、本地实时组件清单的大小/SHA-256 校验通过。

## 开发运行组件与回滚

已将验证后的宿主放入 `runtime/realtime/dlss5_realtime_host.exe`，同时更新清单。
只有 EXE 与 `build-manifest.json` 替换，原有许可证/效果文件保留；未复制模型或 GPU DLL。
宿主 3,318,784 bytes，SHA-256：
`2173118b2e3284e79fdf3d54d978abe0c1118380993906cfd0432a624428dccc`。
该体积变化不是 P3 依赖裁剪或发行包体积承诺。204 个输出文件已逐个校验。

本次替换前的宿主与清单保存于 `tmp/mode-contract-closeout-20261011/rollback/`。
旧宿主 SHA-256 为 `84364eca7afd1478a9a1db199803d004c2917f377e74ba065963ef1ac6702968`。
回滚需先关闭应用/实时宿主，再恢复这两个同名文件，并运行
`scripts.realtime_packaging.validate_runtime('runtime/realtime', local_candidate=True)`；不要重新 stage 回滚清单。
复核日期 2026-10-18，不自动删除。其他任务已有回滚未动。
运行组件仍为 `local-validation-only`，分发许可审核状态未改变。

## 复验入口与交付边界

先遵守仓库卫生守则，在新的 `tmp/<task>/` 登记预算并复用现有 `.venv`。

```powershell
.venv/Scripts/python.exe -B scripts/appearance_gpu_smoke.py --output tmp/<task>/local-sdr
.venv/Scripts/python.exe -B scripts/appearance_gpu_smoke.py --output tmp/<task>/local-hdr --hdr
.venv/Scripts/python.exe -B scripts/appearance_validation.py --output tmp/<task>/ui --tests tests/test_parameter_unification.py tests/test_parameter_response.py tests/test_realtime_inspector.py
```

原生以 `native/realtime` 配置 CMake/VS2022 x64 Release，复用固定 SDK，指定任务内唯一 candidate。
构建 `realtime_test_source` 后，以 `scripts/realtime_window_probe.py --effect NR --residual-test --static-quality`
运行自建源；HDR 额外传 `--source-hdr --hdr`，并检查 `residual_confirmed`、HDR 日志和输出计数，
不能只看启动成功。每次探针输出使用新的隔离子目录。

工程收尾无需用户重复自动测试；可选用常用素材/游戏确认 HDR 高光、暗部及调参手感。
显示器主观画质、真实游戏长稳、所有设备组合及正式发行验收不在本次完成声明内。

构建、候选、测试缓存和合成媒体在证据归档后清理；仅保留本轮回滚及 TASK 登记。
已清理 22 个精确目标，按 F 盘前后差值释放 536 MiB；本轮临时目录剩约 10.01 MiB，
仅为回滚与归属登记，复核 2026-10-18。删除的中间产物不经回收站，可从仓库脚本重建。
