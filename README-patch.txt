DLSS5Tool minimal source patch — 2026-10-22

Baseline commit: 7835104bfab3e66d9fb08c3fd5171bc97b9aba9a

This is a source review patch, not a packaged application update.
It refreshes a stale memory snapshot once before denial and includes exact
memory values in errors. It does not lower safety thresholds, reclaim caches,
change pixels/audio, or fix native memory growth.

At the matching source checkout root:
  git apply --check path/to/memory-admission-refresh.patch
  git apply path/to/memory-admission-refresh.patch

Validation command (13 tests passed with Python 3.12.14):
  python -B -m unittest tests.test_memory_admission_refresh tests.test_i18n.LocalizationTests.test_language_catalogs_have_identical_nonempty_keys tests.test_i18n.LocalizationTests.test_translation_formats_named_values_and_falls_back_safely -v

Do not copy these Python files over a packaged exe and assume it is updated.
Use the project's verified development/build workflow for actual deployment.
Full source trace, patch roadmap, audio requirements and GPU acceptance tests
are in DLSS5Tool-memory-review.md. Native/GPU validation remains outstanding.
