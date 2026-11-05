"""Recheck captured drafts locally; this is verifier replay, not a fresh model run.

Usage: python -m qa.replay_verification qa/runs/RUN/eval_results.json [--out FILE]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.agent import DATASET_FACTS
from services.answer_contract import parse_draft, verify_metrics
from services.guardrails import EvidenceIndex, verify_answer
from qa.scoring import score_metric


def run_contract(case: dict) -> tuple[dict, str]:
    if case.get('contract'):
        return case['contract'], 'run_snapshot'
    # Earlier v2 runs archived their exact bindings in the question and their
    # expected values/tolerances in scored. Reconstruct that historical contract
    # instead of silently regrading with later edits to case files.
    try:
        bindings = json.loads(case['question'].rsplit('\n', 1)[-1])
        scores = {item['anchor']: item for item in case['scored']}
        if isinstance(bindings, list) and bindings:
            metrics = []
            for binding in bindings:
                score = scores[binding['id']]
                metrics.append({**binding, 'expected': score['expected'],
                                'tolerance': score['tol'], 'required': True})
            return {'metrics': metrics}, 'archived_question_bindings'
    except (KeyError, TypeError, ValueError):
        pass
    return json.loads((Path(__file__).parent / 'cases' / f"{case['id']}.json").read_text()), 'current_contract'


def replay(path: Path) -> dict:
    run = json.loads(path.read_text())
    cases = []
    for case in run['cases']:
        evidence = EvidenceIndex()
        evidence.add(DATASET_FACTS)
        evidence.add_request(case['question'])
        for result in case.get('evidence', []):
            evidence.add_result(result)
            if result.get('query'):
                evidence.add_query_scope(result['query'])
        for sql in case.get('sql', []):
            evidence.add_query_scope(sql)
        entry = {'id': case['id'], 'semantic_verdict': 'needs_review'}
        try:
            draft = parse_draft(case.get('rejected_draft') or case.get('text', ''))
            metrics = draft.metrics or case.get('metrics', {})
            checked = verify_answer(draft.text, evidence, 'ru')
            cells_ok = verify_metrics(metrics, evidence.results)
            entry.update(verified=checked.ok and cells_ok,
                         unsupported_numbers=checked.unsupported_numbers,
                         unsupported_names=checked.unsupported_names,
                         cells_ok=cells_ok, text=draft.text)
            contract, contract_source = run_contract(case)
            entry['contract_source'] = contract_source
            scores = [score_metric(m, metrics) for m in contract['metrics'] if m['required']]
            entry.update(matched=sum(s['matched'] for s in scores), total=len(scores), scored=scores)
        except ValueError as exc:
            entry.update(verified=False, error=str(exc))
        cases.append(entry)
    return {'kind': 'offline_verifier_replay', 'source_run': str(path), 'cases': cases}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    result = replay(args.run)
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    for case in result['cases']:
        print(case['id'], 'VERIFIED' if case['verified'] else 'REJECTED',
              f"{case.get('matched', 0)}/{case.get('total', 0)} bound metrics",
              case.get('error') or case.get('unsupported_numbers'))
    raise SystemExit(0 if all(c['verified'] for c in result['cases']) else 1)
