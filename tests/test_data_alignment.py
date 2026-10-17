import ast
import csv
import io
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
from app.main import (
    CSV_COLUMNS,
    EXTRA_COLUMNS,
    LIST_FIELDS,
    REFERENCE_COLUMNS,
    GameRoom,
    build_condition_fields,
    serialize_row,
    write_csv,
)

EXPECTED_REFERENCE_COLUMNS = [
    'soldierPolicyA', 'soldierPolicyB', 'posListA', 'posListB', 'warField', 'soldiers', 'mapSize',
    'isBoundary', 'soldierFromBaseA', 'soldierFromBaseB', 'mapColor', 'dev', 'isConsistent',
    'numOfWar', 'warLostA', 'warLostB', 'logisticsA', 'logisticsB', 'warLocation',
]
NEW_ROW_COLUMNS = [
    'trial', 'isPractice', 'formalTrial', 'sourceIndex', 'conditionId', 'showBound',
    'isReferenceCondition',
]
ALL_CELLS = [(r, c) for r in range(6) for c in range(6)]
PLAN_SEED = 20240517
TRIAL_PLAN = build_trial_plan(PLAN_SEED)
BLUE, RED = 1, 2


def matrix(pattern):
    return [pattern[:] for _ in range(6)]


LEFT_BLUE = matrix([BLUE, BLUE, BLUE, RED, RED, RED])
LEFT_RED = matrix([RED, RED, RED, BLUE, BLUE, BLUE])
ALL_BLUE = matrix([BLUE] * 6)
ALL_RED = matrix([RED] * 6)
TOP_RED = ALL_RED[:3] + ALL_BLUE[:3]
TOP_BLUE = ALL_BLUE[:3] + ALL_RED[:3]

CONDITION_EXPECTATIONS = {
    'ref0': {
        'showBound': 0, 'isReferenceCondition': True, 'isBoundary': 1, 'isConsistent': 0,
        'legacyBoards': 3, 'colors1': LEFT_BLUE, 'colors2': LEFT_BLUE,
    },
    'ref1': {
        'showBound': 1, 'isReferenceCondition': True, 'isBoundary': 1, 'isConsistent': 1,
        'legacyBoards': None, 'colors1': LEFT_RED, 'colors2': LEFT_RED,
    },
    'ref2': {
        'showBound': 2, 'isReferenceCondition': True, 'isBoundary': 0, 'isConsistent': 2,
        'legacyBoards': 1, 'colors1': ALL_BLUE, 'colors2': ALL_BLUE,
    },
    'ref3': {
        'showBound': 3, 'isReferenceCondition': True, 'isBoundary': 0, 'isConsistent': 3,
        'legacyBoards': 2, 'colors1': ALL_RED, 'colors2': ALL_RED,
    },
    'ref4': {
        'showBound': 4, 'isReferenceCondition': True, 'isBoundary': 1, 'isConsistent': 4,
        'legacyBoards': None, 'colors1': TOP_RED, 'colors2': TOP_RED,
    },
    'ref5': {
        'showBound': 5, 'isReferenceCondition': True, 'isBoundary': 1, 'isConsistent': 5,
        'legacyBoards': None, 'colors1': TOP_BLUE, 'colors2': TOP_BLUE,
    },
    'asym': {
        'showBound': None, 'isReferenceCondition': False, 'isBoundary': 2, 'isConsistent': 6,
        'legacyBoards': 4, 'colors1': LEFT_BLUE, 'colors2': ALL_RED,
    },
}


def copy_matrix(source):
    return [row[:] for row in source]


def make_room(condition_id='ref3', seed=PLAN_SEED):
    room = GameRoom.__new__(GameRoom)
    room.room_id = 'unit-room'
    room.rows = 6
    room.cols = 6
    room.condition_id = condition_id
    room.condition_fields = build_condition_fields(condition_id)
    room.map_color_1 = copy_matrix(room.condition_fields['mapColor1'])
    room.map_color_2 = copy_matrix(room.condition_fields['mapColor2'])
    room.trial_plan_seed = seed
    room.trial_plan = build_trial_plan(seed)
    room.game_number = 1
    room.num_of_war = 0
    room.selection_sources = {}
    room.record = {'turns': [], 'games': []}
    room.state = create_initial_state(6, 6, room.trial_plan[0], condition_id)
    return room


class DataAlignmentTests(unittest.TestCase):
    def test_trial_plan_shape_and_seed_reproducibility(self):
        self.assertEqual(TOTAL_TRIALS, 7)
        self.assertEqual(PRACTICE_TRIALS, 1)
        self.assertEqual(FORMAL_TRIALS, 6)
        plan = build_trial_plan(PLAN_SEED)
        self.assertEqual(len(plan), TOTAL_TRIALS)
        self.assertEqual([entry['trial'] for entry in plan], list(range(TOTAL_TRIALS)))
        self.assertEqual([entry['game'] for entry in plan], list(range(1, TOTAL_TRIALS + 1)))

        practice = plan[0]
        self.assertTrue(practice['isPractice'])
        self.assertEqual(practice['formalTrial'], 0)
        self.assertEqual(practice['sourceIndex'], 0)
        self.assertEqual(practice['soldierFromBaseA'], 7)
        self.assertEqual(practice['soldierFromBaseB'], 7)

        formal = plan[1:]
        self.assertEqual([entry['formalTrial'] for entry in formal], list(range(1, FORMAL_TRIALS + 1)))
        self.assertEqual([entry['isPractice'] for entry in formal], [False] * FORMAL_TRIALS)
        self.assertEqual(sorted(entry['sourceIndex'] for entry in formal), list(range(1, TOTAL_TRIALS)))
        for entry in plan:
            source = entry['sourceIndex']
            self.assertEqual(entry['soldierFromBaseA'], INITIAL_SOLDIERS_A[source])
            self.assertEqual(entry['soldierFromBaseB'], INITIAL_SOLDIERS_B[source])

        self.assertEqual(build_trial_plan(PLAN_SEED), plan)
        orders = {
            tuple(entry['sourceIndex'] for entry in build_trial_plan(seed))
            for seed in range(6)
        }
        self.assertGreater(len(orders), 1)

    def test_condition_layouts_and_metadata(self):
        self.assertEqual(MAP_CONDITION_IDS, ('ref0', 'ref1', 'ref2', 'ref3', 'ref4', 'ref5', 'asym'))
        self.assertEqual(set(MAP_CONDITION_IDS), set(MAP_CONDITIONS))
        self.assertEqual(set(CONDITION_EXPECTATIONS), set(MAP_CONDITIONS))
        for condition_id, expected in CONDITION_EXPECTATIONS.items():
            metadata = get_condition_metadata(condition_id)
            self.assertEqual(metadata['conditionId'], condition_id)
            for field in ('showBound', 'isReferenceCondition', 'isBoundary', 'isConsistent', 'legacyBoards'):
                self.assertEqual(metadata[field], expected[field], f'{condition_id} {field}')
            self.assertEqual(metadata['dev'], 0)

            colors1 = get_condition_colors(condition_id, 1)
            colors2 = get_condition_colors(condition_id, 2)
            self.assertEqual(colors1, expected['colors1'], condition_id)
            self.assertEqual(colors2, expected['colors2'], condition_id)
            self.assertEqual(len(colors1), 6)
            self.assertTrue(all(len(row) == 6 for row in colors1))
            self.assertTrue(all(value in (BLUE, RED) for row in colors1 for value in row))

            fields = build_condition_fields(condition_id)
            self.assertEqual(fields['conditionId'], condition_id)
            self.assertEqual(fields['mapColor'], colors1)
            self.assertEqual(fields['mapColor1'], colors1)
            self.assertEqual(fields['mapColor2'], colors2)
            self.assertEqual(fields['isBoundary1'], condition_flags(colors1))
            self.assertEqual(fields['isBoundary2'], condition_flags(colors2))

    def test_asym_is_an_independent_level(self):
        metadata = get_condition_metadata('asym')
        self.assertIsNone(metadata['showBound'])
        self.assertFalse(metadata['isReferenceCondition'])
        self.assertEqual(metadata['isBoundary'], 2)
        self.assertEqual(metadata['isConsistent'], 6)
        self.assertEqual(metadata['legacyBoards'], 4)
        fields = build_condition_fields('asym')
        self.assertEqual(fields['mapColor1'], LEFT_BLUE)
        self.assertEqual(fields['mapColor2'], ALL_RED)
        self.assertEqual(fields['isBoundary1'], 1)
        self.assertEqual(fields['isBoundary2'], 0)
        self.assertNotEqual(fields['isBoundary'], fields['isBoundary1'])
        for condition_id in ('ref0', 'ref1', 'ref2', 'ref3', 'ref4', 'ref5'):
            self.assertTrue(get_condition_metadata(condition_id)['isReferenceCondition'])

    def test_initial_state_uses_trial_plan(self):
        for entry in TRIAL_PLAN:
            state = create_initial_state(6, 6, entry, 'ref3')
            self.assertEqual(state['numbers'][1][1], entry['soldierFromBaseA'])
            self.assertEqual(state['numbers'][4][4], entry['soldierFromBaseB'])
            self.assertEqual(state['reinforcementA'], entry['soldierFromBaseA'])
            self.assertEqual(state['reinforcementB'], entry['soldierFromBaseB'])
            self.assertEqual(state['trial'], entry['trial'])
            self.assertEqual(state['isPractice'], entry['isPractice'])
            self.assertEqual(state['sourceIndex'], entry['sourceIndex'])
            self.assertEqual(state['conditionId'], 'ref3')
            self.assertEqual(state['gameNumber'], entry['game'])
            self.assertEqual(state['mapSize'], [6, 6])
            self.assertEqual(state['baseAIndex'], 7)
            self.assertEqual(state['baseBIndex'], 28)
            self.assertEqual(state['colors'], ALL_RED)

    def test_invalid_initial_state_arguments_raise(self):
        entry = TRIAL_PLAN[0]
        with self.assertRaises(ValueError):
            create_initial_state(5, 6, entry, 'ref0')
        with self.assertRaises(ValueError):
            create_initial_state(6, 5, entry, 'ref0')
        with self.assertRaises(ValueError):
            create_initial_state(6, 6, dict(entry, trial=-1, game=0), 'ref0')
        with self.assertRaises(ValueError):
            create_initial_state(6, 6, dict(entry, sourceIndex=3), 'ref0')
        with self.assertRaises(ValueError):
            create_initial_state(6, 6, entry, 'unknown')

    def test_empty_selection_raises(self):
        state = create_initial_state(6, 6, TRIAL_PLAN[0], 'ref0')
        with self.assertRaisesRegex(ValueError, 'both players must select at least one cell'):
            play_turn([], [(1, 1)], 1, state)
        with self.assertRaisesRegex(ValueError, 'both players must select at least one cell'):
            play_turn([(1, 1)], [], 1, state)
        with self.assertRaisesRegex(ValueError, 'both players must select at least one cell'):
            calculate_turn([], [], 1, state)

    def test_determine_winner(self):
        only_b = [[2 for _ in range(6)] for _ in range(6)]
        only_a = [[1 for _ in range(6)] for _ in range(6)]
        all_empty = [[0 for _ in range(6)] for _ in range(6)]
        mixed = create_initial_state(6, 6, TRIAL_PLAN[0], 'ref0')['shapes']
        self.assertEqual(determine_winner(only_b), 2)
        self.assertEqual(determine_winner(only_a), 1)
        self.assertIsNone(determine_winner(mixed))
        self.assertIsNone(determine_winner(all_empty))

    def test_condition_flags(self):
        self.assertEqual(condition_flags(ALL_BLUE), 0)
        self.assertEqual(condition_flags(ALL_RED), 0)
        self.assertEqual(condition_flags(LEFT_BLUE), 1)
        self.assertEqual(condition_flags(TOP_RED), 1)
        state = create_initial_state(6, 6, TRIAL_PLAN[0], 'asym')
        view1 = get_player_view(1, 1, 0, state, 'asym')
        view2 = get_player_view(2, 1, 0, state, 'asym')
        self.assertEqual(set(view1), {'colors', 'shapes', 'numbers', 'warLocation'})
        self.assertEqual(condition_flags(view1['colors']), 1)
        self.assertEqual(condition_flags(view2['colors']), 0)
        self.assertEqual(view1['colors'], LEFT_BLUE)
        self.assertEqual(view2['colors'], ALL_RED)
        for view in (view1, view2):
            self.assertEqual(view['shapes'], state['shapes'])
            self.assertEqual(view['numbers'], state['numbers'])
            self.assertEqual(view['warLocation'], state['warLocation'])

    def test_forced_completion_padding(self):
        state = create_initial_state(6, 6, TRIAL_PLAN[0], 'ref0')
        state['shapes'][1][1] = 2
        state['numbers'][1][1] = 0
        steps = complete_game_to_turn_20(state, 13, [7], [28])
        self.assertEqual(len(steps), 8)
        for forced_state, details in steps:
            self.assertTrue(details['forced'])
            self.assertEqual(details['posListA'], [7])
            self.assertEqual(details['posListB'], [28])
            self.assertEqual(details['soldierPolicyA'], [0 for _ in range(36)])
            self.assertGreater(sum(details['soldierPolicyB']), 0)
            self.assertEqual(details['mapSize'], [6, 6])
            field = [value for row in forced_state['shapes'] for value in row]
            self.assertEqual(field.count(1), 0)
            self.assertGreater(field.count(2), 0)
        last_state, _ = steps[-1]
        self.assertEqual(determine_winner(last_state['shapes']), 2)
        with self.assertRaises(ValueError):
            complete_game_to_turn_20(
                create_initial_state(6, 6, TRIAL_PLAN[0], 'ref0'), 13, [7], [28]
            )

    def test_reference_columns_and_serialization(self):
        self.assertEqual(REFERENCE_COLUMNS, EXPECTED_REFERENCE_COLUMNS)
        self.assertEqual(CSV_COLUMNS[:19], EXPECTED_REFERENCE_COLUMNS)
        self.assertEqual(CSV_COLUMNS[19:], EXTRA_COLUMNS)
        for column in NEW_ROW_COLUMNS:
            self.assertIn(column, CSV_COLUMNS)
            self.assertIn(column, EXTRA_COLUMNS)
        _, rows, _, _ = self.simulate_annihilation()
        header, data_rows = self.parse_csv(write_csv(rows))
        self.assertEqual(header, CSV_COLUMNS)
        self.assertEqual(header[:19], EXPECTED_REFERENCE_COLUMNS)
        self.assertEqual(len(data_rows), 21)
        for values in data_rows:
            mapping = dict(zip(header, values))
            for column in LIST_FIELDS:
                parsed = ast.literal_eval(mapping[column])
                self.assertIsInstance(parsed, list)
            self.assertEqual(mapping['soldierPolicyA'], str(ast.literal_eval(mapping['soldierPolicyA'])))
            self.assertEqual(mapping['mapSize'], '[6, 6]')
            self.assertEqual(mapping['trial'], '0')
            self.assertEqual(mapping['isPractice'], '1')
            self.assertEqual(mapping['formalTrial'], '0')
            self.assertEqual(mapping['sourceIndex'], '0')
            self.assertEqual(mapping['conditionId'], 'ref3')
            self.assertEqual(mapping['showBound'], '3')
            self.assertEqual(mapping['isReferenceCondition'], 'True')
            self.assertEqual(mapping['boards'], '2')
        serialized = serialize_row(rows[1])
        self.assertEqual(len(serialized), len(CSV_COLUMNS))
        self.assertEqual(serialized[0], str(rows[1]['soldierPolicyA']))
        self.assertEqual(serialized[18], str(rows[1]['warLocation']))

    def test_annihilation_game_has_21_rows_and_summary(self):
        room, rows, summary, end_turn = self.simulate_annihilation()
        self.assertLess(end_turn, 20)
        self.assertEqual(len(rows), 21)
        self.assertEqual([row['round'] for row in rows], list(range(21)))
        self.assertEqual(summary['endReason'], 'annihilation')
        self.assertIn(summary['winner'], (1, 2))
        self.assertEqual(summary['endTurn'], end_turn)
        self.assertEqual(summary['forcedRounds'], 20 - end_turn)
        self.assertEqual(summary['endTurn'] + summary['forcedRounds'], 20)
        self.assertEqual(summary['completedRounds'], 20)
        self.assertEqual(sum(row['forced'] for row in rows), 20 - end_turn)
        for row in rows:
            self.assertEqual(row['endReason'], 'annihilation')
            self.assertEqual(row['winner'], summary['winner'])
            self.assertEqual(len(row['soldierPolicyA']), 36)
            self.assertEqual(len(row['soldierPolicyB']), 36)
            self.assertEqual(len(row['warField']), 36)
        for row in rows[end_turn + 1:]:
            self.assertEqual(row['selectionSource1'], 'forced')
            self.assertEqual(row['selectionSource2'], 'forced')
            self.assertEqual(row['autoSelected1'], 0)
            self.assertEqual(row['autoSelected2'], 0)
        last_field = rows[-1]['warField']
        if summary['winner'] == 1:
            self.assertEqual(last_field.count(2), 0)
            self.assertGreater(last_field.count(1), 0)
        else:
            self.assertEqual(last_field.count(1), 0)
            self.assertGreater(last_field.count(2), 0)
        running = 0
        for row in rows:
            running += len(row['warLocation'])
            self.assertEqual(row['numOfWar'], running)
        last_real_positions = [row['posListA'] for row in rows if row['round'] == end_turn][0]
        for row in rows[end_turn + 1:]:
            self.assertEqual(row['posListA'], last_real_positions)
        initial = rows[0]
        self.assertEqual(initial['round'], 0)
        self.assertEqual(initial['turn'], 0)
        self.assertEqual(initial['soldierPolicyA'], [0] * 36)
        self.assertEqual(initial['soldierPolicyB'], [0] * 36)
        self.assertEqual(initial['posListA'], [])
        self.assertEqual(initial['numOfWar'], 0)
        self.assertEqual(initial['selectionSource1'], 'initial')
        self.assertEqual(initial['selectionSource2'], 'initial')
        self.assertEqual(initial['numbersBefore'], initial['numbersAfter'])
        self.assertEqual(sum(initial['soldiers']), 14)

    def test_trial_metadata_in_rows_and_summary(self):
        room, rows, summary, _ = self.simulate_annihilation(game=2)
        entry = TRIAL_PLAN[1]
        expected = {
            'trial': 1,
            'game': 2,
            'isPractice': 0,
            'formalTrial': entry['formalTrial'],
            'sourceIndex': entry['sourceIndex'],
            'conditionId': 'ref3',
            'showBound': 3,
            'isReferenceCondition': True,
            'isBoundary': 0,
            'isConsistent': 3,
            'dev': 0,
            'boards': 2,
            'soldierFromBaseA': entry['soldierFromBaseA'],
            'soldierFromBaseB': entry['soldierFromBaseB'],
        }
        for row in rows:
            for field, value in expected.items():
                self.assertEqual(row[field], value, field)
            self.assertEqual(len(row['mapColor1']), 6)
            self.assertEqual(len(row['mapColor2']), 6)
        for field, value in expected.items():
            self.assertEqual(summary[field], value, field)
        initial = rows[0]
        self.assertEqual(sum(initial['soldiers']), entry['soldierFromBaseA'] + entry['soldierFromBaseB'])
        self.assertEqual(summary['soldierFromWarFieldA'], entry['soldierFromBaseA'])
        self.assertEqual(summary['soldierFromWarFieldB'], entry['soldierFromBaseB'])
        for row in rows:
            self.assertEqual(row['trial'], 1)

    def test_practice_row_and_summary_metadata(self):
        room = make_room()
        row = room.build_initial_row(1)
        summary = room.build_game_summary(1, None, 'turn_limit', 20, 0)
        for values in (row, summary):
            self.assertEqual(values['trial'], 0)
            self.assertEqual(values['isPractice'], 1)
            self.assertEqual(values['formalTrial'], 0)
            self.assertEqual(values['sourceIndex'], 0)
            self.assertEqual(values['soldierFromBaseA'], 7)
            self.assertEqual(values['soldierFromBaseB'], 7)
        self.assertEqual(row['game'], 1)
        self.assertEqual(summary['game'], 1)

    def test_asym_row_and_csv_fields(self):
        room = make_room('asym')
        row = room.build_initial_row(1)
        self.assertIsNone(row['showBound'])
        self.assertFalse(row['isReferenceCondition'])
        self.assertEqual(row['isBoundary'], 2)
        self.assertEqual(row['isConsistent'], 6)
        self.assertEqual(row['dev'], 0)
        self.assertEqual(row['boards'], 4)
        self.assertEqual(row['conditionId'], 'asym')
        self.assertEqual(row['mapColor1'], LEFT_BLUE)
        self.assertEqual(row['mapColor2'], ALL_RED)
        self.assertEqual(row['isBoundary1'], 1)
        self.assertEqual(row['isBoundary2'], 0)
        header, data_rows = self.parse_csv(write_csv([row]))
        self.assertEqual(len(data_rows), 1)
        mapping = dict(zip(header, data_rows[0]))
        self.assertEqual(mapping['showBound'], '')
        self.assertEqual(mapping['isReferenceCondition'], 'False')
        self.assertEqual(mapping['isPractice'], '1')
        self.assertEqual(mapping['isBoundary'], '2')
        self.assertEqual(mapping['isConsistent'], '6')
        self.assertEqual(mapping['boards'], '4')
        self.assertEqual(mapping['conditionId'], 'asym')

    def test_turn_limit_game_has_21_rows_and_summary(self):
        room, rows, summary = self.simulate_turn_limit()
        self.assertEqual(len(rows), 21)
        self.assertEqual(summary['endReason'], 'turn_limit')
        self.assertIsNone(summary['winner'])
        self.assertEqual(summary['endTurn'], 20)
        self.assertEqual(summary['forcedRounds'], 0)
        self.assertEqual(summary['completedRounds'], 20)
        self.assertEqual(sum(row['forced'] for row in rows), 0)
        last_field = rows[-1]['warField']
        self.assertGreater(last_field.count(1), 0)
        self.assertGreater(last_field.count(2), 0)
        for row in rows:
            self.assertEqual(row['endReason'], 'turn_limit')
            self.assertIsNone(row['winner'])
        header, data_rows = self.parse_csv(write_csv(rows))
        self.assertEqual(len(data_rows), 21)
        winner_index = header.index('winner')
        for values in data_rows:
            self.assertEqual(values[winner_index], '')

    def simulate_turn_limit(self):
        room = make_room()
        state = create_initial_state(6, 6, room.trial_plan[0], room.condition_id)
        room.state = state
        room.num_of_war = 0
        rows = [room.build_initial_row(1)]
        for turn in range(1, 21):
            room.selection_sources = {1: 'manual', 2: 'manual'}
            numbers_before = copy_matrix(state['numbers'])
            state, details = play_turn([(1, 1)], [(4, 4)], turn, state)
            room.state = state
            room.num_of_war += details['numOfWarTurn']
            rows.append(room.build_turn_row(1, turn, details, numbers_before, state['numbers']))
            self.assertFalse(checkEndGame(state['shapes']))
        room.record = {'turns': rows, 'games': []}
        summary = room.build_game_summary(1, None, 'turn_limit', 20, 0)
        room.record['games'].append(summary)
        room.backfill_game(1, 'turn_limit', None)
        return room, rows, summary

    def simulate_annihilation(self, game=1):
        random_state = random.getstate()
        numpy_state = np.random.get_state()
        try:
            random.seed(17)
            np.random.seed(17)
            room = make_room()
            entry = room.trial_plan[game - 1]
            state = create_initial_state(6, 6, entry, room.condition_id)
            room.state = state
            room.game_number = game
            room.num_of_war = 0
            rows = [room.build_initial_row(game)]
            details = None
            end_turn = None
            for turn in range(1, 21):
                room.selection_sources = {1: 'manual', 2: 'manual'}
                numbers_before = copy_matrix(state['numbers'])
                state, details = play_turn(ALL_CELLS, [(1, 1)], turn, state)
                room.state = state
                room.num_of_war += details['numOfWarTurn']
                rows.append(room.build_turn_row(game, turn, details, numbers_before, state['numbers']))
                if checkEndGame(state['shapes']):
                    end_turn = turn
                    break
            self.assertIsNotNone(end_turn)
            forced_steps = complete_game_to_turn_20(
                state, end_turn + 1, details['posListA'], details['posListB']
            )
            forced_numbers_before = copy_matrix(state['numbers'])
            for forced_turn, (forced_state, forced_details) in enumerate(forced_steps, start=end_turn + 1):
                room.state = forced_state
                room.num_of_war += forced_details['numOfWarTurn']
                rows.append(room.build_turn_row(
                    game, forced_turn, forced_details, forced_numbers_before, forced_state['numbers']
                ))
                forced_numbers_before = copy_matrix(forced_state['numbers'])
            winner = determine_winner(room.state['shapes'])
            room.record = {'turns': rows, 'games': []}
            summary = room.build_game_summary(game, winner, 'annihilation', end_turn, len(forced_steps))
            room.record['games'].append(summary)
            room.backfill_game(game, 'annihilation', winner)
            return room, rows, summary, end_turn
        finally:
            random.setstate(random_state)
            np.random.set_state(numpy_state)

    def parse_csv(self, data):
        self.assertTrue(data.startswith(b'\xef\xbb\xbf'))
        text = data.decode('utf-8-sig')
        rows = list(csv.reader(io.StringIO(text)))
        return rows[0], rows[1:]


if __name__ == '__main__':
    unittest.main(verbosity=2)
