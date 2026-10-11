# v3.0.0 更新日志同步（2026-10-11）

## 变更范围

- 补齐主更新日志中的参数交互反馈、双模式显卡资源协调、轻量版精简及硬件光流说明。
- 状态改为“已完成本地打包，未公开发布”，日期更新为 2026-10-11。
- 原 v3.0.0 尚未上传，本次是同一未发布候选的文案修订；不用于已发布同版本的在线更新。
- 沿用已经验收的主程序、更新助手、推理组件、运行库和模型，不重编译，不重跑或冒称新增 GPU 验收。

## 产物与回滚

- 文案同步版：`dist/v3.0.0-changelog-20261011/editions/`；全部内容校验通过，已登记为当前候选和 v3.0.0 升级基线。
- 原版：`dist/v3.0.0-release-20261011/editions/`，保留为唯一文案同步前回滚；不得混用两目录的 ZIP、分卷、摘要或增量包。
- 原冻结功能验收与分发限制仍见 [打包记录](V300_PACKAGING_20261011.md)。本次不改变 LocalCandidate、许可审查未完成和未公开发布状态。

## 重建与验证

```powershell
.venv/Scripts/python.exe -B scripts/release_updates.py --preflight-version v3.0.0
.venv/Scripts/python.exe -B tmp/changelog-v300-20261011/prepare.py
.venv/Scripts/python.exe -B scripts/package_editions.py --base tmp/changelog-v300-20261011/base --component dist/v3.0.0-release-20261011/editions/DLSS5Tool-v3.0.0-win64-addon/mods/enhancement --models dist/v3.0.0-release-20261011/editions/DLSS5Tool-v3.0.0-win64-addon/mods/models --licenses tmp/package-licenses-v2.1.1 --output dist/v3.0.0-changelog-20261011/editions --local-candidate
.venv/Scripts/python.exe -B scripts/verify_edition_refresh.py --before dist/v3.0.0-release-20261011/editions --after dist/v3.0.0-changelog-20261011/editions --report docs/release/v300-packaging-20261011/changelog-refresh.json
.venv/Scripts/python.exe -B scripts/release_updates.py --check-upload dist/v3.0.0-changelog-20261011/editions/github-assets
```

重建必须使用全新输出目录；已存在时不能直接重复上述打包命令。任务容量与回收登记：`tmp/changelog-v300-20261011/TASK.md`。

## 当前验证记录

- `tests.test_release_packaging tests.test_release_updates`：31 项通过。
- v3.0.0 基线预检通过，只选择正式 v2.3.3 lite/full；旧基线原样保留。
- 补跑完整发行回归测试集：114 项通过（20.802 秒）。
- 三种 ZIP CRC、每个归档文件 SHA256、分卷重组、精确 full = lite + addon、规范轻量 ZIP 附件、三份 Release Notes 一致性通过。
- 相对上一候选，lite/full 只改 `CHANGELOG.md`（增加 365 bytes），addon 文件内容完全不变。重新生成的 ZIP 因条目时间等元数据变化，addon 压缩文件摘要也会变化；不能混用旧分卷和新摘要。
- v2.3.3 → v3.0.0 两种增量流式还原通过，分别覆盖 lite 1,865 / full 4,279 个目标文件，`--check-upload` 通过。没有在旧正式基线上执行安装。
- 小型证据：[内容校验](v300-packaging-20261011/changelog-refresh.json)；完整包与分卷摘要以新目录 `package-report.json`、`SHA256SUMS.txt` 为准。
- 新版登记后，`--preflight-version v3.0.1` 通过，确认下次升级读取新的 v3.0.0 lite/full 清单。打包报告副本见 [新候选报告](v300-packaging-20261011/changelog-package-report.json)。

| 形态 | ZIP 字节数 | SHA256 |
| --- | ---: | --- |
| lite | 588,040,687 | `e9d3c1636eb3122f1f3f4ffa313eaa368936a8b6c735eeda4c22b6d747d45408` |
| addon | 3,053,866,457 | `60a490a9a9cf9e7d761e6c2abfb63759d77df3f0915e9ca5f4b783146ab6ba62` |
| full | 3,641,904,633 | `68e918222bd01e11ecbf6aee46c45351f05af5773fbafe5a85a15dd24203fabc` |

| v2.3.3 → v3.0.0 增量 | 字节数 | SHA256 |
| --- | ---: | --- |
| lite | 55,410,348 | `6494976c91e24bb1a8eb517433b412a17bc7781e85b60495e7820a748218305a` |
| full | 89,769,829 | `515cad54a9c7a16669ac7b2859f9feb719805b1de00995dcecacd749d0ba5239` |

## 临时文件收尾

- 已确认本次打包／准备进程退出；删除前核实 `tmp/changelog-v300-20261011/base` 绝对路径位于本任务目录内，无链接／目录联接，旧验收包及新候选提供重建来源。
- 已永久删除该可重建临时基础包（1,032,092,053 bytes），F 盘可用空间 42,188,574,720 → 43,223,285,760 bytes，实测释放 1,034,711,040 bytes；不是从回收站恢复。
- 本任务临时目录仅留数 KiB 的登记和一次性准备脚本，便于复现，2026-10-18 复核；通用验证脚本保存在 `scripts/verify_edition_refresh.py`。原候选作为一个回滚版本保留，其他任务、旧基线和依赖均未删除。
- 未创建 Git 提交、推送、Release 或上传附件。
