import pytest

from app.game.trials import (
    TrialPlanEntry,
    generate_trial_plan,
    seed_from_hex,
    seed_to_hex,
    turn_seed,
)


def _rows(formal=6):
    return [
        {"soldiersA": 7 + position, "soldiersB": 8 + position}
        for position in range(1 + formal)
    ]


def test_generate_trial_plan_keeps_practice_first_and_randomizes_formal():
    rows = _rows(formal=6)
    plan = generate_trial_plan(rows, 1, 6, True, 1234)

    assert len(plan) == 7
    assert [entry.trial_index for entry in plan] == list(range(7))
    assert plan[0].is_practice is True
    assert plan[0].source_index == 0
    assert plan[0].formal_trial == 0
    assert plan[0].params == {"soldiersA": 7, "soldiersB": 8}

    formal_entries = plan[1:]
    assert all(entry.is_practice is False for entry in formal_entries)
    assert sorted(entry.source_index for entry in formal_entries) == list(range(1, 7))
    assert [entry.formal_trial for entry in formal_entries] == [1, 2, 3, 4, 5, 6]
    assert [entry.source_index for entry in formal_entries] != list(range(1, 7))


def test_generate_trial_plan_moves_values_with_source_index():
    rows = [
        {"soldiersA": 7, "soldiersB": 7},
        {"soldiersA": 8, "soldiersB": 8},
        {"soldiersA": 8, "soldiersB": 9},
        {"soldiersA": 9, "soldiersB": 7},
        {"soldiersA": 7, "soldiersB": 9},
    ]
    plan = generate_trial_plan(rows, 1, 4, True, 97531)

    assert plan[0].source_index == 0
    for entry in plan:
        assert entry.trial_index == plan.index(entry)
        assert entry.params == rows[entry.source_index]
        if entry.is_practice:
            assert entry.source_index == 0
        else:
            assert entry.formal_trial == entry.trial_index
            assert entry.source_index in (1, 2, 3, 4)


def test_generate_trial_plan_formal_numbering_follows_execution_order():
    rows = _rows(formal=6)
    plan = generate_trial_plan(rows, 1, 6, True, 2468)
    formal_entries = [entry for entry in plan if not entry.is_practice]

    assert [entry.formal_trial for entry in formal_entries] == list(range(1, 7))
    for position, entry in enumerate(formal_entries, start=1):
        assert entry.trial_index == position
        assert entry.formal_trial == position


def test_generate_trial_plan_is_reproducible_and_seed_dependent():
    rows = _rows(formal=6)
    first = generate_trial_plan(rows, 1, 6, True, 987654321)
    second = generate_trial_plan(rows, 1, 6, True, 987654321)
    assert first == second

    different = generate_trial_plan(rows, 1, 6, True, 1357911)
    assert first != different
    assert [entry.source_index for entry in first[1:]] != [entry.source_index for entry in different[1:]]


def test_generate_trial_plan_without_randomization_keeps_order():
    rows = _rows(formal=6)
    plan = generate_trial_plan(rows, 1, 6, False, 0)
    assert [entry.source_index for entry in plan] == list(range(7))
    assert [entry.formal_trial for entry in plan] == [0, 1, 2, 3, 4, 5, 6]
    assert isinstance(plan[0], TrialPlanEntry)


def test_generate_trial_plan_does_not_mutate_profile_rows():
    rows = _rows(formal=6)
    snapshot = [dict(row) for row in rows]
    generate_trial_plan(rows, 1, 6, True, 1234)
    assert rows == snapshot


@pytest.mark.parametrize("practice", [0, 2, -1, True])
def test_generate_trial_plan_rejects_practice_count_other_than_one(practice):
    with pytest.raises(ValueError):
        generate_trial_plan(_rows(formal=6), practice, 6, True, 1)


@pytest.mark.parametrize("formal", [0, 5, 7, -1, True])
def test_generate_trial_plan_rejects_wrong_formal_trial_count(formal):
    with pytest.raises(ValueError):
        generate_trial_plan(_rows(formal=6), 1, formal, True, 1)


def test_generate_trial_plan_rejects_wrong_row_count():
    with pytest.raises(ValueError):
        generate_trial_plan(_rows(formal=6)[:-1], 1, 6, True, 1)
    with pytest.raises(ValueError):
        generate_trial_plan(_rows(formal=6) + [{"soldiersA": 5, "soldiersB": 5}], 1, 6, True, 1)
    with pytest.raises(ValueError):
        generate_trial_plan([{"soldiersA": 7, "soldiersB": 7}], 1, 0, True, 1)


def test_generate_trial_plan_rejects_invalid_rows():
    with pytest.raises(ValueError):
        generate_trial_plan("not-a-list", 1, 1, True, 1)

    for invalid in (
        [{"soldiersA": 7, "soldiersB": 7}, "row"],
        [{"soldiersA": 7, "soldiersB": 7}, {"soldiersB": 8}],
        [{"soldiersA": 7, "soldiersB": 7}, {"soldiersA": 8}],
        [{"soldiersA": 7, "soldiersB": 7}, {"soldiersA": 0, "soldiersB": 8}],
        [{"soldiersA": 7, "soldiersB": 7}, {"soldiersA": 8, "soldiersB": 0}],
        [{"soldiersA": 7, "soldiersB": 7}, {"soldiersA": -3, "soldiersB": 8}],
        [{"soldiersA": 7, "soldiersB": 7}, {"soldiersA": 8.5, "soldiersB": 8}],
        [{"soldiersA": 7, "soldiersB": 7}, {"soldiersA": True, "soldiersB": 8}],
    ):
        with pytest.raises(ValueError):
            generate_trial_plan(invalid, 1, 1, True, 1)


def test_generate_trial_plan_rejects_invalid_switches_and_seed():
    with pytest.raises(ValueError):
        generate_trial_plan(_rows(formal=6), 1, 6, "yes", 1)
    with pytest.raises(ValueError):
        generate_trial_plan(_rows(formal=6), 1, 6, 1, 1)

    for seed in (-1, 1.5, True, 2 ** 64):
        with pytest.raises(ValueError):
            generate_trial_plan(_rows(formal=6), 1, 6, True, seed)


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
