#!/usr/bin/env python3
"""Complete, reproducible solution for challenge 1.

The classifier is a real supervised logistic-regression model trained from the
two labelled ciphertext files.  It deliberately uses shift-invariant
statistical features instead of memorising the two encryption keys.
"""

from __future__ import annotations

import argparse
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile


ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
ENGLISH_FREQ = (
    8.17,
    1.50,
    2.78,
    4.25,
    12.70,
    2.23,
    2.02,
    6.09,
    6.97,
    0.15,
    0.77,
    4.03,
    2.41,
    6.75,
    7.51,
    1.93,
    0.10,
    5.99,
    6.33,
    9.06,
    2.76,
    0.98,
    2.36,
    0.15,
    1.97,
    0.07,
)

CAESAR_TARGET = (
    "ZNKYUBKXKOMTZEULZNKXKVAHROIULQUXKGYNGRRXKYOJKOTZNKVKUVRKGTJGRRYZGZKGAZNUXOZEY"
    "NGRRKSGTGZKLXUSZNKVKUVRK"
)
VIGENERE_TARGET = (
    "DSZGXFPMSRQYOMXPECSAOAPPUSNJTTYCZOBRLGZAODDRNSYOVNZPJDUOLIRJVWNHJDPVICRZMWCID"
    "COUVPHOWKEZTAYXOVNZPJDUO"
)
CLASSIFIER_SAMPLES = (
    "NKRRUZNOYOYGIRGYYOIGRIOVNKXGTGREYOYVXUHRKSLUXZNKIXEVZGTGREYOYIUSVKZOZOUTIUTMXGZARG"
    "ZOUTYUTMKZZOTMZNKIUXXKIZGTYCKX",
    "ROVVYDRSCSCKMVKCCSMKVMSZROBKXKVICSCZBYLVOWPYBDROMBIZDKXKVICSCMYWZODSDSYXMYXQBKD"
    "EVKDSYXCYXQODDSXQDROMYBBOMDKXCGOB",
    "DRKXUIYEPYBIYEBZKBDSMSZKDSYXGOGSCRIYEKVVDROLOCDSXIYEBPEDEBOOXNOKFYBC",
    "ZNGTQEUALUXEUAXVGXZOIOVGZOUTCKCOYNEUAGRRZNKHKYZOTEUAXLAZAXKKTJKGBUXY",
)

EXPECTED_TARGET_PLAINTEXT = (
    "THESOVEREIGNTYOFTHEREPUBLICOFKOREASHALLRESIDEINTHEPEOPLEANDALLSTATEAUTHORITY"
    "SHALLEMANATEFROMTHEPEOPLE"
)
EXPECTED_SAMPLE_PLAINTEXTS = (
    "HELLOTHISISACLASSICALCIPHERANALYSISPROBLEMFORTHECRYPTANALYSISCOMPETITION"
    "CONGRATULATIONSONGETTINGTHECORRECTANSWER",
    "HELLOTHISISACLASSICALCIPHERANALYSISPROBLEMFORTHECRYPTANALYSISCOMPETITION"
    "CONGRATULATIONSONGETTINGTHECORRECTANSWER",
    "THANKYOUFORYOURPARTICIPATIONWEWISHYOUALLTHEBESTINYOURFUTUREENDEAVORS",
    "THANKYOUFORYOURPARTICIPATIONWEWISHYOUALLTHEBESTINYOURFUTUREENDEAVORS",
)

FEATURE_NAMES = (
    "IC",
    "entropy",
    "best_caesar_chi2_per_char",
    "maximum_symbol_frequency",
    *(f"coincidence_lag_{lag}" for lag in range(1, 11)),
    *(f"mean_column_IC_period_{period}" for period in range(2, 6)),
)


def clean(text: str) -> str:
    return "".join(ch for ch in text.upper() if ch in ALPHABET)


def index_of_coincidence(text: str) -> float:
    counts = Counter(text)
    n = len(text)
    if n < 2:
        return 0.0
    return sum(value * (value - 1) for value in counts.values()) / (n * (n - 1))


def caesar_decrypt(text: str, shift: int) -> str:
    return "".join(ALPHABET[(ord(ch) - ord("A") - shift) % 26] for ch in text)


def chi_squared(text: str) -> float:
    counts = Counter(text)
    n = len(text)
    if n == 0:
        return math.inf
    return sum(
        (counts.get(ALPHABET[i], 0) - n * ENGLISH_FREQ[i] / 100.0) ** 2
        / (n * ENGLISH_FREQ[i] / 100.0)
        for i in range(26)
    )


@dataclass(frozen=True)
class CaesarCandidate:
    shift: int
    plaintext: str
    chi2: float
    counts: tuple[int, ...]


def caesar_candidates(text: str) -> list[CaesarCandidate]:
    candidates = []
    for shift in range(26):
        plaintext = caesar_decrypt(text, shift)
        counter = Counter(plaintext)
        candidates.append(
            CaesarCandidate(
                shift,
                plaintext,
                chi_squared(plaintext),
                tuple(counter.get(letter, 0) for letter in ALPHABET),
            )
        )
    return candidates


def best_caesar(text: str) -> CaesarCandidate:
    return min(caesar_candidates(text), key=lambda item: (item.chi2, item.shift))


def vigenere_decrypt(text: str, key: str) -> str:
    shifts = [ord(ch) - ord("A") for ch in key]
    return "".join(
        ALPHABET[(ord(ch) - ord("A") - shifts[i % len(shifts)]) % 26]
        for i, ch in enumerate(text)
    )


def vigenere_decrypt_lines(lines: list[str], key: str) -> list[str]:
    return [vigenere_decrypt(line, key) for line in lines]


def repeated_ngram_distances(lines: list[str], size: int) -> list[int]:
    """Collect adjacent repeat distances without crossing line-reset boundaries."""

    distances: list[int] = []
    for line in lines:
        positions: dict[str, list[int]] = defaultdict(list)
        for offset in range(len(line) - size + 1):
            positions[line[offset : offset + size]].append(offset)
        for offsets in positions.values():
            distances.extend(right - left for left, right in zip(offsets, offsets[1:]))
    return distances


def kasiski_period_scores(lines: list[str], size: int = 5) -> tuple[list[int], dict[int, int]]:
    distances = repeated_ngram_distances(lines, size)
    scores = {period: sum(distance % period == 0 for distance in distances) for period in range(2, 6)}
    return distances, scores


def recover_vigenere_key(lines: list[str], period: int) -> tuple[str, list[CaesarCandidate]]:
    columns = ["".join(line[position::period] for line in lines) for position in range(period)]
    winners = [best_caesar(column) for column in columns]
    return "".join(ALPHABET[item.shift] for item in winners), winners


def best_caesar_chi2_per_character(text: str) -> float:
    """Compute the best Caesar score without constructing 26 plaintext strings."""

    counts = [text.count(letter) for letter in ALPHABET]
    n = len(text)
    return min(
        sum(
            (counts[(plain_index + shift) % 26] - n * ENGLISH_FREQ[plain_index] / 100.0) ** 2
            / (n * ENGLISH_FREQ[plain_index] / 100.0)
            for plain_index in range(26)
        )
        / n
        for shift in range(26)
    )


def classifier_features(text: str) -> tuple[float, ...]:
    """Return 18 global-shift-invariant statistical features."""

    text = clean(text)
    n = len(text)
    if n < 2:
        raise ValueError("classifier input must contain at least two letters")
    counts = Counter(text)
    probabilities = [value / n for value in counts.values()]
    features = [
        index_of_coincidence(text),
        -sum(probability * math.log(probability) for probability in probabilities),
        best_caesar_chi2_per_character(text),
        max(counts.values()) / n,
    ]
    features.extend(
        sum(text[i] == text[i + lag] for i in range(n - lag)) / (n - lag)
        if n > lag
        else 0.0
        for lag in range(1, 11)
    )
    for period in range(2, 6):
        columns = [text[position::period] for position in range(period)]
        features.append(sum(len(column) * index_of_coincidence(column) for column in columns) / n)
    return tuple(features)


@dataclass(frozen=True)
class LogisticRegression:
    means: tuple[float, ...]
    scales: tuple[float, ...]
    weights: tuple[float, ...]

    def probability_vigenere(self, features: tuple[float, ...]) -> float:
        standardized = [
            (value - mean) / scale
            for value, mean, scale in zip(features, self.means, self.scales)
        ]
        score = self.weights[0] + sum(
            weight * value for weight, value in zip(self.weights[1:], standardized)
        )
        score = max(-30.0, min(30.0, score))
        return 1.0 / (1.0 + math.exp(-score))

    def predict(self, features: tuple[float, ...]) -> int:
        return int(self.probability_vigenere(features) >= 0.5)


def fit_logistic_regression(
    examples: list[tuple[tuple[float, ...], int]],
    *,
    epochs: int = 1_500,
    learning_rate: float = 0.1,
    l2: float = 0.01,
) -> LogisticRegression:
    dimension = len(examples[0][0])
    means = tuple(sum(features[j] for features, _ in examples) / len(examples) for j in range(dimension))
    scales = tuple(
        math.sqrt(sum((features[j] - means[j]) ** 2 for features, _ in examples) / len(examples))
        or 1.0
        for j in range(dimension)
    )
    standardized = [
        (tuple((value - mean) / scale for value, mean, scale in zip(features, means, scales)), label)
        for features, label in examples
    ]
    weights = [0.0] * (dimension + 1)
    for _ in range(epochs):
        gradient = [0.0] * len(weights)
        for features, label in standardized:
            score = weights[0] + sum(weight * value for weight, value in zip(weights[1:], features))
            score = max(-30.0, min(30.0, score))
            error = 1.0 / (1.0 + math.exp(-score)) - label
            gradient[0] += error
            for j, value in enumerate(features, 1):
                gradient[j] += error * value
        for j in range(len(weights)):
            regularization = l2 * weights[j] if j else 0.0
            weights[j] -= learning_rate * (gradient[j] / len(standardized) + regularization)
    return LogisticRegression(means, scales, tuple(weights))


@dataclass(frozen=True)
class ClassifierEvaluation:
    model: LogisticRegression
    train_count: int
    test_count: int
    confusion: tuple[tuple[int, int], tuple[int, int]]

    @property
    def correct(self) -> int:
        return self.confusion[0][0] + self.confusion[1][1]


def train_and_evaluate_classifier(
    caesar_lines: list[str], vigenere_lines: list[str]
) -> ClassifierEvaluation:
    """Use a paired line-index split so plaintext never leaks across the split."""

    if len(caesar_lines) != len(vigenere_lines):
        raise ValueError("the two labelled files must have matching line counts")
    train: list[tuple[tuple[float, ...], int]] = []
    test: list[tuple[tuple[float, ...], int]] = []
    for line_index, (caesar_line, vigenere_line) in enumerate(zip(caesar_lines, vigenere_lines)):
        if len(caesar_line) < 50 or len(vigenere_line) < 50:
            continue
        destination = test if line_index % 5 == 0 else train
        destination.append((classifier_features(caesar_line), 0))
        destination.append((classifier_features(vigenere_line), 1))
    model = fit_logistic_regression(train)
    confusion = [[0, 0], [0, 0]]
    for features, actual in test:
        confusion[actual][model.predict(features)] += 1
    return ClassifierEvaluation(
        model,
        len(train),
        len(test),
        (tuple(confusion[0]), tuple(confusion[1])),
    )


def uniform_shift(left: str, right: str) -> int | None:
    if len(left) != len(right) or not left:
        return None
    shifts = {(ord(b) - ord(a)) % 26 for a, b in zip(left, right)}
    return shifts.pop() if len(shifts) == 1 else None


def print_caesar_table(candidates: list[CaesarCandidate], full: bool) -> None:
    print("\nCaesar exhaustive search (all 26 keys):")
    if full:
        print("key  chi2       counts(A..Z)                                                    plaintext-prefix")
        for item in candidates:
            counts = ",".join(str(value) for value in item.counts)
            print(f"{item.shift:2d}  {item.chi2:10.3f}  {counts:<66}  {item.plaintext[:60]}")
    else:
        print("key  chi2")
        for item in candidates:
            print(f"{item.shift:2d}  {item.chi2:10.3f}")


def dump_caesar_candidates(directory: Path, candidates: list[CaesarCandidate]) -> None:
    """Materialize all full decryptions when a judge wants the 3-a artifacts."""

    directory.mkdir(parents=True, exist_ok=True)
    table = ["key\tchi2\t" + "\t".join(ALPHABET)]
    for item in candidates:
        (directory / f"key_{item.shift:02d}.txt").write_text(item.plaintext + "\n", encoding="ascii")
        table.append(
            f"{item.shift}\t{item.chi2:.6f}\t" + "\t".join(str(value) for value in item.counts)
        )
    (directory / "frequency_table.tsv").write_text("\n".join(table) + "\n", encoding="ascii")


def load_ciphertexts() -> tuple[list[str], list[str]]:
    root = Path(__file__).resolve().parents[1]
    with ZipFile(root / "problems" / "1_암호분석.zip") as archive:
        caesar_raw = archive.read("ciphertexts1.txt").decode()
        vigenere_raw = archive.read("ciphertexts2.txt").decode()
    caesar_lines = [clean(line) for line in caesar_raw.splitlines() if clean(line)]
    vigenere_lines = [clean(line) for line in vigenere_raw.splitlines() if clean(line)]
    return caesar_lines, vigenere_lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--full-caesar-table",
        action="store_true",
        help="include A..Z counts and plaintext prefixes for every Caesar key",
    )
    parser.add_argument(
        "--dump-caesar-dir",
        type=Path,
        help="write all 26 full Caesar decryptions and a TSV frequency table to this directory",
    )
    args = parser.parse_args()

    caesar_lines, vigenere_lines = load_ciphertexts()
    ciphertext1 = "".join(caesar_lines)
    ciphertext2 = "".join(vigenere_lines)
    print(f"ciphertexts1 length={len(ciphertext1)} IC={index_of_coincidence(ciphertext1):.6f}")
    print(f"ciphertexts2 length={len(ciphertext2)} IC={index_of_coincidence(ciphertext2):.6f}")

    candidates = caesar_candidates(ciphertext1)
    print_caesar_table(candidates, args.full_caesar_table)
    if args.dump_caesar_dir is not None:
        dump_caesar_candidates(args.dump_caesar_dir, candidates)
        print(f"full Caesar candidate artifacts written to {args.dump_caesar_dir}")
    caesar_winner = min(candidates, key=lambda item: (item.chi2, item.shift))
    print(f"best Caesar key={caesar_winner.shift}, plaintext-prefix={caesar_winner.plaintext[:100]}")

    distances, period_scores = kasiski_period_scores(vigenere_lines)
    period = max(period_scores, key=lambda value: (period_scores[value] / len(distances), value))
    print("\nKasiski repeated-5-gram distances (within reset lines):")
    print(f"distance-count={len(distances)}")
    for candidate_period, divisible in period_scores.items():
        print(f"period={candidate_period}: divisible={divisible}/{len(distances)} ({divisible / len(distances):.3%})")
    key, column_winners = recover_vigenere_key(vigenere_lines, period)
    print(f"estimated period={period}, Vigenere key={key}")
    for position, item in enumerate(column_winners):
        print(f"column={position}: shift={item.shift:2d} key={ALPHABET[item.shift]} chi2={item.chi2:.3f}")
    vigenere_plaintext = "".join(vigenere_decrypt_lines(vigenere_lines, key))
    print(f"full plaintext agreement with Caesar result={vigenere_plaintext == caesar_winner.plaintext}")

    caesar_target_plaintext = caesar_decrypt(CAESAR_TARGET, caesar_winner.shift)
    vigenere_target_plaintext = vigenere_decrypt(VIGENERE_TARGET, key)
    print(f"\n3-c Caesar target plaintext={caesar_target_plaintext}")
    print(f"4-c Vigenere target plaintext={vigenere_target_plaintext}")

    evaluation = train_and_evaluate_classifier(caesar_lines, vigenere_lines)
    print("\nLearned classifier: standardized L2 logistic regression")
    print(f"features={len(FEATURE_NAMES)} train={evaluation.train_count} held-out={evaluation.test_count}")
    print(f"confusion(actual rows C,V; predicted columns C,V)={evaluation.confusion}")
    print(f"held-out accuracy={evaluation.correct}/{evaluation.test_count} ({evaluation.correct / evaluation.test_count:.3%})")
    predictions = []
    for number, sample in enumerate(CLASSIFIER_SAMPLES, 1):
        features = classifier_features(sample)
        probability = evaluation.model.probability_vigenere(features)
        prediction = "Vigenere" if probability >= 0.5 else "Caesar-like"
        sample_winner = best_caesar(sample)
        predictions.append(prediction)
        print(
            f"sample={number}: prediction={prediction}, P(Vigenere)={probability:.6f}, "
            f"best_shift={sample_winner.shift}, plaintext={sample_winner.plaintext}"
        )

    shift_12 = uniform_shift(CLASSIFIER_SAMPLES[0], CLASSIFIER_SAMPLES[1])
    shift_34 = uniform_shift(CLASSIFIER_SAMPLES[2], CLASSIFIER_SAMPLES[3])
    print("\nIdentifiability audit:")
    print(f"sample 1 -> 2 is one global Caesar shift: delta={shift_12}")
    print(f"sample 3 -> 4 is one global Caesar shift: delta={shift_34}")
    print(
        "A Vigenere cipher with a one-letter key is exactly a Caesar cipher; hidden constructor labels "
        "for these pairs cannot be inferred from ciphertext alone."
    )

    assert len(ciphertext1) == len(ciphertext2) == 19_897
    assert round(index_of_coincidence(ciphertext1), 6) == 0.067638
    assert round(index_of_coincidence(ciphertext2), 6) == 0.043972
    assert caesar_winner.shift == 6
    assert period == 5 and key == "KLVOJ"
    assert vigenere_plaintext == caesar_winner.plaintext
    assert caesar_target_plaintext == vigenere_target_plaintext == EXPECTED_TARGET_PLAINTEXT
    assert evaluation.correct == evaluation.test_count
    assert [best_caesar(sample).plaintext for sample in CLASSIFIER_SAMPLES] == list(EXPECTED_SAMPLE_PLAINTEXTS)
    assert predictions == ["Caesar-like"] * 4
    assert shift_12 == 4 and shift_34 == 22
    print("self-checks: PASS")


if __name__ == "__main__":
    main()
