# 自动预渲染开关（2026-10-01）

## 行为

- 「预览性能」顶部增加「自动预渲染」，默认关闭；旧设置文件中缺少该字段时也保持关闭。
- `preview_auto_prerender` 随界面设置保存。导入其他素材和重启后保持用户选择。
- 关闭时，导入、跳转和调参仍异步生成当前帧精确预览；完成后不启动后续帧任务。
- 播放始终允许按需缓冲；暂停时立即收紧超分 / 插帧的预取范围。
- 切换开关保留已完成缓存。普通预览撤销排队任务及旧工作代次；共享管线停止继续预取，不销毁已完成像素和时序状态。
- 插帧画面只计算所需的右端点；跳转时仍允许重建必需的时序历史，不跳过质量所需的计算。
- 导出恢复共享管线的预取能力，不受暂停预览开关影响。

## 验证

复用现有 `.venv`，使用 CPU 模拟渲染器及 Tk 控件测试，没有复制模型、CUDA 或开发环境。

执行范围：`test_auto_prerender.py`、`test_gui_player.py`、`test_preview_switches.py`、
`test_preview_latency.py`、`test_preview_interaction_continuity.py`、`test_preview_cache_clear.py`、
`test_render_cache.py`、`test_preview_feedback.py`、`test_i18n.py`、`test_stability.py`、
`test_gui_guidance_tab.py`。

- 主验证：228 项通过、176 个 subtest 通过；两项旧界面测试遇到间歇性 Tk 初始化错误。
- 独立复测：18 项新增开关测试和上述两项界面测试全部通过，共 20 项。
- 验证了相同 / 不同预览尺寸下的单帧上限、停止后的回调、缓存保留、播放与暂停、开关持久化、插帧右端点、三级共享管线及导出恢复。
- 现有 App 构造测试确认开关默认关闭且位于设置面板首行；中英文本和翻译键检查通过。
- 最后复查开关与翻译：31 项通过、2 个 subtest 通过。新增测试随后整理为标准库 unittest 格式，12 项（含 18 种场景）全部通过，可被现有 CI 的 `unittest discover` 执行，无新增测试依赖。
- `git diff --check` 通过。未进行真实 GPU / 视频运行验证。

本机 Python 的 Tk 数据不完整，界面测试通过本次命令的 `TCL_LIBRARY` 和 `TK_LIBRARY`
复用正式 v2.3.3 lite 基线的 `_internal/_tcl_data`、`_internal/_tk_data`；基线只读使用。

测试临时产物统一位于 `tmp/auto-prerender-20261001/`，开始时 F 盘可用约 75.3 GiB，
新增峰值预算小于 10 MiB。测试完成后核实引用、进程及链接并删除本任务可重建产物；
现有持久依赖不参与清理。

收尾已检查源码引用、运行进程和目录链接，删除本任务目录；逻辑文件体积为 14,259 字节，
删除前后 F 盘空闲空间增加 36,864 字节，本任务临时剩余占用为 0。

新增逻辑可用 `.venv/Scripts/python.exe -B -m unittest -q tests.test_auto_prerender` 重测；
执行前创建任务目录并将 `TMPDIR`、`TEMP`、`TMP` 指向其 `runtime` 子目录。
