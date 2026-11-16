"""公开实验入口失败时不能启动实验或回显候选内容。"""
import json
from pathlib import Path
import subprocess
import sys


def test_lab_cli_rejects_bad_candidate_without_side_effects(tmp_path):
    candidate = tmp_path / 'candidate.json'
    candidate.write_text(json.dumps({'role': 'fixture-secret-input'}), encoding='utf-8')
    output = tmp_path / 'private-output'
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, str(root/'scripts/v2_acceptance.py'),
        'lab', 'run', '--case', 'all', '--candidate-manifest', str(candidate),
        '--out-private', str(output)], cwd=root, capture_output=True, text=True)
    assert result.returncode == 42
    body = json.loads(result.stdout)
    assert body['blockers']
    assert body['production_ready'] is False
    assert 'fixture-secret-input' not in result.stdout + result.stderr
    assert not result.stderr
    assert not output.exists()
