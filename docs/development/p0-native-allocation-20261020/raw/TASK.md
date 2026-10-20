# P0 原生内存归属与分配类别定位

- 负责人：Codex / 用户授权的 P0 本地样本排查。
- 创建：2026-10-20；复核到期：2026-10-27；任务尚未结束。
- 目的：区分精确测试进程的私有提交增长与其他应用占用，进一步观察原生堆和虚拟内存类别。
- 输入：已有只读运行库、.venv；合成 1080p 图片，不读取其他应用的数据。
- 环境：不修改 NVIDIA/Windows 全局设置，不安装工具，不重启系统。
- 初始可用空间：F 盘约 59.45 GiB；预计任务磁盘峰值不超过 128 MiB；进程树提交上限 8 GiB，物理/提交余量各 8 GiB。
- 重建命令：设置 TEMP/TMP 为本目录，PYTHONDONTWRITEBYTECODE=1，使用 .venv/Scripts/python.exe -B；先执行 scripts/inspect_native_allocations.py --self-check，再执行下面的诊断：
  `DLSS5TOOL_P0_MEMORY_MAP=1 .venv/Scripts/python.exe -B scripts/verify_p0_stability.py --task tmp/p0-native-allocation-20261020 --case native-composer --frames 32 --idle-seconds 60 --timeout 150 --label map`
  上述环境变量按 PowerShell 的 `$env:...` 形式设置，详细参数和源码哈希随报告归档。
- 可复用代码：scripts/inspect_native_allocations.py；结论与必要原始证据保存至 docs/development/。
- 预计输出：虚拟地址区元数据、默认进程堆汇总、原有采样/事件/模块清单；不生成完整内存转储或用户内容。
- 清理：报告归档校验后，仅清理本任务创建的可重建输出，保留本登记。删除前核对绝对路径、重解析点、进程、引用与独占句柄。
