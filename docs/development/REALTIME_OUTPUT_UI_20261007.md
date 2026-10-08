# 实时输出方式入口升级（2026-10-07～08）

## 范围与行为

- 目标窗口下方增加「全屏输出／窗口输出」双选项，支持鼠标及左右方向键；移除显示页重复的窗口化开关。继续使用 `windowed` 布尔配置，不迁移预设、不修改默认值。
- 切到窗口输出时仅解决已知冲突：DD → WGC、关闭并禁用全屏游戏鼠标模式。兼容的 WGC/GDI/DWM 保留，发生联动时在选择项下方说明。
- 窗口模式下再选择 DD 仍留在窗口输出，并解释回到 WGC；不会因此意外切成全屏。切回全屏不自动恢复 DD 或鼠标模式。
- 窗口输出倍率仅在窗口模式可编辑，全屏时保留数值并灰显。加载旧预设、命名预设或会话后同步显示与启用状态。
- 所有改动仅进入编辑草稿；运行中仍沿用确认重启流程，不自动开始、停止、重启或热更新捕获设置。无效且未完成的其他参数输入不会被清除。
- 紧急停止键不可用时，「定位设置」直接聚焦新的输出选择，不再跳到被移除的旧开关。
- 不增加多会话／多窗口同时增强，不改变原生宿主或渲染链路。

## 退出提示核查

`scripts/prepare_realtime_build.py` 中生成的 OverlayDrawer 使用 foreground draw-list
绘制左下角文字和半透明底色，不创建 ImGui 交互窗口或输入区域。现有实现每帧绘制，
所以关闭工具栏后仍常驻；不抢鼠标点击，但会覆盖该区域内容，不能声称完全不影响观看。
此次保留其显示和独立停止保护，不做自动隐藏，也未测量提示自身的帧率开销。

## 验证方式

- 最终 7 组回归合并运行 **144 项全部通过**（217.206 秒）：realtime UI、readiness、i18n、workbench UI、inspector、realtime 配置、safety。`git diff --check` 通过。
- 控制器回归新增覆盖：入口可见/键盘、DD/鼠标模式冲突、窗口内重选 DD、兼容捕获及未完成输入保留、运行中仅标记重启、预设同步及倍率保留、会话持久化。
- 启动检查定位测试改为检查聚焦调用与原页面保留；不依赖其他窗口可能占用的系统前台焦点。
- 主工作台 1000×680 / 1280×800、深浅两主题布局断言包含新输出选择及原有开始/停止控件。
- `scripts/realtime_output_ui_probe.py`：使用 mock 客户端和隔离配置，只对本进程窗口调用 PrintWindow（Pillow `window=`），不枚举或捕获用户窗口、不启动实时引擎。
- 已查看中文深色窗口输出、英文浅色全屏输出截图；联动说明、禁用倍率、开始/停止均可见，回调异常为空。本机 DPI 使完整窗口实际尺寸为 1471×1021。
- 此次未重复运行原生捕获测试；原生全屏/窗口与退出回归见 [卡死修复记录](REALTIME_PARAMETER_FREEZE_20261007.md)。没有重新构建或覆盖宿主、打包、上传、提交、推送。
- 已安装宿主 SHA-256 仍为 `bc7be69c08fa0993176454854eab062e45d78ac3f9a6a1d46b8b1bdab6463bce`。

## 复现

在仓库根使用已安装 Python，设置 `PYTHONDONTWRITEBYTECODE=1`、`TEMP` 与 `TMP`
为 `tmp/realtime-output-ui-20261007`。

```powershell
python -B -m unittest discover -s tests -p test_realtime_ui.py
python -B -m unittest discover -s tests -p test_realtime_readiness.py
python -B -m unittest discover -s tests -p test_realtime_i18n.py
python -B -m unittest discover -s tests -p test_workbench_ui.py
python -B -m unittest discover -s tests -p test_realtime_inspector.py
python -B -m unittest discover -s tests -p test_realtime.py
python -B -m unittest discover -s tests -p test_realtime_safety.py
python -B scripts/realtime_output_ui_probe.py --work-dir tmp/realtime-output-ui-20261007 --language zh_CN --theme dark --windowed
python -B scripts/realtime_output_ui_probe.py --work-dir tmp/realtime-output-ui-20261007 --language en_US --theme light
```

## 空间预算

开始时 F 盘可用约 89.7 GiB，tmp 总量约 29.53 GiB；预算小于 20 MiB。
未复制依赖或模型，未新建大型构建产物。本次任务目录仅承载临时测试配置和截图，
验证完可依上述脚本重建；已有依赖与上一任务回滚文件不属于此次清理范围。

2026-10-08 收尾：测试进程与截图探针均已正常结束，确认无目录链接，逐个清理本任务的
4 张截图、隔离 settings.json 与 queue.json；逻辑文件量 509,726 字节，删除前后盘可用空间
增加 520,192 字节。临时测试子目录已由测试自行移除。剩余仅约 1 KiB 的 TASK.md，
用于保留归属和重建说明，2026-10-14 复核；上述删除内容可通过保留的探针重建。
