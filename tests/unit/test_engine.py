import pytest

from app.game import engine
from app.game.engine import (
    Board,
    initial_board,
    player_without_territory,
    resolve_forced_turn,
    resolve_turn,
    total_soldiers,
    valid_selection,
)

import reference_legacy


def _cells(rows, cols, owner_fn, soldier_fn, reinforcement_a=0, reinforcement_b=0):
    result = []
    for row in range(rows):
        for col in range(cols):
            result.append(
                {
                    "row": row,
                    "col": col,
                    "initialOwner": owner_fn(row, col),
                    "initialSoldiers": soldier_fn(row, col),
                    "reinforcementA": reinforcement_a(row, col)
                    if callable(reinforcement_a)
                    else reinforcement_a,
                    "reinforcementB": reinforcement_b(row, col)
                    if callable(reinforcement_b)
                    else reinforcement_b,
                }
            )
    return result


@pytest.mark.parametrize("rows,cols", [(5, 7), (7, 5), (3, 4)])
def test_initial_board_uses_row_major_indices_and_forces_bases(rows, cols):
    total = rows * cols
    base_a = 0
    base_b = total - 1

    def owner(row, col):
        return 1 if col < cols // 2 else 2

    def soldiers(row, col):
        return (row * cols + col) % 7

    cells = _cells(rows, cols, owner, soldiers)
    cells[base_a]["initialOwner"] = 2
    cells[base_a]["initialSoldiers"] = 0
    cells[base_b]["initialOwner"] = 1
    cells[base_b]["initialSoldiers"] = 0
    cells.reverse()

    board = initial_board(cells, base_a, base_b, 11, 13)

    assert board.rows == rows
    assert board.cols == cols
    assert len(board.owners) == total
    assert len(board.soldiers) == total
    for index in range(total):
        row, col = divmod(index, cols)
        if index == base_a:
            assert board.owners[index] == 1
            assert board.soldiers[index] == 11
        elif index == base_b:
            assert board.owners[index] == 2
            assert board.soldiers[index] == 13
        else:
            assert board.owners[index] == owner(row, col)
            assert board.soldiers[index] == soldiers(row, col)


@pytest.mark.parametrize("base_a,base_b", [(-1, 11), (0, 12), (12, 11), (5, 5)])
def test_initial_board_rejects_invalid_base_indices(base_a, base_b):
    cells = _cells(3, 4, lambda row, col: 0, lambda row, col: 0)
    with pytest.raises(ValueError):
        initial_board(cells, base_a, base_b, 5, 5)


def test_valid_selection_normalizes_indices():
    assert valid_selection([6, 0, 6, 3], 5, 7) == [0, 3, 6]
    assert valid_selection([(2, 3), (0, 0), (2, 3)], 5, 7) == [0, 17]
    assert valid_selection([(0, 6), 6], 5, 7) == [6]
    with pytest.raises(ValueError):
        valid_selection([], 5, 7)
    with pytest.raises(ValueError):
        valid_selection([35], 5, 7)
    with pytest.raises(ValueError):
        valid_selection([-1], 5, 7)
    with pytest.raises(ValueError):
        valid_selection([(5, 0)], 5, 7)
    with pytest.raises(ValueError):
        valid_selection([(0, 7)], 5, 7)


@pytest.mark.parametrize("cols", [4, 5, 6, 7])
def test_adjacency_never_crosses_row_boundary(cols):
    assert engine._is_adjacent(0, 1, cols)
    assert engine._is_adjacent(0, cols, cols)
    assert engine._is_adjacent(cols - 1, 2 * cols - 1, cols)
    assert not engine._is_adjacent(cols - 1, cols, cols)
    assert not engine._is_adjacent(0, 0, cols)


def test_direction_blocking_uses_cols_as_row_stride():
    rows, cols = 5, 7
    owners = [0] * (rows * cols)
    owners[26] = 1
    owners[33] = 2

    index_list, direction_list, _ = engine._generate_direction([34], owners, rows, cols, 1)

    assert index_list == [26]
    assert direction_list == [engine.RIGHT]
    assert engine._calculate_toward_list(index_list, direction_list, cols) == [27]


@pytest.mark.parametrize("rows,cols", [(5, 7), (7, 5), (3, 4)])
def test_annihilation_detection_and_forced_turn_on_non_square(rows, cols):
    total = rows * cols
    base_b = total - 1
    base_a = base_b - cols
    cells = _cells(rows, cols, lambda row, col: 0, lambda row, col: 0)
    board = initial_board(cells, base_a, base_b, 12, 1)

    result = resolve_turn(
        board,
        [base_b],
        [base_b],
        seed=99,
        base_a_index=base_a,
        base_b_index=base_b,
        reinforcement_a=[0] * total,
        reinforcement_b=[0] * total,
    )

    assert result.board.rows == rows
    assert result.board.cols == cols
    assert len(result.board.owners) == total
    assert result.board.owners[base_b] == 1
    assert player_without_territory(result.board) == 2
    assert all(0 <= index < total for index in result.war_location)
    assert len(result.soldier_policy_p1) == total
    assert len(result.soldier_policy_p2) == total

    reinforcement_a = [index % 3 for index in range(total)]
    forced = resolve_forced_turn(
        result.board,
        seed=100,
        base_a_index=base_a,
        base_b_index=base_b,
        reinforcement_a=reinforcement_a,
        reinforcement_b=[0] * total,
    )

    assert forced.soldier_policy_p2 == tuple(0 for _ in range(total))
    assert len(forced.board.owners) == total
    assert player_without_territory(forced.board) == 2
    for index in range(total):
        if result.board.owners[index] == 1:
            assert forced.board.owners[index] == 1
            assert forced.board.soldiers[index] == result.board.soldiers[index] + reinforcement_a[index]
        else:
            assert forced.board.owners[index] == 0
            assert forced.board.soldiers[index] == 0

    second_forced = resolve_forced_turn(
        forced.board,
        seed=101,
        base_a_index=base_a,
        base_b_index=base_b,
        reinforcement_a=reinforcement_a,
        reinforcement_b=[0] * total,
    )
    assert len(second_forced.board.owners) == total
    for index in range(total):
        if forced.board.owners[index] == 1:
            assert second_forced.board.soldiers[index] == forced.board.soldiers[index] + reinforcement_a[index]


@pytest.mark.parametrize("rows,cols", [(5, 7), (7, 5), (3, 4)])
def test_resolve_turn_applies_reinforcement_per_cell(rows, cols):
    total = rows * cols
    owners = tuple(1 for _ in range(total))
    soldiers = tuple(5 + index % 3 for index in range(total))
    board = Board(rows=rows, cols=cols, owners=owners, soldiers=soldiers)
    base_a = 0
    base_b = total - 1

    result_zero = resolve_turn(
        board,
        [0],
        [total - 1],
        seed=7,
        base_a_index=base_a,
        base_b_index=base_b,
        reinforcement_a=[0] * total,
        reinforcement_b=[0] * total,
    )
    reinforcement_a = [index % 4 for index in range(total)]
    result_full = resolve_turn(
        board,
        [0],
        [total - 1],
        seed=7,
        base_a_index=base_a,
        base_b_index=base_b,
        reinforcement_a=reinforcement_a,
        reinforcement_b=[1] * total,
    )

    assert result_zero.war_location == ()
    assert result_zero.board.owners == result_full.board.owners
    assert len(result_full.board.owners) == total
    for index in range(total):
        assert result_full.board.soldiers[index] - result_zero.board.soldiers[index] == reinforcement_a[index]


def test_resolve_turn_accepts_64_bit_seed():
    rows, cols = 3, 4
    total = rows * cols
    cells = _cells(rows, cols, lambda row, col: 0, lambda row, col: 0)
    board = initial_board(cells, 7, 11, 8, 7)
    seed = 0xF3A91C0D5E7B2468

    first = resolve_turn(
        board,
        [11],
        [11],
        seed=seed,
        base_a_index=7,
        base_b_index=11,
        reinforcement_a=[0] * total,
        reinforcement_b=[0] * total,
    )
    second = resolve_turn(
        board,
        [11],
        [11],
        seed=seed,
        base_a_index=7,
        base_b_index=11,
        reinforcement_a=[0] * total,
        reinforcement_b=[0] * total,
    )

    assert first == second
    assert len(first.board.owners) == total
    assert first.war_location == (11,)


def test_resolve_forced_turn_rejects_live_game():
    board = Board(
        rows=2,
        cols=2,
        owners=(1, 2, 0, 0),
        soldiers=(3, 4, 0, 0),
    )
    with pytest.raises(ValueError):
        resolve_forced_turn(
            board,
            seed=1,
            base_a_index=0,
            base_b_index=1,
            reinforcement_a=[0, 0, 0, 0],
            reinforcement_b=[0, 0, 0, 0],
        )


def test_resolve_forced_turn_handles_both_sides_empty():
    board = Board(
        rows=2,
        cols=3,
        owners=(0, 0, 0, 0, 0, 0),
        soldiers=(0, 0, 0, 0, 0, 0),
    )
    result = resolve_forced_turn(
        board,
        seed=1,
        base_a_index=0,
        base_b_index=5,
        reinforcement_a=[2] * 6,
        reinforcement_b=[3] * 6,
    )
    assert result.board.owners == (0, 0, 0, 0, 0, 0)
    assert result.board.soldiers == (0, 0, 0, 0, 0, 0)
    assert result.soldier_policy_p1 == (0, 0, 0, 0, 0, 0)
    assert result.soldier_policy_p2 == (0, 0, 0, 0, 0, 0)


def test_player_without_territory_and_total_soldiers():
    board = Board(rows=2, cols=3, owners=(1, 1, 0, 2, 0, 0), soldiers=(3, 4, 0, 5, 0, 0))
    assert player_without_territory(board) is None
    assert total_soldiers(board, 1) == 7
    assert total_soldiers(board, 2) == 5

    board = Board(rows=2, cols=3, owners=(0, 1, 0, 0, 0, 0), soldiers=(0, 4, 0, 0, 0, 0))
    assert player_without_territory(board) == 2

    board = Board(rows=2, cols=3, owners=(0, 0, 0, 2, 0, 0), soldiers=(0, 0, 0, 6, 0, 0))
    assert player_without_territory(board) == 1

    board = Board(rows=2, cols=3, owners=(0, 0, 0, 0, 0, 0), soldiers=(0, 0, 0, 0, 0, 0))
    assert player_without_territory(board) is None


def test_resolve_turn_rejects_invalid_inputs():
    board = Board(rows=2, cols=2, owners=(1, 2, 0, 0), soldiers=(3, 4, 0, 0))
    with pytest.raises(ValueError):
        resolve_turn(
            board,
            [],
            [1],
            seed=1,
            base_a_index=0,
            base_b_index=1,
            reinforcement_a=[0, 0, 0, 0],
            reinforcement_b=[0, 0, 0, 0],
        )
    with pytest.raises(ValueError):
        resolve_turn(
            board,
            [4],
            [1],
            seed=1,
            base_a_index=0,
            base_b_index=1,
            reinforcement_a=[0, 0, 0, 0],
            reinforcement_b=[0, 0, 0, 0],
        )
    with pytest.raises(ValueError):
        resolve_turn(
            board,
            [0],
            [1],
            seed=1,
            base_a_index=0,
            base_b_index=1,
            reinforcement_a=[0, 0],
            reinforcement_b=[0, 0, 0, 0],
        )


def _non_square_round(board, round_number, rows, cols, reinforcement_a, reinforcement_b):
    total = rows * cols
    targets = [cols // 2, cols + cols // 2, (rows - 1) * cols + cols // 2]
    target = targets[(round_number - 1) % len(targets)]
    selection_a = target
    selection_b = target
    if 1 in board.owners and 2 in board.owners:
        return resolve_turn(
            board,
            [selection_a],
            [selection_b],
            seed=1000 + round_number,
            base_a_index=0,
            base_b_index=total - 1,
            reinforcement_a=reinforcement_a,
            reinforcement_b=reinforcement_b,
        )
    return resolve_forced_turn(
        board,
        seed=1000 + round_number,
        base_a_index=0,
        base_b_index=total - 1,
        reinforcement_a=reinforcement_a,
        reinforcement_b=reinforcement_b,
    )


@pytest.mark.parametrize("rows,cols", [(5, 7), (7, 5), (3, 4)])
def test_non_square_multiple_rounds_and_determinism(rows, cols):
    total = rows * cols

    def owner(row, col):
        return 1 if col < cols // 2 else 2

    cells = _cells(rows, cols, owner, lambda row, col: 4 if owner(row, col) else 0)
    board = initial_board(cells, 0, total - 1, 8, 7)
    reinforcement_a = [1] * total
    reinforcement_b = [1] * total

    def play():
        current = board
        resolutions = []
        war_rounds = 0
        for round_number in range(1, 7):
            resolution = _non_square_round(
                current, round_number, rows, cols, reinforcement_a, reinforcement_b
            )
            assert resolution.board.rows == rows
            assert resolution.board.cols == cols
            assert len(resolution.board.owners) == total
            assert len(resolution.board.soldiers) == total
            assert all(owner_value in (0, 1, 2) for owner_value in resolution.board.owners)
            assert all(soldier >= 0 for soldier in resolution.board.soldiers)
            assert len(resolution.soldier_policy_p1) == total
            assert len(resolution.soldier_policy_p2) == total
            assert all(0 <= index < total for index in resolution.war_location)
            if resolution.war_location:
                war_rounds += 1
            resolutions.append(resolution)
            current = resolution.board
        return resolutions, war_rounds

    first, war_rounds = play()
    second, second_war_rounds = play()
    assert first == second
    assert war_rounds == second_war_rounds
    assert war_rounds >= 1
    assert len(first) == 6


def _six_by_six_owners(kind):
    if kind == "left-right":
        return [1 if col < 3 else 2 for _ in range(6) for col in range(6)]
    if kind == "top-bottom":
        return [1 if row < 3 else 2 for row in range(6) for _ in range(6)]
    if kind == "bases-only":
        owners = [0] * 36
        owners[22] = 1
        owners[28] = 2
        return owners
    raise ValueError("unknown layout")


def _six_by_six_scenario(identifier, layout, seed, base_a, base_b, base_a_soldiers, base_b_soldiers, fill, reinforcement_a, reinforcement_b, selections_a, selections_b, rounds, expect_annihilation=False):
    owners = _six_by_six_owners(layout)
    soldiers = [fill if owner != 0 else 0 for owner in owners]
    soldiers[base_a] = base_a_soldiers
    soldiers[base_b] = base_b_soldiers
    return {
        "id": identifier,
        "owners": owners,
        "soldiers": soldiers,
        "seed": seed,
        "base_a": base_a,
        "base_b": base_b,
        "base_a_soldiers": base_a_soldiers,
        "base_b_soldiers": base_b_soldiers,
        "reinforcement_a": reinforcement_a,
        "reinforcement_b": reinforcement_b,
        "selections_a": selections_a,
        "selections_b": selections_b,
        "rounds": rounds,
        "expect_annihilation": expect_annihilation,
    }


_SCENARIOS = [
    _six_by_six_scenario(
        "left-right-seed-101",
        "left-right",
        101,
        7,
        28,
        9,
        9,
        4,
        1,
        1,
        [5, 10, 15, 20, 25, 30],
        [0, 7, 14, 21, 28, 35],
        14,
    ),
    _six_by_six_scenario(
        "top-bottom-seed-202",
        "top-bottom",
        202,
        7,
        28,
        10,
        8,
        3,
        2,
        1,
        [28, 22, 16, 10, 4],
        [7, 13, 19, 25, 31],
        14,
    ),
    _six_by_six_scenario(
        "left-right-seed-303",
        "left-right",
        303,
        7,
        28,
        7,
        9,
        5,
        1,
        2,
        [35, 34, 33, 32, 31],
        [0, 1, 2, 3, 4],
        14,
    ),
    _six_by_six_scenario(
        "annihilation-seed-404",
        "bases-only",
        404,
        22,
        28,
        25,
        1,
        0,
        1,
        1,
        [28],
        [28],
        20,
        expect_annihilation=True,
    ),
]


def _build_six_by_six(scenario):
    cells = []
    for index, owner in enumerate(scenario["owners"]):
        row, col = divmod(index, 6)
        cells.append(
            {
                "row": row,
                "col": col,
                "initialOwner": owner,
                "initialSoldiers": scenario["soldiers"][index],
                "reinforcementA": scenario["reinforcement_a"],
                "reinforcementB": scenario["reinforcement_b"],
            }
        )
    return initial_board(
        cells,
        scenario["base_a"],
        scenario["base_b"],
        scenario["base_a_soldiers"],
        scenario["base_b_soldiers"],
    )


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[scenario["id"] for scenario in _SCENARIOS])
def test_six_by_six_matches_frozen_reference(scenario):
    board = _build_six_by_six(scenario)
    reference_owners = list(board.owners)
    reference_soldiers = list(board.soldiers)
    reinforcement_a = [scenario["reinforcement_a"]] * 36
    reinforcement_b = [scenario["reinforcement_b"]] * 36

    normal_rounds = 0
    forced_rounds = 0
    war_rounds = 0
    loss_rounds = 0
    annihilation_seen = False

    for round_number in range(1, scenario["rounds"] + 1):
        round_seed = scenario["seed"] * 100 + round_number
        if 1 in board.owners and 2 in board.owners:
            selection_a = scenario["selections_a"][(round_number - 1) % len(scenario["selections_a"])]
            selection_b = scenario["selections_b"][(round_number - 1) % len(scenario["selections_b"])]
            resolution = resolve_turn(
                board,
                [selection_a],
                [selection_b],
                seed=round_seed,
                base_a_index=scenario["base_a"],
                base_b_index=scenario["base_b"],
                reinforcement_a=reinforcement_a,
                reinforcement_b=reinforcement_b,
            )
            reference = reference_legacy.resolve_turn_reference(
                reference_owners,
                reference_soldiers,
                [selection_a],
                [selection_b],
                round_seed,
                scenario["base_a"],
                scenario["base_b"],
                scenario["reinforcement_a"],
                scenario["reinforcement_b"],
            )
            normal_rounds += 1
        else:
            resolution = resolve_forced_turn(
                board,
                seed=round_seed,
                base_a_index=scenario["base_a"],
                base_b_index=scenario["base_b"],
                reinforcement_a=reinforcement_a,
                reinforcement_b=reinforcement_b,
            )
            reference = reference_legacy.resolve_forced_turn_reference(
                reference_owners,
                reference_soldiers,
                round_seed,
                scenario["base_a"],
                scenario["base_b"],
                scenario["reinforcement_a"],
                scenario["reinforcement_b"],
            )
            forced_rounds += 1
            if player_without_territory(board) is not None:
                annihilation_seen = True

        if resolution.war_location:
            war_rounds += 1
        if resolution.war_lost_p1:
            loss_rounds += 1

        assert list(resolution.board.owners) == reference["owners"]
        assert list(resolution.board.soldiers) == reference["soldiers"]
        assert list(resolution.soldier_policy_p1) == reference["soldier_policy_a"]
        assert list(resolution.soldier_policy_p2) == reference["soldier_policy_b"]
        assert list(resolution.war_location) == reference["war_location"]
        assert list(resolution.war_lost_p1) == reference["war_lost_a"]
        assert list(resolution.war_lost_p2) == reference["war_lost_b"]
        assert resolution.logistics_p1 == reference["logistics_a"]
        assert resolution.logistics_p2 == reference["logistics_b"]

        board = resolution.board
        reference_owners = list(reference["owners"])
        reference_soldiers = list(reference["soldiers"])

    assert board.rows == 6
    assert board.cols == 6
    assert len(board.owners) == 36
    assert normal_rounds + forced_rounds == scenario["rounds"]
    assert normal_rounds + forced_rounds >= 12
    assert war_rounds >= 1
    assert loss_rounds >= 1
    if scenario["expect_annihilation"]:
        assert annihilation_seen
        assert forced_rounds >= 15
