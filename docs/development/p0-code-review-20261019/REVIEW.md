# P0 code review — 2026-10-19

Verdict: CHANGES_NEEDED. Scope: the current P0 diff against ab6ffc3 and its direct callers. Production code was not edited during this review. Existing v3.0.1 release-note edits are excluded.

Follow-up: the user subsequently authorized implementation. All four findings now have source fixes and targeted verification; see [P0 review fixes](../P0_REVIEW_FIX_20261019.md). The verdict and evidence below describe the original reviewed state.

## Findings

1. [P2, DIFF_BLOCKER] `dlss5tool/dlss_host_process.py:376-378` (same new throw in `super_resolution.py:435-437`): a worker still alive after stop/terminate/kill now causes close to raise. The sequential cleanup in GUI SDR/HDR exports (`gui.py:10157-10164`, `10296-10305`) then skips healthy VSR close and writer abort. Baseline/current fake-worker comparisons observe close/abort 1/1 versus 0/0. Each independent resource must receive cleanup even when another close fails.
2. [P2, DIFF_RISK] `dlss5tool/video_export.py:592-594`: memory admission runs before HDR sequence EOF/closed handling. With headroom exhausted after the last frame, the baseline returns None and completes; the current implementation aborts a fully processed one-frame export. Honor known EOF/closed state before allocating the next frame.
3. [P2, DIFF_RISK] `dlss5tool/frame_generation.py:439-441`: unconditional SR/NR resource estimates reject a plain 128x128 export with scale=1, multiplier=1, enhance=False. After the existing reserve, 256 MiB headroom is compared with a 537,657,344-byte plan that includes unused processing components. The baseline completes; current code creates no writer. Estimate only enabled stages and real upcoming allocations.
4. [P2, DIFF_RISK] `dlss5tool/dlss_host_process.py:238-242`: admission uses requested 16 slots although the legacy backend is actually capped at 3. At 3840x2160 SDR with 512 MiB headroom, the code requests 1,194,393,600 bytes instead of the 331,776,000 bytes corresponding to 3 slots. Baseline reaches shared-memory allocation; current rejects early. Reuse the effective capacity rule from `_configure_host`.

## Evidence and limits

- See `evidence.json`. Targeted comparisons used synchronous fake processes/readers/writers, synthetic frames, and mocked memory availability. No full regression suite, real encoder/worker, GPU stability run, or real OOM was performed in this review.
- Baseline implementations were extracted from HEAD with AST into isolated namespaces. The corrected legacy control uses HEAD init and HEAD close together; the initial mixed-version control is excluded.
- `git diff --check` passes (Git reports the existing gui.py CRLF normalization warning).
- Review-only artifacts are retained as small documentation. Dummy inputs/outputs and per-probe logs are reconstructible and are cleaned from this task's tmp directory.
