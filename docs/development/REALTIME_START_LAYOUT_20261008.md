# 实时启动区布局集中 · 2026-10-08

## 采用的布局

- 左侧按来源窗口、画面方案、输出方式、启动检查、画面控制排列。个人预设与参数复制在画面方案下默认折叠，方案撤销继续使用回退箭头。
- 全屏／窗口切换只有左侧一个编辑入口；「更多输出设置」进入右侧「输出」，调整显示器、倍率、同步及帧率。右侧顶部只读「当前草稿」摘要不代表实际运行状态。
- 保护区域保留在右侧「调整」中默认折叠，与残差合成相邻：它属于画面细调，不是每次启动的必选项。示意图仍只是区域编辑器，不是实时预览。
- 左侧设置区可独立滚动；实际会话、紧急退出说明、关键通知、简要指标与开始／停止固定在底部。右侧仍为「调整／输出／高级」三页。
- 定位已移到左侧的控件不切换右侧标签；定位预设会展开其折叠分组，启动检查会滚动到检查结果。帮助继续使用悬浮说明，不恢复 ⓘ 或展开正文。

## 实现边界

`dlss5tool/realtime_ui.py` 复用滚动页构造、增加左侧固定底部及单一输出入口；
`dlss5tool/realtime_controls.py` 使左侧短提示沿用 Stage 背景；中英文文案与使用指南同步。

不修改 shader、原生渲染、参数步长或输出算法；不自动启动、提交草稿或重启增强。
模式／主题记忆、主动切换模式时的反色、目标切换确认及安全停止语义保持不变。
未打包 EXE，未提交、推送或发布。

## 回归验证

两组共 **212 项测试通过**，按不同测试模块计数，不累计重复运行：

```powershell
$env:TEMP='F:\project\DLSS5Tool\tmp\realtime-start-layout-20261008'
$env:TMP=$env:TEMP
$env:DLSS5TOOL_DISABLE_UPDATE_CHECK='1'
.venv\Scripts\python.exe -B -m unittest tests.test_realtime_layout tests.test_realtime_ui tests.test_realtime_readiness tests.test_realtime_effects tests.test_realtime_panel_sync tests.test_workbench_ui tests.test_realtime_i18n tests.test_i18n
.venv\Scripts\python.exe -B -m unittest tests.test_realtime_inspector tests.test_workbench_memory tests.test_workbench_transition
```

- 第一组 166 项，第二组 46 项。新增布局测试覆盖左侧归属、保护保留、预设展开、右侧标签不变、只导航不提交及只读草稿摘要。
- 展开预设与运行详情后，在深／浅主题及 800×600、1000×680、1280×800 工作区检查固定启停、会话、错误与退出提示可见。
- 保留窗口输出与捕获／鼠标模式联动、待重启确认、参数草稿、面板同步、模式记忆与主题切换测试。
- 本轮 Python 文件 AST 解析、中英文 JSON 解析以及 `git diff --check` 通过。既有 libpng 色彩配置警告不影响测试结果。

## 视觉验收

使用 `scripts/realtime_panel_probe.py` 串行创建隔离模拟窗口，只截取探针自身 HWND；
无回调错误，所有场景均 `native_started=false`，没有捕获用户游戏或启动实际增强。

验看中文深色默认页、英文浅色输出页、中文浅色保护展开页、中文深色待重启状态。
探针请求 1000×680，当前 DPI 与应用最小尺寸使实际窗口为 1471×1021；上述小尺寸测试针对独立工作区。

初次截图曾出现输出按钮空白及保护页旧画面。原因是两个从启动计时的回调在繁忙布局后连续执行，
截取早于场景的原生绘制完成。探针改为场景布局完成后再延迟截图；复查控件绘制正常，
保护已展开并滚动到区域编辑器。未因此改动公共绘制控件。

```powershell
.venv\Scripts\python.exe -B scripts/realtime_panel_probe.py --work-dir tmp/realtime-start-layout-20261008 --scenario idle --theme dark
.venv\Scripts\python.exe -B scripts/realtime_panel_probe.py --work-dir tmp/realtime-start-layout-20261008 --scenario idle --theme light --language en_US --page display
.venv\Scripts\python.exe -B scripts/realtime_panel_probe.py --work-dir tmp/realtime-start-layout-20261008 --scenario idle --theme light --page protection
.venv\Scripts\python.exe -B scripts/realtime_panel_probe.py --work-dir tmp/realtime-start-layout-20261008 --scenario restart --theme dark
```

## 临时文件

本任务目录为 `tmp/realtime-start-layout-20261008`，登记见其中 `TASK.md`。
仅清理本轮可重建的四张截图及两个隔离配置文件，不触及真实用户配置、其他任务或持久依赖。
清理前核实绝对路径、目录无链接、相关测试进程已结束及无业务引用；删除六个文件共 545,665 字节，
F 盘可用空间从 96,297,349,120 增至 96,297,906,176 字节，观测释放 557,056 字节。
剩余只有不足 2 KiB 的任务登记，保留用于追溯，2026-10-15 复核；截图和隔离配置可按上述命令重建。
