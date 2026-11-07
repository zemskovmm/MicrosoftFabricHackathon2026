import re
from difflib import SequenceMatcher

from .models import Master, Policy


def normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower().replace("millimeter", "mm")))


def identifier(value: str) -> str:
    return "".join(re.findall(r"[a-z0-9]+", value.lower()))


def match(
    source_sku: str,
    description: str,
    masters: list[Master],
    policy: Policy,
    manufacturer: str = "",
    manufacturer_part_number: str = "",
) -> dict:
    if manufacturer_part_number:
        candidates = [
            m
            for m in masters
            if identifier(m.manufacturer_part_number) == identifier(manufacturer_part_number)
            and (not manufacturer or identifier(m.manufacturer) == identifier(manufacturer))
        ]
        if len(candidates) == 1:
            return dict(
                canonical_sku=candidates[0].canonical_sku, confidence=1.0, method="manufacturer_and_mpn"
            )
        return dict(canonical_sku=None, confidence=0.0, method="unknown_or_ambiguous_mpn")
    if manufacturer:
        masters = [m for m in masters if identifier(m.manufacturer) == identifier(manufacturer)]
    exact = [m for m in masters if identifier(m.canonical_sku) == identifier(source_sku)]
    if len(exact) == 1:
        return dict(canonical_sku=exact[0].canonical_sku, confidence=1.0, method="identifier")
    if len(exact) > 1:
        return dict(canonical_sku=None, confidence=0.0, method="ambiguous_identifier")
    ranked = sorted(
        [
            (SequenceMatcher(None, normalize(description), normalize(m.description)).ratio(), m.canonical_sku)
            for m in masters
            if re.findall(r"\d+", description) == re.findall(r"\d+", m.description)
        ],
        reverse=True,
    )
    if not ranked:
        return dict(canonical_sku=None, confidence=0.0, method="no_master")
    best, sku = ranked[0]
    margin = best - ranked[1][0] if len(ranked) > 1 else 1.0
    accepted = best >= policy.match_threshold and margin >= policy.ambiguity_margin
    return dict(
        canonical_sku=sku if accepted else None,
        confidence=round(best, 4),
        method="description_similarity" if accepted else "review_required",
    )


def scorecard(labels: list[dict], masters: list[Master], policy: Policy) -> dict:
    tp = fp = fn = tn = 0
    examples = []
    for label in labels:
        result = match(
            label["source_sku"],
            label["description"],
            masters,
            policy,
            label.get("manufacturer", ""),
            label.get("manufacturer_part_number", ""),
        )
        predicted, expected = result["canonical_sku"], label["canonical_sku"]
        tp += int(predicted is not None and predicted == expected)
        fp += int(predicted is not None and predicted != expected)
        fn += int(expected is not None and predicted != expected)
        tn += int(predicted is None and expected is None)
        examples.append({**label, "predicted": predicted, "correct": predicted == expected})
    return dict(
        true_positive=tp,
        false_positive=fp,
        false_negative=fn,
        true_negative=tn,
        precision=tp / (tp + fp) if tp + fp else None,
        recall=tp / (tp + fn) if tp + fn else None,
        sample_size=len(labels),
        examples=examples,
        limitation="Synthetic labelled sample; not evidence of production accuracy.",
    )
