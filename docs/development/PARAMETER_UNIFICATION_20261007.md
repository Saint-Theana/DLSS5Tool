# 本地／实时参数交互统一

2026-10-07。用户同意其余统一性调整，但质疑「局部色调／局部结构」的改名；本轮保留「本地色调／本地结构」。仅修改 Python 工作台、文案和测试，不修改增强算法、shader 或各后端默认值。

## 上游名称核对

| 本地只读参考源码 | 原文 |
| --- | --- |
| `tmp/dlss5standaloneV2/gui.py` 第 397、399 行 | 本地色调、本地结构 |
| `third_party/realtime/magpie/src/Effects/DLSSNR/DLSSNR_AI_Filter.hlsl` 第 119、128 行 | Local Tone Strength、Local Structure Strength |
| `third_party/realtime/veyra/apps/veyra/SettingsWindow.cpp` 第 72 行 | 局部明暗、局部结构 |

「局部色调」是此前建议，不是这些参考项目统一采用的中文名称。技术参数 ID 不翻译，界面延续用户认可的本地术语。

## 已实施

- 两边共有参数统一为风格、强度、本地色调、本地结构、皮肤蒙版；输出混合单列输出合成。预览入口使用「原图／增强／对比」，实时预设页签使用「参数预设」，不改算法名称或内部视图 ID。
- 实时第 1／2／3 遍强度、色调、结构增加同一行的开关，沿用本地的关闭记忆值／按零生效规则。皮肤蒙版沿用上一轮配对行为。
- 本地复用 `ParameterRow`，补齐单项／整组恢复、一步撤销、非默认反馈；恢复和撤销包含开关。仅修改输出混合时保留昂贵的增强缓存。
- 两边共享有限数值及百分比解析，精细数值不按滑条步长强制量化，无效／越界输入就地显示原因，不静默截断手工输入。本地导出、入队和向队列应用参数先校验草稿。
- 本地关闭实验范围时收回超限数值的既有行为不变；本地默认上限 1、实验上限 5，实时参数范围仍来自元数据，不强求相同。
- 双向复制明确列出覆盖内容并确认，限唯一 NR 步骤第一遍的五个共有参数及开关。不带入输出混合、保护、后续遍数、其他效果、捕获、设备、显示或导出设置；不改已排队任务。越界整次拒绝，不自动开启实验范围。
- 实时复制只改草稿，可撤销；清除先前排队的自动参数提交，避免旧手势确认后提交新复制值。不启动／重启，也不立即改变运行参数；后续主动调整／应用沿用已有规则。本地复制按原来的预览更新规则生效。

## 状态边界

- `disabled_parameters` 是效果配置中的可选 UI 记忆列表，仅允许内置 NR 三遍的强度／色调／结构 ID；预设与会话保留记忆原值，旧预设缺字段按开启处理。
- `effective_nr_skin` 现同时处理普通标量开关和皮肤参数对，向原生引擎提交前移除 UI 字段并转换有效值。`RealtimeClient.start` 也执行边界转换，避免其他调用者漏做。
- 确认后的运行状态只恢复有效值已经匹配的记忆，不能把其他待应用草稿冒充已生效值。热更新依然等待原生确认，需重启参数不部分提交。
- 旧预设可在当前版本载入；包含新开关字段的预设不承诺能被旧程序读取。皮肤蒙版本身继续使用原来的两个原生字段。
- 本地保留原 Tk 变量／控件入口，使用适配层分开原始输入草稿与有效参数。无效草稿不写入渲染参数；撤销可恢复无效文本以便修正。

## 验证与复现

复用 `.venv`，所有实时宿主均为测试替身，无真实捕获、推理或大型构建。

```powershell
$env:TEMP = 'F:\project\DLSS5Tool\tmp\parameter-unification-20261007'
$env:TMP = $env:TEMP
$env:DLSS5TOOL_DISABLE_UPDATE_CHECK = '1'
.venv/Scripts/python.exe -B -m unittest tests.test_parameter_unification tests.test_realtime_inspector tests.test_realtime_ui tests.test_realtime_skin_mask tests.test_realtime_i18n tests.test_realtime tests.test_realtime_effects tests.test_workbench_ui tests.test_gui_player.WidgetSmokeTests.test_closed_switch_sends_zero_and_remembers
.venv/Scripts/python.exe -B -m unittest tests.test_gui_player.SettingsPanelPersistenceTests tests.test_gui_player.EffectiveSliderTests tests.test_gui_player.OutputViewTests tests.test_preview_switches tests.test_preview_feedback tests.test_layout
.venv/Scripts/python.exe -B -m unittest tests.test_parameter_unification.TransferIntegrationTests.test_invalid_local_draft_blocks_queue_and_export tests.test_i18n
```

- 参数测试覆盖百分比／有限数值／精细数值、九个开关的记忆与原生隔离、旧／新预设往返、拒绝未确认记忆、第一遍复制边界、超限拒绝、恢复撤销、输出合成缓存回调、跨模式确认／取消、旧提交排队与新草稿隔离、无效输入阻止导出／队列。
- 几何断言覆盖本地中英文最小检查器宽度与深浅主题；实时皮肤组合控件覆盖中英文、深浅主题以及 800×600／1000×680。未进行像素级截图或真实游戏画质验收。
- 第一组 152 项通过，352.744 秒；第二组 41 项通过，4.551 秒。队列校验补充与多语言最终复核 14 项通过，3.522 秒（含第一组已运行的一项再次验证）。新增参数统一测试文件包含 16 项测试。
- `git diff --check` 定向检查通过；既有换行提示未涉及内容错误。未提交、推送或打包，保留工作区原有修改。

## 仓库卫生

开始及收尾检查 F 盘可用约 89.65 GiB；tmp 上次盘点约 29.45 GiB，超过 20 GiB 预警，因此本轮只预算 20 MiB 小型夹具。不复制依赖／模型，不下载、不打包，不清理已有目录。任务登记位于 `tmp/parameter-unification-20261007/TASK.md`，2026-10-14 复核；测试夹具已自行回收，收尾仅剩不足 2 KiB 的归属记录。未额外执行删除，不声称释放已有空间。
