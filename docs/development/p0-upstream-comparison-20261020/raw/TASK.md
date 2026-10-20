# P0 原版参考项目同机对照
- 负责人：当前对话 Codex；用户已授权原版参考项目同机对照。
- 创建：2026-10-20；复核：2026-10-27，非自动删除授权。
- 输入：既有 Veyra 1.4.4 原版包、dlss5standaloneV2；本项目当前工作树与已验收 runtime。
- 临时目录：tmp/p0-upstream-comparison-20261020/。
- 预计新增峰值：2 GiB，保留至少15 GiB；复用既有Python/SDK，不复制Torch/CUDA/模型。
- 重建：.venv/Scripts/python.exe -B scripts/verify_upstream_p0.py（参数与运行记录见各case result.json）。
- 目的：固定进程身份比较私有提交、实际模块与短线程；区分处理通过与内存平台。
- 约束：不改驱动、注册表、服务或安装目录；不终止无关进程；不放宽原P0门槛。
- 清理：归档脚本/哈希/曲线/日志到docs后，清理本任务可重建副本与媒体。依赖源目录原样保留。
