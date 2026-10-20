# P0：关闭 NVIDIA 浮窗后的本地复测 · 2026-10-20

## 结论

**在用户确认浮窗主开关关闭后，内存增长仍能复现，P0 继续保持部分完成。** 五组处理和退出检查均完成，全部观察到的测试进程已退出，未触发 supervisor 安全停止或兜底回收。

VSR、NR、独立合成器以及 GUI 新进程仍加载 `nvspcap64.dll`。这既不能证明截图中的开关没关，也不能证明相关 hook 仍启用；本轮没有形成“该模块完全未加载”的环境对照。**当前证据不能确认或排除 NVIDIA 覆盖层为增长根因。**

原始采样、模块清单、设置/运行库哈希、输出元数据及比较结果见 [verification-summary.json](p0-overlay-off-20261020/verification-summary.json) 和 [comparison.json](p0-overlay-off-20261020/raw/comparison.json)。上一轮证据保留在 [P0 真实负载记录](P0_STABILITY_20261020.md)。

## 测量结果

“上一轮”指已归档的本地观察，不表示已核实当时浮窗处于开启状态。斜率只描述所测空闲窗口，不外推到小时级占用。

| 场景 | 上一轮 | 当前开关关闭后的观察 |
| --- | ---: | ---: |
| VSR 首帧后空闲 300 秒 | 约 52.4 MiB/分钟 | 约 **77.6 MiB/分钟**，仍增长 |
| NR 首帧后空闲 60 秒 | 约 43.5 MiB/分钟 | 约 **69.9 MiB/分钟**，仍增长 |
| 独立合成器首帧后空闲 60 秒 | 约 57.0 MiB/分钟 | 约 **78.6 MiB/分钟**，仍增长 |
| 同一大图第 1→4 轮 GUI 私有提交增量 | 约 97.7 MiB | 约 **95.3 MiB**，仍抬高 |
| 上述 GUI Python heap 增量 / Tk 图像数 | 约 1.85 MiB / 296→296 | 约 **1.85 MiB / 296→296** |
| 1,800 帧连续 SR+NR：预热后树提交前后差 | 约 121.6 MiB | 约 **121.4 MiB**，仍未进入平台 |

前三项跟踪同一个 PID 和创建时间，排除临时 `nvngx_update.exe` 后代出现/退出的干扰；排除空闲最初 10 秒，对剩余窗口前后各 1/5 样本取中位数，以两个中位时间点间隔计算斜率。VSR 当前单一工作进程的前后中位差约 299.9 MiB。

连续视频排除首个处理进度后的 20 秒预热，取处理窗口前后各 1/5 样本的中位数；因此与上一报告按 1/4 窗口计算的数字不同，表内两次已使用同一算法重算。图片私有提交增量使用 trace/GC 检查点。完整算法保留在 `scripts/compare_p0_stability.py`。

这些是各一次顺序复测，背景负载和测量时间不同；不能把当前较大的空闲斜率解释为“关闭覆盖层使问题更严重”。本轮能确认的是：当前关闭开关的环境下，增长仍存在。

## 功能与退出

| 本轮目录 | 参数与结果 | 树私有提交峰值 |
| --- | --- | ---: |
| `native-sr-off` | 960×540 → 1920×1080，首帧后空闲 300 秒，共 512 帧，309.343 秒结束 | 0.842 GiB |
| `native-nr-off` | 1920×1080，首帧后空闲 60 秒，共 3,600 帧，111.954 秒结束 | 1.089 GiB |
| `native-composer-off` | 1080p，首帧后空闲 60 秒，共 32 帧；上下文创建/销毁 1/1、设备遗留引用 0 | 0.295 GiB |
| `images-off` | 三种尺寸轮换 6 次，预览、导出、60 秒空闲、暂停、清缓存、退出；Tk 回调无错误、清理账目归零 | 2.244 GiB |
| `continuous-off` | 960×540 → 1920×1080，30 fps、1,800 帧，输出完整，124.077 秒结束 | 2.261 GiB |

`passed` 仅表示所测处理和进程树退出完成；所有记录的 `long_term_memory_plateau_verified` 仍为 false。

## 可比性与范围

- 当前机器为 64 GiB RAM、RTX 4070 SUPER 12 GiB、驱动 617.42；覆盖层 DLL 文件版本为 11.0.9.565。全局 GPU 快照不能用于逐进程显存归属。
- 五组保存设置与各自上一轮文件逐字节 SHA256 一致；1,800 帧输入视频也与上一轮 SHA256 相同。
- 六个生产源码文件、五个正式运行库均与上一轮交付时的源码/运行库清单一致。本轮只增强诊断模块清单、比较与归档脚本，并更新维护文档。
- 上一轮早期的部分 native/continuous 用例在运行期余量轮询修复之前执行，未逐轮保存源码快照；不能用该轮结束时的源码清单证明所有旧用例都运行了完全相同的 Python 代码。这也限制了因果比较。正式原生运行库保持相同。
- 本轮没有修改用户 NVIDIA/系统设置或运行库，没有制造真实 OOM。沿用树提交上限 8 GiB、物理及提交余量各 8 GiB 的受控退出界限。没有重复执行全量/关联单元测试；上一轮 233 项通过记录仍属于上一轮。
- 64 GiB 合成样本观察仍不能替代原用户 32 GiB 故障、实际素材和系统异常验收。

## 下一步

后续已完成 [进程归属与原生分配调用栈定位](P0_NATIVE_ALLOCATION_20261020.md)：主要捕获栈位于 NVIDIA 驱动，最小 CUDA/D3D11 组合可在不加载项目原生运行库时复现。该新证据仍未区分驱动独立问题与注入环境触发；本报告的五组原始结果及比较限制保持有效。

保持当前开关关闭，维护者方便时重启一次 Windows，再检查新进程是否仍加载该 DLL。重启是为了再验证环境状态，不是已确认的内存修复；如果 DLL 仍存在或增长仍复现，继续定位实际原生分配来源，不通过重启 NR 历史或降低画质来隐藏增长。

本轮没有新生产修复需要打包；前一轮资源所有权和内存压力退出修复继续保留，原生增长仍是 P0 待办。

## 重建与仓库卫生

唯一临时目录为 `tmp/p0-overlay-off-20261020/`，开始 F 盘可用约 59.45 GiB，预计新增低于 512 MiB；复用既有环境、模型和运行库。创建日期 2026-10-20，剩余任务登记复核日期 2026-10-27。

按仓库卫生守则登记新任务目录后，使用与原任务相同的脚本参数，设置 TEMP/TMP 到该目录、`PYTHONDONTWRITEBYTECODE=1`。五组参数见上表及各 `result.json` 的 `run_arguments`；例如：

```powershell
.venv/Scripts/python.exe -B scripts/verify_p0_stability.py --task tmp/<registered-task> --case native-sr --native-width 960 --frames 512 --idle-seconds 300 --timeout 390 --label off
.venv/Scripts/python.exe -B scripts/verify_p0_stability.py --task tmp/<registered-task> --case images --cycles 6 --frames 32 --idle-seconds 60 --timeout 360 --trace-gui --label off
.venv/Scripts/python.exe -B scripts/compare_p0_stability.py --baseline docs/development/p0-stability-final-20261020 --task tmp/<registered-task> --output tmp/<registered-task>/comparison.json
.venv/Scripts/python.exe -B scripts/collect_p0_stability.py --task tmp/<registered-task> --output docs/development/<new-evidence-dir> --runtime-only
```

证据归档逐文件校验，原始采样无损压缩；清理只涉及本任务可重建媒体/日志，保留 TASK.md。实际清理空间及校验结果见本次归档的 `cleanup.json` 和 `archive-verification.json`。

收尾已验证 43 份原始证据、源码/运行库清单和媒体哈希；检查观察过的精确进程身份全部退出、源码无任务临时目录引用、目标路径/祖先/条目无重解析点，并逐文件独占打开后删除 10 个明确任务内目标。共删除 56 文件、144,454,755 逻辑 bytes；F 盘可用空间实测增加 **144,560,128 bytes（约 137.86 MiB）**。仅保留 **3319 bytes** 的 TASK.md，供 2026-10-27 复核；以前任务、环境、运行库和发行基线均未清理。
