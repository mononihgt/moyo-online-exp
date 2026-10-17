import asyncio
import csv
import io
import json
import os
import random
import secrets
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .functionWarGame import *
from .game_logic import (
    FORMAL_TRIALS,
    MAP_CONDITION_IDS,
    PRACTICE_TRIALS,
    TOTAL_TRIALS,
    BoardState,
    build_trial_plan,
    complete_game_to_turn_20,
    condition_flags,
    create_initial_state,
    determine_winner,
    get_condition_colors,
    get_condition_metadata,
    get_flashing_cells,
    get_player_view,
    play_turn,
)

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title='Canvas Duel Game')

# 公网部署时可用逗号分隔域名，例如：game.example.com,www.game.example.com
# 默认允许所有 Host，便于 Render/Railway/Fly.io 等平台首次部署。
allowed_hosts = [h.strip() for h in os.getenv('ALLOWED_HOSTS', '*').split(',') if h.strip()]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or ['*'])
app.mount('/static', StaticFiles(directory=str(BASE_DIR / 'static')), name='static')

TURN_SECONDS = 30
REST_SECONDS = 60
TURNS_PER_GAME = 20
DATA_DIR = BASE_DIR.parent / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)

MAP_CONDITION = os.getenv('MAP_CONDITION', 'ref0')
if MAP_CONDITION not in MAP_CONDITION_IDS:
    raise ValueError(
        f'MAP_CONDITION must be one of {", ".join(MAP_CONDITION_IDS)}, got {MAP_CONDITION!r}'
    )
MAP_CONDITION_METADATA = get_condition_metadata(MAP_CONDITION)

REFERENCE_COLUMNS = [
    'soldierPolicyA', 'soldierPolicyB', 'posListA', 'posListB', 'warField', 'soldiers', 'mapSize',
    'isBoundary', 'soldierFromBaseA', 'soldierFromBaseB', 'mapColor', 'dev', 'isConsistent',
    'numOfWar', 'warLostA', 'warLostB', 'logisticsA', 'logisticsB', 'warLocation',
]
EXTRA_COLUMNS = [
    'game', 'round', 'roomId', 'player1Indices', 'player1Cells', 'player2Indices', 'player2Cells',
    'numbersBefore', 'numbersAfter', 'selectionSource1', 'selectionSource2', 'autoSelected1',
    'autoSelected2', 'forced', 'endReason', 'winner', 'soldierFromWarFieldA', 'soldierFromWarFieldB',
    'boards', 'mapColor1', 'mapColor2', 'isBoundary1', 'isBoundary2',
    'trial', 'isPractice', 'formalTrial', 'sourceIndex', 'conditionId', 'showBound',
    'isReferenceCondition',
]
CSV_COLUMNS = REFERENCE_COLUMNS + EXTRA_COLUMNS
LIST_FIELDS = {
    'soldierPolicyA', 'soldierPolicyB', 'posListA', 'posListB', 'warField', 'soldiers', 'mapSize',
    'mapColor', 'warLostA', 'warLostB', 'warLocation', 'player1Indices', 'player1Cells',
    'player2Indices', 'player2Cells', 'numbersBefore', 'numbersAfter', 'mapColor1', 'mapColor2',
}


@app.get('/')
async def index():
    return FileResponse(str(BASE_DIR / 'static' / 'index.html'))


@app.get('/healthz')
async def healthz():
    """供公网托管平台和容器编排系统做健康检查。"""
    return {
        'status': 'ok',
        'waitingPlayers': len(waiting),
        'mapCondition': MAP_CONDITION,
        'showBound': MAP_CONDITION_METADATA['showBound'],
        'isReferenceCondition': MAP_CONDITION_METADATA['isReferenceCondition'],
    }


def _record_path(room_id: str) -> Path:
    return DATA_DIR / f'{room_id}.json'


def _load_analysis_record(room_id: str):
    path = _record_path(room_id)
    if not path.exists():
        return None, JSONResponse({'error': 'record not found'}, status_code=404)
    record = json.loads(path.read_text(encoding='utf-8'))
    if record.get('schemaVersion') != 3:
        return None, JSONResponse(
            {'error': 'records with schemaVersion other than 3 are not supported by analysis exports'},
            status_code=409,
        )
    return record, None


def serialize_row(row: Dict) -> List:
    values = []
    for column in CSV_COLUMNS:
        value = row.get(column)
        if column in LIST_FIELDS:
            values.append(str(value))
        elif value is None:
            values.append('')
        else:
            values.append(value)
    return values


def write_csv(rows: List[Dict]) -> bytes:
    sorted_rows = sorted(rows, key=lambda row: (row['game'], row['round']))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_COLUMNS)
    for row in sorted_rows:
        writer.writerow(serialize_row(row))
    return output.getvalue().encode('utf-8-sig')


def build_condition_fields(condition_id: str) -> Dict:
    metadata = get_condition_metadata(condition_id)
    colors1 = get_condition_colors(condition_id, 1)
    colors2 = get_condition_colors(condition_id, 2)
    return {
        'conditionId': condition_id,
        'showBound': metadata['showBound'],
        'isReferenceCondition': metadata['isReferenceCondition'],
        'isBoundary': metadata['isBoundary'],
        'isConsistent': metadata['isConsistent'],
        'dev': metadata['dev'],
        'legacyBoards': metadata['legacyBoards'],
        'mapColor': [row[:] for row in colors1],
        'mapColor1': [row[:] for row in colors1],
        'mapColor2': [row[:] for row in colors2],
        'isBoundary1': condition_flags(colors1),
        'isBoundary2': condition_flags(colors2),
    }


@app.get('/data/{room_id}.json')
async def download_room_json(room_id: str):
    path = _record_path(room_id)
    if not path.exists():
        return JSONResponse({'error': 'record not found'}, status_code=404)
    return FileResponse(path, media_type='application/json', filename=f'game-{room_id}.json')


@app.get('/data/{room_id}.csv')
async def download_room_csv(room_id: str):
    record, error = _load_analysis_record(room_id)
    if error:
        return error
    data = write_csv(record.get('turns', []))
    return StreamingResponse(io.BytesIO(data), media_type='text/csv; charset=utf-8', headers={
        'Content-Disposition': f'attachment; filename=game-{room_id}.csv'
    })


@app.get('/data/{room_id}.zip')
async def download_room_zip(room_id: str):
    record, error = _load_analysis_record(room_id)
    if error:
        return error
    turns = record.get('turns', [])
    trials = sorted({row['trial'] for row in turns})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for trial in trials:
            trial_rows = [row for row in turns if row['trial'] == trial]
            archive.writestr(f'{room_id}-trial{trial}.csv', write_csv(trial_rows))
    buffer.seek(0)
    return StreamingResponse(buffer, media_type='application/zip', headers={
        'Content-Disposition': f'attachment; filename=game-{room_id}.zip'
    })


@app.get('/data')
async def list_records():
    records = []
    for path in sorted(DATA_DIR.glob('*.json'), key=lambda x: x.stat().st_mtime, reverse=True):
        room_id = path.stem
        records.append({
            'roomId': room_id,
            'jsonUrl': f'/data/{room_id}.json',
            'csvUrl': f'/data/{room_id}.csv',
            'zipUrl': f'/data/{room_id}.zip',
        })
    return {'records': records}


class Player:
    def __init__(self, ws: WebSocket, rows: int, cols: int):
        self.id = str(uuid.uuid4())
        self.ws = ws
        self.rows = rows
        self.cols = cols
        self.number = 0
        self.room: Optional['GameRoom'] = None

    async def send(self, payload: Dict):
        await self.ws.send_text(json.dumps(payload, ensure_ascii=False))


class GameRoom:
    def __init__(self, p1: Player, p2: Player):
        self.players = [p1, p2]
        p1.number, p2.number = 1, 2
        p1.room = p2.room = self
        # 服务端固定 6x6 和 7 个 trial，客户端传入的尺寸与 games 不参与匹配。
        self.rows = 6
        self.cols = 6
        self.condition_id = MAP_CONDITION
        self.condition_fields = build_condition_fields(self.condition_id)
        self.map_color_1 = [row[:] for row in self.condition_fields['mapColor1']]
        self.map_color_2 = [row[:] for row in self.condition_fields['mapColor2']]
        self.trial_plan_seed = secrets.randbits(64)
        self.trial_plan = build_trial_plan(self.trial_plan_seed)
        self.room_id = str(uuid.uuid4())
        self.selection_open = False
        self.selection_sources: Dict[int, str] = {}
        self.num_of_war = 0
        self.created_at = datetime.now(timezone.utc)

        self.current_plan = self.trial_plan[0]
        self.trial = self.current_plan['trial']
        self.game_number = self.current_plan['game']
        self.turn_number = 0
        self.state: BoardState = create_initial_state(
            self.rows, self.cols, self.current_plan, self.condition_id
        )

        self.record = {
            'schemaVersion': 3,
            'roomId': self.room_id,
            'createdAt': self.created_at.isoformat(),
            'completedAt': None,
            'rows': self.rows,
            'cols': self.cols,
            'boards': self.condition_fields['legacyBoards'],
            'totalGames': TOTAL_TRIALS,
            'experiment': {
                'totalTrials': TOTAL_TRIALS,
                'practiceTrials': PRACTICE_TRIALS,
                'formalTrials': FORMAL_TRIALS,
                'trialPlanSeed': self.trial_plan_seed,
                'trialOrder': [entry['sourceIndex'] for entry in self.trial_plan],
                'mapCondition': self.condition_id,
            },
            'condition': self.condition_fields,
            'trialPlan': self.trial_plan,
            'players': [
                {'number': 1, 'id': p1.id},
                {'number': 2, 'id': p2.id},
            ],
            'games': [],
            'turns': [],
        }
        self.selections: Dict[int, List[Tuple[int, int]]] = {}
        self.rest_ready: Set[int] = set()
        self.condition = asyncio.Condition()
        self.closed = False
        self.task = asyncio.create_task(self.run())

    async def safe_send(self, player: Player, payload: Dict):
        try:
            await player.send(payload)
        except Exception:
            self.closed = True

    async def broadcast(self, payload: Dict):
        await asyncio.gather(*(self.safe_send(p, payload) for p in self.players))

    async def send_state_to_each(self, phase: str, seconds: int = 0, flashing=None):
        for p in self.players:
            view = get_player_view(
                p.number, self.game_number, self.turn_number, self.state, self.condition_id
            )
            payload = {
                'type': 'state', 'phase': phase, 'player': p.number,
                'game': self.game_number, 'totalGames': TOTAL_TRIALS,
                'trial': self.current_plan['trial'],
                'isPractice': bool(self.current_plan['isPractice']),
                'formalTrial': self.current_plan['formalTrial'],
                'totalFormal': FORMAL_TRIALS,
                'totalTrials': TOTAL_TRIALS,
                'turn': self.turn_number, 'turnsPerGame': TURNS_PER_GAME,
                'seconds': seconds, 'rows': self.rows, 'cols': self.cols,
                'board': view,
                'flashing': flashing or [],
            }
            await self.safe_send(p, payload)

    def _condition_values(self) -> Dict:
        return {
            'conditionId': self.condition_fields['conditionId'],
            'showBound': self.condition_fields['showBound'],
            'isReferenceCondition': self.condition_fields['isReferenceCondition'],
            'isBoundary': self.condition_fields['isBoundary'],
            'dev': self.condition_fields['dev'],
            'isConsistent': self.condition_fields['isConsistent'],
            'mapColor': [row[:] for row in self.map_color_1],
            'mapColor1': [row[:] for row in self.map_color_1],
            'mapColor2': [row[:] for row in self.map_color_2],
            'isBoundary1': self.condition_fields['isBoundary1'],
            'isBoundary2': self.condition_fields['isBoundary2'],
            'boards': self.condition_fields['legacyBoards'],
        }

    def _trial_values(self, game: int) -> Dict:
        entry = self.trial_plan[game - 1]
        return {
            'trial': entry['trial'],
            'isPractice': 1 if entry['isPractice'] else 0,
            'formalTrial': entry['formalTrial'],
            'sourceIndex': entry['sourceIndex'],
        }

    def _game_values(self) -> Dict:
        return {
            'soldierFromBaseA': self.state['reinforcementA'],
            'soldierFromBaseB': self.state['reinforcementB'],
            'soldierFromWarFieldA': self.state['reinforcementA'],
            'soldierFromWarFieldB': self.state['reinforcementB'],
        }

    def build_initial_row(self, game: int) -> Dict:
        war_field = transformShapesToWarField(self.state['shapes'])
        soldiers = transformNumbersToSoldiers(self.state['numbers'])
        numbers = [row[:] for row in self.state['numbers']]
        row = {
            'game': game,
            'round': 0,
            'turn': 0,
            'roomId': self.room_id,
            'soldierPolicyA': [0 for _ in range(self.rows * self.cols)],
            'soldierPolicyB': [0 for _ in range(self.rows * self.cols)],
            'posListA': [],
            'posListB': [],
            'warField': war_field,
            'soldiers': soldiers,
            'mapSize': list(self.state['mapSize']),
            'numOfWar': 0,
            'warLostA': [],
            'warLostB': [],
            'logisticsA': 0,
            'logisticsB': 0,
            'warLocation': [],
            'player1Indices': [],
            'player1Cells': [],
            'player2Indices': [],
            'player2Cells': [],
            'numbersBefore': numbers,
            'numbersAfter': [row[:] for row in numbers],
            'selectionSource1': 'initial',
            'selectionSource2': 'initial',
            'autoSelected1': 0,
            'autoSelected2': 0,
            'forced': 0,
            'endReason': None,
            'winner': None,
        }
        row.update(self._condition_values())
        row.update(self._trial_values(game))
        row.update(self._game_values())
        return row

    def build_turn_row(self, game: int, turn: int, details: Dict, numbers_before, numbers_after) -> Dict:
        pos_a = list(details['posListA'])
        pos_b = list(details['posListB'])
        if details['forced']:
            source1 = 'forced'
            source2 = 'forced'
        else:
            source1 = self.selection_sources[1]
            source2 = self.selection_sources[2]
        row = {
            'game': game,
            'round': turn,
            'turn': turn,
            'roomId': self.room_id,
            'soldierPolicyA': list(details['soldierPolicyA']),
            'soldierPolicyB': list(details['soldierPolicyB']),
            'posListA': pos_a,
            'posListB': pos_b,
            'warField': list(details['warField']),
            'soldiers': list(details['soldiers']),
            'mapSize': list(details['mapSize']),
            'numOfWar': self.num_of_war,
            'warLostA': list(details['warLostA']),
            'warLostB': list(details['warLostB']),
            'logisticsA': details['logisticsA'],
            'logisticsB': details['logisticsB'],
            'warLocation': list(details['warLocation']),
            'player1Indices': list(pos_a),
            'player1Cells': [[index // self.cols, index % self.cols] for index in pos_a],
            'player2Indices': list(pos_b),
            'player2Cells': [[index // self.cols, index % self.cols] for index in pos_b],
            'numbersBefore': [row[:] for row in numbers_before],
            'numbersAfter': [row[:] for row in numbers_after],
            'selectionSource1': source1,
            'selectionSource2': source2,
            'autoSelected1': 1 if source1 == 'timeout' else 0,
            'autoSelected2': 1 if source2 == 'timeout' else 0,
            'forced': 1 if details['forced'] else 0,
            'endReason': None,
            'winner': None,
        }
        row.update(self._condition_values())
        row.update(self._trial_values(game))
        row.update(self._game_values())
        return row

    def build_game_summary(self, game: int, winner, end_reason: str, end_turn: int, forced_rounds: int) -> Dict:
        summary = {
            'game': game,
            'winner': winner,
            'endReason': end_reason,
            'endTurn': end_turn,
            'completedRounds': TURNS_PER_GAME,
            'forcedRounds': forced_rounds,
        }
        summary.update(self._condition_values())
        summary.update(self._trial_values(game))
        summary.update(self._game_values())
        return summary

    def backfill_game(self, game: int, end_reason: str, winner):
        trial = game - 1
        for row in self.record['turns']:
            if row['trial'] == trial:
                row['endReason'] = end_reason
                row['winner'] = winner

    async def run(self):
        await asyncio.gather(
            self.safe_send(self.players[0], {'type': 'matched', 'player': 1, 'roomId': self.room_id}),
            self.safe_send(self.players[1], {'type': 'matched', 'player': 2, 'roomId': self.room_id}),
        )
        for entry in self.trial_plan:
            if self.closed: return
            self.current_plan = entry
            self.trial = entry['trial']
            self.game_number = entry['game']
            self.turn_number = 0
            self.num_of_war = 0
            self.state = create_initial_state(self.rows, self.cols, entry, self.condition_id)
            self.record['turns'].append(self.build_initial_row(entry['game']))
            self.save_record()
            await self.send_state_to_each('game_start')
            await asyncio.sleep(0.5)

            game_ended_early = False
            for turn in range(1, TURNS_PER_GAME + 1):
                if self.closed: return
                self.turn_number = turn
                self.selections = {}
                self.selection_sources = {}
                self.selection_open = True
                await self.send_state_to_each('turn', TURN_SECONDS)

                try:
                    async with self.condition:
                        await asyncio.wait_for(self.condition.wait_for(lambda: len(self.selections) == 2 or self.closed), TURN_SECONDS)
                except asyncio.TimeoutError:
                    pass
                if self.closed: return
                self.selection_open = False

                all_cells = [(r, c) for r in range(self.rows) for c in range(self.cols)]
                for n in (1, 2):
                    if n not in self.selections:
                        cell = random.choice(all_cells)
                        self.selections[n] = [cell]
                        self.selection_sources[n] = 'timeout'
                        await self.safe_send(self.players[n - 1], {
                            'type': 'auto_selected', 'game': entry['game'], 'turn': turn,
                            'cells': [list(cell)],
                        })

                numbers_before = [row[:] for row in self.state["numbers"]]
                self.state, details = play_turn(self.selections[1], self.selections[2], turn, self.state)
                self.num_of_war += details["numOfWarTurn"]
                self.record['turns'].append(
                    self.build_turn_row(entry['game'], turn, details, numbers_before, self.state["numbers"])
                )
                self.save_record()

                flashing = get_flashing_cells(self.selections[1], self.selections[2], turn, self.state)
                await self.send_state_to_each('turn_result', flashing=flashing)
                await asyncio.sleep(1.0)

                if checkEndGame(self.state["shapes"]):
                    winner = determine_winner(self.state["shapes"])
                    end_turn = turn
                    forced_steps = complete_game_to_turn_20(
                        self.state, turn + 1, details["posListA"], details["posListB"]
                    )
                    forced_numbers_before = [row[:] for row in self.state["numbers"]]
                    for forced_turn, (forced_state, forced_details) in enumerate(forced_steps, start=turn + 1):
                        self.state = forced_state
                        self.num_of_war += forced_details["numOfWarTurn"]
                        self.record['turns'].append(self.build_turn_row(
                            entry['game'], forced_turn, forced_details,
                            forced_numbers_before, self.state["numbers"],
                        ))
                        forced_numbers_before = [row[:] for row in self.state["numbers"]]
                    self.save_record()
                    self.record['games'].append(
                        self.build_game_summary(
                            entry['game'], winner, "annihilation", end_turn, len(forced_steps)
                        )
                    )
                    self.backfill_game(entry['game'], "annihilation", winner)
                    self.save_record()
                    game_ended_early = True
                    break

            if not game_ended_early:
                self.record['games'].append(
                    self.build_game_summary(
                        entry['game'], None, "turn_limit", TURNS_PER_GAME, 0
                    )
                )
                self.backfill_game(entry['game'], "turn_limit", None)
                self.save_record()

            if entry['trial'] < TOTAL_TRIALS - 1:
                self.rest_ready = set()
                await self.send_state_to_each('rest', REST_SECONDS)
                try:
                    async with self.condition:
                        await asyncio.wait_for(self.condition.wait_for(lambda: len(self.rest_ready) == 2 or self.closed), REST_SECONDS)
                except asyncio.TimeoutError:
                    pass
                if self.closed: return
                await self.broadcast({'type': 'rest_complete'})
            else:
                self.record['completedAt'] = datetime.now(timezone.utc).isoformat()
                self.save_record()
                await self.broadcast({
                    'type': 'game_over',
                    'roomId': self.room_id,
                    'jsonUrl': f'/data/{self.room_id}.json',
                    'csvUrl': f'/data/{self.room_id}.csv',
                    'zipUrl': f'/data/{self.room_id}.zip',
                })

    def save_record(self):
        path = _record_path(self.room_id)
        tmp = path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(self.record, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(path)

    async def submit(self, player: Player, game: int, turn: int, cells):
        if not self.selection_open: return
        if game != self.game_number or turn != self.turn_number: return
        clean = []
        seen = set()
        for item in cells:
            if isinstance(item, list) and len(item) == 2:
                r, c = item
                if isinstance(r, int) and isinstance(c, int) and 0 <= r < self.rows and 0 <= c < self.cols and (r, c) not in seen:
                    seen.add((r, c)); clean.append((r, c))
        if not clean:
            await self.safe_send(player, {'type': 'invalid_selection', 'message': 'Select at least one cell'})
            return
        async with self.condition:
            if not self.selection_open or game != self.game_number or turn != self.turn_number:
                return
            if player.number not in self.selections:
                self.selections[player.number] = clean
                self.selection_sources[player.number] = "manual"
                self.condition.notify_all()

    async def ready_after_rest(self, player: Player):
        async with self.condition:
            self.rest_ready.add(player.number)
            self.condition.notify_all()


waiting: List[Player] = []
waiting_lock = asyncio.Lock()


async def enqueue(player: Player):
    async with waiting_lock:
        match = None
        for p in waiting:
            if p.rows == player.rows and p.cols == player.cols:
                match = p; break
        if match:
            waiting.remove(match)
            GameRoom(match, player)
        else:
            waiting.append(player)
            await player.send({'type': 'waiting'})


@app.websocket('/ws')
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    player = None
    try:
        await ws.receive_json()
        # 服务端固定 6x6 和 7 个 trial；客户端传来的 rows/cols/totalGames/boards 被忽略。
        rows = 6
        cols = 6
        player = Player(ws, rows, cols)
        await enqueue(player)
        while True:
            msg = await ws.receive_json()
            if not player.room: continue
            if msg.get('type') == 'submit':
                await player.room.submit(
                    player,
                    int(msg.get('game', 0)),
                    int(msg.get('turn', 0)),
                    msg.get('cells', []),
                )
            elif msg.get('type') == 'rest_ready':
                await player.room.ready_after_rest(player)
    except WebSocketDisconnect:
        pass
    finally:
        if player:
            async with waiting_lock:
                if player in waiting: waiting.remove(player)
            if player.room:
                player.room.closed = True
                for p in player.room.players:
                    if p is not player:
                        await player.room.safe_send(p, {'type': 'opponent_left'})
