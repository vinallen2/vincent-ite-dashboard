"""Deterministic ITE question planning: broad coverage with a real cooldown.

The model writes clinical questions but does not select from its own recent favorites.
Question topics last published in the previous 14 days are not eligible, even when
a 1- or 3-day recall review is due. Such concepts can be reinforced in teaching
without reusing the same scored clinical stem.
"""
from datetime import date
from difflib import SequenceMatcher
import re

# Canonical domain/topic pairs. Keep granular and diversify the full ABA blueprint.
BLUEPRINT = [
    ("Airway", "Awake intubation decision-making"),
    ("Airway", "Failed intubation rescue and oxygenation"),
    ("Airway", "Extubation planning for a difficult airway"),
    ("Airway", "Double-lumen tube placement verification"),
    ("Airway", "Aspiration risk and rapid sequence induction"),
    ("Respiratory", "Auto-PEEP and dynamic hyperinflation"),
    ("Respiratory", "Pulmonary shunt versus dead-space physiology"),
    ("Respiratory", "Ventilator compliance and driving pressure"),
    ("Respiratory", "Hypoxic pulmonary vasoconstriction"),
    ("Respiratory", "Alveolar ventilation and carbon dioxide"),
    ("Cardiac", "Aortic stenosis perioperative hemodynamics"),
    ("Cardiac", "Right ventricular failure and pulmonary hypertension"),
    ("Cardiac", "Mitral regurgitation hemodynamic management"),
    ("Cardiac", "Coronary perfusion pressure and ischemia"),
    ("Cardiac", "Intraoperative transesophageal echo for shock"),
    ("Pharmacology", "Age adjustment of minimum alveolar concentration"),
    ("Pharmacology", "Context-sensitive decrement time of anesthetic infusions"),
    ("Pharmacology", "Neuromuscular blockade reversal strategy"),
    ("Pharmacology", "Local anesthetic systemic toxicity treatment"),
    ("Pharmacology", "Malignant hyperthermia recognition and dantrolene"),
    ("Pediatric", "Neonatal oxygen consumption and desaturation"),
    ("Pediatric", "Pediatric bronchospasm management"),
    ("Pediatric", "Infant endotracheal tube sizing"),
    ("Pediatric", "Pediatric fluid and glucose management"),
    ("Pediatric", "Congenital heart disease shunt physiology"),
    ("Obstetric", "Spinal anesthesia hypotension for cesarean delivery"),
    ("Obstetric", "Postpartum hemorrhage and uterotonic choice"),
    ("Obstetric", "Preeclampsia magnesium and anesthesia"),
    ("Obstetric", "Neuraxial anesthesia and anticoagulation in pregnancy"),
    ("Obstetric", "Maternal oxygenation and fetal physiology"),
    ("Neuro", "Intracranial compliance and autoregulation"),
    ("Neuro", "Intracranial aneurysm surgery hemodynamics"),
    ("Neuro", "Spinal cord perfusion during aortic repair"),
    ("Neuro", "Neurophysiologic monitoring during spine surgery"),
    ("Neuro", "Anesthetic management of traumatic brain injury"),
    ("Regional", "Interscalene block and phrenic nerve paresis"),
    ("Regional", "Adductor canal versus femoral nerve block"),
    ("Regional", "Neuraxial opioid adverse effects"),
    ("Regional", "Epidural test-dose interpretation"),
    ("Regional", "Regional anesthesia with antithrombotic medication"),
    ("Equipment", "Vaporizer output at altitude"),
    ("Equipment", "Fresh gas flow effects on delivered tidal volume"),
    ("Equipment", "Anesthesia circle system and absorber exhaustion"),
    ("Equipment", "Oxygen supply failure safety mechanisms"),
    ("Equipment", "Anesthesia machine pipeline and cylinder pressures"),
    ("Transfusion", "Massive transfusion and citrate hypocalcemia"),
    ("Transfusion", "Transfusion-associated circulatory overload"),
    ("Transfusion", "Fibrinogen deficiency and viscoelastic testing"),
    ("Transfusion", "Coagulopathy management during liver transplantation"),
    ("Transfusion", "Acute hemolytic transfusion reaction"),
    ("Physiology", "Mixed venous oxygen saturation and oxygen delivery"),
    ("Physiology", "Oxyhemoglobin dissociation curve shifts"),
    ("Physiology", "Renal autoregulation and renal perfusion"),
    ("Physiology", "Acid-base compensation for respiratory disorders"),
    ("Physiology", "Hepatic blood flow and anesthetic clearance"),
    ("Perioperative", "Perioperative anaphylaxis treatment"),
    ("Perioperative", "Preventing postoperative nausea and vomiting"),
    ("Perioperative", "Hypothermia prevention and management"),
    ("Perioperative", "Operating room fire prevention and response"),
    ("Perioperative", "Hemodynamic assessment of perioperative hypotension"),
    ("Pain", "Opioid-induced hyperalgesia"),
    ("Pain", "Multimodal analgesia in renal impairment"),
    ("Pain", "Acute pain after chronic opioid exposure"),
    ("Pain", "Perioperative management of buprenorphine"),
    ("Pain", "Preventing persistent postsurgical pain"),
    ("Statistics", "Type I and Type II errors and study power"),
    ("Statistics", "Interpreting likelihood ratios"),
    ("Statistics", "Confounding and selection bias in studies"),
    ("Statistics", "Noninferiority trial interpretation"),
    ("Statistics", "Absolute versus relative risk reduction"),
    ("Cardiothoracic", "Cardiopulmonary bypass heparin and ACT"),
    ("Cardiothoracic", "Weaning from bypass with ventricular dysfunction"),
    ("Cardiothoracic", "Aortic cross clamp and unclamp physiology"),
    ("Cardiothoracic", "Protamine-associated cardiovascular collapse"),
    ("Cardiothoracic", "One lung ventilation rescue of hypoxemia"),
]


def normalized(value):
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def same_concept(a, b):
    a, b = normalized(a), normalized(b)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 16 and len(b) >= 16 and (a in b or b in a):
        return True
    at, bt = set(a.split()), set(b.split())
    common = at & bt
    if len(common) >= 3 and len(common) / min(len(at), len(bt)) >= .72:
        return True
    return SequenceMatcher(None, a, b).ratio() >= .83


def make_question_plan(context):
    today = date.fromisoformat(context["date"])
    history = list(context.get("prior_objectives", []))
    history += list(context.get("historical_question_log", []))
    recent = []
    for row in history:
        try:
            age = (today - date.fromisoformat(row["date"])).days
        except (ValueError, TypeError, KeyError):
            continue
        if 0 <= age < 14 and row.get("topic"):
            recent.append(row["topic"])
    candidates = [
        (domain, topic) for domain, topic in BLUEPRINT
        if not any(same_concept(topic, old) for old in recent)
    ]
    if not candidates:
        raise ValueError("No fresh ITE concepts remain after the 14-day cooldown")
    domains = list(dict.fromkeys(domain for domain, _ in BLUEPRINT))
    today_count = sum(1 for item in context.get("prior_objectives", [])
                      if item.get("date") == context["date"]) // 3
    rotation = (today.toordinal() + today_count * 3) % len(domains)
    rotated_domains = domains[rotation:] + domains[:rotation]
    selected = []
    # Fairly rotate high-yield domains while prioritizing long-unseen topics.
    for domain in rotated_domains:
        eligible = [t for d, t in candidates if d == domain]
        if not eligible:
            continue
        seen = lambda topic: sum(same_concept(topic, row.get("topic")) for row in history)
        eligible.sort(key=lambda t: (seen(t), (today.toordinal() + len(t)) % 71, t))
        selected.append({"domain": domain, "topic": eligible[0], "mode": "new_application"})
        if len(selected) == 3:
            break
    if len(selected) != 3:
        raise ValueError("Insufficient distinct anesthesia domains after cooldown")
    return selected


def stem_is_repeated(stem, previous_stems):
    """Catch lightly reworded or re-numbered stems, beyond exact topic matching."""
    def without_numbers(text):
        return re.sub(r"\b\d+(?:\.\d+)?\b", "#", normalized(text))
    stem = without_numbers(stem)
    return any(
        SequenceMatcher(None, stem, without_numbers(past)).ratio() >= .76
        for past in previous_stems if past
    )
