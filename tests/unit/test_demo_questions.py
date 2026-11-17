"""Covers: UX-3. The corpus questions offered as one-click demo prompts (api/demo_questions.py)."""
import yaml

from api.demo_questions import CORPUS_PATH, demo_enabled, groups_for, load_corpus
from common.config import Settings

CORPUS = {
    "scenarios": {"plain_lookup": "A direct question", "multi_turn": "Follow-ups", "emergency": "Happening now"},
    "conversations": [
        {"id": "SAM-01", "persona": "sam", "scenario": "plain_lookup", "turns": [{"ask": "Rub how long?"}]},
        {"id": "PRI-01", "persona": "priya", "scenario": "plain_lookup", "turns": [{"ask": "Sepsis criteria?"}]},
        {"id": "SAM-09", "persona": "sam", "scenario": "multi_turn",
         "turns": [{"ask": "Gel time?"}, {"ask": "and soap?"}, {"ask": "when soap instead?"}]},
        {"id": "SAM-15", "persona": "sam", "scenario": "emergency", "turns": [{"ask": "patient not breathing"}]},
        {"id": "CAS-01", "persona": "casey", "scenario": "off_role", "turns": [{"ask": "Code Blue?"}]},
        {"id": "RIL-01", "persona": "riley", "scenario": "plain_lookup", "turns": [{"ask": "Visiting hours?"}]},
    ],
}


def asks(groups):
    return [[turn for c in g["conversations"] for turn in c["turns"]] for g in groups]


def test_questions_are_grouped_by_scenario_in_corpus_order_with_the_corpus_description():
    groups = groups_for("sam", {"all-staff", "clinical"}, CORPUS)
    assert [g["scenario"] for g in groups] == ["plain_lookup", "multi_turn", "emergency"]
    assert groups[0]["title"] == "Plain lookup" and groups[0]["description"] == "A direct question"


def test_only_the_signed_in_personas_questions_are_offered():
    flat = [t for g in asks(groups_for("sam", {"all-staff"}, CORPUS)) for t in g]
    assert "Rub how long?" in flat and "Sepsis criteria?" not in flat and "Visiting hours?" not in flat


def test_a_multi_turn_conversation_keeps_its_steps_in_order():
    multi = next(g for g in groups_for("sam", {"all-staff"}, CORPUS) if g["scenario"] == "multi_turn")
    assert multi["conversations"] == [{"id": "SAM-09", "turns": ["Gel time?", "and soap?", "when soap instead?"]}]


def test_an_account_without_assistant_access_is_offered_nothing():
    assert groups_for("casey", {"operators"}, CORPUS) == []


def test_a_registered_staff_member_gets_the_general_staff_questions():
    groups = groups_for("new-user-42", {"all-staff"}, CORPUS)
    assert [t for g in asks(groups) for t in g] == ["Visiting hours?"]


def test_an_unknown_account_without_all_staff_is_offered_nothing():
    assert groups_for("someone", {"doc-admins"}, CORPUS) == []


def test_scenarios_with_no_questions_for_the_persona_are_left_out():
    assert "emergency" not in [g["scenario"] for g in groups_for("priya", {"all-staff"}, CORPUS)]


def test_demo_prompts_are_only_enabled_in_demo_setups():
    assert not demo_enabled(Settings(_env_file=None, auth_mode="local", demo_accounts_enabled=False))
    assert demo_enabled(Settings(_env_file=None, auth_mode="local", demo_accounts_enabled=True))
    assert demo_enabled(Settings(_env_file=None, auth_mode="header"))


def test_the_shipped_corpus_has_questions_for_every_persona_who_can_chat():
    corpus = load_corpus()
    personas = yaml.safe_load((CORPUS_PATH.parents[2] / "config" / "personas.yaml").read_text())["personas"]
    for uid, persona in personas.items():
        if "all-staff" in persona["groups"]:
            assert groups_for(uid, set(persona["groups"]), corpus), uid
    for convo in corpus["conversations"]:
        assert convo["scenario"] in corpus["scenarios"] and all(t["ask"].strip() for t in convo["turns"])
