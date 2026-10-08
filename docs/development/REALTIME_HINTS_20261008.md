# 实时模式撤销与帮助精简（2026-10-08）

根据用户两张截图及追加要求，移除全部额外 ⓘ，说明只在现有内容上悬浮展示。

- 画面方案与当前效果的撤销均改用回退箭头图标，沿用共享图标绘制和按钮禁用/键盘逻辑。
  保留各自作用范围的悬浮说明，不与单项恢复默认值的圆形箭头混淆。
- `InlineHelp` 只保留短文字行，不再创建说明按钮、展开状态或重复正文。
  方案摘要、效果名称及提示文字悬停可看完整说明；Tab 聚焦同样可看，Esc 隐藏。
- 原先没有短文字、仅有说明图标的行直接删除，帮助附在残差合成、保护区域、运行详情的
  原有分组标题上。区域坐标说明也可从比例示意图悬停查看。
- 提示在切页、控件销毁、主题变化及说明更新时关闭，避免悬浮残留；不会因展示帮助重排参数区。
- 不修改参数、应用/撤销语义、模式反色或持久化，不启动真实捕获，不打包。

## 验证与重现

复用 `.venv`，无环境复制。TEMP/TMP 隔离到 `tmp/realtime-hints-20261008`，
设置 `DLSS5TOOL_DISABLE_UPDATE_CHECK=1`，Python 使用 `-B`。

```powershell
.venv/Scripts/python.exe -B -m unittest tests.test_realtime_panel_sync tests.test_realtime_readiness tests.test_realtime_inspector tests.test_realtime_layout tests.test_realtime_effects
.venv/Scripts/python.exe -B scripts/realtime_panel_probe.py --work-dir tmp/realtime-hints-20261008 --scenario idle --theme dark
.venv/Scripts/python.exe -B scripts/realtime_panel_probe.py --work-dir tmp/realtime-hints-20261008 --scenario idle --language en_US --theme light
```

最终版回归 107 项全部通过（138.543 秒），覆盖撤销、参数回执、布局、启动检查，以及
新增的无图标悬浮说明、键盘聚焦/Esc、切页回收提示、说明更新和空白帮助行移除。
Python AST 语法及 `git diff --check` 通过。

中文深色、英文浅色自身窗口截图检查通过：两处撤销均为回退图标，无 ⓘ、无说明展开入口、
无文字重叠。探针两次均 `callback_errors=[]`、`native_started=false`；不是实际捕获/GPU 验收。

卫生收尾：核实本任务进程退出、无链接和运行引用后，删除两张模拟截图与两份隔离配置，
合计 234,313 字节；删除窗口内磁盘可用空间净增 237,568 字节。可用原探针重建，不进回收站。
任务目录只留小于 2 KiB 的登记用于复现/审计，2026-10-15 复核；未清理其他任务或用户数据。
