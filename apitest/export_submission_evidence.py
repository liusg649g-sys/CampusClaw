"""Run only five isolated evidence tests and export sanitized synthetic samples."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apitest'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'submission' / 'evidence')
    arguments = parser.parse_args()
    source = ROOT / 'apitest' / 'cases' / 'submission' / 'EVIDENCE.py'
    spec = importlib.util.spec_from_file_location('public_submission_evidence', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(module.SubmissionEvidenceTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    statistics = {
        'total': result.testsRun,
        'passed': result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
        'failed': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
        'llm': 'Mock HTTP transport; no real model API called',
        'mcp': 'real isolated local MCP server and deterministic calculator',
        'fixtures': 'temporary synthetic data only; no original data or credentials exported',
    }
    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    # No raw unittest tracebacks/logs, headers, runtime config or account files.
    (output / 'test_summary.json').write_text(json.dumps(statistics, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if not result.wasSuccessful():
        print('Evidence tests failed; sample export not updated.')
        return 1
    if len(module.EVIDENCE) != 5:
        raise RuntimeError('Missing acceptance evidence; refusing partial export')
    for name, evidence in sorted(module.EVIDENCE.items()):
        # All values are synthetic and selected by tests; forbid accidental
        # runtime credential/config fields before writing public artifacts.
        text = json.dumps(evidence, ensure_ascii=False, indent=2)
        for forbidden in ('Authorization', 'Bearer ', 'auth_token', 'api_key', 'token_blob', 'password', 'TEST_ACCOUNTS'):
            if forbidden.lower() in text.lower():
                raise RuntimeError('Sensitive field found; refusing export')
        (output / (name + '.json')).write_text(text + '\n', encoding='utf-8')
    print('Exported five synthetic samples and test summary:', output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
