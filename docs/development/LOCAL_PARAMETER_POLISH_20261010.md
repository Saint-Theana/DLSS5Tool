# 本地参数区减法与范围开关位置（2026-10-10）

## 交付范围

- 本地画面参数删除逐项复位、常驻整组复位、非默认计数；只保留“撤销调参”和“···”。无效输入仍就地提示，合法状态不占提示行。
- “···”收纳从实时复制参数和唯一的本地画面参数恢复入口。恢复须确认、可撤销，不更改预览方式、扩展范围、导出、队列、实时设置；未发生变化时不覆盖撤销记录。
- 更多菜单按右侧按钮向左展开，兼顾中文、英文及窄参数栏。
- 实时“扩展调节范围”移到“画面调整”的参数末尾、后续遍数之前。参数上限、旧高值迁移、范围检查及开关行为均未修改。
- “界面元素修正”改称“画面内 UI 修正（实验性）”，明确不是软件排版修正，不承诺自动识别或可靠保护 HUD／字幕；固定位置保护仍使用保护区域。保留原字段、数值及后端行为。

## 后续：顶部操作栏统一

按截图反馈将本地操作栏移到风格参数之前：左侧 DLSS NR，右侧撤销调参与更多，与实时模式一致；扩展范围仍在参数下方。两模式更多按钮改为现有 `more` 图标的 icon-only 控件，宽度约 36 逻辑像素并随 DPI 缩放，保留原按钮高度、键盘操作和悬停说明。没有改动设置或回退逻辑。

46 项参数统一、快捷键、范围测试通过（39.108 秒），涵盖中英文／深浅主题窄栏、操作栏顶部顺序、标题和按钮无重叠、更多按钮宽度，以及原来的恢复／撤销／复制回归。此次以真实 Tk 控件的几何断言验证，未另作人工窗口截图验收；`git diff --check` 通过。临时目录 `tmp/parameter-header-20261010/` 仅保留小型 TASK 登记，测试配置均由测试自动清理，2026-10-17 复核。

## 作用依据与边界

提交前补充：画面内 UI 修正的勾选框移到文字左侧，复用与扩展范围相同的 CheckToggle，文字可点击；第 2／3 遍同类字段同步调整。其他布尔参数的布局不变。57 项参数范围、统一操作、快捷键和双语测试通过（54.393 秒），新增中英文／深浅主题下实际控件坐标对齐，以及开关数值提交与撤销验证。本次测试配置自动清理，`tmp/ui-correction-align-20261010/` 只保留 TASK 登记，2026-10-17 复核；未打包或推送。

`third_party/realtime/magpie/src/Magpie.Core/DLSSNRFilter.cpp` 的参数构造读取 `uiCorrection`，`SetEvaluateParametersUnsafe` 将其提交给 `DLSSNR.UICorrection`。这证明开关接入了引擎，不能据此证明实际画质效果。

本次没有 GPU／游戏内 A/B 验证，也不把另一条 Veyra 管线的历史样本结论当作当前引擎的效果证明。只修正文案及操作布局，不增加渲染功能，不改变用户已有配置。

## 验证

- 参数统一、范围、双语：40 项通过，包含新增的菜单入口／对齐、取消不改值、集中恢复可撤销、编辑器重建保留值、无效提示及实时范围位置回归。
- 工作台、记忆、实时检查器、自定义快捷键、皮肤蒙版：97 项通过（315.636 秒）。合计 137 个不同测试；菜单最后对齐调整后重跑本地 7 项也全部通过。
- 因完整窗口回归运行较慢，额外以 100 秒总时限诊断重跑工作台；该重复运行触发总时限。触发时所在的停止按钮可用性用例单独重跑 3.097 秒通过。完整原始回归已通过，不把重复运行记作额外通过数量。
- computer-use 检查真实隔离窗口：中文浅色本地、中文深色实时、英文深色本地及更多菜单；位置与文字正常，探针回调错误均为空，`native_started=false`。探针使用普通 Tk 根窗口，已有拖放初始化提示不在本次验证范围内；未导入素材。
- `git diff --check` 通过。未改原生引擎、未构建／打包、未提交／推送。

复现命令（复用 `.venv`，TMP/TEMP 指向任务目录）：

```text
.venv/Scripts/python.exe -B -m unittest -v tests.test_parameter_unification tests.test_parameter_range tests.test_realtime_i18n
.venv/Scripts/python.exe -B -m unittest -v tests.test_workbench_ui tests.test_workbench_memory tests.test_realtime_inspector tests.test_realtime_shortcuts tests.test_realtime_skin_mask
.venv/Scripts/python.exe -B scripts/realtime_panel_probe.py --mode local --language en_US --theme dark --geometry 1280x900 --no-screenshot --hold-seconds 180 --work-dir tmp/local-parameter-polish-20261010/local-en
```

## 临时产物

任务目录 `tmp/local-parameter-polish-20261010/`，初始 F 盘空闲 94,798,475,264 字节，预算 100 MiB。复用依赖，没有下载或大文件生成。

确认测试与探针退出、无代码引用或链接后，仅删除本任务 `local`、`local-en`、`realtime`、`tmpd54s3mwe` 中的模拟配置／队列，合计文件 11,425 字节，可由探针或测试重建。清理时磁盘空闲 94,798,438,400 → 94,798,454,784 字节，净释放 16,384 字节。其他任务与用户设置未动；仅保留约 1 KiB 的 TASK 登记供归属审计，2026-10-17 复核。
