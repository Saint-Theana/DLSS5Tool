# 实时工作台布局升级（2026-10-08）

范围：落实用户确认的布局方案 1～4；第 5 点未采用，保留模式切换反色和上次模式/主题记忆。
仅修改源码 UI、文案、测试和模拟探针。不构建原生程序、不打包、不操作用户实际增强会话。

## 分区与层级

- 右侧从四页整理为「调整 / 输出 / 高级」，参数区适度加宽，自适应工作台宽度。
- 「调整」顶部保留内置画面方案，个人预设/参数复制入口集中折叠；随后直接展示当前效果的
  常用参数与撤销。原有风格、开关、数值、滑条和范围/重置行为不变。
- 多遍、输入分辨率、其他参数收纳在「更多画面参数」；插帧、残差合成、保护区域、
  处理流程与算法分别折叠。算法库、排序、替换、完整参数及原有预设管理均保留。
- 「输出」承载窗口/全屏、显示器、倍率、同步与帧率等；「高级」承载捕获、设备、
  兼容性、运行库与诊断。错误定位沿实际控件祖先查找页面，并展开所需折叠区后滚动定位。
- 左侧不再放大面积归一化保护示意图，只保留来源、实际会话、画面控制与运行数据。
  保护示意图移至「调整 → 保护区域」，仍为比例编辑器，不是源窗口预览。
- 日志默认收起，错误和停止提示仍可见；运行详情按需展开。正常生命周期不再重复占据通知行，
  完整状态仍写入日志。主应用的日志展开状态继续由两种工作模式共用。

## 交互和安全边界

- 开始/停止始终留在固定操作区，底部操作区优先分配空间；运行中开始按钮禁用，
  只有实际需要应用重启时右侧才出现对应动作，不再同时常驻一个可点击的重启入口。
- 画面对比、画面内参数、统计与截图仍调用原有原生输出，首帧确认之前或停止期间禁用入口。
- 下拉框表示待编辑来源，独立会话摘要只读正在运行的目标。选择其他窗口不自动切换；
  点击「切换并重启」前，参数和保护区草稿不向原目标提交。重新选回原目标且无参数差异时，
  待切换动作消失。现有开始前检查、停止、原生回执和恢复流程继续有效。
- 参数提交入口也检查来源身份：即使旧会话的保护区回执尚未到达、编辑器暂处于「应用中」，
  新来源参数也只保留草稿，不发送给原会话，不清空原会话仍待确认的请求。
- 隐藏/展开页面不销毁控件，不丢失未完成输入，不发送参数，不自动开启额外遍数。
- 不新增快照、内嵌实时预览、字幕/HUD 识别或跟踪，不调整算法、参数步进或渲染管线。

## 验证

复用 `.venv`，TEMP/TMP 隔离到本任务目录；原生客户端、来源窗口和参数数据均模拟。
首轮发现的旧页面位置断言已改为新入口的可达性断言，不放宽数值、启停或回执的行为约束。
最小窗口尺寸变化后的原生 Configure 事件使用完整 Tk update 处理后检查实际位置。

```powershell
$env:TEMP='F:\project\DLSS5Tool\tmp\realtime-layout-20261008'
$env:TMP=$env:TEMP
$env:DLSS5TOOL_DISABLE_UPDATE_CHECK='1'
.venv/Scripts/python.exe -B -m unittest tests.test_realtime_inspector tests.test_realtime_panel_sync tests.test_workbench_ui tests.test_workbench_memory tests.test_workbench_transition
.venv/Scripts/python.exe -B -m unittest tests.test_realtime_layout tests.test_realtime_ui tests.test_realtime_readiness tests.test_realtime_effects tests.test_realtime_skin_mask tests.test_parameter_range tests.test_parameter_unification tests.test_realtime_i18n tests.test_i18n tests.test_gui_player
# 日志断言更新、目标隔离边界修复后的受影响范围复验
.venv/Scripts/python.exe -B -m unittest tests.test_gui_player
.venv/Scripts/python.exe -B -m unittest tests.test_realtime_layout tests.test_realtime_inspector tests.test_realtime_panel_sync tests.test_realtime_i18n tests.test_i18n
.venv/Scripts/python.exe -B scripts/realtime_panel_probe.py --work-dir tmp/realtime-layout-20261008 --scenario restart --theme dark
.venv/Scripts/python.exe -B scripts/realtime_panel_probe.py --work-dir tmp/realtime-layout-20261008 --scenario idle --language en_US --theme light --page display
.venv/Scripts/python.exe -B scripts/realtime_panel_probe.py --work-dir tmp/realtime-layout-20261008 --scenario idle --theme light --page protection
.venv/Scripts/python.exe -B scripts/realtime_panel_probe.py --work-dir tmp/realtime-layout-20261008 --scenario idle --language en_US --theme dark --page runtime
```

视觉检查：中文深色调整页（待重启）、英文浅色输出页、中文浅色保护区域、英文深色高级页
均无回调异常、未启动原生捕获。操作按钮、页签、长英文和展开后的保护编辑器未见重叠或越界。
探针请求 1000×680，受主应用高 DPI/最小尺寸约束，实际截图为 1471×1021；不将截图当成
物理 1000×680 验收。800×600、1000×680、1280×800 的独立工作台边界由自动测试检查。
探针只截取自身窗口，不捕获用户素材；四次均 `native_started=false`、`callback_errors=[]`。

回归结果（去除重复执行后共 325 项）：

- Inspector、面板同步、工作台、模式/主题记忆及过渡首组 98 项通过。
- 布局、实时 UI、启动检查、效果、皮肤蒙版、参数范围/统一、中英文、本地播放器组：
  最初 226 项中 224 项通过，2 项为日志默认收起后的旧断言；修正后播放器 78 项全部通过。
- 新增 1 项「旧保护区回执未到达时切换目标」测试，先复现错误发送，再在提交入口拦截；
  最终重跑布局、Inspector、面板同步和中英文共 88 项全部通过（包括该新增项，其他为复验）。
- `git diff --check`、Python AST 语法与两份语言 JSON 检查通过。
- Tk 测试和截图探针串行运行。未验证真实游戏/GPU/HDR/多屏兼容，不把模拟结果当作原生验收。

临时目录回收：核实进程已结束、目录/文件无链接且无运行依赖引用后，仅删除本任务的 6 张
模拟截图及 `settings.json`、`queue.json`，共 8 个文件、731,618 字节。删除窗口内 F 盘
可用空间从 96,297,791,488 增至 96,298,532,864 字节，净增 741,376 字节（含文件系统分配差异）。
这些文件不进回收站，可用上面的探针命令重建；用户配置、旧依赖及其他任务产物均未改动。
任务目录仅保留小于 2 KiB 的 `TASK.md` 作为预算/复现/清理记录，2026-10-15 复核。
