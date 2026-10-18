# P0 内存释放与压力保护落地 · 2026-10-19

状态：源码首轮修复与定向验收完成。应用版本仍为 v3.0.1，未构建／打包、提交或推送。
起点与原始证据见 [首轮诊断](P0_MEMORY_DIAGNOSIS_20261019.md)。用户完整长视频及全部进程退出后的系统异常仍需现场复核，不据本轮结果宣称全部 P0 现象解决。

## 已落地

### 合成上下文生命周期

- `residual_composition.py` 使用持有 DLL 和句柄的 `_NativeBridge` 所有者；线程本地缓存消失时释放原生资源，同线程继续复用。
- 显式关闭幂等；覆盖替换 DLL、禁用原生入口、dispatch 失败、所有者／帧数组分配失败。即使异常 traceback 留在预览结果中，也及时释放句柄。
- GUI 关闭本地会话、清理预览缓存以及正常退出时释放当前线程的合成器；清理保持等待在途工作退休的顺序。
- 线程之间不互相销毁资源。工作线程不注册主线程 atexit 清理，避免解释器退出时销毁仍在原生调用中的设备；主线程保留 atexit 兜底。

### 内存保护

新增 `memory_budget.py`，读取 Windows 可用物理内存与提交余量，快照缓存 250 ms；读取不可用时保留既有预算行为。

- 用户保存的预算保持原值，运行时缓存上限取用户预算、物理 RAM 的 1/4 及当前安全余量三者最小值。
- 安全余量预留 `max(2 GiB, 总物理内存 / 8)` 给系统、模型和活跃处理。已计入的缓存字节只抵扣一次；余量低于预留值时要求缓存收缩。
- 共享账本、无共享池的画面缓存、原始光流缓存及旧预览缓存都使用这一上限；内存恢复后可再次缓存，不改保存偏好或画质。
- 解码预读按实际帧字节数限制队列，每条队列最多使用预留后余量的 1/4；无法容纳一帧时有明确错误，保留已有顺序和背压。
- 在途槽数同时受 RAM 余量约束；超分在共享帧分配／子进程启动前检查已知 RAM 峰值估算，不足时明确停止当前任务。
- 诊断上下文增加系统总 RAM、可用 RAM 和提交余量；普通界面没有新增内部阶段统计。

这些保护是缓存和已知缓冲区的运行策略，不是整个进程的硬配额；驱动、模型内部工作区及其他应用的突发分配仍需实际负载验证。

## 真实 DLL 验收

复用诊断时同一 DLL，未重新编译。原始结果见 [修复后 JSON](p0-memory-20261019/composer-lifetime-fixed.json)，修复前见 [原始 JSON](p0-memory-20261019/composer-lifetime.json)。

| 项目 | 修复前 | 修复后 |
| --- | --- | --- |
| 6 次短线程创建／正常销毁 | 6／0 | 6／6 |
| 结束后遗留上下文 | 6 | 0 |
| 1000×1000 SDR 私有提交，第 1→6 轮 | 111.27→328.07 MiB | 72.23→82.30 MiB |
| 6 次 dispatch | 成功 | 成功，0 次失败 |

修复后各轮私有提交约 72～83 MiB，有初始化／分配器波动；不把工作集或提交量未恢复到启动值视为句柄仍未释放，也不把 6 次短测称为完整长稳证明。

另测 6 次“显式清理→重新创建→合成”：创建 6、正常销毁 6、遗留 0。
确定性随机 RGBA 图与 CPU 对照的最大 RGB 差异为 1 个 8-bit 码值，alpha 完全一致。
同线程普通复用仍只创建一个上下文；mock 的 24 次短线程创建／销毁均为 24。

## 定向测试

基础环境：**125 passed、2 skipped、35 subtests passed**。
两项缺 Torch 的缓存模型用例在既有 `tmp/guidance-cuda-env` 补测，**2／2 通过**，合计 127 项不重复用例通过。

覆盖：

- 正常短线程销毁、同线程复用、幂等释放、切换／禁用、失败重试、分配失败及在途线程隔离。
- 32／8 GiB RAM 模拟、物理／提交压力、已占缓存抵扣、压力恢复、共享池及独立缓存收缩。
- 解码队列缩容／不足一帧时退出、超分分配前拒绝、在途槽上限。
- 缓存容量、顺序回放、清理生命周期、预览开关／响应、HDR／SDR 合同及本地化。

没有执行全量回归、模型下载、环境复制或大文件构建。

```powershell
$env:TEMP = 'F:\project\DLSS5Tool\tmp\p0-memory-20261019'
$env:TMP = $env:TEMP
.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider --basetemp=tmp/p0-memory-20261019/pytest-verified tests/test_native_composer_lifetime.py tests/test_memory_budget.py tests/test_render_cache.py tests/test_guidance_cache.py tests/test_shared_cache_budget.py tests/test_preview_cache_clear.py tests/test_mode_contract.py tests/test_super_resolution.py tests/test_preview_latency.py tests/test_preview_switches.py tests/test_auto_prerender.py tests/test_i18n.py
tmp/guidance-cuda-env/Scripts/python.exe -B -m unittest -v tests.test_guidance_cache.ModelCacheTests
.venv/Scripts/python.exe -B scripts/diagnose_composer_lifetime.py --native --cycles 6
.venv/Scripts/python.exe -B scripts/diagnose_composer_lifetime.py --native --cycles 6 --persistent-thread --release-each-cycle --verify-pixels
```

## 使用与后续

通过 `run.bat` 重启源码程序后生效。现有已打包 EXE／冻结组件不会热更新，正式分发需要另行完成打包和对应验收。
下一步用固定用户素材检查长视频、同线程批量图片和关闭后的完整进程树，确认是否还有独立增长路径。
P1 的显卡选择／吞吐、本地 HDR 接入及免读回继续沿用各自 TODO。

## 空间

复用已有依赖与任务目录；开始 F 盘可用约 31.66 GiB，新增磁盘预算小于 5 MiB。
小型原始报告已归档，测试夹具可按上述命令重建；仅清理本任务明确产生的 pytest 子目录，用途登记约数 KiB 保留至 2026-10-26 复核。旧依赖、回滚及正式基线保持原样。
收尾已核实相关进程退出、四个目标均位于本任务内且无链接／目录联接，删除 `pytest/`、`pytest-final/`、`pytest-final-check/`、`pytest-verified/`。夹具逻辑文件合计 80 B，F 盘可用空间实测差为 0 B；仅保留约 3 KiB 用途登记，不声称释放可观磁盘容量。
