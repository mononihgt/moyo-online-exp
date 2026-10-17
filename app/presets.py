from .constants import CONDITION_SCHEMA_VERSION

ROWS = 6
COLS = 6
BASE_A_INDEX = 7
BASE_B_INDEX = 28
INITIAL_SOLDIERS_A = (7, 8, 7, 8, 7, 9, 8)
INITIAL_SOLDIERS_B = (7, 8, 7, 9, 8, 8, 7)
PRACTICE_TRIALS = 1
FORMAL_TRIALS = 6
TURN_COUNT = 20
TURN_SECONDS = 30
REST_SECONDS = 60

COLOR_BLUE = "#3498DB"
COLOR_RED = "#E74C3C"

BLUE = 1
RED = 2


def _rows(keys):
    return [list(row) for row in keys]


_LEFT_BLUE = _rows([[BLUE, BLUE, BLUE, RED, RED, RED] for _ in range(6)])
_LEFT_RED = _rows([[RED, RED, RED, BLUE, BLUE, BLUE] for _ in range(6)])
_ALL_BLUE = _rows([[BLUE for _ in range(6)] for _ in range(6)])
_ALL_RED = _rows([[RED for _ in range(6)] for _ in range(6)])
_TOP_RED = _rows([[RED for _ in range(6)] for _ in range(3)] + [[BLUE for _ in range(6)] for _ in range(3)])
_TOP_BLUE = _rows([[BLUE for _ in range(6)] for _ in range(3)] + [[RED for _ in range(6)] for _ in range(3)])

PRESET_DEFINITIONS = {
    "ref0": {
        "showBound": 0,
        "isReferenceCondition": True,
        "isBoundary": 1,
        "isConsistent": 0,
        "dev": 0,
        "legacyBoards": 3,
        "colorsByPlayer": {1: _LEFT_BLUE, 2: _LEFT_BLUE},
    },
    "ref1": {
        "showBound": 1,
        "isReferenceCondition": True,
        "isBoundary": 1,
        "isConsistent": 1,
        "dev": 0,
        "legacyBoards": None,
        "colorsByPlayer": {1: _LEFT_RED, 2: _LEFT_RED},
    },
    "ref2": {
        "showBound": 2,
        "isReferenceCondition": True,
        "isBoundary": 0,
        "isConsistent": 2,
        "dev": 0,
        "legacyBoards": 1,
        "colorsByPlayer": {1: _ALL_BLUE, 2: _ALL_BLUE},
    },
    "ref3": {
        "showBound": 3,
        "isReferenceCondition": True,
        "isBoundary": 0,
        "isConsistent": 3,
        "dev": 0,
        "legacyBoards": 2,
        "colorsByPlayer": {1: _ALL_RED, 2: _ALL_RED},
    },
    "ref4": {
        "showBound": 4,
        "isReferenceCondition": True,
        "isBoundary": 1,
        "isConsistent": 4,
        "dev": 0,
        "legacyBoards": None,
        "colorsByPlayer": {1: _TOP_RED, 2: _TOP_RED},
    },
    "ref5": {
        "showBound": 5,
        "isReferenceCondition": True,
        "isBoundary": 1,
        "isConsistent": 5,
        "dev": 0,
        "legacyBoards": None,
        "colorsByPlayer": {1: _TOP_BLUE, 2: _TOP_BLUE},
    },
    "asym": {
        "showBound": None,
        "isReferenceCondition": False,
        "isBoundary": 2,
        "isConsistent": 6,
        "dev": 0,
        "legacyBoards": 4,
        "colorsByPlayer": {1: _LEFT_BLUE, 2: _ALL_RED},
    },
}

PRESET_NAMES = tuple(PRESET_DEFINITIONS)


def _visual_layer(color_matrix):
    return [
        {
            "color": COLOR_BLUE if value == BLUE else COLOR_RED,
            "backgroundAssetId": None,
        }
        for row in color_matrix
        for value in row
    ]


def _cells():
    cells = []
    for index in range(ROWS * COLS):
        owner = 0
        if index == BASE_A_INDEX:
            owner = 1
        elif index == BASE_B_INDEX:
            owner = 2
        cells.append(
            {
                "row": index // COLS,
                "col": index % COLS,
                "initialOwner": owner,
                "initialSoldiers": 0,
                "reinforcementA": 0,
                "reinforcementB": 0,
            }
        )
    return cells


def _trial_params():
    params = []
    for source_index in range(PRACTICE_TRIALS + FORMAL_TRIALS):
        is_practice = source_index < PRACTICE_TRIALS
        params.append(
            {
                "sourceIndex": source_index,
                "isPractice": is_practice,
                "formalTrial": 0 if is_practice else source_index - PRACTICE_TRIALS + 1,
                "baseSoldiersA": INITIAL_SOLDIERS_A[source_index],
                "baseSoldiersB": INITIAL_SOLDIERS_B[source_index],
                "reinforcementOverrides": {
                    "player1": [{"cellIndex": index, "value": INITIAL_SOLDIERS_A[source_index]} for index in range(ROWS * COLS)],
                    "player2": [{"cellIndex": index, "value": INITIAL_SOLDIERS_B[source_index]} for index in range(ROWS * COLS)],
                },
            }
        )
    return params


def preset_payload(name: str) -> dict:
    definition = PRESET_DEFINITIONS[name]
    metadata = {
        "conditionId": name,
        "showBound": definition["showBound"],
        "isReferenceCondition": definition["isReferenceCondition"],
        "isBoundary": definition["isBoundary"],
        "isConsistent": definition["isConsistent"],
        "dev": definition["dev"],
        "legacyBoards": definition["legacyBoards"],
    }
    return {
        "name": name,
        "version": 1,
        "schema_version": CONDITION_SCHEMA_VERSION,
        "description": f"内置预设 {name}",
        "rows": ROWS,
        "cols": COLS,
        "cells": _cells(),
        "visuals": {
            "player1": _visual_layer(definition["colorsByPlayer"][1]),
            "player2": _visual_layer(definition["colorsByPlayer"][2]),
        },
        "base_a_index": BASE_A_INDEX,
        "base_b_index": BASE_B_INDEX,
        "trial_params": _trial_params(),
        "practice_trials": PRACTICE_TRIALS,
        "formal_trials": FORMAL_TRIALS,
        "turn_count": TURN_COUNT,
        "turn_seconds": TURN_SECONDS,
        "rest_seconds": REST_SECONDS,
        "randomize_formal": True,
        "metadata": metadata,
    }
