"""Rebuild from hints by asking (hint_quiz.py, web.quiz_json)."""
import json
from pathlib import Path

import yaml

from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.hint_quiz import Quiz
from quadrilla_solver.hints import extract_hints, same_structure
from quadrilla_solver.model import PortRef, layout_from_dict
from quadrilla_solver.validation import validate_layout
from quadrilla_solver.web import quiz_json

ROOT = Path(__file__).resolve().parents[1]
CAT = load_catalog(ROOT / "catalog" / "parts.yaml")
SEED12 = ROOT / "examples" / "hint_quiz" / "seed12.yaml"


def _hints(path):
    data = yaml.safe_load(path.read_text())
    layout = layout_from_dict(data)
    src = data["routing_query"]["source"]
    return data, layout, extract_hints(layout, CAT, "grid", PortRef(src["component_id"], src["port"]))


def test_quiz_answers_lead_back_to_the_original():
    _, original, hints = _hints(SEED12)
    quiz = Quiz(hints, CAT)
    assert quiz.complete and len(quiz.cands) > 1
    asked = 0
    while (q := quiz.question()) is not None:
        assert q["id"] in hints["answers"]
        quiz.answer(q["id"], hints["answers"][q["id"]])
        asked += 1
    assert len(quiz.cands) == 1 and asked <= 12
    data = quiz.layout(0)
    rebuilt = layout_from_dict(data)
    assert same_structure(original, rebuilt, CAT)
    q = data["routing_query"]
    result = validate_layout(rebuilt, CAT, source=PortRef(**q["source"]),
                             sinks=tuple(PortRef(**s) for s in q["sinks"]))
    assert result.valid, result.errors[:3]


def test_quiz_json_flow_and_skip():
    data, _, _ = _hints(SEED12)
    r = json.loads(quiz_json(json.dumps({"action": "start", "layout": data}), str(ROOT)))
    assert r["count"] > 1 and r["question"] and r["hints"]["tower_parts"]
    first = r["question"]["id"]
    r = json.loads(quiz_json(json.dumps({"action": "answer", "qid": first, "value": None}), str(ROOT)))
    assert r["question"]["id"] != first                  # a skipped question is not asked again
    answers = json.loads(quiz_json(json.dumps({"action": "start", "layout": data}), str(ROOT)))["hints"]["answers"]
    r = json.loads(quiz_json(json.dumps({"action": "start", "layout": data}), str(ROOT)))
    while r["question"]:
        r = json.loads(quiz_json(json.dumps({"action": "answer", "qid": r["question"]["id"],
                                             "value": answers[r["question"]["id"]]}), str(ROOT)))
    assert r["count"] == 1 and r["same"] is True


def test_quiz_json_refuses_seesaws():
    data = yaml.safe_load((ROOT / "examples" / "gallery" / "mr-5af6029a.yaml").read_text())
    assert any(p["part_type"] == "seesaw" for p in data["parts"])
    r = json.loads(quiz_json(json.dumps({"action": "start", "layout": data}), str(ROOT)))
    assert r.get("code") == "unsupported"
