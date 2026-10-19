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


def generate_trial_plan(profile_rows, practice_trials, formal_trials, randomize_formal, seed):
    practice_trials = _require_int(practice_trials, "practice_trials")
    if practice_trials != 1:
        raise ValueError("practice_trials 必须等于 1")
    if not isinstance(randomize_formal, bool):
        raise ValueError("randomize_formal 必须是布尔值")
    seed = _require_seed(seed, "seed")

    if not isinstance(profile_rows, (list, tuple)):
        raise ValueError("profile_rows 必须是列表")
    rows = list(profile_rows)
    if len(rows) < 2:
        raise ValueError("profile_rows 必须包含练习行和至少一行正式配置")
    formal_trials = _require_int(formal_trials, "formal_trials")
    if formal_trials != len(rows) - 1:
        raise ValueError("formal_trials 必须等于 profile_rows 长度减一")

    normalized = []
    for position, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("profile_rows 第 %d 项必须是 dict" % position)
        for field in ("soldiersA", "soldiersB"):
            if field not in row:
                raise ValueError("profile_rows 第 %d 项缺少字段: %s" % (position, field))
        normalized.append(
            {
                "soldiersA": _require_positive_int(
                    row["soldiersA"], "profile_rows 第 %d 项的 soldiersA" % position
                ),
                "soldiersB": _require_positive_int(
                    row["soldiersB"], "profile_rows 第 %d 项的 soldiersB" % position
                ),
            }
        )

    # 练习行固定在最前，正式行按房间种子随机排列，数值随原始行一起移动。
    formal_sources = list(range(1, len(normalized)))
    if randomize_formal:
        random.Random(seed).shuffle(formal_sources)
    order = [0] + formal_sources

    plan = []
    for trial_index, source_index in enumerate(order):
        is_practice = trial_index < practice_trials
        plan.append(
            TrialPlanEntry(
                trial_index=trial_index,
                source_index=source_index,
                is_practice=is_practice,
                formal_trial=0 if is_practice else trial_index - practice_trials + 1,
                params=dict(normalized[source_index]),
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
