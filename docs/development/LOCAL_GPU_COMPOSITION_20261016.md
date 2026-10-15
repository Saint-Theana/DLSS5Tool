# 本地媒体 GPU 残差合成

## 结论

v3.0.0 比 v2.3.3 慢的主要原因仍是版本差异：v3.0.0 在每帧 DLSS 输出之后新增了外观/残差合成，v2.3.3 没有这段 CPU NumPy 工作。因此这不是插帧倍率本身变慢；用户反馈场景的诊断日志也没有真正启动 DLSSG 插帧。

本轮没有新开一套算法路线。复用 `native/realtime/quality.*` 使用的 Veyra `ResidualComposite` compute shader，并增加一个可选的 `dlss5_quality.dll` bridge。Python 的现有 `residual_composition.compose()` 在大尺寸 SDR 帧上调用 bridge；DLL 缺失、设备创建失败或 dispatch 失败时自动回到 NumPy 实现。

## 边界

- bridge 只处理 SDR `uint8`，默认达到 1,000,000 像素才启用，避免小预览被 CPU↔GPU 搬运拖慢。
- HDR/PQ/HLG/scRGB 保留现有线性光 CPU 路径，避免把传递函数和读回成本混在首轮迁移中。
- bridge 使用默认 D3D11 硬件适配器；多 GPU 选择和零读回的 D3D12 资源互操作仍是后续优化点。
- 画质控制、保护区域、羽化、alpha 保留和 residual fine controls 均在共享 shader 中处理；CPU 对照的 SDR 最大差异为 1 个 8-bit 码值。

## 本机验证

在已登记的 `tmp/feedback-repro-20261016/quality-build/` 中重建：

```powershell
cmake -S native/realtime -B tmp/feedback-repro-20261016/quality-build -G "Visual Studio 17 2022" -A x64 -DPython3_EXECUTABLE=.venv/Scripts/python.exe
cmake --build tmp/feedback-repro-20261016/quality-build --config Release --target dlss5_quality realtime_quality_tests dlss5_realtime_host --parallel 4
```

原生质量测试 10/10 通过。当前机器的随机 SDR 对照结果：2064×1152 约 2.26×，4128×2304 约 6.23×；两组 alpha 均完全一致。
