import random
from typing import Dict, List, Optional, Tuple, TypedDict

Coordinate = Tuple[int, int]
Matrix = List[List[int]]
from .functionWarGame import *

TOTAL_TRIALS = 7
PRACTICE_TRIALS = 1
FORMAL_TRIALS = 6
INITIAL_SOLDIERS_A = (7, 8, 7, 8, 7, 9, 8)
INITIAL_SOLDIERS_B = (7, 8, 7, 9, 8, 8, 7)
BASE_A_INDEX = 7
BASE_B_INDEX = 28
MAP_CONDITION_IDS = ('ref0', 'ref1', 'ref2', 'ref3', 'ref4', 'ref5', 'asym')

BLUE = 1
RED = 2


def _frozen_matrix(rows: List[List[int]]) -> Tuple[Tuple[int, ...], ...]:
    return tuple(tuple(row) for row in rows)


_LEFT_BLUE = _frozen_matrix([[BLUE, BLUE, BLUE, RED, RED, RED] for _ in range(6)])
_LEFT_RED = _frozen_matrix([[RED, RED, RED, BLUE, BLUE, BLUE] for _ in range(6)])
_ALL_BLUE = _frozen_matrix([[BLUE for _ in range(6)] for _ in range(6)])
_ALL_RED = _frozen_matrix([[RED for _ in range(6)] for _ in range(6)])
_TOP_RED = _frozen_matrix([[RED for _ in range(6)] for _ in range(3)] + [[BLUE for _ in range(6)] for _ in range(3)])
_TOP_BLUE = _frozen_matrix([[BLUE for _ in range(6)] for _ in range(3)] + [[RED for _ in range(6)] for _ in range(3)])

# 颜色矩阵与参考 initialize.py 及 DrawWarField 的映射保持一致。
MAP_CONDITIONS = {
    'ref0': {
        'conditionId': 'ref0',
        'showBound': 0,
        'isReferenceCondition': True,
        'isBoundary': 1,
        'isConsistent': 0,
        'dev': 0,
        'legacyBoards': 3,
        'colorsByPlayer': {1: _LEFT_BLUE, 2: _LEFT_BLUE},
    },
    'ref1': {
        'conditionId': 'ref1',
        'showBound': 1,
        'isReferenceCondition': True,
        'isBoundary': 1,
        'isConsistent': 1,
        'dev': 0,
        'legacyBoards': None,
        'colorsByPlayer': {1: _LEFT_RED, 2: _LEFT_RED},
    },
    'ref2': {
        'conditionId': 'ref2',
        'showBound': 2,
        'isReferenceCondition': True,
        'isBoundary': 0,
        'isConsistent': 2,
        'dev': 0,
        'legacyBoards': 1,
        'colorsByPlayer': {1: _ALL_BLUE, 2: _ALL_BLUE},
    },
    'ref3': {
        'conditionId': 'ref3',
        'showBound': 3,
        'isReferenceCondition': True,
        'isBoundary': 0,
        'isConsistent': 3,
        'dev': 0,
        'legacyBoards': 2,
        'colorsByPlayer': {1: _ALL_RED, 2: _ALL_RED},
    },
    'ref4': {
        'conditionId': 'ref4',
        'showBound': 4,
        'isReferenceCondition': True,
        'isBoundary': 1,
        'isConsistent': 4,
        'dev': 0,
        'legacyBoards': None,
        'colorsByPlayer': {1: _TOP_RED, 2: _TOP_RED},
    },
    'ref5': {
        'conditionId': 'ref5',
        'showBound': 5,
        'isReferenceCondition': True,
        'isBoundary': 1,
        'isConsistent': 5,
        'dev': 0,
        'legacyBoards': None,
        'colorsByPlayer': {1: _TOP_BLUE, 2: _TOP_BLUE},
    },
    'asym': {
        'conditionId': 'asym',
        'showBound': None,
        'isReferenceCondition': False,
        'isBoundary': 2,
        'isConsistent': 6,
        'dev': 0,
        'legacyBoards': 4,
        'colorsByPlayer': {1: _LEFT_BLUE, 2: _ALL_RED},
    },
}

_METADATA_FIELDS = ('conditionId', 'showBound', 'isReferenceCondition', 'isBoundary', 'isConsistent', 'dev', 'legacyBoards')
_PLAN_FIELDS = ('trial', 'game', 'isPractice', 'formalTrial', 'sourceIndex', 'soldierFromBaseA', 'soldierFromBaseB')


class BoardState(TypedDict):
    colors: Matrix
    shapes: Matrix
    numbers: Matrix
    warLocation: List[Coordinate]
    gameNumber: int
    trial: int
    isPractice: bool
    sourceIndex: int
    conditionId: str
    mapSize: List[int]
    reinforcementA: int
    reinforcementB: int
    baseAIndex: int
    baseBIndex: int


class TurnDetails(TypedDict):
    soldierPolicyA: List[int]
    soldierPolicyB: List[int]
    posListA: List[int]
    posListB: List[int]
    warField: List[int]
    soldiers: List[int]
    mapSize: List[int]
    warLocation: List[int]
    warLostA: List[int]
    warLostB: List[int]
    logisticsA: int
    logisticsB: int
    numOfWarTurn: int
    forced: bool


def get_condition_metadata(condition_id: str) -> dict:
    if condition_id not in MAP_CONDITIONS:
        raise ValueError("unknown map condition: %s" % condition_id)
    condition = MAP_CONDITIONS[condition_id]
    return {field: condition[field] for field in _METADATA_FIELDS}


def get_condition_colors(condition_id: str, player_number: int) -> List[List[int]]:
    if condition_id not in MAP_CONDITIONS:
        raise ValueError("unknown map condition: %s" % condition_id)
    if player_number not in (1, 2):
        raise ValueError("player_number must be 1 or 2")
    layout = MAP_CONDITIONS[condition_id]["colorsByPlayer"][player_number]
    return [list(row) for row in layout]


def build_trial_plan(seed: int) -> List[dict]:
    formal_sources = list(range(1, TOTAL_TRIALS))
    random.Random(seed).shuffle(formal_sources)
    source_indices = [0] + formal_sources
    plan = []
    for trial, source_index in enumerate(source_indices):
        is_practice = trial < PRACTICE_TRIALS
        plan.append({
            "trial": trial,
            "game": trial + 1,
            "isPractice": is_practice,
            "formalTrial": 0 if is_practice else trial - PRACTICE_TRIALS + 1,
            "sourceIndex": source_index,
            "soldierFromBaseA": INITIAL_SOLDIERS_A[source_index],
            "soldierFromBaseB": INITIAL_SOLDIERS_B[source_index],
        })
    return plan


def _validate_plan_entry(plan_entry: dict) -> None:
    if not isinstance(plan_entry, dict):
        raise ValueError("plan_entry must be a dict")
    missing = [field for field in _PLAN_FIELDS if field not in plan_entry]
    if missing:
        raise ValueError("plan_entry is missing fields: %s" % ", ".join(missing))

    trial = plan_entry["trial"]
    game = plan_entry["game"]
    is_practice = plan_entry["isPractice"]
    formal_trial = plan_entry["formalTrial"]
    source_index = plan_entry["sourceIndex"]
    soldier_a = plan_entry["soldierFromBaseA"]
    soldier_b = plan_entry["soldierFromBaseB"]

    if not isinstance(trial, int) or not 0 <= trial < TOTAL_TRIALS:
        raise ValueError("plan_entry trial must be an integer between 0 and %d" % (TOTAL_TRIALS - 1))
    if game != trial + 1:
        raise ValueError("plan_entry game must equal trial + 1")
    if not isinstance(is_practice, bool) or is_practice != (trial < PRACTICE_TRIALS):
        raise ValueError("plan_entry isPractice does not match trial")
    expected_formal = 0 if is_practice else trial - PRACTICE_TRIALS + 1
    if formal_trial != expected_formal:
        raise ValueError("plan_entry formalTrial does not match trial")
    if not isinstance(source_index, int) or not 0 <= source_index < TOTAL_TRIALS:
        raise ValueError("plan_entry sourceIndex must be an integer between 0 and %d" % (TOTAL_TRIALS - 1))
    if is_practice and source_index != 0:
        raise ValueError("practice trial must use sourceIndex 0")
    if not is_practice and source_index == 0:
        raise ValueError("formal trials must use sourceIndex 1 to %d" % (TOTAL_TRIALS - 1))
    if soldier_a != INITIAL_SOLDIERS_A[source_index] or soldier_b != INITIAL_SOLDIERS_B[source_index]:
        raise ValueError("plan_entry soldiers do not match sourceIndex")


def create_initial_state(rows: int, cols: int, plan_entry: dict, condition_id: str) -> BoardState:
    if rows != 6 or cols != 6:
        raise ValueError("online game mechanics only support a 6x6 board")
    _validate_plan_entry(plan_entry)
    if condition_id not in MAP_CONDITIONS:
        raise ValueError("unknown map condition: %s" % condition_id)

    colors = get_condition_colors(condition_id, 1)
    shapes = [[0 for _ in range(cols)] for _ in range(rows)]
    numbers = [[-1 for _ in range(cols)] for _ in range(rows)]
    base_a_row, base_a_col = divmod(BASE_A_INDEX, cols)
    base_b_row, base_b_col = divmod(BASE_B_INDEX, cols)
    shapes[base_a_row][base_a_col] = 1
    shapes[base_b_row][base_b_col] = 2
    numbers[base_a_row][base_a_col] = plan_entry["soldierFromBaseA"]
    numbers[base_b_row][base_b_col] = plan_entry["soldierFromBaseB"]

    return {
        "colors": colors,
        "shapes": shapes,
        "numbers": numbers,
        "warLocation": [],
        "gameNumber": plan_entry["game"],
        "trial": plan_entry["trial"],
        "isPractice": plan_entry["isPractice"],
        "sourceIndex": plan_entry["sourceIndex"],
        "conditionId": condition_id,
        "mapSize": [rows, cols],
        "reinforcementA": plan_entry["soldierFromBaseA"],
        "reinforcementB": plan_entry["soldierFromBaseB"],
        "baseAIndex": BASE_A_INDEX,
        "baseBIndex": BASE_B_INDEX,
    }


def play_turn(
    player1_selected: List[Coordinate],
    player2_selected: List[Coordinate],
    turn_number: int,
    current_state: BoardState,
) -> Tuple[BoardState, TurnDetails]:
    if not player1_selected or not player2_selected:
        raise ValueError("both players must select at least one cell")

    mapSize = list(current_state["mapSize"])
    baseAIndex = current_state["baseAIndex"]
    baseBIndex = current_state["baseBIndex"]
    soldierFromWarFieldA = current_state["reinforcementA"]
    soldierFromWarFieldB = current_state["reinforcementB"]

    posListA = transformPlayerSelectToPosList(player1_selected, mapSize)
    posListB = transformPlayerSelectToPosList(player2_selected, mapSize)
    warField = transformShapesToWarField(current_state["shapes"])
    soldiers = transformNumbersToSoldiers(current_state["numbers"])

    indexListA, directionListA, defendLineBelongListA = generateDirectionA(posListA, warField, mapSize)
    soldiersMoveA, towardListA = linearProgramingA(mapSize, soldiers, indexListA, directionListA)
    soldierPolicyA = moveSoldiers(soldiersMoveA, towardListA, warField)
    indexListB, directionListB, defendLineBelongListB = generateDirectionB(posListB, warField, mapSize)
    soldiersMoveB, towardListB = linearProgramingB(mapSize, soldiers, indexListB, directionListB)
    soldierPolicyB = moveSoldiers(soldiersMoveB, towardListB, warField)

    soldiers, warField, warLocation, warLostA, warLostB, logisticsA, logisticsB = forwardNextStep(
        soldierPolicyA, soldierPolicyB, warField, mapSize,
        soldierFromWarFieldA, soldierFromWarFieldB, baseAIndex, baseBIndex)

    details: TurnDetails = {
        "soldierPolicyA": soldierPolicyA,
        "soldierPolicyB": soldierPolicyB,
        "posListA": posListA,
        "posListB": posListB,
        "warField": warField,
        "soldiers": soldiers,
        "mapSize": mapSize,
        "warLocation": warLocation,
        "warLostA": warLostA,
        "warLostB": warLostB,
        "logisticsA": logisticsA,
        "logisticsB": logisticsB,
        "numOfWarTurn": len(warLocation),
        "forced": False,
    }

    newState: BoardState = dict(current_state)
    newState["shapes"] = transformWarFieldToShapes(warField, mapSize)
    newState["numbers"] = transformSoldiersToNumbers(soldiers, warField, mapSize)
    newState["warLocation"] = transformWarLocationToCoordinate(warLocation, mapSize)
    newState["mapSize"] = mapSize
    return newState, details


def calculate_turn(
    player1_selected: List[Coordinate],
    player2_selected: List[Coordinate],
    turn_number: int,
    current_state: BoardState,
) -> BoardState:
    newState, _ = play_turn(player1_selected, player2_selected, turn_number, current_state)
    return newState


def complete_game_to_turn_20(
    state: BoardState,
    start_turn: int,
    last_pos_list_a: List[int],
    last_pos_list_b: List[int],
) -> List[Tuple[BoardState, TurnDetails]]:
    steps: List[Tuple[BoardState, TurnDetails]] = []
    current_state = state
    for _turn in range(start_turn, 21):
        warFieldBefore = transformShapesToWarField(current_state["shapes"])
        if warFieldBefore.count(1) > 0 and warFieldBefore.count(2) > 0:
            raise ValueError("game has not ended; cannot complete remaining rounds")

        soldiersBefore = transformNumbersToSoldiers(current_state["numbers"])
        if warFieldBefore.count(1) == 0:
            soldierPolicyA = [0 for _ in range(len(soldiersBefore))]
            soldierPolicyB = soldiersBefore
        else:
            soldierPolicyB = [0 for _ in range(len(soldiersBefore))]
            soldierPolicyA = soldiersBefore

        mapSize = list(current_state["mapSize"])
        soldiers, warField, warLocation, warLostA, warLostB, logisticsA, logisticsB = forwardNextStep(
            soldierPolicyA, soldierPolicyB, warFieldBefore, mapSize,
            current_state["reinforcementA"], current_state["reinforcementB"],
            current_state["baseAIndex"], current_state["baseBIndex"])

        details: TurnDetails = {
            "soldierPolicyA": soldierPolicyA,
            "soldierPolicyB": soldierPolicyB,
            "posListA": list(last_pos_list_a),
            "posListB": list(last_pos_list_b),
            "warField": warField,
            "soldiers": soldiers,
            "mapSize": mapSize,
            "warLocation": warLocation,
            "warLostA": warLostA,
            "warLostB": warLostB,
            "logisticsA": logisticsA,
            "logisticsB": logisticsB,
            "numOfWarTurn": len(warLocation),
            "forced": True,
        }

        newState: BoardState = dict(current_state)
        newState["shapes"] = transformWarFieldToShapes(warField, mapSize)
        newState["numbers"] = transformSoldiersToNumbers(soldiers, warField, mapSize)
        newState["warLocation"] = transformWarLocationToCoordinate(warLocation, mapSize)
        newState["mapSize"] = mapSize
        steps.append((newState, details))
        current_state = newState

    return steps


def determine_winner(shapes) -> Optional[int]:
    warField = transformShapesToWarField(shapes)
    countA = warField.count(1)
    countB = warField.count(2)
    if countA == 0 and countB > 0:
        return 2
    if countB == 0 and countA > 0:
        return 1
    return None


def condition_flags(colors: Matrix) -> int:
    for r in range(len(colors)):
        for c in range(len(colors[r])):
            if c + 1 < len(colors[r]) and colors[r][c] != colors[r][c + 1]:
                return 1
            if r + 1 < len(colors) and colors[r][c] != colors[r + 1][c]:
                return 1
    return 0


def get_flashing_cells(
    player1_selected: List[Coordinate],
    player2_selected: List[Coordinate],
    turn_number: int,
    state_after_turn: BoardState,
) -> List[Coordinate]:
    """TODO: return cells that should flash for one second after a turn."""
    return state_after_turn["warLocation"]
    # return []


def get_player_view(
    player_number: int,
    game_number: int,
    turn_number: int,
    shared_state: BoardState,
    condition_id: str,
) -> dict:
    """返回玩家实际看到的颜色矩阵，不向浏览器发送内部状态元数据。"""
    colors = get_condition_colors(condition_id, player_number)
    return {
        "colors": colors,
        "shapes": shared_state["shapes"],
        "numbers": shared_state["numbers"],
        "warLocation": shared_state["warLocation"],
    }
