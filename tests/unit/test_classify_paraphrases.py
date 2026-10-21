"""Covers: AG-1, AG-7. UX decisions P0-2 (dose paraphrases) and P0-3 (emergency phrasings)."""
import pytest

from assistant.classify import classify

ORDERS = [
    "Heparin drip rate for a 90 kg pt?",
    "What premedication dose of prednisone for a patient with a prior contrast reaction?",
    "ok what dose of reversal agent?",
    "How many mg of morphine for a 70 kg man",
    "vanc dose 70kg",
    "titrate the insulin drip for this patient",
    "what rate should the heparin run at for 85kg",
    "bolus amount for a 60 kg patient",
    "What is the dosage of ceftriaxone for my patient?",
]
NOT_ORDERS = [
    "Which medications need an independent double-check?",
    "Who do I call for weight-based dosing questions?",
    "What is the controlled substance waste policy?",
    "How does the pharmacy consult work for dosing?",
    "What are the sepsis screening criteria?",
]
EMERGENCIES = [
    "pt face drooping and slurred speech right now",
    "A visitor collapsed in the lobby and isn't breathing",
    "he is unconscious on the floor",
    "my patient isn't responding",
    "someone just passed out in the hallway",
    "patient having a seizure right now",
    "the patient collapsed",
    "she has slurred speech and her arm is weak, happening now",
]
NOT_EMERGENCIES = [
    "What are the signs of stroke in BE-FAST?",
    "What does the stroke alert protocol say about face drooping?",
    "Where do I find the Code Blue procedure?",
    "What is the cardiac arrest policy?",
    "How do we document a visitor who collapsed last week?",
    "How long should I stay with a patient after a seizure?",
]


@pytest.mark.parametrize("text", ORDERS)
def test_dose_questions_are_patient_orders(text):
    assert classify(text).label == "patient_order"


@pytest.mark.parametrize("text", NOT_ORDERS)
def test_policy_questions_about_medication_are_not_orders(text):
    assert classify(text).label != "patient_order"


@pytest.mark.parametrize("text", EMERGENCIES)
def test_live_emergencies_are_recognised(text):
    assert classify(text).label == "emergency"


@pytest.mark.parametrize("text", NOT_EMERGENCIES)
def test_policy_questions_about_emergencies_are_not_alarms(text):
    assert classify(text).label != "emergency"
