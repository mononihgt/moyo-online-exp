import copy
import hashlib
import random
import re
from dataclasses import dataclass
from numbers import Integral

_SEED_HEX_PATTERN = re.compile(r"[0-9a-fA-F]{1,16}")
_SEED_MAX = 2 ** 64 - 1


@dataclass(frozen=True)
class TrialPlanEntry:
    trial_index: int
    source_index: int
    is_practice: bool
    formal_trial: int
    params: dict


def generate_trial_plan(trial_params, practice_trials, formal_trials, randomize_formal, seed):
    practice_trials = _require_non_negative_int(practice_trials, "practice_trials")
    formal_trials = _require_non_negative_int(formal_trials, "formal_trials")
    if formal_trials < 1:
        raise ValueError("formal_trials 至少为 1")
    if not isinstance(randomize_formal, bool):
        raise ValueError("randomize_formal 必须是布尔值")
    seed = _require_non_negative_int(seed, "seed")

    if not isinstance(trial_params, (list, tuple)):
        raise ValueError("trial_params 必须是列表")
    params_list = list(trial_params)
    expected = practice_trials + formal_trials
    if len(params_list) != expected:
        raise ValueError(
            "trial_params 长度必须等于 practice_trials + formal_trials"
        )

    for position, item in enumerate(params_list):
        _validate_trial_params(item, position, practice_trials)

    source_indices = list(range(expected))
    formal_sources = source_indices[practice_trials:]
    if randomize_formal:
        random.Random(seed).shuffle(formal_sources)
    order = source_indices[:practice_trials] + formal_sources

    plan = []
    for trial_index, source_index in enumerate(order):
        item = params_list[source_index]
        is_practice = trial_index < practice_trials
        plan.append(
            TrialPlanEntry(
                trial_index=trial_index,
                source_index=source_index,
                is_practice=is_practice,
                formal_trial=0 if is_practice else trial_index - practice_trials + 1,
                params={
                    "baseSoldiersA": int(item["baseSoldiersA"]),
                    "baseSoldiersB": int(item["baseSoldiersB"]),
                    "reinforcementOverrides": copy.deepcopy(item["reinforcementOverrides"]),
                },
            )
        )
    return plan


def seed_from_hex(value):
    if not isinstance(value, str) or _SEED_HEX_PATTERN.fullmatch(value) is None:
        raise ValueError("seed 必须是 1 到 16 位十六进制字符串")
    return int(value, 16)


def seed_to_hex(value):
    value = _require_non_negative_int(value, "seed")
    if value > _SEED_MAX:
        raise ValueError("seed 必须小于 2 ** 64")
    return "%016x" % value


def turn_seed(room_seed, trial_index, round_number, recovery_count):
    room_seed = _require_seed(room_seed, "room_seed")
    trial_index = _require_non_negative_int(trial_index, "trial_index")
    round_number = _require_non_negative_int(round_number, "round_number")
    recovery_count = _require_non_negative_int(recovery_count, "recovery_count")
    payload = "%d:%d:%d:%d" % (room_seed, trial_index, round_number, recovery_count)
    digest = hashlib.sha256(payload.encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big")


def _validate_trial_params(item, position, practice_trials):
    if not isinstance(item, dict):
        raise ValueError("trial_params 的每一项必须是 dict")
    required = (
        "sourceIndex",
        "isPractice",
        "formalTrial",
        "baseSoldiersA",
        "baseSoldiersB",
        "reinforcementOverrides",
    )
    for field in required:
        if field not in item:
            raise ValueError("trial_params 第 %d 项缺少字段: %s" % (position, field))

    source_index = _require_non_negative_int(item["sourceIndex"], "sourceIndex")
    if source_index != position:
        raise ValueError("trial_params 第 %d 项的 sourceIndex 必须等于 %d" % (position, position))

    is_practice = item["isPractice"]
    if not isinstance(is_practice, bool):
        raise ValueError("trial_params 第 %d 项的 isPractice 必须是布尔值" % position)
    expected_practice = position < practice_trials
    if is_practice != expected_practice:
        raise ValueError("trial_params 第 %d 项的 isPractice 标记不一致" % position)

    formal_trial = _require_non_negative_int(item["formalTrial"], "formalTrial")
    expected_formal = 0 if is_practice else position - practice_trials + 1
    if formal_trial != expected_formal:
        raise ValueError("trial_params 第 %d 项的 formalTrial 标记不一致" % position)

    _require_positive_int(item["baseSoldiersA"], "baseSoldiersA")
    _require_positive_int(item["baseSoldiersB"], "baseSoldiersB")

    overrides = item["reinforcementOverrides"]
    if overrides is not None and not isinstance(overrides, dict):
        raise ValueError("trial_params 第 %d 项的 reinforcementOverrides 必须是 dict 或 None" % position)


def _require_int(value, name):
    if not isinstance(value, Integral) or isinstance(value, bool):
        raise ValueError("%s 必须是整数" % name)
    return int(value)


def _require_non_negative_int(value, name):
    number = _require_int(value, name)
    if number < 0:
        raise ValueError("%s 不能为负数" % name)
    return number


def _require_positive_int(value, name):
    number = _require_int(value, name)
    if number <= 0:
        raise ValueError("%s 必须大于零" % name)
    return number


def _require_seed(value, name):
    number = _require_non_negative_int(value, name)
    if number > _SEED_MAX:
        raise ValueError("%s 必须小于 2 ** 64" % name)
    return number
