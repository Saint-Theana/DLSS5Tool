# 实时启停提示与游戏控制（2026-10-08）

## 范围

- 新建实时会话默认窗口输出；已有完整或稀疏 v1 预设保留旧语义，不重写用户配置。
- 首次实际提交内容帧后，顶部工具栏和原位置左下角退出提示显示 5 秒，随后共同淡出 300 ms。静止源无新帧时也更新提示；悬停、固定或编辑时保持显示。停止键不可用时警告常驻。
- 独立、无焦点、鼠标穿透的中心窗口显示启用／开启／退出中／已退出。成功提示 1 秒，不人为延长停止；只对本次源、输出或调参窗口前台显示，并排除屏幕捕获。
- 按效果链选择「DLSS 增强」或「实时增强」，不将普通缩放标为 DLSS。
- Ctrl+Alt+P 复用参数编辑输入宿主，显式取得前台后解除鼠标限制；返回时交还输入。游戏鼠标模式启用安全的显式编辑入口，但不以游戏鼠标悬停唤出工具栏。只读预览不在此模式接收鼠标，避免意外解除游戏锁定。
- 快捷键占用在界面工具提示、日志和画面内退出说明中明确提示。Ctrl+Alt+F10 的独立停止线程、停止超时和仅绑定本次宿主的终止保护保持不变。
- 修复独立资源表的 XAML 属性名映射，避免面板显示 Home_FrameSync 等内部资源键。

## 实现边界

`native/realtime/guidance_model.h` 单独建模计时；`guidance.cpp` 中心提示不依赖渲染线程。`scripts/prepare_realtime_build.py` 生成上游适配源，不修改 pinned third_party 文件。游戏模式只放开参数入口及编辑期间的操作，不直接解除所有上游游戏限制。

启动／停止／失败状态不会因延迟首帧误报成功；晚到首帧不会把正在停止或失败状态改回运行。窗口化输出不意味着可同时增强多窗口。

## 验证与复现

可复用脚本：`scripts/realtime_guidance_probe.py`。只操作自建 Tk 源及本次原生宿主，单独 watchdog 上限 25 秒；日志、状态和截图进入 `tmp/realtime-guidance-20261008/probe/`。

```powershell
.venv\Scripts\python.exe -B scripts/realtime_guidance_probe.py --host runtime/realtime/dlss5_realtime_host.exe --output tmp/realtime-guidance-20261008/probe/windowed --static
.venv\Scripts\python.exe -B scripts/realtime_guidance_probe.py --host runtime/realtime/dlss5_realtime_host.exe --output tmp/realtime-guidance-20261008/probe/game --fullscreen --game --nr
.venv\Scripts\python.exe -B scripts/realtime_guidance_probe.py --host runtime/realtime/dlss5_realtime_host.exe --output tmp/realtime-guidance-20261008/probe/fault --fullscreen --game --nr --fault
```

已观察：静止窗口的提示到时隐藏；NR 全屏游戏鼠标模式的编辑前后限位切换；宿主暂停后独立超时终止和鼠标恢复。前台不属于会话时编辑被拒绝，中心提示不覆盖其他应用。

测试边界：这不是实际游戏兼容性验收。调参通过协议调用（测试期间 Ctrl+Alt+P 被其他进程占用），紧急停止向独立线程投递 WM_HOTKEY；不是物理组合键端到端测试。面板外点击使用消息投递，不据此宣称真实硬件点击穿透测试通过。系统报告的光标 visible 标志在此合成源中始终为 true，已验证的是限位解除／恢复及编辑输入归属，而非所有游戏的隐藏光标行为。

独占全屏、反作弊、高权限目标、游戏主动重设鼠标捕获，以及其他显示配置仍需分别验证。失败时使用 Ctrl+Alt+F10 停止后在主界面调整，不注入或绕过游戏保护。

本轮仅用于本机开发验证，没有打包、发布、上传或推送。公开二进制分发审核仍关闭。

## 本轮交接状态

- 原生 Release 构建和 guidance 计时测试通过。45 项配置／安全／语言／构建测试通过；109 项界面测试中，首次保存用例的夹具冲突修正后补测通过（另两项新增用例一并复测）。合计 154 个不同 Python 用例。
- 静止窗口验收：首帧约 0.44 秒，正常停止约 0.16 秒；提示共同隐藏、编辑焦点归属和生命周期文案通过。
- NR 全屏游戏鼠标验收：正常停止约 0.21 秒；宿主暂停后，独立停止保护约 2.08 秒触发，记录到 cursor_restore 成功。原始记录保留在任务 probe 目录。
- 最终候选另加入游戏只读预览不接收鼠标的限制，编译／生成断言通过；最终整组原生复测被当前在用实例占据停止快捷键阻止，未绕过安全前置检查。
- **尚未替换本地运行时**：检查时 `runtime/realtime/dlss5_realtime_host.exe` 仍在使用。不停止用户实例，不覆盖运行文件。待正常退出应用后备份旧宿主和 build-manifest，再复制候选、运行 `scripts/realtime_provenance.py` 并补做最终原生验收。
- 已安装旧宿主 SHA256：`bc7be69c08fa0993176454854eab062e45d78ac3f9a6a1d46b8b1bdab6463bce`。
- 待安装候选：`tmp/realtime-guidance-20261008/candidate/dlss5_realtime_host.exe`，SHA256 `6bd0c4fcb261ffdba4bcdafaafda15fe65b7d3844f9c984cbbd4c8e3540ff0b4`。
- 已清理本任务构建中间文件、生成检查目录、字体／shader 缓存和截图，磁盘实际释放约 137.8 MiB；保留约 4.38 MiB 候选及验收记录，2026-10-15 复核。缓存可重建，未删除任何旧任务备份或用户素材。
