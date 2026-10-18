# P1/P2 本地合成实施记录

2026-10-19。用户批准继续落地 P1/P2，复用参考项目；真实多卡结果待后续用户反馈，不阻塞本轮单卡及故障路径验证。未授权发布。

## 回滚点

- `6e05ff6`：P0 内存生命周期与预算保护。
- `ac9bb01`：统一 SDR/PQ/HLG/scRGB 零效果旁路。原始 JUnit 失败日志保留原样，其尾空格不作源代码空白检查。
- 原有 `docs/release/RELEASE_NOTES_v3.0.1.md` 与 `packaging/update-policy.json` 修改不属于本任务。

## 实施顺序与验收

1. 明确合成适配器契约：传递实际选定的 LUID；不存在/旧 DLL 不支持则 CPU 回退，不静默换卡。预览 worker 保留一个执行和一个可替换请求，设备资源只由所属线程释放，退出关闭。
2. 复用 Veyra shader，HDR 细调与 CPU 的线性亮度/色度公式对齐；PQ/HLG Rec.2100、scRGB Rec.709，保留有符号/超白。
3. 四种 profile 共用 native 合成入口；保持百万像素门槛、小图 CPU 与故障回退。
4. 复用现有同卡 CUDA/NVENC 资源契约，合成纹理交给真实 GPU 消费者；CPU 消费者保留读回。所有权/同步及格式/transfer 明确。
5. 根据真实证据减少转换/复制、完成相关模块回归和有界内存实测；不提高队列上限冒充流水线。

## 复用边界

- 来源固定在 `native/realtime/sources.lock.json`、`native/realtime/NOTICE.md`。
- Veyra `NrResidualComposite.hlsl` 已在现有构建中复用；只在 prepare 脚本和本项目适配层修改，不改 vendor 产品/运行时。
- Magpie/Veyra 设备和共享纹理生命周期作为参考；编码继续复用本项目 `gpu_video_export` / `cuda_interop`，不另造编码器。
- 实时宿主的中性 `applyControls=false` 路径不变；不向实时插入 CPU-pointer 桥。

## 当前状态

- 第 1 项完成本机及故障路径验证：create_on_adapter + 实际身份返回/复核；缺失设备/旧 DLL/错误身份回退 CPU。大图才解析设备，不给小图增加枚举成本。
- 两种 GUI 合成 job 改为持久 latest-only worker；最多一个执行/一个替换请求。失效/退出在 owner 线程释放，空闲 30 秒释放 GPU 但保留轻量线程；结束活动任务后异步关闭，不从 Tk 销毁工作线程的资源。
- 定向测试：`python -m pytest tests/test_composer_device_and_worker.py tests/test_native_composer_lifetime.py tests/test_parameter_response.py tests/test_preview_cache_clear.py -q`：45 passed、7 subtests。pytest 默认 cache 目录写入权限警告不影响断言；后续使用任务内 cache。
- 构建：`scripts/build_realtime.ps1 -QualityOnly -BuildDirectory F:/project/DLSS5Tool/tmp/p1-p2-composer-20261019/build -OutputDirectory F:/project/DLSS5Tool/tmp/p1-p2-composer-20261019/candidate` 成功，仅构建质量桥与相关 shader/GPU 测试，不编译整个实时宿主。
- 实卡：`scripts/verify_local_composer.py --dll tmp/p1-p2-composer-20261019/candidate/dlss5_quality.dll --task tmp/p1-p2-composer-20261019`：4070 SUPER LUID 0:79242 身份一致；不存在的 LUID 被拒绝；6 次请求同线程/同 handle。1,002,001 像素 SDR 与 CPU 最大误差 1 个 8-bit code；首帧约 224 ms，预热后约 12.5–13.7 ms（仅合成调用，不等于整个 GUI 加速）。
- `realtime_quality_tests.exe`：20 个原有实卡 shader/直写/拷贝回退用例通过。
- 第 2/3 项完成：在既有 Veyra shader 加入线性 HDR 亮度/色度细调及显式权重；实时中性分支保持旧运算顺序。四档共用设备、阈值、故障回退策略，HDR 上传 RGBA32F 线性值以避免额外 FP16 中间量化，输出按原 profile/dtype 恢复，保留 alpha。PQ/HLG 仍复用 Python 原 EOTF/OETF，不另起颜色转换栈。ABI v2 之前的 DLL 不开启 HDR。
- HDR 定向测试 93 passed（`hdr-verified-unit-tests.xml`）。首轮断言执行完毕后 pytest 清理系统旧临时链接遇到权限错误，退出 1；改用本任务独立 `--basetemp` 重跑通过，没有删除系统目录。
- 实卡 `hdr-native.json`：18 组 profile/dtype/RGB/BGR 非中性细调＋保护遮罩对照及两组独立线性权重检查。线性最大绝对误差 1.44e-6；PQ float32 最大 1.69e-5、HLG 3.95e-6，float16 至多相邻量化码，alpha 全部精确；scRGB 负值/超白保留。16-bit PQ 原先过严的 1/65535 阈值观察到 2/65535 差异，改为预先说明的 3/65535 上限（低于 0.05 个 10-bit code），不声称逐 bit 一致。原有 20 个实卡 shader 用例仍通过。
- 第 4/5 项继续施工，不把上述单卡检查扩展为多卡实际通过。
- 新任务目录 `tmp/p1-p2-composer-20261019/`，峰值预算 4 GiB，开始可用约 61.9 GiB。
