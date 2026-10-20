# P0 剩余增长修补与验收

- 授权/负责人：维护者 2026-10-20 要求一次性继续修补完成；Codex。
- 基线：6e3db90；保留用户已有 RELEASE_NOTES_v3.0.1.md 修改，单独记录哈希，不纳入代码提交。
- 复核日期：2026-10-27。用途：GUI 预览/导出原生分配栈、VSR/NR 单变量对照、确认项目侧修复与实际平台结果。
- 初始 F 盘可用约 59.42 GiB；新增峰值预算 2 GiB，保留至少 15 GiB 余量。复用 .venv、编译器、模型及已有 DLL，不复制整套环境，不下载依赖。
- 重建：设置 PYTHONDONTWRITEBYTECODE=1，TEMP/TMP 到本任务；用 .venv/Scripts/python.exe -B 运行 scripts/verify_p0_stability.py 与定向 pytest。诊断 DLL 由 scripts/native_heap_trace.cpp 和既有 Visual Studio BuildTools 编译，命令保留本目录。
- 安全：任务树私有提交上限 8 GiB、系统物理/提交余量至少 8 GiB，有限超时与精确进程身份回收；不制造真实 OOM，不重启系统或更换驱动，不降低质量或周期重置 NR。
- 输出：可复用代码留 scripts/、必要原始证据和结论留 docs/development/；不修改已验证旧证据。
- 收尾：先核验归档、精确进程退休、独占文件句柄与路径/重解析点；仅清理本任务明确拥有的可重建副本和合成素材，保留登记、必要失败材料并报告占用。
- 2026-10-20 用户明确授权当前测试结束后临时重启 NVIDIA Display Container LS 一次。03:07:19–03:07:20 UTC 已执行成功，服务恢复 Running、启动方式仍为 Automatic；未修改驱动/服务配置。普通权限首次尝试失败记录与提权后成功记录均保留，后续相同代码对照单独标记 after-service。
- 收尾状态：GUI 30 次轮换／300 秒空闲、本地合成器 300 秒空闲及 1800 秒连续换尺寸通过本轮门槛；长测 94,957 帧。220 项不同 Python 关联回归、23 个原生 GPU 用例、20 组色彩对照和三组 NVENC 交接通过。实际本地运行库加载及三次 GUI 重开完成，23 个 supervisor 用例均无遗留或强制回收。
- 已验收 DLL 原样更新到项目 runtime/，原 DLL SHA256 32ea271a83786b1533f4074cb29534cf866b4778d68b0b823dbf4c5dbaf544b6 保存在 rollback/dlss5_quality.dll；该唯一回滚副本保留至另获删除授权，2026-10-27 复核。
- 未通过槽位恢复检查的虚拟内存实验已撤回，原始失败与测量源码留证。P0 未全部完成：VSR／NR 的 NVIDIA 原生增长在服务重启后仍存在，不能用压力停止代替平台；未更换驱动、重启 Windows 或正式打包。
- 证据归档目标 docs/development/p0-completion-20261020/；重建命令与候选源码保留在归档 raw/，仅清理本任务已归档、已退休且可重建的文件，保留本登记及唯一回滚副本。
