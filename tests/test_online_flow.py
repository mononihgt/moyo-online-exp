import ast
import csv
import io
import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path

from websockets.sync.client import connect

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.game_logic import (
    FORMAL_TRIALS,
    INITIAL_SOLDIERS_A,
    INITIAL_SOLDIERS_B,
    PRACTICE_TRIALS,
    TOTAL_TRIALS,
)
from app.main import CSV_COLUMNS, LIST_FIELDS, REFERENCE_COLUMNS

DATA_DIR = PROJECT_ROOT / 'data'
ARTIFACT_DIR = PROJECT_ROOT.parent / '.review'
ALL_CELLS = [[r, c] for r in range(6) for c in range(6)]
LEFT_BLUE = [[1, 1, 1, 2, 2, 2] for _ in range(6)]
ALL_RED = [[2, 2, 2, 2, 2, 2] for _ in range(6)]
NEW_COLUMNS = [
    'trial', 'isPractice', 'formalTrial', 'sourceIndex', 'conditionId', 'showBound',
    'isReferenceCondition',
]


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class UvicornServer:
    def __init__(self, condition='ref3'):
        self.condition = condition
        self.port = free_port()
        self.base_url = f'http://127.0.0.1:{self.port}'
        self.ws_url = f'ws://127.0.0.1:{self.port}/ws'
        env = dict(os.environ)
        env['PYTHONUNBUFFERED'] = '1'
        if condition is None:
            env.pop('MAP_CONDITION', None)
        else:
            env['MAP_CONDITION'] = condition
        self.process = subprocess.Popen(
            [
                sys.executable, '-m', 'uvicorn', 'app.main:app',
                '--host', '127.0.0.1', '--port', str(self.port), '--workers', '1',
                '--log-level', 'warning',
            ],
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def wait_ready(self):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                output = self.process.communicate(timeout=5)[0]
                raise RuntimeError(f'uvicorn exited before startup:\n{output}')
            try:
                with urllib.request.urlopen(self.base_url + '/healthz', timeout=1) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                time.sleep(0.1)
        self.stop()
        raise RuntimeError(f'uvicorn did not become ready:\n{self.process.communicate(timeout=5)[0]}')

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.communicate(timeout=10)


class OnlineFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = UvicornServer('ref3')
        cls.server.wait_ready()
        cls.created_rooms = set()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        for room_id in cls.created_rooms:
            path = DATA_DIR / f'{room_id}.json'
            if path.exists():
                path.unlink()

    def setUp(self):
        self.clients = []

    def tearDown(self):
        for client in reversed(self.clients):
            try:
                client.close()
            except Exception:
                pass

    def connect_player(self, server=None, hello=None):
        server = server or self.server
        client = connect(server.ws_url, open_timeout=10, close_timeout=5)
        self.clients.append(client)
        # 旧客户端字段全部发送错误值，验证服务端固定 6x6、7 trial 且忽略这些字段。
        hello = hello or {'rows': 5, 'cols': 5, 'totalGames': 1, 'boards': 1}
        client.send(json.dumps(hello))
        return client

    def match_pair(self, server=None):
        server = server or self.server
        player1 = self.connect_player(
            server, {'rows': 5, 'cols': 5, 'totalGames': 1, 'boards': 1}
        )
        self.receive_type(player1, {'waiting'}, timeout=10)
        player2 = self.connect_player(
            server, {'rows': 4, 'cols': 4, 'totalGames': 9, 'boards': 4}
        )
        matched2 = self.receive_type(player2, {'matched'}, timeout=10)
        matched1 = self.receive_type(player1, {'matched'}, timeout=10)
        self.assertEqual(matched1['roomId'], matched2['roomId'])
        room_id = matched1['roomId']
        self.created_rooms.add(room_id)
        return player1, player2, room_id

    def receive(self, client, timeout):
        return json.loads(client.recv(timeout=timeout))

    def receive_until(self, client, predicate, timeout, description):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(f'timed out waiting for {description}')
            try:
                message = self.receive(client, remaining)
            except TimeoutError:
                raise AssertionError(f'timed out waiting for {description}')
            if predicate(message):
                return message

    def receive_type(self, client, wanted_types, timeout=10):
        return self.receive_until(
            client, lambda message: message.get('type') in wanted_types, timeout,
            f'message types {wanted_types}',
        )

    def wait_state(self, client, phase, trial=None, turn=None, timeout=30):
        def matches(message):
            if message.get('type') != 'state' or message.get('phase') != phase:
                return False
            if trial is not None and message.get('trial') != trial:
                return False
            if turn is not None and message.get('turn') != turn:
                return False
            return True
        return self.receive_until(
            client, matches, timeout, f'state phase={phase} trial={trial} turn={turn}',
        )

    def wait_following_state(self, client, trial, timeout=30):
        def matches(message):
            if message.get('type') == 'game_over':
                return True
            return (
                message.get('type') == 'state'
                and message.get('phase') in ('turn', 'rest')
                and message.get('trial') == trial
            )
        return self.receive_until(client, matches, timeout, f'following state for trial {trial}')

    def submit(self, client, game, turn, cells):
        client.send(json.dumps({'type': 'submit', 'game': game, 'turn': turn, 'cells': cells}))

    def http_get(self, path, server=None):
        server = server or self.server
        with urllib.request.urlopen(server.base_url + path, timeout=10) as response:
            return response.read(), response.headers

    def http_error_status(self, path, server=None):
        server = server or self.server
        try:
            with urllib.request.urlopen(server.base_url + path, timeout=10):
                self.fail(f'expected HTTP error for {path}')
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            return status

    def parse_csv(self, data):
        self.assertTrue(data.startswith(b'\xef\xbb\xbf'))
        text = data.decode('utf-8-sig')
        rows = list(csv.reader(io.StringIO(text)))
        return rows[0], rows[1:]

    def play_trial(self, player1, player2, trial):
        game = trial + 1
        start1 = self.wait_state(player1, 'game_start', trial=trial, timeout=30)
        start2 = self.wait_state(player2, 'game_start', trial=trial, timeout=30)
        for start in (start1, start2):
            self.assertEqual(start['game'], game)
            self.assertEqual(start['totalGames'], TOTAL_TRIALS)
            self.assertEqual(start['totalTrials'], TOTAL_TRIALS)
            self.assertEqual(start['totalFormal'], FORMAL_TRIALS)
            self.assertEqual(start['isPractice'], trial == 0)
            self.assertEqual(start['formalTrial'], 0 if trial == 0 else trial)
            self.assertEqual(set(start['board']), {'colors', 'shapes', 'numbers', 'warLocation'})
            self.assertNotIn('boards', start)
            self.assertNotIn('conditionId', start)
        self.assertEqual(start2['player'], 2)
        self.assertEqual(start1['board']['colors'], ALL_RED)
        self.assertEqual(start2['board']['colors'], ALL_RED)

        current1 = self.wait_state(player1, 'turn', trial=trial, turn=1, timeout=30)
        current2 = self.wait_state(player2, 'turn', trial=trial, turn=1, timeout=30)
        real_turns = 0
        while True:
            turn = current1['turn']
            self.assertEqual(turn, real_turns + 1)
            self.assertEqual(current2['turn'], turn)
            self.assertEqual(current1['phase'], 'turn')
            self.assertEqual(current2['phase'], 'turn')
            self.submit(player1, game, turn, ALL_CELLS)
            self.submit(player2, game, turn, [[1, 1]])
            self.wait_state(player1, 'turn_result', trial=trial, turn=turn, timeout=30)
            self.wait_state(player2, 'turn_result', trial=trial, turn=turn, timeout=30)
            real_turns = turn

            following1 = self.wait_following_state(player1, trial)
            following2 = self.wait_following_state(player2, trial)
            if following1['type'] == 'game_over':
                self.assertEqual(following2['type'], 'game_over')
                return real_turns, following1
            self.assertEqual(following1['phase'], following2['phase'], 'players must see the same phase')
            if following1['phase'] == 'turn':
                self.assertEqual(following1['turn'], turn + 1)
                self.assertEqual(following2['turn'], turn + 1)
                current1 = following1
                current2 = following2
                continue

            self.assertEqual(following1['phase'], 'rest')
            self.assertLess(trial, TOTAL_TRIALS - 1)
            self.assertEqual(following2['phase'], 'rest')
            player1.send(json.dumps({'type': 'rest_ready'}))
            player2.send(json.dumps({'type': 'rest_ready'}))
            self.receive_type(player1, {'rest_complete'}, timeout=20)
            self.receive_type(player2, {'rest_complete'}, timeout=20)
            return real_turns, None

    def test_healthz_reports_condition(self):
        body = json.loads(self.http_get('/healthz')[0])
        self.assertEqual(body['status'], 'ok')
        self.assertEqual(body['mapCondition'], 'ref3')
        self.assertEqual(body['showBound'], 3)
        self.assertTrue(body['isReferenceCondition'])

    def test_default_condition_is_ref0(self):
        server = UvicornServer(None)
        server.wait_ready()
        try:
            body = json.loads(self.http_get('/healthz', server=server)[0])
            self.assertEqual(body['mapCondition'], 'ref0')
            self.assertEqual(body['showBound'], 0)
            self.assertTrue(body['isReferenceCondition'])
        finally:
            server.stop()

    def test_full_seven_trials_and_exports(self):
        player1, player2, room_id = self.match_pair()
        real_turns = []
        game_over = None
        for trial in range(TOTAL_TRIALS):
            turns, over = self.play_trial(player1, player2, trial)
            self.assertLess(turns, 20, f'trial {trial} should end by annihilation')
            real_turns.append(turns)
            if over is not None:
                game_over = over
                break
        self.assertIsNotNone(game_over)
        self.assertEqual(len(real_turns), TOTAL_TRIALS)
        self.assertEqual(game_over['roomId'], room_id)
        self.assertEqual(game_over['zipUrl'], f'/data/{room_id}.zip')
        self.assertEqual(game_over['csvUrl'], f'/data/{room_id}.csv')
        self.assertEqual(game_over['jsonUrl'], f'/data/{room_id}.json')

        record = json.loads(self.http_get(f'/data/{room_id}.json')[0])
        self.assertEqual(record['schemaVersion'], 3)
        self.assertEqual(record['roomId'], room_id)
        self.assertEqual(record['rows'], 6)
        self.assertEqual(record['cols'], 6)
        self.assertEqual(record['boards'], 2)
        self.assertIsNotNone(record['createdAt'])
        self.assertIsNotNone(record['completedAt'])
        self.assertEqual(len(record['players']), 2)

        experiment = record['experiment']
        self.assertEqual(experiment['totalTrials'], TOTAL_TRIALS)
        self.assertEqual(experiment['practiceTrials'], PRACTICE_TRIALS)
        self.assertEqual(experiment['formalTrials'], FORMAL_TRIALS)
        self.assertIsInstance(experiment['trialPlanSeed'], int)
        self.assertGreaterEqual(experiment['trialPlanSeed'], 0)
        self.assertLess(experiment['trialPlanSeed'], 2 ** 64)
        self.assertEqual(experiment['mapCondition'], 'ref3')
        trial_order = experiment['trialOrder']
        self.assertEqual(len(trial_order), TOTAL_TRIALS)
        self.assertEqual(trial_order[0], 0)
        self.assertEqual(sorted(trial_order[1:]), list(range(1, TOTAL_TRIALS)))

        condition = record['condition']
        self.assertEqual(condition['conditionId'], 'ref3')
        self.assertEqual(condition['showBound'], 3)
        self.assertTrue(condition['isReferenceCondition'])
        self.assertEqual(condition['isBoundary'], 0)
        self.assertEqual(condition['isConsistent'], 3)
        self.assertEqual(condition['dev'], 0)
        self.assertEqual(condition['legacyBoards'], 2)
        self.assertEqual(condition['mapColor'], ALL_RED)
        self.assertEqual(condition['mapColor1'], ALL_RED)
        self.assertEqual(condition['mapColor2'], ALL_RED)
        self.assertEqual(condition['isBoundary1'], 0)
        self.assertEqual(condition['isBoundary2'], 0)

        plan = record['trialPlan']
        self.assertEqual(len(plan), TOTAL_TRIALS)
        for trial, entry in enumerate(plan):
            self.assertEqual(entry['trial'], trial)
            self.assertEqual(entry['game'], trial + 1)
            self.assertEqual(entry['isPractice'], trial == 0)
            self.assertEqual(entry['formalTrial'], 0 if trial == 0 else trial)
            self.assertEqual(entry['sourceIndex'], trial_order[trial])
            self.assertEqual(entry['soldierFromBaseA'], INITIAL_SOLDIERS_A[entry['sourceIndex']])
            self.assertEqual(entry['soldierFromBaseB'], INITIAL_SOLDIERS_B[entry['sourceIndex']])
        self.assertEqual(plan[0]['sourceIndex'], 0)
        self.assertEqual(plan[0]['soldierFromBaseA'], 7)
        self.assertEqual(plan[0]['soldierFromBaseB'], 7)

        summaries = sorted(record['games'], key=lambda summary: summary['game'])
        self.assertEqual(len(summaries), TOTAL_TRIALS)
        for trial, summary in enumerate(summaries):
            entry = plan[trial]
            self.assertEqual(summary['game'], trial + 1)
            self.assertEqual(summary['trial'], trial)
            self.assertEqual(summary['isPractice'], 1 if trial == 0 else 0)
            self.assertEqual(summary['formalTrial'], entry['formalTrial'])
            self.assertEqual(summary['sourceIndex'], entry['sourceIndex'])
            self.assertEqual(summary['conditionId'], 'ref3')
            self.assertEqual(summary['showBound'], 3)
            self.assertTrue(summary['isReferenceCondition'])
            self.assertEqual(summary['isBoundary'], 0)
            self.assertEqual(summary['isConsistent'], 3)
            self.assertEqual(summary['dev'], 0)
            self.assertEqual(summary['boards'], 2)
            self.assertEqual(summary['endReason'], 'annihilation')
            self.assertIn(summary['winner'], (1, 2))
            self.assertEqual(summary['endTurn'], real_turns[trial])
            self.assertEqual(summary['forcedRounds'], 20 - real_turns[trial])
            self.assertEqual(summary['endTurn'] + summary['forcedRounds'], 20)
            self.assertEqual(summary['completedRounds'], 20)
            self.assertEqual(summary['soldierFromBaseA'], entry['soldierFromBaseA'])
            self.assertEqual(summary['soldierFromBaseB'], entry['soldierFromBaseB'])
            self.assertEqual(summary['soldierFromWarFieldA'], entry['soldierFromBaseA'])
            self.assertEqual(summary['soldierFromWarFieldB'], entry['soldierFromBaseB'])

        turns = record['turns']
        self.assertEqual(len(turns), TOTAL_TRIALS * 21)
        for trial, entry in enumerate(plan):
            trial_rows = [row for row in turns if row['trial'] == trial]
            self.assertEqual(len(trial_rows), 21, f'trial {trial} row count')
            self.assertEqual([row['round'] for row in trial_rows], list(range(21)))
            self.assertEqual({row['game'] for row in trial_rows}, {entry['game']})
            self.assertEqual(sum(row['forced'] for row in trial_rows), 20 - real_turns[trial])
            running_war = 0
            for row in trial_rows:
                self.assertEqual(row['roomId'], room_id)
                self.assertEqual(row['trial'], trial)
                self.assertEqual(row['isPractice'], 1 if trial == 0 else 0)
                self.assertEqual(row['formalTrial'], entry['formalTrial'])
                self.assertEqual(row['sourceIndex'], entry['sourceIndex'])
                self.assertEqual(row['soldierFromBaseA'], entry['soldierFromBaseA'])
                self.assertEqual(row['soldierFromBaseB'], entry['soldierFromBaseB'])
                self.assertEqual(row['conditionId'], 'ref3')
                self.assertEqual(row['showBound'], 3)
                self.assertTrue(row['isReferenceCondition'])
                self.assertEqual(row['isBoundary'], 0)
                self.assertEqual(row['isConsistent'], 3)
                self.assertEqual(row['dev'], 0)
                self.assertEqual(row['boards'], 2)
                self.assertEqual(row['endReason'], 'annihilation')
                self.assertEqual(row['winner'], summaries[trial]['winner'])
                self.assertEqual(row['mapSize'], [6, 6])
                self.assertEqual(len(row['soldierPolicyA']), 36)
                self.assertEqual(len(row['soldierPolicyB']), 36)
                self.assertEqual(len(row['warField']), 36)
                self.assertEqual(len(row['soldiers']), 36)
                self.assertEqual(len(row['mapColor1']), 6)
                self.assertEqual(len(row['mapColor2']), 6)
                self.assertEqual(row['mapColor1'], ALL_RED)
                running_war += len(row['warLocation'])
                self.assertEqual(row['numOfWar'], running_war)
            initial = trial_rows[0]
            self.assertEqual(initial['round'], 0)
            self.assertEqual(initial['soldierPolicyA'], [0] * 36)
            self.assertEqual(initial['posListA'], [])
            self.assertEqual(initial['numOfWar'], 0)
            self.assertEqual(initial['selectionSource1'], 'initial')
            self.assertEqual(initial['selectionSource2'], 'initial')
            self.assertEqual(
                sum(initial['soldiers']),
                entry['soldierFromBaseA'] + entry['soldierFromBaseB'],
            )

        csv_bytes, csv_headers = self.http_get(f'/data/{room_id}.csv')
        self.assertEqual(csv_headers.get_content_type(), 'text/csv')
        header, csv_rows = self.parse_csv(csv_bytes)
        self.assertEqual(header, CSV_COLUMNS)
        self.assertEqual(header[:19], REFERENCE_COLUMNS)
        for column in NEW_COLUMNS:
            self.assertIn(column, header)
        self.assertEqual(len(csv_rows), TOTAL_TRIALS * 21)
        trial_counts = {trial: 0 for trial in range(TOTAL_TRIALS)}
        for values in csv_rows:
            mapping = dict(zip(header, values))
            for column in LIST_FIELDS:
                parsed = ast.literal_eval(mapping[column])
                self.assertIsInstance(parsed, list)
            self.assertEqual(mapping['endReason'], 'annihilation')
            self.assertEqual(mapping['conditionId'], 'ref3')
            self.assertEqual(mapping['showBound'], '3')
            self.assertEqual(mapping['isReferenceCondition'], 'True')
            self.assertEqual(mapping['isBoundary'], '0')
            self.assertEqual(mapping['isConsistent'], '3')
            self.assertEqual(ast.literal_eval(mapping['mapSize']), [6, 6])
            trial_counts[int(mapping['trial'])] += 1
        self.assertEqual(trial_counts, {trial: 21 for trial in range(TOTAL_TRIALS)})

        zip_bytes, zip_headers = self.http_get(f'/data/{room_id}.zip')
        self.assertEqual(zip_headers.get_content_type(), 'application/zip')
        expected_names = [f'{room_id}-trial{trial}.csv' for trial in range(TOTAL_TRIALS)]
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            self.assertEqual(archive.namelist(), expected_names)
            trial_csvs = {trial: archive.read(name) for trial, name in enumerate(expected_names)}
        practice_header, practice_rows = self.parse_csv(trial_csvs[0])
        self.assertEqual(practice_header, CSV_COLUMNS)
        self.assertEqual(len(practice_rows), 21)
        practice_mapping = dict(zip(practice_header, practice_rows[0]))
        self.assertEqual(practice_mapping['trial'], '0')
        self.assertEqual(practice_mapping['isPractice'], '1')
        self.assertEqual(practice_mapping['formalTrial'], '0')
        self.assertEqual(practice_mapping['sourceIndex'], '0')
        practice_soldiers = ast.literal_eval(practice_mapping['soldiers'])
        self.assertEqual(practice_soldiers.count(0), 34)
        self.assertEqual(sum(practice_soldiers), 14)
        for trial, data in trial_csvs.items():
            trial_header, trial_rows = self.parse_csv(data)
            self.assertEqual(trial_header, CSV_COLUMNS)
            self.assertEqual(len(trial_rows), 21)
            self.assertEqual(trial_rows[0][trial_header.index('trial')], str(trial))
            expected_practice = '1' if trial == 0 else '0'
            self.assertEqual(
                trial_rows[0][trial_header.index('isPractice')], expected_practice
            )
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        (ARTIFACT_DIR / 'anova-trial1.csv').write_bytes(trial_csvs[1])

        listing_bytes, _ = self.http_get('/data')
        listing = json.loads(listing_bytes)
        entries = [entry for entry in listing['records'] if entry['roomId'] == room_id]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['zipUrl'], f'/data/{room_id}.zip')

    def test_asym_condition_instance(self):
        server = UvicornServer('asym')
        server.wait_ready()
        try:
            health = json.loads(self.http_get('/healthz', server=server)[0])
            self.assertEqual(health['mapCondition'], 'asym')
            self.assertIsNone(health['showBound'])
            self.assertFalse(health['isReferenceCondition'])
            player1, player2, room_id = self.match_pair(server)
            self.wait_state(player1, 'turn', trial=0, turn=1, timeout=20)
            self.wait_state(player2, 'turn', trial=0, turn=1, timeout=20)
            record = json.loads(self.http_get(f'/data/{room_id}.json', server=server)[0])
            condition = record['condition']
            self.assertEqual(record['schemaVersion'], 3)
            self.assertEqual(condition['conditionId'], 'asym')
            self.assertIsNone(condition['showBound'])
            self.assertFalse(condition['isReferenceCondition'])
            self.assertEqual(condition['isBoundary'], 2)
            self.assertEqual(condition['isConsistent'], 6)
            self.assertEqual(condition['dev'], 0)
            self.assertEqual(condition['legacyBoards'], 4)
            self.assertEqual(condition['mapColor'], LEFT_BLUE)
            self.assertEqual(condition['mapColor1'], LEFT_BLUE)
            self.assertEqual(condition['mapColor2'], ALL_RED)
            self.assertEqual(condition['isBoundary1'], 1)
            self.assertEqual(condition['isBoundary2'], 0)
            trial0 = [row for row in record['turns'] if row['trial'] == 0][0]
            self.assertEqual(trial0['conditionId'], 'asym')
            self.assertIsNone(trial0['showBound'])
            self.assertFalse(trial0['isReferenceCondition'])
            self.assertEqual(trial0['isBoundary'], 2)
            self.assertEqual(trial0['isConsistent'], 6)
            self.assertEqual(trial0['boards'], 4)
            csv_bytes, csv_headers = self.http_get(f'/data/{room_id}.csv', server=server)
            self.assertEqual(csv_headers.get_content_type(), 'text/csv')
            csv_header, csv_rows = self.parse_csv(csv_bytes)
            self.assertEqual(csv_header, CSV_COLUMNS)
            self.assertGreaterEqual(len(csv_rows), 1)
            asym_row = dict(zip(csv_header, csv_rows[0]))
            self.assertEqual(asym_row['conditionId'], 'asym')
            self.assertEqual(asym_row['showBound'], '')
            self.assertEqual(asym_row['isReferenceCondition'], 'False')
            self.assertEqual(asym_row['isBoundary'], '2')
            self.assertEqual(asym_row['isConsistent'], '6')
        finally:
            server.stop()
            path = DATA_DIR / f'{room_id}.json'
            if path.exists():
                path.unlink()

    def test_invalid_map_condition_aborts_startup(self):
        env = dict(os.environ)
        env['PYTHONUNBUFFERED'] = '1'
        env['MAP_CONDITION'] = 'invalid-condition'
        port = free_port()
        process = subprocess.Popen(
            [
                sys.executable, '-m', 'uvicorn', 'app.main:app',
                '--host', '127.0.0.1', '--port', str(port), '--workers', '1',
                '--log-level', 'warning',
            ],
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            output, _ = process.communicate(timeout=20)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('ValueError', output)
        self.assertIn('MAP_CONDITION', output)

    def test_empty_and_stale_submissions(self):
        player1, player2, room_id = self.match_pair()
        self.wait_state(player1, 'turn', trial=0, turn=1, timeout=20)
        self.wait_state(player2, 'turn', trial=0, turn=1, timeout=20)
        self.submit(player1, 1, 1, [])
        invalid = self.receive_type(player1, {'invalid_selection'}, timeout=5)
        self.assertEqual(invalid['message'], 'Select at least one cell')
        self.submit(player2, 1, 1, [[4, 4]])
        with self.assertRaises(TimeoutError):
            player1.recv(timeout=1.5)
        with self.assertRaises(TimeoutError):
            player2.recv(timeout=1.5)
        self.submit(player1, 1, 1, [[1, 1]])
        self.wait_state(player1, 'turn_result', trial=0, turn=1, timeout=20)
        self.wait_state(player2, 'turn_result', trial=0, turn=1, timeout=20)

        self.wait_state(player1, 'turn', trial=0, turn=2, timeout=20)
        self.wait_state(player2, 'turn', trial=0, turn=2, timeout=20)
        self.submit(player1, 1, 1, [[0, 0]])
        self.submit(player1, 1, 2, [[2, 2]])
        self.submit(player2, 1, 2, [[4, 4]])
        self.wait_state(player1, 'turn_result', trial=0, turn=2, timeout=20)
        self.wait_state(player2, 'turn_result', trial=0, turn=2, timeout=20)

        record = json.loads(self.http_get(f'/data/{room_id}.json')[0])
        turn1 = [row for row in record['turns'] if row['trial'] == 0 and row['turn'] == 1][0]
        turn2 = [row for row in record['turns'] if row['trial'] == 0 and row['turn'] == 2][0]
        self.assertEqual(turn1['player1Indices'], [7])
        self.assertEqual(turn1['selectionSource1'], 'manual')
        self.assertEqual(turn1['selectionSource2'], 'manual')
        self.assertEqual(turn2['player1Indices'], [14])
        self.assertEqual(turn2['player1Cells'], [[2, 2]])
        self.assertEqual(turn2['selectionSource1'], 'manual')

    def test_timeout_selects_one_cell(self):
        player1, player2, room_id = self.match_pair()
        self.wait_state(player1, 'turn', trial=0, turn=1, timeout=20)
        self.wait_state(player2, 'turn', trial=0, turn=1, timeout=20)
        auto1 = self.receive_type(player1, {'auto_selected'}, timeout=35)
        auto2 = self.receive_type(player2, {'auto_selected'}, timeout=35)
        self.assertEqual(auto1['game'], 1)
        self.assertEqual(auto1['turn'], 1)
        self.assertEqual(auto2['game'], 1)
        self.assertEqual(auto2['turn'], 1)
        self.assertEqual(len(auto1['cells']), 1)
        self.assertEqual(len(auto1['cells'][0]), 2)
        self.assertEqual(len(auto2['cells']), 1)
        self.assertEqual(len(auto2['cells'][0]), 2)
        self.wait_state(player1, 'turn_result', trial=0, turn=1, timeout=20)
        self.wait_state(player2, 'turn_result', trial=0, turn=1, timeout=20)

        record = json.loads(self.http_get(f'/data/{room_id}.json')[0])
        turn1 = [row for row in record['turns'] if row['trial'] == 0 and row['turn'] == 1][0]
        self.assertEqual(turn1['selectionSource1'], 'timeout')
        self.assertEqual(turn1['selectionSource2'], 'timeout')
        self.assertEqual(turn1['autoSelected1'], 1)
        self.assertEqual(turn1['autoSelected2'], 1)
        self.assertEqual(len(turn1['player1Cells']), 1)
        self.assertEqual(len(turn1['player2Cells']), 1)
        self.assertEqual(turn1['player1Cells'], auto1['cells'])
        self.assertEqual(turn1['player2Cells'], auto2['cells'])

    def test_legacy_record_analysis_exports_return_409(self):
        legacy_records = [
            {
                'schemaVersion': 2,
                'roomId': 'legacy-v2',
                'rows': 6,
                'cols': 6,
                'boards': 3,
                'totalGames': 1,
                'turns': [],
            },
            {
                'roomId': 'legacy-unversioned',
                'rows': 6,
                'cols': 6,
                'turns': [],
            },
        ]
        for record in legacy_records:
            legacy_id = f"{record['roomId']}-{uuid.uuid4()}"
            path = DATA_DIR / f'{legacy_id}.json'
            record = dict(record, roomId=legacy_id)
            path.write_text(json.dumps(record), encoding='utf-8')
            try:
                json_bytes, _ = self.http_get(f'/data/{legacy_id}.json')
                self.assertEqual(json.loads(json_bytes)['roomId'], legacy_id)
                self.assertEqual(self.http_error_status(f'/data/{legacy_id}.csv'), 409)
                self.assertEqual(self.http_error_status(f'/data/{legacy_id}.zip'), 409)
            finally:
                path.unlink()


if __name__ == '__main__':
    unittest.main(verbosity=2)
