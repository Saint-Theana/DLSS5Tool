# 实时参数减法与自定义快捷键（2026-10-10）

## 范围与交付

- 实时参数区移除行内复位、分组复位、默认数值帮助与“非默认”计数。保留描述符默认值用于旧预设解析及必要恢复，不主动重置用户数值。
- 画面标题旁的“···”仅提供当前效果参数恢复，确认后执行，支持现有撤销；不重置效果链、步骤缩放、输出、设备、保护区、预设或应用全局设置。本地媒体的独立恢复入口未扩大修改。
- 高级页及快捷键异常提示都可打开四动作快捷键设置。手动输入 Ctrl / Alt / Shift + 字母、数字、功能键，排除重复、裸键、Shift-only、Win、F12、Alt+F4。
- 设置在 `realtime_presets.json` 的 `local.hotkeys` 持久化，保留原 `runtime_directory`；不进入外部预设。原设置无该字段时继续原按键，不做迁移覆盖。
- 停止增强后才能改键；在后台关闭闲置宿主、重新注册并等待真实 ready。四键全部可用才保存；失败重新启动旧绑定并验证原可用状态。磁盘写入失败也请求回退。
- 独立安全停止线程接收真实停止组合，原生注册、工具栏与退出提示保持一致。旧宿主忽略新键时拒绝声称成功；紧急停止不可用继续阻止全屏。
- 重复效果目录回包不重建参数编辑器，避免改键重启宿主时丢失草稿／撤销。关闭窗口会等待本次改键工作线程后关闭宿主，避免注册泄漏。

未改变着色器、渲染参数范围、图像处理质量、左栏宽度和预设行为。没有打整套 EXE、发版、提交或推送。

## 验证证据

- Python 语法、JSON 重复键和 `git diff --check` 通过。
- 参数、皮肤蒙版、范围、实时 UI 与 polish：99 项通过。
- 安全、i18n、readiness、工作台与参数统一组合原运行 105 项；一个旧测试仍调用被删除的行内复位，调整为集中入口后对应 RealtimeSwitchTests 三项通过。
- 最新快捷键 16 项 + RealtimeSwitchTests 三项：19 项通过，覆盖解析、重复键、保留本地设置、原子写入失败、旧宿主拒绝、注册回退、自定义停止键、集中恢复确认与撤销、重开恢复、重复目录不损失草稿、运行中锁定。
- 最终安全、i18n、构建完整性组合 27 项通过。
- 原生 Release 宿主及 `realtime_hotkeys_tests` 编译成功，CTest `realtime_hotkeys` 通过。
- `scripts/realtime_shortcuts_probe.py` 对候选及最终 runtime 各验证一次：实际新键注册、旧停止键释放、故意占用新停止键导致拒绝、旧四键注册恢复、独立停止保护、关闭后无注册泄漏，全部通过。没有注入键盘或启动捕获／渲染。
- computer-use 实际查看中文深色与英文浅色隔离预览，检查参数菜单、设置入口、四项绑定与状态、模拟保存成功。中文最终复查通过，各探针 callback_errors 为空，native_started=false。
- 检查中修复了标签自身 Configure → wraplength → grid 请求宽度的布局循环；最终改为固定宽度下的换行，并只在消息变化后更新高度。

- 最后 realtime / effects / layout / panel sync / workspace / source preview / UI / polish 组合：168 项全部通过（294.379 秒）。上述各轮去重后共 337 项 Python 测试通过；单独重跑的项目不重复计数。

未验证真实游戏画面中的自定义按键触发或 GPU 兼容性，注册成功不等于游戏适配通过。

## 原生构建与容量

临时目录：`tmp/realtime-shortcuts-20261010/`，负责人当前任务 Codex，复核日 2026-10-17。
初始 F 盘可用 94,810,509,312 字节；预算 2 GiB，实际候选加构建约 740 MB。复用现有依赖，不复制 GPU 环境。

原构建缓存已清理，因此新建唯一候选。CMake 配置：

```text
cmake -S native/realtime -B tmp/realtime-shortcuts-20261010/build -G "Visual Studio 17 2022" -A x64 -DPython3_EXECUTABLE=F:/project/DLSS5Tool/.venv/Scripts/python.exe -DREALTIME_OUTPUT_DIR=F:/project/DLSS5Tool/tmp/realtime-shortcuts-20261010/candidate
cmake --build tmp/realtime-shortcuts-20261010/build --config Release --target dlss5_realtime_host realtime_hotkeys_tests --parallel 4
ctest --test-dir tmp/realtime-shortcuts-20261010/build -C Release -R ^realtime_hotkeys$ --output-on-failure
.venv/Scripts/python.exe -B scripts/realtime_shortcuts_probe.py --host runtime/realtime/dlss5_realtime_host.exe --work-dir tmp/realtime-shortcuts-20261010
```

本机 MSBuild 首次配置遇到 PATH / Path 重复环境键，使用大小写归一后的**子进程环境**重试成功，未修改系统环境。其他警告是已有依赖 UTF-8 提示及 MSBuild 对任务临时目录的增量构建提示。

验证后更新 `runtime/realtime/dlss5_realtime_host.exe`，执行 `scripts/realtime_provenance.py`，记录 440 个输入、204 个输出。运行时完整性校验通过；发布分发审核门禁仍保留。

宿主 SHA256：`FF072386E5872692D956003324271ABC467155B95296B800A54860CD67AFDFAD`。

已核实无构建／原生任务运行、候选与 runtime 哈希一致、目标无链接且严格位于本任务内，清理 `build`、`candidate`、`MSBuildTemp`、`native-state`。清理前后 F 盘可用 94,058,741,760 → 94,799,716,352 字节，净增加 740,974,592 字节；代码、测试、探针和运行宿主均保留可重建。其他任务目录及用户设置未清理。

收尾再清理本任务模拟预览设置、队列及三个空的中断测试目录；这些均可由保留探针重建。临时任务目录仅留下约 2 KiB 的 TASK 登记，用于归属／重建审计，2026-10-17 复核。

## API 依据

Win32 的注册线程归属、失败返回值、修饰键以及 F12 保留限制按 [Microsoft RegisterHotKey 文档](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey) 核对。全局快捷键不可用不推断具体占用者；界面只报告注册事实。
