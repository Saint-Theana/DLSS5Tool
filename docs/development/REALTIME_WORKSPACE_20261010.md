# 实时工作台信息架构落地（2026-10-10）

## 范围

用户选择紧凑会话栏、预设分类切换、参数单层分组；本轮在原有工作树上继续修改，
不撤销此前来源截图／日志等改动。不修改原生渲染、参数范围、预设格式、版本号；
不构建 EXE，不打包、提交、推送或发布。

## 布局与保留能力

- 左侧自动布局改为约 340～400 逻辑像素的会话栏，仍可拖动分界；手动尺寸优先。
- 右侧四页：画面、算法与流程、输出、高级；页签可聚焦后用左右键切换。
- 常驻「算法库 · N」按当前目录动态计数。完整库与处理流程独立，不再叠套折叠；
  分类、搜索、收藏、不可用说明全部保留，并增加清除筛选。
- 默认添加新步骤，卡片上的更换操作进入明确的替换模式，显示步骤编号、参数重置提醒与取消。
  按用途选择作为库的同级单层分组保留；变体、排序、移除、撤销仍使用原有实现。
- 精细调整改为静态标题，参数组均为直接子节点。第 2／3 遍位于常用参数之后，
  启用与展开独立；关闭第 2 遍仍连带关闭第 3 遍但保留数值。
- 修复多遍标题被新建兄弟 Frame 遮挡：显式提高 Canvas 窗口堆叠层级（不能调用 Canvas 的 tag_raise）。
  标题支持换行，开关显示「启用」，分组计数明确为「已调整 N 项」。
- 输出页集中显示尺寸、插帧、同步、目标帧率、性能策略；仍区分输入处理分辨率、步骤尺寸、窗口倍率。
- 捕获、命名 GPU 选择、运行库／诊断在高级页分组；原始设备编号与保护坐标可按需展开。
  命名设备选择反映已保存 ID，未枚举的设备明确提示，不能默默变成自动设备。
- 预设沿用「完整配置／仅 NR 画质」分类；绑定应用的预设名称显示在折叠区外。
- 保护区仍共用同一份数据，来源截图显示区域数量；原始坐标入口可直接定位高级页。
- 对比、画面内参数、性能统计和增强输出截图常驻左下方；输出未确认时禁用，停止入口不受滚动影响。
- 实时模式隐藏本地待机状态，后台本地导出／队列状态仍保留。

## 验证方式

复用 `.venv`；TEMP/TMP 指向 `tmp/realtime-workspace-20261010/`，禁止写入 Python 字节码。

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:TEMP='F:\project\DLSS5Tool\tmp\realtime-workspace-20261010'
$env:TMP=$env:TEMP
.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_realtime*.py' -v -f
.venv\Scripts\python.exe -m unittest -v -f tests.test_workbench_ui tests.test_workbench_memory tests.test_parameter_range tests.test_parameter_unification tests.test_i18n tests.test_realtime_workspace.RealtimeWorkspaceTests.test_tab_keyboard_navigation_and_region_summary_are_non_mutating
```

隔离界面探针（模拟引擎与窗口；禁用实际来源截图）：

```powershell
.venv\Scripts\python.exe scripts/realtime_panel_probe.py --work-dir tmp/realtime-workspace-20261010 --language zh_CN --theme dark --geometry 1280x960 --full-catalog --no-screenshot --hold-seconds 240
```

本机该探针正常退出，`callback_errors=[]`、`native_started=false`，启停区与分界可见。
computer-use 的目标窗口截图授权超时，未取得实际视觉截图；不声称完成截图视觉验收，
也没有改用其他截图方式绕过授权。深浅主题、双语、窄栏标题与开关几何由 Tk 回归检查。

首轮回归发现流程提示的旧挂载位置，修正为流程卡片之后；第二轮发现 Canvas 的
`tkraise` 是 tag_raise 别名，已改为明确的窗口 raise 并通过多遍标题遮挡检查。

## 最终验证结果

- 实时回归：255 项通过，399.478 秒，退出码 0。
- 工作台、记忆、参数范围／统一性、国际化，以及最后补充的页签键盘导航／保护区摘要回归：
  78 项通过，213.403 秒，退出码 0。
- 两条完整回归命令共 333 项通过；此前重复执行的定向检查不额外累计。
- 收尾移除重复的页签绑定与同名方法定义（行为不变）；再次执行
  `tests.test_realtime_workspace`，10 项全部通过，18.692 秒，退出码 0。
  这 10 项属重复验证，不额外计入 333 项；相关源码／测试的重复方法结构检查通过。
- Tk 回调异常会使测试失败；布局检查覆盖主题、语言、窄栏、标题遮挡和非破坏性页签切换。
- 未启动真实增强，未验证原生引擎／GPU 兼容性；完整库探针使用模拟元数据，
  不代表这些算法均可在当前设备运行。窗口截图授权超时，人工视觉验收未完成。
- 未构建或更新现有 EXE；本次交付为源码、回归用例、探针与用户指南。

## 临时文件收尾

- 已确认本轮探针及测试进程退出；任务目录与目标文件无符号链接／目录联接，
  源码及脚本不依赖生成的两个配置文件。
- 仅删除 `tmp/realtime-workspace-20261010/settings.json`（2,823 字节）与
  `queue.json`（35 字节）；它们是隔离模拟探针的可重建配置，并非用户设置或队列。
  删除不经过回收站，可用上述探针命令重新生成。
- 删除前 F 盘可用 94,811,144,192 字节，删除后 94,811,148,288 字节，
  实测可用空间增加 4,096 字节。
- 本轮未生成截图；临时目录仅保留不足 2 KiB 的 `TASK.md` 供审计与重建，复核日期 2026-10-17。
  旧任务目录、依赖、环境、备份均未清理。
