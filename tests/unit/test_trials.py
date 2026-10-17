import pytest

from app.game.trials import (
    TrialPlanEntry,
    generate_trial_plan,
    seed_from_hex,
    seed_to_hex,
    turn_seed,
)


def _params(practice=1, formal=6):
    total = practice + formal
    result = []
    for position in range(total):
        is_practice = position < practice
        result.append(
            {
                "sourceIndex": position,
                "isPractice": is_practice,
                "formalTrial": 0 if is_practice else position - practice + 1,
                "baseSoldiersA": 7 + position,
                "baseSoldiersB": 8 + position,
                "reinforcementOverrides": None,
            }
        )
    return result


def test_generate_trial_plan_keeps_practice_first_and_randomizes_formal():
    params = _params(practice=1, formal=6)
    plan = generate_trial_plan(params, practice_trials=1, formal_trials=6, randomize_formal=True, seed=1234)

    assert len(plan) == 7
    assert [entry.trial_index for entry in plan] == list(range(7))
    assert plan[0].is_practice is True
    assert plan[0].source_index == 0
    assert plan[0].formal_trial == 0
    assert plan[0].params["baseSoldiersA"] == 7
    assert plan[0].params["baseSoldiersB"] == 8
    assert plan[0].params["reinforcementOverrides"] is None

    formal_entries = plan[1:]
    assert all(entry.is_practice is False for entry in formal_entries)
    assert sorted(entry.source_index for entry in formal_entries) == list(range(1, 7))
    assert [entry.formal_trial for entry in formal_entries] == [1, 2, 3, 4, 5, 6]
    for entry in plan:
        assert entry.params["baseSoldiersA"] == 7 + entry.source_index
        assert entry.params["baseSoldiersB"] == 8 + entry.source_index


def test_generate_trial_plan_with_multiple_practice_trials():
    params = _params(practice=3, formal=4)
    plan = generate_trial_plan(params, practice_trials=3, formal_trials=4, randomize_formal=False, seed=5)

    assert [entry.source_index for entry in plan[:3]] == [0, 1, 2]
    assert [entry.source_index for entry in plan[3:]] == [3, 4, 5, 6]
    assert [entry.formal_trial for entry in plan] == [0, 0, 0, 1, 2, 3, 4]
    assert [entry.is_practice for entry in plan] == [True, True, True, False, False, False, False]


def test_generate_trial_plan_is_reproducible_and_seed_dependent():
    params = _params(practice=1, formal=6)
    first = generate_trial_plan(params, 1, 6, True, 987654321)
    second = generate_trial_plan(params, 1, 6, True, 987654321)
    assert first == second

    different = generate_trial_plan(params, 1, 6, True, 1357911)
    assert first != different
    assert [entry.source_index for entry in first[1:]] != list(range(1, 7))


def test_generate_trial_plan_without_randomization_keeps_order():
    params = _params(practice=1, formal=6)
    plan = generate_trial_plan(params, 1, 6, False, 0)
    assert [entry.source_index for entry in plan] == list(range(7))
    assert isinstance(plan[0], TrialPlanEntry)


@pytest.mark.parametrize(
    "practice,formal",
    [(-1, 6), (1, 0)],
)
def test_generate_trial_plan_rejects_invalid_trial_counts(practice, formal):
    params = _params(max(practice, 0), formal)
    with pytest.raises(ValueError):
        generate_trial_plan(params, practice, formal, True, 1)


def test_generate_trial_plan_rejects_wrong_length():
    params = _params(practice=1, formal=6)
    with pytest.raises(ValueError):
        generate_trial_plan(params[:-1], 1, 6, True, 1)
    with pytest.raises(ValueError):
        generate_trial_plan(params + [_params(0, 1)[0]], 1, 6, True, 1)


def test_generate_trial_plan_rejects_inconsistent_markers():
    params = _params(practice=1, formal=6)
    params[0]["isPractice"] = False
    with pytest.raises(ValueError):
        generate_trial_plan(params, 1, 6, True, 1)

    params = _params(practice=1, formal=6)
    params[1]["isPractice"] = True
    with pytest.raises(ValueError):
        generate_trial_plan(params, 1, 6, True, 1)

    params = _params(practice=1, formal=6)
    params[-1]["formalTrial"] = 99
    with pytest.raises(ValueError):
        generate_trial_plan(params, 1, 6, True, 1)

    params = _params(practice=1, formal=6)
    params[2]["sourceIndex"] = 5
    with pytest.raises(ValueError):
        generate_trial_plan(params, 1, 6, True, 1)


def test_generate_trial_plan_rejects_invalid_values():
    params = _params(practice=1, formal=6)
    params[2]["baseSoldiersA"] = 0
    with pytest.raises(ValueError):
        generate_trial_plan(params, 1, 6, True, 1)

    params = _params(practice=1, formal=6)
    params[2]["baseSoldiersB"] = -3
    with pytest.raises(ValueError):
        generate_trial_plan(params, 1, 6, True, 1)

    params = _params(practice=1, formal=6)
    params[2]["reinforcementOverrides"] = [1, 2]
    with pytest.raises(ValueError):
        generate_trial_plan(params, 1, 6, True, 1)

    with pytest.raises(ValueError):
        generate_trial_plan(_params(1, 6), 1, 6, "yes", 1)
    with pytest.raises(ValueError):
        generate_trial_plan("not-a-list", 1, 6, True, 1)


def test_seed_hex_round_trip():
    for value in (0, 1, 0xDEADBEEF, 0xF3A91C0D5E7B2468, 2 ** 64 - 1):
        text = seed_to_hex(value)
        assert len(text) == 16
        assert seed_from_hex(text) == value
    assert seed_to_hex(0) == "0000000000000000"
    assert seed_to_hex(0xDEADBEEF) == "00000000deadbeef"
    assert seed_from_hex("F3A91C0D5E7B2468") == 0xF3A91C0D5E7B2468

    for value in ("", "xyz", "0" * 17, "-1", "0x1234", "1\n"):
        with pytest.raises(ValueError):
            seed_from_hex(value)
    with pytest.raises(ValueError):
        seed_from_hex(123)
    with pytest.raises(ValueError):
        seed_to_hex(-1)
    with pytest.raises(ValueError):
        seed_to_hex(2 ** 64)


def test_turn_seed_is_stable_and_depends_on_all_inputs():
    room_seed = 0xF3A91C0D5E7B2468
    first = turn_seed(room_seed, 2, 7, 0)
    assert isinstance(first, int)
    assert 0 <= first < 2 ** 64
    assert first == turn_seed(room_seed, 2, 7, 0)

    values = {
        turn_seed(room_seed, 2, 7, 0),
        turn_seed(room_seed + 1, 2, 7, 0),
        turn_seed(room_seed, 3, 7, 0),
        turn_seed(room_seed, 2, 8, 0),
        turn_seed(room_seed, 2, 7, 1),
    }
    assert len(values) == 5

    with pytest.raises(ValueError):
        turn_seed(room_seed, -1, 7, 0)
    with pytest.raises(ValueError):
        turn_seed(room_seed, 2, -1, 0)
    with pytest.raises(ValueError):
        turn_seed(room_seed, 2, 7, -1)
    with pytest.raises(ValueError):
        turn_seed(2 ** 64, 0, 0, 0)
