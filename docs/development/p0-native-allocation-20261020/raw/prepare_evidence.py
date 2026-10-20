import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.verify_p0_stability import checked_path, save

task = checked_path(Path(__file__).resolve().parent)
def digest(path):
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()

baseline = json.loads((ROOT/'docs/development/p0-overlay-off-20261020/verification-summary.json').read_text(encoding='utf-8'))
expected = {r['file']: r['sha256'] for r in baseline['source_and_runtime_manifest']}
production = ['dlss5tool/'+n+'.py' for n in ('gui','dlss_host_process','render_cache',
              'shared_render_preview','memory_budget','super_resolution')]
production += ['runtime/'+n+'.dll' for n in ('vsr_host','nvngx_vsr','nvngx_dlssnr','dlssnr_host_v2','dlss5_quality')]
check = [dict(file=n, current_sha256=digest(ROOT/n), previous_sha256=expected[n],
              matches_previous=digest(ROOT/n) == expected[n]) for n in production]
assert all(r['matches_previous'] for r in check)
sources = ['inspect_native_allocations.py','native_heap_trace.cpp','summarize_native_heap_trace.py',
           'profile_native_frame_memory.py','verify_p0_stability.py','collect_p0_stability.py']
snapshots = []
for name in sources:
    source = checked_path(ROOT/'scripts'/name)
    target = checked_path(task/('source-final-'+name))
    assert not target.exists()
    target.write_bytes(source.read_bytes())
    assert digest(target) == digest(source)
    snapshots.append(dict(source=str(source.relative_to(ROOT)), snapshot=target.name, sha256=digest(target)))
driver = checked_path(Path('C:/WINDOWS/System32/DriverStore/FileRepository/nv_dispi.inf_amd64_feedb8c0271ca811/nvwgf2umx.dll'))
save(task/'case-provenance.json', dict(production_and_runtimes=check, source_snapshots=snapshots,
    snapshot_scope='Final diagnostic sources; not per-case pre-run snapshots. Only additive diagnostic branches changed between cases.',
    driver=dict(path=str(driver), version='32.0.16.1742', sha256=digest(driver), bytes=driver.stat().st_size),
    trace_binary=dict(file='native_heap_trace.dll', sha256=digest(task/'native_heap_trace.dll')),
    case_environment={p.name:dict(DLSS5TOOL_P0_MEMORY_MAP='1',
        DLSS5TOOL_P0_HEAP_TRACE='1' if p.name.endswith('-heap') else None)
        for p in task.iterdir() if p.is_dir() and (p/'result.json').is_file()},
    unit_tests_rerun=False, original_32g_incident_reproduced=False,
    self_check_first_failure='Optimized test-client tail call omitted its module frame; allocation was recorded. Client /Od rerun passed.',
    minimal_trace_capacity_limit='8192 stack capacity reached; dropped_stacks=1298308. Use for path identity only.'))
print(json.dumps(dict(production_and_runtime_matches=len(check), source_snapshots=len(snapshots))))
