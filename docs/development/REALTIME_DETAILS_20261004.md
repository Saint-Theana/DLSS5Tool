# 实时工作台：底部日志与参数细节

2026-10-04。接续实时调整面板第一版；范围仅 Python UI、国际化、相关测试和隔离检查脚本。未构建／打包，未改原生引擎、效果元数据或用户配置。

## 本次变化

- 本地与实时日志共享根窗口底部位置、相同高度／字体／主题色和「更多」展开状态。各自保留内容和滚动位置；实时日志到达时，仅已在底部的阅读位置自动跟随。右侧删除日志标签，保留调整／保护／显示／预设四页；诊断导出移至预设页。
- NR 输入分辨率、AMD／NVIDIA 光流质量、第 2／3 遍参数按前置条件灰显。鼠标、键盘都不能改灰显控件，原值仍保存；说明随中／英文切换。未知第三方参数不强套 NR 规则。
- 当前效果参数显示「非默认值」与「待应用」两个独立状态，分组标题统计非默认项目数。运行引擎确认后只清除待应用，自定义标记不丢失。
- 单项恢复、整组恢复及当前效果单步撤销。分辨率组恢复同时覆盖输出缩放。批量恢复先抑制变量提交，再整组验证／提交；重启型修改仍需用户确认。撤销包含未完成输入，切换效果／载入预设重新记录；数值格式变化不产生假撤销步骤。
- 应用区区分无效输入、提交失败、等待确认、已应用与需重启原因；提交／画质确认超时可直接重试，不自动重启或清空草稿。只有匹配的命令／会话回执影响当前提交；无关操作失败不取消参数确认。
- 原生失败 ACK 不含 run_id 时，依已验证 generation 和匹配 command ID 处理；带有旧 run_id 的回执不接受。画质成功仍要求 ACK 与 GPU revision 对应。

## 定向回归

只运行本次修改及直接依赖，没有全量测试。

```powershell
$env:TEMP = 'F:\project\DLSS5Tool\tmp\realtime-details-20261004'
$env:TMP = $env:TEMP
$env:DLSS5TOOL_DISABLE_UPDATE_CHECK = '1'
.venv/Scripts/python.exe -B -m unittest tests.test_realtime_inspector tests.test_realtime_ui tests.test_realtime_i18n tests.test_i18n tests.test_workbench_ui tests.test_gui_player.WidgetSmokeTests.test_queue_resume_after_stop_and_stable_export_chrome
```

- 联合定向 77 项通过（67.705 秒）；回执兼容收尾新增一项后，仅重跑 inspector／realtime_ui 两模块 41 项，全部通过（33.624 秒）。最终覆盖 78 个受影响用例。
- 覆盖底部位置与开关、日志分离与滚动保留、主题、禁用控件键鼠、值恢复、修改标记、整组恢复不部分发送、单步撤销、缩放单位、错误重试、旧回执与画质 revision。保留原来的队列／底栏定向用例。
- 中／英两次 10 秒隔离启动：1000×680，中文浅色正常过渡、英文深色 reduced-motion，各往返模式两次。均载入 157 个效果、33 个参数、7 个分组，17 项依条件禁用，4 个标签；日志在共享底部、另一模式日志隐藏、应用按钮可见、会话 idle、callback_errors=[]、caption_error=null。
- 隔离探针不提供可捕获目标，不操作正在运行的主窗口。以上为控件几何／状态检查，不是像素截图或真实游戏渲染验收。

## 空间与清理

开始 F 盘约 89.66 GiB 可用，tmp 29.45 GiB；新增峰值预算 20 MiB，复用现有 .venv/runtime。两个探针和测试均退出，临时测试目录自行回收。

核实明确绝对路径、引用、非链接属性，并通过文件独占打开检查后，删除本任务生成的 probe-settings.json、probe-queue.json、native/logs/realtime.log 和空目录：文件共 51587 字节，磁盘前后可用空间增加 53248 字节，均可用脚本重建。只保留约 1.3 KiB 的 TASK.md 至 2026-10-11 复核；旧依赖、备份和用户数据未清理。
