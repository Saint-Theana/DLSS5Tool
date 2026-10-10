"""Run selected Tk tests in fresh processes (Tcl interpreter teardown isolation).

Use --tests to extend scope. Never installs dependencies or modifies user state.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume', action='store_true', help='Reuse prior passes only when source is unchanged')
    parser.add_argument('--tests', nargs='+', default=[
        'tests/test_parameter_unification.py', 'tests/test_parameter_range.py',
        'tests/test_realtime_source_preview.py', 'tests/test_workbench_ui.py'])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = args.output / 'results.json'
    prior = json.loads(report.read_text(encoding='utf-8')) if args.resume and report.is_file() else []
    passed = {r['node'] for r in prior if r['returncode'] == 0}
    command = [sys.executable, '-B', '-m', 'pytest', '-p', 'no:cacheprovider']
    result = subprocess.run(command+['--collect-only', '-q', *args.tests], cwd=ROOT,
                            capture_output=True, text=True, encoding='utf-8', errors='replace', check=True)
    nodes = [line.strip() for line in result.stdout.splitlines() if line.startswith('tests/') and '::' in line]
    results = [r for r in prior if r['node'] in passed and r['node'] in nodes]
    for index, node in enumerate(nodes):
        if node in passed:
            continue
        try:
            result = subprocess.run(command+['-q', node, '--basetemp', str(args.output / f'test-{index}')],
                                    cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
            item = {'node': node, 'returncode': result.returncode, 'output': result.stdout+result.stderr}
        except subprocess.TimeoutExpired:
            item = {'node': node, 'returncode': 124, 'output': 'Timed out after 60 seconds'}
        results.append(item)
        print(f'{index+1}/{len(nodes)} {"PASS" if item["returncode"] == 0 else "FAIL"} {node}', flush=True)
        report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    return int(any(r['returncode'] for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
