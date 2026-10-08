# 参数小数显示与扩展范围升级

2026-10-07，按用户确认升级本地／实时工作台交互。未修改增强算法、原生宿主、shader、原生画面内面板或运行上限，不打包、不发版。

## 结果

- 修复原生 float32 步长的显示污染：`0.05` 序列化为 `0.05000000074505806` 时不再被当成多位小数精度。步长做展示规范化；常用值显示 `1.00`、`0.75`。同一 float32 表示的数值尾差可收敛显示，但手动精细值不按滑条步长强制舍入；整数、细步长和未知效果仍保留各自格式。
- 两边统一为「扩展调节范围」，标出各自上限；默认 0～1.00，本地最高 5.00，实时常用参数最高 2.00（实际读取元数据）。本地仍使用原 `enable_5x` 持久键，避免破坏设置兼容。
- 实时同一开关作用于三遍强度／本地色调／本地结构／皮肤蒙版；不影响残差合成、其他效果及风格枚举。本地范围仍覆盖这四项和输出混合。
- 滑条下方标出 0、1.00 与扩展上限，1.00 是常规处理强度参考，不是画质百分比。中英文提示均更新。
- 关闭范围前检查相关全部原始输入，包括关闭参数及未启用遍数的记忆值。超出 0～1 或无效输入时列出并提示先调整，保持扩展开启，不自动截断、不改变值。
- 本地旧配置里 1～5 的合法值自动开启扩展并保留；实时载入高值自动展开，超出实际后端上限仍报错。撤销恢复高值时同步恢复所需范围。
- 跨模式复制遵守目标当前选择的范围；不会借复制自动开大范围。单独切换实时范围不会提交已有数值草稿、启动或重启。

## 数据边界

- 实时效果新增可选 UI 字段 `extended_range: true`，白名单仅允许内置 NR、严格布尔类型；关闭不存字段。完整预设、NR-only 预设与已确认会话可携带该偏好。
- `effective_nr_skin` 提交边界移除该 UI 字段；保留原生字段名、类型、上限、步长。恢复会话时只保存范围偏好与已确认的数值记忆，不将未应用的数值草稿存成运行状态。
- 行控件将「当前可调上限」与「原生上限」分开，避免修改共享 catalog、使复制误认后端能力或影响第三方效果。
- 旧设置无需手动迁移；包含新增字段的预设不承诺旧程序可以导入。

## 步进核对与保留事项

实时 `DLSSNR_AI_Filter.hlsl` 三遍常用浮点项声明步进 0.05；原生 `EffectParameterValue.h`、`ScalingRuntime.cpp`、`Renderer.cpp` 与 `OverlayDrawer.cpp` 都有按该步长归一化的路径。因此本轮保留实时 0.05、本地 0.01，不在 Python 一侧虚构 0.01 原生精度，也不放开实时 5×。

输入框保留精细草稿是编辑行为，不代表原生运行值支持相同精度。进一步统一步进需要连同原生面板、提交确认和运行验证另做，不包含在本轮交付；本轮没有真实游戏画质或 GPU 验证。

## 验证

复用 `.venv`，模拟实时宿主，不捕获外部窗口、不加载推理环境。

```powershell
$env:TEMP = 'F:\project\DLSS5Tool\tmp\parameter-range-20261007'
$env:TMP = $env:TEMP
$env:DLSS5TOOL_DISABLE_UPDATE_CHECK = '1'
.venv/Scripts/python.exe -B -m unittest tests.test_realtime_inspector tests.test_realtime_skin_mask tests.test_realtime tests.test_realtime_ui tests.test_workbench_ui tests.test_realtime_effects tests.test_parameter_unification tests.test_gui_player.SettingsPanelPersistenceTests tests.test_gui_player.EffectiveSliderTests tests.test_gui_player.WidgetSmokeTests.test_closed_switch_sends_zero_and_remembers tests.test_realtime_i18n tests.test_i18n
.venv/Scripts/python.exe -B -m unittest tests.test_parameter_range tests.test_preview_switches tests.test_preview_feedback tests.test_layout
```

- 主回归 173 项通过，220.783 秒；最终范围／预览／布局回归 37 项通过，16.135 秒，共 210 项。
- 新增 11 项范围测试覆盖真实 float32 元数据、精细值、整数、旧配置、高值迁移、关闭拦截、隐藏遍数／关闭参数记忆、预设、原生边界、复制范围、撤销、无提交／无重启。
- 中英文与深浅主题、800×600 控件几何断言通过；原有本地最小检查器宽度和实时皮肤控件布局回归也通过。未执行截图像素级验收。
- 定向 `git diff --check` 通过，既有 CRLF 提示保留；未提交或推送，原工作区修改未回退。

## 临时文件

开始／收尾 F 盘可用约 89.72 GiB，tmp 约 29.45 GiB，超过 20 GiB 预警。最大既有目录为 guidance-cuda-env 7.163 GiB、三套已有备份各 4.433 GiB、guidance-probe-env 3.199 GiB；不触碰这些目录。任务预算 20 MiB，仅生成小型测试夹具。

所有夹具已自行回收，`tmp/parameter-range-20261007/` 仅留不足 2 KiB 的 TASK.md 作归属和重建记录，2026-10-14 复核。未额外执行删除，不声称释放已有空间；无构建或下载产物。
