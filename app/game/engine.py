import math
import random
from dataclasses import dataclass
from numbers import Integral

import numpy as np

STILL = 0
UP = 1
DOWN = 2
LEFT = 3
RIGHT = 4

_MAX_WAR_PART_SIZE = 6


@dataclass(frozen=True)
class Board:
    rows: int
    cols: int
    owners: tuple[int, ...]
    soldiers: tuple[int, ...]


@dataclass(frozen=True)
class TurnResolution:
    board: Board
    pre_combat_policy_p1: tuple[int, ...]
    pre_combat_policy_p2: tuple[int, ...]
    movements_p1: tuple[dict, ...]
    movements_p2: tuple[dict, ...]
    soldier_policy_p1: tuple[int, ...]
    soldier_policy_p2: tuple[int, ...]
    war_location: tuple[int, ...]
    war_lost_p1: tuple[int, ...]
    war_lost_p2: tuple[int, ...]
    logistics_p1: int
    logistics_p2: int


def valid_selection(cells, rows, cols):
    rows, cols = _validate_size(rows, cols)
    if cells is None:
        raise ValueError("selection 不能为空")
    try:
        items = list(cells)
    except TypeError:
        raise ValueError("selection 必须是索引或 (row, col) 的可迭代对象") from None
    if not items:
        raise ValueError("selection 不能为空")
    result = set()
    for item in items:
        result.add(_selection_to_index(item, rows, cols))
    return sorted(result)


def initial_board(rows, cols, spawn_a_index, spawn_b_index, soldiers_a, soldiers_b):
    rows, cols = _validate_size(rows, cols)
    total = rows * cols
    spawn_a_index = _check_index(spawn_a_index, total, "spawn_a_index")
    spawn_b_index = _check_index(spawn_b_index, total, "spawn_b_index")
    if spawn_a_index == spawn_b_index:
        raise ValueError("出生格 A 和出生格 B 不能重合")
    soldiers_a = _require_non_negative_int(soldiers_a, "soldiers_a")
    soldiers_b = _require_non_negative_int(soldiers_b, "soldiers_b")

    # 初始棋盘全部中立，只有两个出生格分别属于玩家 1 和玩家 2。
    owners = [0 for _ in range(total)]
    soldiers = [0 for _ in range(total)]
    owners[spawn_a_index] = 1
    soldiers[spawn_a_index] = soldiers_a
    owners[spawn_b_index] = 2
    soldiers[spawn_b_index] = soldiers_b

    return Board(rows=rows, cols=cols, owners=tuple(owners), soldiers=tuple(soldiers))


def resolve_turn(
    board,
    p1_cells,
    p2_cells,
    *,
    seed,
    base_a_index,
    base_b_index,
    reinforcement_a,
    reinforcement_b,
):
    _validate_board(board)
    total = board.rows * board.cols
    base_a_index = _check_index(base_a_index, total, "base_a_index")
    base_b_index = _check_index(base_b_index, total, "base_b_index")
    reinforcement_a = _normalize_reinforcement(reinforcement_a, total, "reinforcement_a")
    reinforcement_b = _normalize_reinforcement(reinforcement_b, total, "reinforcement_b")

    pos_list_a = valid_selection(p1_cells, board.rows, board.cols)
    pos_list_b = valid_selection(p2_cells, board.rows, board.cols)

    owners = [int(owner) for owner in board.owners]
    soldiers = [int(soldier) for soldier in board.soldiers]

    index_list_a, direction_list_a, _ = _generate_direction(
        pos_list_a, owners, board.rows, board.cols, 1
    )
    soldiers_move_a, toward_list_a = _linear_programing(
        board.cols, soldiers, index_list_a, direction_list_a
    )
    soldier_policy_a = _move_soldiers(soldiers_move_a, toward_list_a, owners)
    movements_a = _build_movements(index_list_a, toward_list_a, soldiers_move_a)

    index_list_b, direction_list_b, _ = _generate_direction(
        pos_list_b, owners, board.rows, board.cols, 2
    )
    soldiers_move_b, toward_list_b = _linear_programing(
        board.cols, soldiers, index_list_b, direction_list_b
    )
    soldier_policy_b = _move_soldiers(soldiers_move_b, toward_list_b, owners)
    movements_b = _build_movements(index_list_b, toward_list_b, soldiers_move_b)

    rng, np_rng = _make_rngs(seed)
    return _forward_next_step(
        soldier_policy_a,
        soldier_policy_b,
        owners,
        board.rows,
        board.cols,
        reinforcement_a,
        reinforcement_b,
        base_a_index,
        base_b_index,
        rng,
        np_rng,
        pre_combat_policy_a=soldier_policy_a,
        pre_combat_policy_b=soldier_policy_b,
        movements_a=movements_a,
        movements_b=movements_b,
    )


def resolve_forced_turn(
    board,
    *,
    seed,
    base_a_index,
    base_b_index,
    reinforcement_a,
    reinforcement_b,
):
    _validate_board(board)
    total = board.rows * board.cols
    base_a_index = _check_index(base_a_index, total, "base_a_index")
    base_b_index = _check_index(base_b_index, total, "base_b_index")
    reinforcement_a = _normalize_reinforcement(reinforcement_a, total, "reinforcement_a")
    reinforcement_b = _normalize_reinforcement(reinforcement_b, total, "reinforcement_b")

    owners = [int(owner) for owner in board.owners]
    soldiers = [int(soldier) for soldier in board.soldiers]
    count_a = owners.count(1)
    count_b = owners.count(2)
    if count_a > 0 and count_b > 0:
        raise ValueError("双方都还有领地，不能进行补算回合")

    # 与参考实现一致：玩家1领地归零时由玩家1补零；双方都归零时同样按玩家1归零处理。
    if count_a == 0:
        soldier_policy_a = [0 for _ in range(total)]
        soldier_policy_b = list(soldiers)
    else:
        soldier_policy_a = list(soldiers)
        soldier_policy_b = [0 for _ in range(total)]

    rng, np_rng = _make_rngs(seed)
    return _forward_next_step(
        soldier_policy_a,
        soldier_policy_b,
        owners,
        board.rows,
        board.cols,
        reinforcement_a,
        reinforcement_b,
        base_a_index,
        base_b_index,
        rng,
        np_rng,
        pre_combat_policy_a=soldier_policy_a,
        pre_combat_policy_b=soldier_policy_b,
        movements_a=(),
        movements_b=(),
    )


def player_without_territory(board):
    _validate_board(board)
    has_p1 = 1 in board.owners
    has_p2 = 2 in board.owners
    if has_p1 == has_p2:
        return None
    return 2 if has_p1 else 1


def annihilation_result(board):
    _validate_board(board)
    has_p1 = 1 in board.owners
    has_p2 = 2 in board.owners
    if has_p1 and has_p2:
        return False, None
    if has_p1:
        return True, 1
    if has_p2:
        return True, 2
    return True, None


def total_soldiers(board, player):
    _validate_board(board)
    player = _require_int(player, "player")
    if player not in (1, 2):
        raise ValueError("player 只能取 1 或 2")
    return sum(int(board.soldiers[i]) for i in range(len(board.owners)) if board.owners[i] == player)


def _validate_size(rows, cols):
    rows = _require_int(rows, "rows")
    cols = _require_int(cols, "cols")
    if rows < 1 or cols < 1:
        raise ValueError("rows 和 cols 必须大于零")
    return rows, cols


def _require_int(value, name):
    if not isinstance(value, Integral) or isinstance(value, bool):
        raise ValueError("%s 必须是整数" % name)
    return int(value)


def _require_non_negative_int(value, name):
    number = _require_int(value, name)
    if number < 0:
        raise ValueError("%s 不能为负数" % name)
    return number


def _check_index(index, total, name):
    index = _require_int(index, name)
    if not 0 <= index < total:
        raise ValueError("%s 越界" % name)
    return index


def _selection_to_index(item, rows, cols):
    total = rows * cols
    if isinstance(item, Integral) and not isinstance(item, bool):
        index = int(item)
        if not 0 <= index < total:
            raise ValueError("选择索引越界: %d" % index)
        return index
    try:
        values = tuple(item)
    except TypeError:
        raise ValueError("selection 的每一项必须是索引或 (row, col)") from None
    if len(values) != 2:
        raise ValueError("selection 的坐标必须是 (row, col)")
    row = _require_int(values[0], "row")
    col = _require_int(values[1], "col")
    if not 0 <= row < rows or not 0 <= col < cols:
        raise ValueError("选择坐标越界: (%d, %d)" % (row, col))
    return row * cols + col


def _validate_board(board):
    if not isinstance(board, Board):
        raise ValueError("board 必须是 Board")
    rows, cols = _validate_size(board.rows, board.cols)
    total = rows * cols
    if len(board.owners) != total:
        raise ValueError("board.owners 长度必须等于 rows * cols")
    if len(board.soldiers) != total:
        raise ValueError("board.soldiers 长度必须等于 rows * cols")
    for owner in board.owners:
        value = _require_int(owner, "owner")
        if value not in (0, 1, 2):
            raise ValueError("owner 只能取 0、1、2")
    for soldier in board.soldiers:
        _require_non_negative_int(soldier, "soldier")


def _normalize_reinforcement(values, total, name):
    try:
        items = list(values)
    except TypeError:
        raise ValueError("%s 必须是长度 %d 的列表" % (name, total)) from None
    if len(items) != total:
        raise ValueError("%s 长度必须等于 rows * cols" % name)
    return [_require_int(value, name) for value in items]


def _make_rngs(seed):
    seed = _require_non_negative_int(seed, "seed")
    # np.random.RandomState 只接受 32 位种子；随机源仍完全由 seed 决定。
    return random.Random(seed), np.random.RandomState(seed % (2 ** 32))


def _calculate_relative_location(index, relative_index, cols):
    row = index // cols
    col = index % cols
    relative_row = relative_index // cols
    relative_col = relative_index % cols
    if relative_row > row and relative_col > col:
        return [RIGHT, DOWN]
    if relative_row > row and relative_col == col:
        return [DOWN]
    if relative_row > row and relative_col < col:
        return [LEFT, DOWN]
    if relative_row == row and relative_col > col:
        return [RIGHT]
    if relative_row == row and relative_col == col:
        return [STILL]
    if relative_row == row and relative_col < col:
        return [LEFT]
    if relative_row < row and relative_col > col:
        return [RIGHT, UP]
    if relative_row < row and relative_col == col:
        return [UP]
    if relative_row < row and relative_col < col:
        return [LEFT, UP]
    raise ValueError("无法计算相对方向")


def _calculate_2d_distance(index1, index2, cols):
    return abs(index1 // cols - index2 // cols) + abs(index1 % cols - index2 % cols)


def _find_the_nearest(index, defend_list, cols):
    distances = [_calculate_2d_distance(index, defend_index, cols) for defend_index in defend_list]
    return defend_list[distances.index(min(distances))]


def _check_directions(index, directions, owners, opponent, rows, cols, target):
    result = [directions[i] for i in range(len(directions))]
    row = index // cols
    col = index % cols
    for direction in result:
        if direction == RIGHT:
            if col + 1 < cols and owners[index + 1] == opponent and index + 1 != target:
                directions.remove(RIGHT)
        if direction == LEFT:
            if col - 1 >= 0 and owners[index - 1] == opponent and index - 1 != target:
                directions.remove(LEFT)
        if direction == UP:
            if row - 1 >= 0 and owners[index - cols] == opponent and index - cols != target:
                directions.remove(UP)
        if direction == DOWN:
            if row + 1 < rows and owners[index + cols] == opponent and index + cols != target:
                directions.remove(DOWN)
    return directions


def _merge_direction(direction_list, temp_list):
    result = []
    defend_line_belong = []
    for i in range(len(direction_list)):
        temp1 = direction_list[i]
        temp2 = temp_list[i]
        for j in range(len(temp2)):
            if temp2[j] in temp1:
                defend_line_belong.append([i, temp1.index(temp2[j])])
            if temp2[j] not in temp1:
                temp1.append(temp2[j])
                defend_line_belong.append([i, len(temp1) - 1])
        result.append(temp1)
    return result, defend_line_belong


def _unfold(index_list, direction_list, defend_line_belong_list):
    index_unfold = []
    direction_unfold = []
    defend_line_unfold = [[] for _ in range(len(defend_line_belong_list))]
    for i in range(len(direction_list)):
        for j in range(len(direction_list[i])):
            index_unfold.append(index_list[i])
            direction_unfold.append(direction_list[i][j])
            for k in range(len(defend_line_belong_list)):
                if [i, j] in defend_line_belong_list[k]:
                    defend_line_unfold[k].append(len(index_unfold) - 1)
    return index_unfold, direction_unfold, defend_line_unfold


def _generate_direction(pos_list, owners, rows, cols, player):
    opponent = 2 if player == 1 else 1
    direction_list = []
    index_list = []
    defend_line_belong_list = []
    for i in range(len(pos_list)):
        defend_list = [pos_list[i]]
        temp_list = []
        for j in range(len(owners)):
            if owners[j] == player:
                nearest = _find_the_nearest(j, defend_list, cols)
                relative = _calculate_relative_location(j, nearest, cols)
                temp_list.append(
                    _check_directions(j, relative, owners, opponent, rows, cols, nearest)
                )
                if i == 0:
                    index_list.append(j)
        if i == 0:
            direction_list = temp_list
        direction_list, defend_line_belong = _merge_direction(direction_list, temp_list)
        defend_line_belong_list.append(defend_line_belong)
    index_list, direction_list, defend_line_belong_list = _unfold(
        index_list, direction_list, defend_line_belong_list
    )
    return index_list, direction_list, defend_line_belong_list


def _calculate_toward_list(index_list, direction_list, cols):
    result = []
    for i in range(len(index_list)):
        if direction_list[i] == UP:
            result.append(index_list[i] - cols)
        if direction_list[i] == DOWN:
            result.append(index_list[i] + cols)
        if direction_list[i] == LEFT:
            result.append(index_list[i] - 1)
        if direction_list[i] == RIGHT:
            result.append(index_list[i] + 1)
        if direction_list[i] == STILL:
            result.append(index_list[i])
    return result


def _linear_programing(cols, soldiers, index_list, direction_list):
    toward_list = _calculate_toward_list(index_list, direction_list, cols)
    soldiers_move = [
        round(soldiers[index_list[i]] / index_list.count(index_list[i]))
        for i in range(len(index_list))
    ]
    return soldiers_move, toward_list


def _move_soldiers(soldiers_move, toward_list, owners):
    soldier_policy = [0 for _ in range(len(owners))]
    for i in range(len(toward_list)):
        soldier_policy[toward_list[i]] += soldiers_move[i]
    return [round(soldier_policy[i]) for i in range(len(owners))]


def _build_movements(index_list, toward_list, soldiers_move):
    grouped: dict[tuple[int, int], int] = {}
    for source, target, soldiers in zip(index_list, toward_list, soldiers_move):
        count = int(soldiers)
        if count <= 0:
            continue
        key = (int(source), int(target))
        grouped[key] = grouped.get(key, 0) + count
    return tuple(
        {"from": source, "to": target, "soldiers": grouped[(source, target)]}
        for source, target in sorted(grouped)
    )


def _is_adjacent(index_a, index_b, cols):
    return _calculate_2d_distance(index_a, index_b, cols) == 1


def _is_adjacent_to_any(index, subset, cols):
    return any(_is_adjacent(index, member, cols) for member in subset)


def _add_war_part(index, war_parts, cols):
    for part in war_parts:
        if len(part) < _MAX_WAR_PART_SIZE and _is_adjacent_to_any(index, part, cols):
            part.append(index)
            return war_parts
    war_parts.append([index])
    return war_parts


def _generate_war_parts(war_location, cols):
    if not war_location:
        return []
    war_parts = [[war_location[0]]]
    for index in war_location[1:]:
        war_parts = _add_war_part(index, war_parts, cols)
    return war_parts


def _calculate_winner(soldiers_a, soldiers_b, rng):
    ratio = soldiers_a / (soldiers_a + soldiers_b)
    coin = rng.uniform(0, 1)
    if coin < ratio:
        return 1
    return 2


def _calculate_lost_rate(soldiers_a, soldiers_b):
    factor_a = 0.02
    factor_b = 0.8
    if soldiers_a < 1:
        return [1, 0]
    if soldiers_b < 1:
        return [0, 1]
    if soldiers_b >= soldiers_a:
        lost_rate_a = factor_a * math.exp(factor_b * (soldiers_b / soldiers_a - 1))
        lost_rate_b = factor_a * math.exp(factor_b * (1 - soldiers_b / soldiers_a))
    else:
        lost_rate_a = factor_a * math.exp(factor_b * (1 - soldiers_a / soldiers_b))
        lost_rate_b = factor_a * math.exp(factor_b * (soldiers_a / soldiers_b - 1))
    return [min(lost_rate_a, 1), min(lost_rate_b, 1)]


def _simulate_war_process(soldiers_a, soldiers_b, rng, np_rng):
    lost_limit = 0.7
    initial_soldiers_a = soldiers_a
    initial_soldiers_b = soldiers_b

    while True:
        lost_rate = _calculate_lost_rate(soldiers_a, soldiers_b)
        lamda_a = max(round(soldiers_a * lost_rate[0]), 1)
        lamda_b = max(round(soldiers_b * lost_rate[1]), 1)
        lost_soldier_a = np_rng.poisson(lamda_a, 1)
        lost_soldier_b = np_rng.poisson(lamda_b, 1)
        soldiers_a -= lost_soldier_a[0]
        soldiers_b -= lost_soldier_b[0]
        soldiers_a = max(soldiers_a, 0)
        soldiers_b = max(soldiers_b, 0)
        if soldiers_b == 0:
            return soldiers_a, soldiers_b, 1
        elif soldiers_a == 0:
            return soldiers_a, soldiers_b, 2
        if soldiers_a / initial_soldiers_a < lost_limit and soldiers_b / initial_soldiers_b >= lost_limit:
            return soldiers_a, soldiers_b, 2
        if soldiers_a / initial_soldiers_a >= lost_limit and soldiers_b / initial_soldiers_b < lost_limit:
            return soldiers_a, soldiers_b, 1
        if soldiers_a / initial_soldiers_a < lost_limit and soldiers_b / initial_soldiers_b < lost_limit:
            return soldiers_a, soldiers_b, _calculate_winner(soldiers_a, soldiers_b, rng)


def _simulate_winning_rate(soldiers_a, soldiers_b, rng, np_rng):
    simulate_round = 100
    lost_list_a = []
    lost_list_b = []
    outcome_list = []
    for _ in range(simulate_round):
        remaining_a, remaining_b, winner = _simulate_war_process(soldiers_a, soldiers_b, rng, np_rng)
        outcome_list.append(winner)
        lost_list_a.append((soldiers_a - remaining_a) / soldiers_a)
        lost_list_b.append((soldiers_b - remaining_b) / soldiers_b)
    winning_rate_a = outcome_list.count(1) / simulate_round
    return np.mean(lost_list_a), np.mean(lost_list_b), winning_rate_a


def _compute_adjacent(binary_index, war_parts, cols):
    adjacent_list = [[] for _ in range(len(war_parts))]
    for i in range(len(war_parts)):
        for j in range(len(war_parts)):
            if _is_adjacent(war_parts[i], war_parts[j], cols):
                adjacent_list[i].append(j)

    adjacent_grids = 0
    for i in range(len(binary_index)):
        for j in range(len(adjacent_list[i])):
            if binary_index[i] == binary_index[adjacent_list[i][j]]:
                adjacent_grids += 1
    return adjacent_grids / 2


def _normalize(values):
    if values == [] or sum(values) == 0:
        return []
    total = sum(values)
    return [values[i] / total for i in range(len(values))]


def _generate_winner_list(winning_rate_a_list, war_part, cols, rng):
    def binary(number):
        return "" if number == 0 else binary(number // 2) + str(number % 2)

    correlation_rate = 2 ** (1 / len(war_part))

    result = [0 for _ in range(2 ** len(winning_rate_a_list))]
    distribution = []
    distribution_indicator = []
    for i in range(len(result)):
        value = 1
        binary_index = list(map(int, binary(i)))
        while len(binary_index) < len(winning_rate_a_list):
            binary_index.insert(0, 0)
        for j in range(len(winning_rate_a_list)):
            value = (
                value
                * (winning_rate_a_list[j] ** binary_index[j])
                * ((1 - winning_rate_a_list[j]) ** (1 - binary_index[j]))
            )
        adjacent = _compute_adjacent(binary_index, war_part, cols)
        value = value * correlation_rate ** adjacent
        distribution.append(value)
        distribution_indicator.append(binary_index)
    distribution[0] = distribution[0] * correlation_rate
    distribution[-1] = distribution[-1] * correlation_rate
    distribution = _normalize(distribution)

    temp = 0
    coin = rng.uniform(0, 1)
    result_index = 0
    for i in range(len(distribution)):
        temp += distribution[i]
        if coin < temp:
            result_index = i
            break
    return distribution_indicator[result_index]


def _find_retrieve_location(index, war_location, cols, player):
    if player == 1:
        while index % cols > 0:
            index -= 1
            if index not in war_location:
                return index
        return -1
    if player == 2:
        while index % cols < cols - 1:
            index += 1
            if index not in war_location:
                return index
        return -1
    raise ValueError("player 只能取 1 或 2")


def _simulate_war(soldier_policy_a, soldier_policy_b, cols, rng, np_rng):
    soldier_policy_a_new = list(soldier_policy_a)
    soldier_policy_b_new = list(soldier_policy_b)

    war_lost_a = []
    war_lost_b = []

    war_location = [
        i
        for i in range(len(soldier_policy_a))
        if soldier_policy_a[i] > 0 and soldier_policy_b[i] > 0
    ]
    war_parts = _generate_war_parts(war_location, cols)

    for part in war_parts:
        winning_rate_a_list = []
        for cell in part:
            lost_rate_a, lost_rate_b, winning_rate_a = _simulate_winning_rate(
                soldier_policy_a_new[cell], soldier_policy_b_new[cell], rng, np_rng
            )
            war_lost_a.append(round(soldier_policy_a_new[cell] * lost_rate_a))
            soldier_policy_a_new[cell] = round(soldier_policy_a_new[cell] * (1 - lost_rate_a))

            war_lost_b.append(round(soldier_policy_b_new[cell] * lost_rate_b))
            soldier_policy_b_new[cell] = round(soldier_policy_b_new[cell] * (1 - lost_rate_b))

            winning_rate_a_list.append(winning_rate_a)

        winner_list = _generate_winner_list(winning_rate_a_list, part, cols, rng)
        for j in range(len(part)):
            if winner_list[j] == 1:
                retrieve_location = _find_retrieve_location(part[j], war_location, cols, 2)
                if retrieve_location >= 0:
                    soldier_policy_b_new[retrieve_location] += soldier_policy_b_new[part[j]]
                soldier_policy_b_new[part[j]] = 0

            if winner_list[j] == 0:
                retrieve_location = _find_retrieve_location(part[j], war_location, cols, 1)
                if retrieve_location >= 0:
                    soldier_policy_a_new[retrieve_location] += soldier_policy_a_new[part[j]]
                soldier_policy_a_new[part[j]] = 0

    return soldier_policy_a_new, soldier_policy_b_new, war_lost_a, war_lost_b


def _calculate_logistic_rate(index, base_index, rows, cols, owners, player):
    # 参考实现里 constant 为 6 且距离非负，补给率恒为 0。
    return 0


def _forward_next_step(
    soldier_policy_a,
    soldier_policy_b,
    owners,
    rows,
    cols,
    reinforcement_a,
    reinforcement_b,
    base_a_index,
    base_b_index,
    rng,
    np_rng,
    *,
    pre_combat_policy_a,
    pre_combat_policy_b,
    movements_a,
    movements_b,
):
    war_location = [
        i
        for i in range(len(owners))
        if soldier_policy_a[i] > 0 and soldier_policy_b[i] > 0
    ]

    soldier_policy_a, soldier_policy_b, war_lost_a, war_lost_b = _simulate_war(
        soldier_policy_a, soldier_policy_b, cols, rng, np_rng
    )

    owners_new = [0 for _ in range(len(owners))]
    for i in range(len(owners_new)):
        if soldier_policy_a[i] > 0:
            owners_new[i] = 1
        if soldier_policy_b[i] > 0:
            owners_new[i] = 2
        if soldier_policy_a[i] == soldier_policy_b[i] == 0:
            owners_new[i] = owners[i]

    soldier_policy_a_new = [
        soldier_policy_a[i]
        - round(
            soldier_policy_a[i]
            * _calculate_logistic_rate(i, base_a_index, rows, cols, owners_new, 1)
        )
        for i in range(len(soldier_policy_a))
    ]
    soldier_policy_b_new = [
        soldier_policy_b[i]
        - round(
            soldier_policy_b[i]
            * _calculate_logistic_rate(i, base_b_index, rows, cols, owners_new, 2)
        )
        for i in range(len(soldier_policy_b))
    ]

    logistics_a = sum(soldier_policy_a) - sum(soldier_policy_a_new)
    logistics_b = sum(soldier_policy_b) - sum(soldier_policy_b_new)

    for i in range(len(owners_new)):
        if owners_new[i] == 1:
            soldier_policy_a_new[i] = soldier_policy_a_new[i] + reinforcement_a[i]
        if owners_new[i] == 2:
            soldier_policy_b_new[i] = soldier_policy_b_new[i] + reinforcement_b[i]

    soldiers_new = [
        max(soldier_policy_a_new[i], soldier_policy_b_new[i], 0)
        for i in range(len(soldier_policy_a_new))
    ]

    board = Board(
        rows=rows,
        cols=cols,
        owners=tuple(int(owner) for owner in owners_new),
        soldiers=tuple(int(soldier) for soldier in soldiers_new),
    )
    return TurnResolution(
        board=board,
        pre_combat_policy_p1=tuple(int(value) for value in pre_combat_policy_a),
        pre_combat_policy_p2=tuple(int(value) for value in pre_combat_policy_b),
        movements_p1=tuple(movements_a),
        movements_p2=tuple(movements_b),
        soldier_policy_p1=tuple(int(value) for value in soldier_policy_a),
        soldier_policy_p2=tuple(int(value) for value in soldier_policy_b),
        war_location=tuple(int(value) for value in war_location),
        war_lost_p1=tuple(int(value) for value in war_lost_a),
        war_lost_p2=tuple(int(value) for value in war_lost_b),
        logistics_p1=int(logistics_a),
        logistics_p2=int(logistics_b),
    )
