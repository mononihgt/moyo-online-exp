import random
import sys
import unittest
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.game_logic import (
    FORMAL_TRIALS,
    INITIAL_SOLDIERS_A,
    INITIAL_SOLDIERS_B,
    MAP_CONDITION_IDS,
    MAP_CONDITIONS,
    PRACTICE_TRIALS,
    TOTAL_TRIALS,
    build_trial_plan,
    calculate_turn,
    checkEndGame,
    complete_game_to_turn_20,
    condition_flags,
    create_initial_state,
    determine_winner,
    get_condition_colors,
    get_condition_metadata,
    get_player_view,
    play_turn,
)

BLUE = 1
RED = 2
METADATA_KEYS = {
    'conditionId', 'showBound', 'isReferenceCondition', 'isBoundary', 'isConsistent', 'dev', 'legacyBoards',
}
PLAN_KEYS = {
    'trial', 'game', 'isPractice', 'formalTrial', 'sourceIndex', 'soldierFromBaseA', 'soldierFromBaseB',
}
VIEW_KEYS = {'colors', 'shapes', 'numbers', 'warLocation'}
STATE_METADATA_KEYS = (
    'gameNumber', 'trial', 'isPractice', 'sourceIndex', 'conditionId',
    'reinforcementA', 'reinforcementB', 'baseAIndex', 'baseBIndex',
)

LEFT_BLUE = [[BLUE, BLUE, BLUE, RED, RED, RED] for _ in range(6)]
LEFT_RED = [[RED, RED, RED, BLUE, BLUE, BLUE] for _ in range(6)]
ALL_BLUE = [[BLUE for _ in range(6)] for _ in range(6)]
ALL_RED = [[RED for _ in range(6)] for _ in range(6)]
TOP_RED = [[RED for _ in range(6)] for _ in range(3)] + [[BLUE for _ in range(6)] for _ in range(3)]
TOP_BLUE = [[BLUE for _ in range(6)] for _ in range(3)] + [[RED for _ in range(6)] for _ in range(3)]

EXPECTED_LAYOUTS = {
    'ref0': (LEFT_BLUE, LEFT_BLUE),
    'ref1': (LEFT_RED, LEFT_RED),
    'ref2': (ALL_BLUE, ALL_BLUE),
    'ref3': (ALL_RED, ALL_RED),
    'ref4': (TOP_RED, TOP_RED),
    'ref5': (TOP_BLUE, TOP_BLUE),
    'asym': (LEFT_BLUE, ALL_RED),
}

EXPECTED_METADATA = {
    'ref0': {
        'conditionId': 'ref0', 'showBound': 0, 'isReferenceCondition': True,
        'isBoundary': 1, 'isConsistent': 0, 'dev': 0, 'legacyBoards': 3,
    },
    'ref1': {
        'conditionId': 'ref1', 'showBound': 1, 'isReferenceCondition': True,
        'isBoundary': 1, 'isConsistent': 1, 'dev': 0, 'legacyBoards': None,
    },
    'ref2': {
        'conditionId': 'ref2', 'showBound': 2, 'isReferenceCondition': True,
        'isBoundary': 0, 'isConsistent': 2, 'dev': 0, 'legacyBoards': 1,
    },
    'ref3': {
        'conditionId': 'ref3', 'showBound': 3, 'isReferenceCondition': True,
        'isBoundary': 0, 'isConsistent': 3, 'dev': 0, 'legacyBoards': 2,
    },
    'ref4': {
        'conditionId': 'ref4', 'showBound': 4, 'isReferenceCondition': True,
        'isBoundary': 1, 'isConsistent': 4, 'dev': 0, 'legacyBoards': None,
    },
    'ref5': {
        'conditionId': 'ref5', 'showBound': 5, 'isReferenceCondition': True,
        'isBoundary': 1, 'isConsistent': 5, 'dev': 0, 'legacyBoards': None,
    },
    'asym': {
        'conditionId': 'asym', 'showBound': None, 'isReferenceCondition': False,
        'isBoundary': 2, 'isConsistent': 6, 'dev': 0, 'legacyBoards': 4,
    },
}


def make_state(condition_id, seed=2026, trial=0):
    plan = build_trial_plan(seed)
    return create_initial_state(6, 6, plan[trial], condition_id)


class ConditionTests(unittest.TestCase):
    def test_condition_ids_and_metadata(self):
        self.assertEqual(TOTAL_TRIALS, 7)
        self.assertEqual(PRACTICE_TRIALS, 1)
        self.assertEqual(FORMAL_TRIALS, 6)
        self.assertEqual(MAP_CONDITION_IDS, ('ref0', 'ref1', 'ref2', 'ref3', 'ref4', 'ref5', 'asym'))
        self.assertEqual(set(MAP_CONDITIONS), set(MAP_CONDITION_IDS))
        for condition_id in MAP_CONDITION_IDS:
            with self.subTest(condition_id=condition_id):
                metadata = get_condition_metadata(condition_id)
                self.assertEqual(set(metadata), METADATA_KEYS)
                self.assertEqual(metadata, EXPECTED_METADATA[condition_id])
                self.assertEqual(metadata['conditionId'], condition_id)
                self.assertEqual(metadata['isReferenceCondition'], condition_id != 'asym')

    def test_condition_layouts(self):
        for condition_id, (colors1, colors2) in EXPECTED_LAYOUTS.items():
            with self.subTest(condition_id=condition_id):
                actual1 = get_condition_colors(condition_id, 1)
                actual2 = get_condition_colors(condition_id, 2)
                self.assertEqual(actual1, colors1)
                self.assertEqual(actual2, colors2)
                for colors in (actual1, actual2):
                    self.assertEqual(len(colors), 6)
                    self.assertTrue(all(len(row) == 6 for row in colors))
                    self.assertTrue({value for row in colors for value in row} <= {BLUE, RED})

    def test_condition_colors_are_fresh_matrices(self):
        first = get_condition_colors('ref0', 1)
        second = get_condition_colors('ref0', 1)
        self.assertIsNot(first, second)
        self.assertIsNot(first[0], second[0])
        self.assertIsNot(first[0], first[1])
        first[0][0] = 99
        first[1][1] = 99
        self.assertEqual(get_condition_colors('ref0', 1), LEFT_BLUE)

        asym1 = get_condition_colors('asym', 1)
        asym2 = get_condition_colors('asym', 2)
        self.assertIsNot(asym1, asym2)
        asym1[0][0] = 99
        self.assertEqual(get_condition_colors('asym', 1), LEFT_BLUE)
        self.assertEqual(get_condition_colors('asym', 2), ALL_RED)

    def test_asym_is_independent_level(self):
        metadata = get_condition_metadata('asym')
        self.assertIsNone(metadata['showBound'])
        self.assertFalse(metadata['isReferenceCondition'])
        self.assertEqual(metadata['isBoundary'], 2)
        self.assertEqual(metadata['isConsistent'], 6)
        self.assertEqual(metadata['dev'], 0)
        self.assertEqual(metadata['legacyBoards'], 4)
        self.assertNotIn(metadata['isBoundary'], (0, 1))
        self.assertEqual(get_condition_colors('asym', 1), get_condition_colors('ref0', 1))
        self.assertEqual(get_condition_colors('asym', 2), ALL_RED)
        self.assertNotEqual(get_condition_colors('asym', 2), get_condition_colors('ref0', 2))
        for condition_id in MAP_CONDITION_IDS[:-1]:
            reference = get_condition_metadata(condition_id)
            self.assertTrue(reference['isReferenceCondition'])
            self.assertNotEqual(reference['isConsistent'], 6)
            self.assertNotEqual(reference['isBoundary'], 2)
            self.assertIn(reference['showBound'], (0, 1, 2, 3, 4, 5))

    def test_unknown_condition_raises(self):
        with self.assertRaises(ValueError):
            get_condition_metadata('ref6')
        with self.assertRaises(ValueError):
            get_condition_colors('unknown', 1)
        with self.assertRaises(ValueError):
            create_initial_state(6, 6, build_trial_plan(0)[0], 'asymmetric')
        state = make_state('ref0')
        with self.assertRaises(ValueError):
            get_player_view(1, 1, 0, state, 'ref9')
        with self.assertRaises(ValueError):
            get_condition_colors('ref0', 0)
        with self.assertRaises(ValueError):
            get_condition_colors('ref0', 3)


class TrialPlanTests(unittest.TestCase):
    def test_trial_plan_structure(self):
        plan = build_trial_plan(2026)
        self.assertEqual(len(plan), TOTAL_TRIALS)
        self.assertEqual([entry['trial'] for entry in plan], list(range(TOTAL_TRIALS)))
        self.assertEqual([entry['game'] for entry in plan], list(range(1, TOTAL_TRIALS + 1)))
        for entry in plan:
            self.assertEqual(set(entry), PLAN_KEYS)
            self.assertEqual(entry['soldierFromBaseA'], INITIAL_SOLDIERS_A[entry['sourceIndex']])
            self.assertEqual(entry['soldierFromBaseB'], INITIAL_SOLDIERS_B[entry['sourceIndex']])

        practice = plan[0]
        self.assertEqual(practice['sourceIndex'], 0)
        self.assertTrue(practice['isPractice'])
        self.assertEqual(practice['formalTrial'], 0)
        self.assertEqual(practice['soldierFromBaseA'], 7)
        self.assertEqual(practice['soldierFromBaseB'], 7)

        formal = plan[1:]
        self.assertEqual([entry['isPractice'] for entry in formal], [False] * FORMAL_TRIALS)
        self.assertEqual([entry['formalTrial'] for entry in formal], list(range(1, FORMAL_TRIALS + 1)))
        self.assertEqual(sorted(entry['sourceIndex'] for entry in formal), list(range(1, TOTAL_TRIALS)))
        self.assertEqual(
            {(entry['soldierFromBaseA'], entry['soldierFromBaseB']) for entry in formal},
            {(8, 8), (7, 7), (8, 9), (7, 8), (9, 8), (8, 7)},
        )

    def test_trial_plan_reproducible_and_seeded(self):
        first = build_trial_plan(12345)
        second = build_trial_plan(12345)
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        first[0]['sourceIndex'] = 6
        first[1]['soldierFromBaseA'] = 99
        self.assertEqual(build_trial_plan(12345), second)

        orders = set()
        for seed in range(10):
            plan = build_trial_plan(seed)
            order = tuple(entry['sourceIndex'] for entry in plan[1:])
            self.assertEqual(sorted(order), list(range(1, TOTAL_TRIALS)))
            orders.add(order)
        self.assertGreater(len(orders), 1)


class InitialStateTests(unittest.TestCase):
    def test_initial_state_matches_plan(self):
        plan = build_trial_plan(42)
        for entry in plan:
            with self.subTest(trial=entry['trial']):
                state = create_initial_state(6, 6, entry, 'ref4')
                self.assertEqual(state['gameNumber'], entry['game'])
                self.assertEqual(state['trial'], entry['trial'])
                self.assertEqual(state['isPractice'], entry['isPractice'])
                self.assertEqual(state['sourceIndex'], entry['sourceIndex'])
                self.assertEqual(state['conditionId'], 'ref4')
                self.assertEqual(state['mapSize'], [6, 6])
                self.assertEqual(state['reinforcementA'], entry['soldierFromBaseA'])
                self.assertEqual(state['reinforcementB'], entry['soldierFromBaseB'])
                self.assertEqual(state['baseAIndex'], 7)
                self.assertEqual(state['baseBIndex'], 28)
                self.assertEqual(state['warLocation'], [])
                self.assertEqual(state['colors'], TOP_RED)

                flat_shapes = [value for row in state['shapes'] for value in row]
                self.assertEqual(flat_shapes.count(1), 1)
                self.assertEqual(flat_shapes.count(2), 1)
                self.assertEqual(flat_shapes.index(1), 7)
                self.assertEqual(flat_shapes.index(2), 28)
                self.assertEqual(state['shapes'][1][1], 1)
                self.assertEqual(state['shapes'][4][4], 2)

                flat_numbers = [value for row in state['numbers'] for value in row]
                self.assertEqual(flat_numbers[7], entry['soldierFromBaseA'])
                self.assertEqual(flat_numbers[28], entry['soldierFromBaseB'])
                self.assertEqual(flat_numbers.count(-1), 34)

    def test_initial_state_uses_condition_colors(self):
        plan = build_trial_plan(7)
        for condition_id in MAP_CONDITION_IDS:
            with self.subTest(condition_id=condition_id):
                state = create_initial_state(6, 6, plan[0], condition_id)
                self.assertEqual(state['colors'], get_condition_colors(condition_id, 1))
        asym_state = create_initial_state(6, 6, plan[0], 'asym')
        self.assertEqual(asym_state['colors'], LEFT_BLUE)

    def test_create_initial_state_validation(self):
        plan = build_trial_plan(0)
        with self.assertRaises(ValueError):
            create_initial_state(5, 6, plan[0], 'ref0')
        with self.assertRaises(ValueError):
            create_initial_state(6, 5, plan[0], 'ref0')
        with self.assertRaises(ValueError):
            create_initial_state(6, 6, None, 'ref0')

        missing = dict(plan[1])
        del missing['sourceIndex']
        with self.assertRaises(ValueError):
            create_initial_state(6, 6, missing, 'ref0')

        bad_source = dict(plan[1])
        bad_source['sourceIndex'] = 0
        with self.assertRaises(ValueError):
            create_initial_state(6, 6, bad_source, 'ref0')

        bad_soldiers = dict(plan[1])
        bad_soldiers['soldierFromBaseA'] = 99
        with self.assertRaises(ValueError):
            create_initial_state(6, 6, bad_soldiers, 'ref0')

        bad_practice = dict(plan[1])
        bad_practice['isPractice'] = True
        with self.assertRaises(ValueError):
            create_initial_state(6, 6, bad_practice, 'ref0')

        bad_game = dict(plan[1])
        bad_game['game'] = 99
        with self.assertRaises(ValueError):
            create_initial_state(6, 6, bad_game, 'ref0')

        bad_formal = dict(plan[1])
        bad_formal['formalTrial'] = 0
        with self.assertRaises(ValueError):
            create_initial_state(6, 6, bad_formal, 'ref0')


class TurnStateTests(unittest.TestCase):
    def test_metadata_preserved_through_turns(self):
        random_state = random.getstate()
        numpy_state = np.random.get_state()
        try:
            random.seed(11)
            np.random.seed(11)
            plan = build_trial_plan(2026)
            entry = plan[3]
            state = create_initial_state(6, 6, entry, 'asym')
            snapshot = {key: state[key] for key in STATE_METADATA_KEYS}

            new_state, details = play_turn([(1, 1)], [(4, 4)], 1, state)
            for key, value in snapshot.items():
                self.assertEqual(new_state[key], value)
            self.assertEqual(new_state['colors'], state['colors'])
            self.assertEqual(set(details), {
                'soldierPolicyA', 'soldierPolicyB', 'posListA', 'posListB', 'warField', 'soldiers',
                'mapSize', 'warLocation', 'warLostA', 'warLostB', 'logisticsA', 'logisticsB',
                'numOfWarTurn', 'forced',
            })
            self.assertEqual(len(details['soldierPolicyA']), 36)
            self.assertEqual(len(details['soldierPolicyB']), 36)
            self.assertEqual(len(details['soldiers']), 36)
            self.assertGreater(sum(details['soldierPolicyA']), 0)
            self.assertGreater(sum(details['soldierPolicyB']), 0)
            self.assertFalse(details['forced'])

            calculated = calculate_turn([(1, 1)], [(4, 4)], 2, new_state)
            for key, value in snapshot.items():
                self.assertEqual(calculated[key], value)

            ended = dict(new_state)
            ended['shapes'] = [[2 for _ in range(6)] for _ in range(6)]
            ended['numbers'] = [[-1 for _ in range(6)] for _ in range(6)]
            ended['numbers'][4][4] = 5
            ended['warLocation'] = []
            steps = complete_game_to_turn_20(ended, 13, [7], [28])
            self.assertEqual(len(steps), 8)
            for forced_state, forced_details in steps:
                for key, value in snapshot.items():
                    self.assertEqual(forced_state[key], value)
                self.assertEqual(forced_state['colors'], state['colors'])
                self.assertTrue(forced_details['forced'])
        finally:
            random.setstate(random_state)
            np.random.set_state(numpy_state)

    def test_empty_selection_raises(self):
        state = make_state('ref0')
        with self.assertRaises(ValueError):
            play_turn([], [(1, 1)], 1, state)
        with self.assertRaises(ValueError):
            play_turn([(1, 1)], [], 1, state)
        with self.assertRaises(ValueError):
            calculate_turn([], [], 1, state)


class PlayerViewTests(unittest.TestCase):
    def test_player_view_only_contains_board_fields(self):
        plan = build_trial_plan(3)
        for condition_id in MAP_CONDITION_IDS:
            with self.subTest(condition_id=condition_id):
                state = create_initial_state(6, 6, plan[0], condition_id)
                for player_number in (1, 2):
                    view = get_player_view(player_number, 1, 0, state, condition_id)
                    self.assertEqual(set(view), VIEW_KEYS)
                    self.assertEqual(view['colors'], get_condition_colors(condition_id, player_number))
                    self.assertEqual(view['shapes'], state['shapes'])
                    self.assertEqual(view['numbers'], state['numbers'])
                    self.assertEqual(view['warLocation'], state['warLocation'])
                view1 = get_player_view(1, 1, 0, state, condition_id)
                view2 = get_player_view(2, 1, 0, state, condition_id)
                self.assertIsNot(view1['colors'], view2['colors'])

    def test_player_view_colors_are_fresh(self):
        state = make_state('ref0')
        first = get_player_view(1, 1, 0, state, 'ref0')
        first['colors'][0][0] = 99
        second = get_player_view(1, 1, 0, state, 'ref0')
        self.assertEqual(second['colors'], LEFT_BLUE)

    def test_asym_views_differ_per_player(self):
        state = make_state('asym')
        self.assertEqual(get_player_view(1, 1, 0, state, 'asym')['colors'], LEFT_BLUE)
        self.assertEqual(get_player_view(2, 1, 0, state, 'asym')['colors'], ALL_RED)


class LegacyBehaviorTests(unittest.TestCase):
    def test_condition_flags_match_reference_boundary_fields(self):
        for condition_id in MAP_CONDITION_IDS[:-1]:
            with self.subTest(condition_id=condition_id):
                metadata = get_condition_metadata(condition_id)
                self.assertEqual(metadata['isBoundary'], condition_flags(get_condition_colors(condition_id, 1)))
        self.assertEqual(condition_flags(get_condition_colors('asym', 1)), 1)
        self.assertEqual(condition_flags(get_condition_colors('asym', 2)), 0)
        self.assertEqual(get_condition_metadata('asym')['isBoundary'], 2)

    def test_winner_and_end_game_helpers(self):
        self.assertEqual(determine_winner(ALL_BLUE), 1)
        self.assertEqual(determine_winner(ALL_RED), 2)
        self.assertIsNone(determine_winner([[0 for _ in range(6)] for _ in range(6)]))
        state = make_state('ref2')
        self.assertFalse(checkEndGame(state['shapes']))
        state['shapes'] = [[2 for _ in range(6)] for _ in range(6)]
        self.assertTrue(checkEndGame(state['shapes']))
        self.assertEqual(determine_winner(state['shapes']), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
