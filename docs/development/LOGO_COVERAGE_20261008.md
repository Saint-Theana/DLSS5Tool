# Logo 覆盖补齐（2026-10-08）

## 本轮落地

- 实时输出：新增 `native/realtime/app_icon.h` 与 `app_icon.rc.in`。
  宿主 EXE 内嵌 `assets/app.ico`，输出窗口创建与 DPI 改变时加载大小图标，
  按窗口属性保留所拥有的句柄，换 DPI 和关闭窗口时释放。图标不绘制到增强画面内。
  在生成适配层接入，不修改第三方源文件；CMake 对缺失 ICO 报错。
  图标文件已纳入 `realtime_provenance.py` 的源输入清单。
- 独立更新器：`build_update_helper.ps1` 检查 ICO 存在并通过 `--icon` 嵌入。
- 关于页：56 逻辑像素 Logo 与软件名称并排；按 UI 缩放显示，透明边角适配明暗背景。
  图片复用现有 `app.png`，保留图片对象引用；图片不可读取时软件名称仍显示。

## 验证

- 使用当前 `.venv`，正常启动前置条件启用 DPI 感知。
  `tests/test_about_dialog.py` 与 `tests/test_app_icon.py` 共 13 项通过（最终 2.20 秒）。
- 关于页中英文、明暗主题 4 组合检查全部可见控件未越出窗口。
  当前 150% DPI 下 Logo 为 84 px，中文窗口 508×428，英文窗口 735×457；截图已目视检查。
- `app_icon_tests.cpp` 使用真实 HWND 验证创建、96/144/192 DPI、主动释放、销毁与重建。
  30 次循环后 GDI 资源数从 4 到 4，无增长。作为 CMake/CTest 目标保留。
- 更新器候选和完整实时宿主 Release 编译成功。通过 `verify_exe_icon.py`
  逐帧比较 EXE 内的资源数据：两者全部 11 帧均与 `assets/app.ico` 一致。
- CMake 首次沙箱配置未发现编译器；MSBuild 沙箱构建出现 PATH/Path 重复。
  正常桌面环境编译成功，没有修改系统环境变量或关闭安全配置。
- 当前 `runtime/realtime/dlss5_realtime_host.exe` 已替换为验证候选，并更新现有溯源清单；
  其他运行资源与许可文件未替换。`validate_runtime(..., local_candidate=True)` 校验通过。
  更新后宿主 `--catalog` 正常退出，读取 157 个效果；未启动媒体捕获或做 GPU 画质验收。
- 已接入宿主 SHA-256：`0ab06c3ae30cb02d93593275fa5d0e36db61d7523ab53d3d582e33c288a0eec8`。
- `git diff --check` 通过。本轮没有生成正式发行包、升版本或发布附件。

Windows 图标设置与句柄生命周期依据
[微软图标文档](https://learn.microsoft.com/en-us/windows/win32/menurc/about-icons)。

## 重建与回滚

```powershell
$env:TEMP='F:\project\DLSS5Tool\tmp\logo-coverage-20261008'
$env:TMP=$env:TEMP
.venv/Scripts/python.exe -B -c "from dlss5tool import ui_theme; ui_theme.enable_dpi_awareness(); import pytest; raise SystemExit(pytest.main(['-q','-p','no:cacheprovider','tests/test_about_dialog.py','tests/test_app_icon.py']))"
./scripts/logo_coverage_probe.ps1 -WorkDirectory tmp/logo-coverage-20261008/native-probe
.venv/Scripts/python.exe -B scripts/about_brand_probe.py --work-dir tmp/logo-coverage-20261008/ui --screenshots
./scripts/build_update_helper.ps1 -OutputDirectory tmp/logo-coverage-20261008/updater -WorkDirectory tmp/logo-coverage-20261008/updater-build
# 按正常 build_realtime.ps1 工作流构建宿主；图标资源自动嵌入。
```

F 盘开始可用约 89.7 GiB，完整原生构建新增峰值预算小于 4 GiB。
依赖复用，没有复制 Torch/CUDA 或模型环境。
临时编译与候选、截图、隔离日志成功验收后清理。
仅在 `tmp/logo-coverage-20261008/rollback/` 保留原宿主及原清单，
另有 `TASK.md` 说明；复核日期为 2026-10-15，不自动删除。
回滚时先关闭实时宿主，将回滚目录中的这两个文件覆盖回 `runtime/realtime/`，
再运行 `validate_runtime(..., local_candidate=True)` 校验。

后续可选项：快捷方式与任务栏固定场景验收、宣传封面统一、横向品牌素材。
