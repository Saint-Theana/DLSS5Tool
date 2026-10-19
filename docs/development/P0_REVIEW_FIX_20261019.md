# P0 审查遗漏修复与定向验收 · 2026-10-19

本轮按用户授权落实 [代码审查](p0-code-review-20261019/REVIEW.md) 的四项发现。既有 P0 回滚、错误持帧和余量保护继续保留；用户长视频、批量图片及真实 GPU 长稳仍待回验。

## 已落地

| 项目 | 修改 | 验收结果 |
| --- | --- | --- |
| 导出清理链中断 | SDR/HDR 清理逐项执行，原始处理错误继续抛出；清理错误写入日志及异常备注。应用仅保留失败清理动作和资源所有者，下一次导出或退出时重试；仍失败时保留对象并阻止新任务继续分配。 | NR 无法结束时，健康 VSR 和编码器仍清理；故障解除后重试释放成功。只有清理失败时，在尝试所有资源后报告错误。 |
| HDR 序列 EOF/已关闭误拒绝 | 已知序列末尾或关闭状态先返回 None，仅在确实读取下一帧时检查内存；序列构造不做尚未发生的帧分配检查，FFmpeg 视频仍在启动前检查。 | PQ/HLG 的 EOF、关闭和越界 seek 在零余量下均正常返回；最后一帧后出现压力的导出仍 finish，未 abort。 |
| 纯导出预算包含未启用组件 | 通用导出按实际 SR/NR 创建条件估算，使用已知缓冲量；保留解码、尺寸转换和插帧缓冲检查及既有系统预留。分层缓存输出不会再次计入上游 SR/NR。资源提示估算的默认调用行为保持原样。 | 256 MiB 余量下纯导出和源帧旁路完成；启用 SR/NR/FG 后超预算仍在创建前拒绝。缓存输出在 30 MiB 余量下正常完成。 |
| legacy 槽数过估 | 新增共享的有效槽数规则供 IPC 准入、原生配置与能力报告使用，legacy 上限 3，非合并/非持久/分区模式为 1；保存偏好保持原值。 | 4K SDR、偏好 16、余量 512 MiB 的 legacy 到达首次分配；v2 的 16 槽预算仍拒绝。旧/新库配置与有效规则一致。 |

## 验证记录

新增 **24 项回归用例**。按测试身份合并各批次，**193 项不同关联用例均有通过记录**；`git diff --check` 与 11 个修改 Python 文件的 AST 解析通过。原有 v3.0.1 发布文案修改逐字节保持一致。

| 批次 | 结果 | 证据 |
| --- | --- | --- |
| 修改前定向对照 | 14 项预期失败、1 项通过 | [red.xml](p0-review-fixes-20261019/red.xml) |
| 首批修复验证 | 104 通过；3 项模拟夹具配置问题、1 项 Tk 初始化失败 | [focused.xml](p0-review-fixes-20261019/focused.xml) |
| 修正夹具后的核心模块 | 112 通过、13 subtests；4 个 UI 参数化用例留在其他批次 | [core.xml](p0-review-fixes-20261019/core.xml) |
| 导出/宿主/缓存/余量/HDR/清理关联模块 | 74 通过、17 subtests；2 项 Tk 初始化失败 | [consumers.xml](p0-review-fixes-20261019/consumers.xml) |
| 上述 3 项 Tk 失败独立重跑 | 各 1 通过，均执行到测试主体 | [HDR UI](p0-review-fixes-20261019/tk-rerun.xml)、[布局](p0-review-fixes-20261019/layout-rerun.xml)、[导出 worker](p0-review-fixes-20261019/export-worker-rerun.xml) |
| 分层缓存预算补验 | 1 通过 | [upstream.xml](p0-review-fixes-20261019/upstream.xml) |

夹具修正为真实接口：HDR 应用提供取消检查，SDR capture 只暴露实际 read/release 接口；关闭/abort/原始错误断言保持。原 P0 的模拟序列 reader 现在显式声明状态，避免通用 Mock 的任意属性被当成已关闭。

Tk 错误发生于 `tk.Tk()` 加载 Tcl/Tk 阶段；保留原失败记录，不将混跑批次描述为一次全绿。[去重统计及新用例清单](p0-review-fixes-20261019/verification-summary.json) 和 [源码哈希](p0-review-fixes-20261019/source-hashes.json) 已保存。

本轮只运行相关模块，用合成图片、模拟内存快照及小型假宿主协议验证；未运行全仓回归、真实 GPU 长稳、真实 OOM、构建或打包。源码重启后生效，现有冻结程序需另行打包交付。

## 复验

复用 `.venv`；先按卫生守则新建并登记任务目录，再将下面的 `<task>` 替换为该任务目录。

```powershell
$env:TEMP='F:\project\DLSS5Tool\tmp\<task>'
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider --basetemp=tmp/<task>/core --junitxml=tmp/<task>/core.xml tests/test_p0_review_regressions.py tests/test_hdr_image_sequence.py tests/test_p0_memory_boundaries.py tests/test_host_queue.py tests/test_super_resolution.py
.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider --basetemp=tmp/<task>/consumers --junitxml=tmp/<task>/consumers.xml tests/test_frame_generation.py tests/test_dlss_host_process.py tests/test_render_cache.py tests/test_memory_budget.py tests/test_hdr_pipeline.py tests/test_preview_cache_clear.py
```

## 仓库卫生

唯一临时任务目录为 `tmp/p0-review-fixes-20261019/`，开始 F 盘可用约 59.45 GiB，新增磁盘峰值预算低于 32 MiB。复用环境，没有复制模型、运行库或依赖。小型验证记录已逐文件校验归档。清理本任务 6,063,707 逻辑 bytes，删除期间 F 盘可用空间增加 6,479,872 bytes（约 6.18 MiB）；剩余临时占用仅 2,673 bytes 的任务登记，保留作归属记录，2026-10-26 复核。原始路径与统计见 [cleanup.json](p0-review-fixes-20261019/cleanup.json)。
