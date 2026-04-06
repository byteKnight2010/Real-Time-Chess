import json
import random
import signal
import threading
import logging
from collections import namedtuple, Counter
from dataclasses import dataclass
from typing import Optional, Tuple


log: logging.Logger = logging.getLogger("chess")

WIN_W: int = 1040
WIN_H: int = 760
BOARD_PX: int = 0
SQ: int = 0
BX: int = 0
BY: int = 0
SB_X: int = 0
SB_W: int = 0
FPS: int = 60
DEFAULT_CD: float = 2.0
SB_MIN: int = 230


def applyLayout(winW: int, winH: int) -> None:
    global WIN_W, WIN_H, BOARD_PX, SQ, BX, BY, SB_X, SB_W
    winW = max(640, winW)
    winH = max(480, winH)
    WIN_W, WIN_H = winW, winH
    BY = max(24, min(44, int(winH * 0.04)))
    bottomPad: int = max(28, int(winH * 0.045))
    availableW: int = winW - SB_MIN - 48
    availableH: int = winH - BY - bottomPad
    raw: int = min(availableW, availableH)
    BOARD_PX = max(8 * 28, (raw // 8) * 8)
    SQ = BOARD_PX // 8
    spaceForBoard: int = winW - SB_MIN - 24
    BX = max(12, (spaceForBoard - BOARD_PX) // 2 + 12)
    SB_X = BX + BOARD_PX + 24
    SB_W = max(160, winW - SB_X - 10)


applyLayout(WIN_W, WIN_H)

BG: tuple[int, int, int] = (10, 12, 28)
C_LIGHT: tuple[int, int, int] = (238, 215, 178)
C_DARK: tuple[int, int, int] = (175, 132, 96)
C_BORDER: tuple[int, int, int] = (8, 9, 18)

HL_SEL: tuple[int, int, int, int] = (22, 222, 88, 195)
HL_VALID: tuple[int, int, int, int] = (55, 200, 75, 118)
HL_CAPTURE: tuple[int, int, int, int] = (200, 60, 60, 130)
HL_PREMW: tuple[int, int, int, int] = (80, 130, 235, 155)
HL_PREMB: tuple[int, int, int, int] = (235, 140, 50, 155)
HL_SAFE: tuple[int, int, int, int] = (48, 210, 82, 155)
HL_RISKY: tuple[int, int, int, int] = (212, 78, 38, 158)
HL_CASTLE: tuple[int, int, int, int] = (80, 180, 240, 140)
HL_EP: tuple[int, int, int, int] = (240, 200, 60, 150)

C_TEXT: tuple[int, int, int] = (220, 225, 245)
C_MUTED: tuple[int, int, int] = (100, 110, 145)
C_BTN: tuple[int, int, int] = (30, 35, 65)
C_BTN_H: tuple[int, int, int] = (48, 58, 98)
C_BTN_ON: tuple[int, int, int] = (30, 148, 88)
C_BAR_BG: tuple[int, int, int] = (24, 28, 52)
C_BAR_FG: tuple[int, int, int] = (74, 196, 106)
C_BAR_DONE: tuple[int, int, int] = (210, 192, 52)
C_DOT_PRE: tuple[int, int, int] = (88, 128, 232)
C_WIN_OVL: tuple[int, int, int, int] = (0, 0, 0, 158)
C_MOD_BG: tuple[int, int, int] = (16, 20, 44)
C_MOD_BD: tuple[int, int, int] = (60, 72, 110)
C_AI_LBL: tuple[int, int, int] = (88, 160, 235)
C_SLIDER: tuple[int, int, int] = (60, 72, 110)
C_SLIDER_H: tuple[int, int, int] = (90, 140, 210)
C_ACCENT: tuple[int, int, int] = (30, 180, 100)

C_DIFF_CLR: dict[str, tuple[int, int, int]] = {
    'Polly':    (130, 215, 130),
    'Boris':    (155, 215, 110),
    'Nelson':   (180, 215, 90),
    'Sophia':   (200, 210, 75),
    'Marco':    (215, 195, 58),
    'Dana':     (225, 175, 50),
    'Rick':     (230, 148, 42),
    'Lena':     (230, 120, 45),
    'Guzman':   (225, 90, 50),
    'Alex':     (218, 68, 55),
    'Magnus':   (210, 42, 62),
    'Stockfish':(185, 18, 80),
}

PROMO_TYPES: list[str] = ['Q', 'R', 'B', 'N']
PROMO_NAMES: dict[str, str] = {
    'Q': 'Queen',
    'R': 'Rook',
    'B': 'Bishop',
    'N': 'Knight'
}

UNICODE_CHESS: dict[tuple[str, str], str] = {
    ('w', 'K'): '\u2654', ('w', 'Q'): '\u2655', ('w', 'R'): '\u2656',
    ('w', 'B'): '\u2657', ('w', 'N'): '\u2658', ('w', 'P'): '\u2659',
    ('b', 'K'): '\u265a', ('b', 'Q'): '\u265b', ('b', 'R'): '\u265c',
    ('b', 'B'): '\u265d', ('b', 'N'): '\u265e', ('b', 'P'): '\u265f',
}

AI_SETTINGS: dict[str, dict[str, int | float | str]] = {
    'Polly': {
        'depth': 0,
        'delay': 2.5,
        'noise': 700,
        'rating': 300,
        'style': 'Wanderer',
        'desc': 'Moves at random. Good luck — you need it?'
    },
    'Boris': {
        'depth': 0,
        'delay': 2.0,
        'noise': 520,
        'rating': 500,
        'style': 'Blunderer',
        'desc': 'Forgets pieces exist. Very forgiving.'
    },
    'Nelson': {
        'depth': 1,
        'delay': 1.7,
        'noise': 380,
        'rating': 700,
        'style': 'Learner',
        'desc': 'Knows the rules, follows basic strategy.'
    },
    'Sophia': {
        'depth': 1,
        'delay': 1.4,
        'noise': 260,
        'rating': 900,
        'style': 'Defender',
        'desc': 'Cautious and careful. Avoids risky moves.'
    },
    'Marco': {
        'depth': 1,
        'delay': 1.0,
        'noise': 180,
        'rating': 1100,
        'style': 'Attacker',
        'desc': 'Loves to attack — sometimes recklessly.'
    },
    'Dana': {
        'depth': 1,
        'delay': 0.8,
        'noise': 110,
        'rating': 1300,
        'style': 'Balanced',
        'desc': 'Well-rounded and consistent. Club level.'
    },
    'Rick': {
        'depth': 2,
        'delay': 0.6,
        'noise': 70,
        'rating': 1500,
        'style': 'Tactician',
        'desc': 'Spots short combinations and tactics.'
    },
    'Lena': {
        'depth': 2,
        'delay': 0.4,
        'noise': 35,
        'rating': 1700,
        'style': 'Positional',
        'desc': 'Controls key squares. Long strategic plans.'
    },
    'Guzman': {
        'depth': 2,
        'delay': 0.28,
        'noise': 14,
        'rating': 1900,
        'style': 'Aggressor',
        'desc': 'Relentless pressure. Never retreats.'
    },
    'Alex': {
        'depth': 3,
        'delay': 0.20,
        'noise': 5,
        'rating': 2100,
        'style': 'Calculator',
        'desc': 'Deep calculation. Very precise and sharp.'
    },
    'Magnus': {
        'depth': 3,
        'delay': 0.13,
        'noise': 1,
        'rating': 2400,
        'style': 'Grandmaster',
        'desc': 'Dominant strategy. Sees everything.'
    },
    'Stockfish': {
        'depth': 3,
        'delay': 0.08,
        'noise': 0,
        'rating': 2800,
        'style': 'Engine',
        'desc': 'Near-perfect machine play. Virtually unbeatable.'
    }
}

DIFFICULTIES: list[str] = list(AI_SETTINGS.keys())

CD_PRESETS: list[tuple[str, float]] = [
    ('Bullet', 1.0),
    ('Blitz', 3.0),
    ('Rapid', 5.0),
    ('Classical', 10.0)
]

PIECE_VALUES: dict[str, int] = {
    'P': 100,
    'N': 320,
    'B': 330,
    'R': 500,
    'Q': 900,
    'K': 20000
}
PIECE_DISP_PTS: dict[str, int] = {
    'P': 1,
    'N': 3,
    'B': 3,
    'R': 5,
    'Q': 9,
    'K': 0
}

PAWN_POS: list[list[int]] = [
    [0, 0, 0, 0, 0, 0, 0, 0],
    [50, 50, 50, 50, 50, 50, 50, 50],
    [10, 10, 20, 30, 30, 20, 10, 10],
    [5, 5, 10, 25, 25, 10, 5, 5],
    [0, 0, 0, 20, 20, 0, 0, 0],
    [5, -5, -10, 0, 0, -10, -5, 5],
    [5, 10, 10, -20, -20, 10, 10, 5],
    [0, 0, 0, 0, 0, 0, 0, 0],
]
KNIGHT_POS: list[list[int]] = [
    [-50, -40, -30, -30, -30, -30, -40, -50],
    [-40, -20, 0, 0, 0, 0, -20, -40],
    [-30, 0, 10, 15, 15, 10, 0, -30],
    [-30, 5, 15, 20, 20, 15, 5, -30],
    [-30, 0, 15, 20, 20, 15, 0, -30],
    [-30, 5, 10, 15, 15, 10, 5, -30],
    [-40, -20, 0, 5, 5, 0, -20, -40],
    [-50, -40, -30, -30, -30, -30, -40, -50],
]
BISHOP_POS: list[list[int]] = [
    [-20, -10, -10, -10, -10, -10, -10, -20],
    [-10, 0, 0, 0, 0, 0, 0, -10],
    [-10, 0, 5, 10, 10, 5, 0, -10],
    [-10, 5, 5, 10, 10, 5, 5, -10],
    [-10, 0, 10, 10, 10, 10, 0, -10],
    [-10, 10, 10, 10, 10, 10, 10, -10],
    [-10, 5, 0, 0, 0, 0, 5, -10],
    [-20, -10, -10, -10, -10, -10, -10, -20],
]
ROOK_POS: list[list[int]] = [
    [0, 0, 0, 0, 0, 0, 0, 0],
    [5, 10, 10, 10, 10, 10, 10, 5],
    [-5, 0, 0, 0, 0, 0, 0, -5],
    [-5, 0, 0, 0, 0, 0, 0, -5],
    [-5, 0, 0, 0, 0, 0, 0, -5],
    [-5, 0, 0, 0, 0, 0, 0, -5],
    [-5, 0, 0, 0, 0, 0, 0, -5],
    [0, 0, 0, 5, 5, 0, 0, 0],
]
QUEEN_POS: list[list[int]] = [
    [-20, -10, -10, -5, -5, -10, -10, -20],
    [-10, 0, 0, 0, 0, 0, 0, -10],
    [-10, 0, 5, 5, 5, 5, 0, -10],
    [-5, 0, 5, 5, 5, 5, 0, -5],
    [0, 0, 5, 5, 5, 5, 0, -5],
    [-10, 5, 5, 5, 5, 5, 0, -10],
    [-10, 0, 5, 0, 0, 0, 0, -10],
    [-20, -10, -10, -5, -5, -10, -10, -20],
]
KING_POS: list[list[int]] = [
    [-30, -40, -40, -50, -50, -40, -40, -30],
    [-30, -40, -40, -50, -50, -40, -40, -30],
    [-30, -40, -40, -50, -50, -40, -40, -30],
    [-30, -40, -40, -50, -50, -40, -40, -30],
    [-20, -30, -30, -40, -40, -30, -30, -20],
    [-10, -20, -20, -20, -20, -20, -20, -10],
    [20, 20, 0, 0, 0, 0, 20, 20],
    [20, 30, 10, 0, 0, 10, 30, 20],
]
POS_TABLES: dict[str, list[list[int]]] = {
    'P': PAWN_POS,
    'N': KNIGHT_POS,
    'B': BISHOP_POS,
    'R': ROOK_POS,
    'Q': QUEEN_POS,
    'K': KING_POS
}


@dataclass
class Piece:
    col: int
    row: int
    color: str
    ptype: str
    cooldown: float = 0.0
    premove: Optional[Tuple[int, int]] = None
    alive: bool = True
    hasMoved: bool = False

    def ready(self) -> bool:
        return self.cooldown <= 0.0 and self.alive


def pseudoLegalMoves(
    piece: Piece,
    allPieces: list[Piece],
    epSq: Optional[tuple[int, int]] = None
) -> set[tuple[int, int]]:
    col: int = piece.col
    row: int = piece.row
    color: str = piece.color
    ptype: str = piece.ptype
    opp: str = 'b' if color == 'w' else 'w'
    occ: dict[tuple[int, int], Piece] = {(p.col, p.row): p for p in allPieces if p.alive}
    moves: set[tuple[int, int]] = set()

    def slide(dc: int, dr: int) -> None:
        c, r = col + dc, row + dr

        while 0 <= c < 8 and 0 <= r < 8:
            if (c, r) in occ:
                if occ[(c, r)].color == opp:
                    moves.add((c, r))
                break

            moves.add((c, r))
            c += dc
            r += dr

    def step(dc: int, dr: int) -> None:
        c, r = col + dc, row + dr

        if 0 <= c < 8 and 0 <= r < 8:
            if (c, r) not in occ or occ[(c, r)].color == opp:
                moves.add((c, r))

    if ptype == 'R':
        [slide(*d) for d in ((1, 0), (-1, 0), (0, 1), (0, -1))]
    elif ptype == 'B':
        [slide(*d) for d in ((1, 1), (1, -1), (-1, 1), (-1, -1))]
    elif ptype == 'Q':
        [slide(*d) for d in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))]
    elif ptype == 'N':
        [step(*d) for d in ((2, 1), (2, -1), (-2, 1), (-2, -1), (1, 2), (1, -2), (-1, 2), (-1, -2))]
    elif ptype == 'K':
        [step(dc, dr) for dc in (-1, 0, 1) for dr in (-1, 0, 1) if dc or dr]
        back: int = 7 if color == 'w' else 0

        if not piece.hasMoved and row == back and col == 4:
            rks: Optional[Piece] = occ.get((7, back))
            if (rks and rks.ptype == 'R' and rks.color == color
                    and not rks.hasMoved
                    and (5, back) not in occ
                    and (6, back) not in occ):
                moves.add((6, back))

            rqs: Optional[Piece] = occ.get((0, back))
            if (rqs and rqs.ptype == 'R' and rqs.color == color
                    and not rqs.hasMoved
                    and (1, back) not in occ
                    and (2, back) not in occ
                    and (3, back) not in occ):
                moves.add((2, back))
    elif ptype == 'P':
        fwd: int
        start: int
        fwd, start = (-1, 6) if color == 'w' else (1, 1)
        nr: int = row + fwd
        if 0 <= nr < 8 and (col, nr) not in occ:
            moves.add((col, nr))
            if row == start and (col, row + 2 * fwd) not in occ:
                moves.add((col, row + 2 * fwd))
        for dc in (-1, 1):
            nc, nr2 = col + dc, row + fwd
            if 0 <= nc < 8 and 0 <= nr2 < 8:
                if (nc, nr2) in occ and occ[(nc, nr2)].color == opp:
                    moves.add((nc, nr2))
                elif epSq and (nc, nr2) == epSq:
                    moves.add(epSq)
    return moves


def allThreatened(
    pieces: list[Piece],
    color: str,
    epSq: Optional[tuple[int, int]] = None
) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()

    for p in pieces:
        if p.alive and p.color == color:
            out |= pseudoLegalMoves(p, pieces, epSq)

    return out


def initPieces() -> list[Piece]:
    ps: list[Piece] = []

    for c, t in enumerate(['R', 'N', 'B', 'Q', 'K', 'B', 'N', 'R']):
        ps.append(Piece(c, 0, 'b', t))
        ps.append(Piece(c, 7, 'w', t))

    for c in range(8):
        ps.append(Piece(c, 1, 'b', 'P'))
        ps.append(Piece(c, 6, 'w', 'P'))

    return ps


BoardState = namedtuple('BoardState', 'col row color ptype cooldown hasMoved alive')


def toBoard(pieces: list[Piece]) -> list[BoardState]:
    return [
        BoardState(p.col, p.row, p.color, p.ptype, p.cooldown, p.hasMoved, p.alive)
        for p in pieces
    ]


def boardMoves(board: list[BoardState], color: str) -> list[tuple[int, int, int]]:
    opp: str = 'b' if color == 'w' else 'w'
    occ: dict[tuple[int, int], str] = {(p.col, p.row): p.color for p in board if p.alive}
    result: list[tuple[int, int, int]] = []

    for idx, p in enumerate(board):
        if not (p.alive and p.color == color and p.cooldown <= 0):
            continue

        col: int = p.col
        row: int = p.row
        ptype: str = p.ptype
        moves: set[tuple[int, int]] = set()

        def slide(dc: int, dr: int) -> None:
            c, r = col + dc, row + dr

            while 0 <= c < 8 and 0 <= r < 8:
                if (c, r) in occ:
                    if occ[(c, r)] == opp:
                        moves.add((c, r))
                    break

                moves.add((c, r))
                c += dc
                r += dr

        def step(dc: int, dr: int) -> None:
            c, r = col + dc, row + dr

            if 0 <= c < 8 and 0 <= r < 8:
                if (c, r) not in occ or occ[(c, r)] == opp:
                    moves.add((c, r))

        if ptype == 'R':
            [slide(*d) for d in ((1, 0), (-1, 0), (0, 1), (0, -1))]
        elif ptype == 'B':
            [slide(*d) for d in ((1, 1), (1, -1), (-1, 1), (-1, -1))]
        elif ptype == 'Q':
            [slide(*d) for d in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))]
        elif ptype == 'N':
            [step(*d) for d in ((2, 1), (2, -1), (-2, 1), (-2, -1), (1, 2), (1, -2), (-1, 2), (-1, -2))]
        elif ptype == 'K':
            [step(dc, dr) for dc in (-1, 0, 1) for dr in (-1, 0, 1) if dc or dr]
            back: int = 7 if color == 'w' else 0

            if not p.hasMoved and row == back and col == 4:
                rk: Optional[BoardState] = next(
                    (q for q in board
                     if q.alive and q.col == 7 and q.row == back
                     and q.color == color and q.ptype == 'R' and not q.hasMoved),
                    None
                )

                if rk and (5, back) not in occ and (6, back) not in occ:
                    moves.add((6, back))

                rq: Optional[BoardState] = next(
                    (q for q in board
                     if q.alive and q.col == 0 and q.row == back
                     and q.color == color and q.ptype == 'R' and not q.hasMoved),
                    None
                )
                if rq and all((c, back) not in occ for c in (1, 2, 3)):
                    moves.add((2, back))
        elif ptype == 'P':
            fwd: int
            start: int
            fwd, start = (-1, 6) if color == 'w' else (1, 1)
            nr: int = row + fwd

            if 0 <= nr < 8 and (col, nr) not in occ:
                moves.add((col, nr))

                if row == start and (col, row + 2 * fwd) not in occ:
                    moves.add((col, row + 2 * fwd))
            for dc in (-1, 1):
                nc, nr2 = col + dc, row + fwd

                if (0 <= nc < 8 and 0 <= nr2 < 8
                        and (nc, nr2) in occ and occ[(nc, nr2)] == opp):
                    moves.add((nc, nr2))

        for tc, tr in moves:
            result.append((idx, tc, tr))

    return result


def boardApply(
    board: list[BoardState],
    idx: int,
    tc: int,
    tr: int,
    promo: str = 'Q'
) -> list[BoardState]:
    new: list[BoardState] = list(board)
    mover: BoardState = new[idx]
    for i, p in enumerate(new):
        if p.alive and p.color != mover.color and p.col == tc and p.row == tr:
            new[i] = p._replace(alive=False)
            break
    pt: str = promo if (mover.ptype == 'P' and (tr == 0 or tr == 7)) else mover.ptype
    new[idx] = mover._replace(col=tc, row=tr, ptype=pt, hasMoved=True, cooldown=2.0)
    return new


def boardEval(board: list[BoardState], aiColor: str) -> float:
    score: float = 0.0
    for p in board:
        if not p.alive:
            continue
        tbl: Optional[list[list[int]]] = POS_TABLES.get(p.ptype)
        ri: int = p.row if p.color == 'w' else (7 - p.row)
        val: int = PIECE_VALUES.get(p.ptype, 0) + (tbl[ri][p.col] if tbl else 0)
        score += val if p.color == aiColor else -val
    return score


def minimax(
    board: list[BoardState],
    depth: int,
    alpha: float,
    beta: float,
    maximizing: bool,
    aiColor: str,
    oppColor: str
) -> float:
    if depth == 0:
        return boardEval(board, aiColor)
    color: str = aiColor if maximizing else oppColor
    moves: list[tuple[int, int, int]] = boardMoves(board, color)
    if not moves:
        return boardEval(board, aiColor)
    occ: set[tuple[int, int]] = {(p.col, p.row) for p in board if p.alive}
    moves.sort(key=lambda m: 0 if (m[1], m[2]) in occ else 1)
    if maximizing:
        val: float = float('-inf')
        for idx, tc, tr in moves:
            val = max(val, minimax(boardApply(board, idx, tc, tr), depth - 1, alpha, beta, False, aiColor, oppColor))
            alpha = max(alpha, val)
            if alpha >= beta:
                break
        return val
    else:
        val = float('inf')
        for idx, tc, tr in moves:
            val = min(val, minimax(boardApply(board, idx, tc, tr), depth - 1, alpha, beta, True, aiColor, oppColor))
            beta = min(beta, val)
            if alpha >= beta:
                break
        return val


def smartAiPromotion(
    board: list[BoardState],
    col: int,
    row: int,
    color: str
) -> str:
    opp: str = 'b' if color == 'w' else 'w'
    baseBoard: list[BoardState] = [p for p in board if not (p.col == col and p.row == row and p.alive)]
    bestPiece: str = 'Q'
    bestScore: float = float('-inf')
    for candidate in PROMO_TYPES:
        newP: BoardState = BoardState(
            col=col, row=row, color=color, ptype=candidate,
            cooldown=0.0, hasMoved=True, alive=True
        )
        testBoard: list[BoardState] = baseBoard + [newP]
        if candidate == 'Q' and len(boardMoves(testBoard, opp)) == 0:
            continue
        score: float = boardEval(testBoard, color)
        oppKing: Optional[tuple[int, int]] = next(
            ((p.col, p.row) for p in testBoard if p.alive and p.color == opp and p.ptype == 'K'),
            None
        )
        if oppKing and any((tc, tr) == oppKing for (_, tc, tr) in boardMoves(testBoard, color)):
            score += 80
        if candidate == 'N':
            knightAttacks: set[tuple[int, int]] = {
                (col + dc, row + dr)
                for dc, dr in ((2, 1), (2, -1), (-2, 1), (-2, -1), (1, 2), (1, -2), (-1, 2), (-1, -2))
                if 0 <= col + dc < 8 and 0 <= row + dr < 8
            }
            hit: list[BoardState] = [
                p for p in testBoard if p.alive and p.color == opp and (p.col, p.row) in knightAttacks
            ]
            if oppKing and oppKing in knightAttacks and len(hit) >= 2:
                score += 200
        if score > bestScore:
            bestScore = score
            bestPiece = candidate
    return bestPiece


class ChessAI:
    def __init__(self, color: str, difficulty: str) -> None:
        self.color: str = color
        self.opp: str = 'b' if color == 'w' else 'w'
        self.difficulty: str = difficulty
        self.thread: Optional[threading.Thread] = None
        self.result: Optional[tuple[int, int, int, int]] = None
        self.lock: threading.Lock = threading.Lock()
        self.cancel: threading.Event = threading.Event()
        self.kickCount: int = 0

    def kickOff(
        self,
        pieces: list[Piece],
        epSq: Optional[tuple[int, int]],
        piecesLock: Optional[threading.Lock] = None
    ) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.cancel.clear()
        with self.lock:
            self.result = None
        if piecesLock:
            with piecesLock:
                board: list[BoardState] = toBoard(pieces)
        else:
            board = toBoard(pieces)
        cfg: dict = AI_SETTINGS[self.difficulty]
        depth: int = cfg['depth']
        noise: int = cfg['noise']
        color: str = self.color
        opp: str = self.opp
        self.kickCount += 1
        kickId: int = self.kickCount

        def search() -> None:
            if hasattr(signal, 'pthread_sigmask'):
                signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
            try:
                moves: list[tuple[int, int, int]] = boardMoves(board, color)
                if not moves:
                    return
                if depth == 0:
                    idx, tc, tr = random.choice(moves)
                    with self.lock:
                        self.result = (board[idx].col, board[idx].row, tc, tr)
                    return
                bestScore: float = float('-inf')
                best: list[tuple[int, int, int]] = []
                for idx, tc, tr in moves:
                    if self.cancel.is_set():
                        return
                    score: float = minimax(
                        boardApply(board, idx, tc, tr),
                        depth - 1,
                        float('-inf'),
                        float('inf'),
                        False,
                        color,
                        opp
                    )
                    score += random.uniform(-noise, noise)
                    if score > bestScore + 0.5:
                        bestScore = score
                        best = [(idx, tc, tr)]
                    elif score >= bestScore - 0.5:
                        best.append((idx, tc, tr))
                if best and not self.cancel.is_set():
                    idx, tc, tr = random.choice(best)
                    with self.lock:
                        self.result = (board[idx].col, board[idx].row, tc, tr)
            except BaseException:
                log.exception(f"search #{kickId}: EXCEPTION in AI thread")

        self.thread = threading.Thread(target=search, daemon=True, name=f"AI-{kickId}")
        self.thread.start()

    def isThinking(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def getResult(self) -> Optional[tuple[int, int, int, int]]:
        with self.lock:
            return self.result

    def consumeResult(self) -> Optional[tuple[int, int, int, int]]:
        with self.lock:
            r: Optional[tuple[int, int, int, int]] = self.result
            self.result = None
            return r

    def cancelSearch(self) -> None:
        self.cancel.set()
        if self.thread:
            self.thread.join(timeout=0.05)


# ── LAN serialisation helpers ─────────────────────────────────────────────


def piecesToJSON(
    pieces: list,
    epSq: Optional[tuple],
    epExpiry: float,
    cooldownSecs: float,
    gameOver: Optional[str] = None,
) -> str:
    """Serialise the full board state to a compact JSON string for LAN sync."""
    data: dict = {
        "pieces": [
            {
                "col": p.col, "row": p.row, "color": p.color, "ptype": p.ptype,
                "cooldown": round(p.cooldown, 4),
                "hasMoved": p.hasMoved, "alive": p.alive,
                "premove": list(p.premove) if p.premove else None,
            }
            for p in pieces
        ],
        "epSq": list(epSq) if epSq else None,
        "epExpiry": epExpiry,
        "cooldownSecs": cooldownSecs,
    }
    if gameOver:
        data["gameOver"] = gameOver
    return json.dumps(data, separators=(",", ":"))


def piecesFromJSON(data: dict, pieces_list: list) -> tuple:
    """Apply a STATE dict onto an existing pieces list **in-place**.

    Returns ``(epSq, epExpiry, cooldownSecs)`` parsed from the snapshot.
    The pieces_list is extended or shrunk to match the snapshot length.
    """
    src: list = data["pieces"]
    # Resize list to match snapshot (reuse existing Piece objects to preserve identity where possible)
    while len(pieces_list) < len(src):
        pieces_list.append(Piece(0, 0, "w", "P"))
    while len(pieces_list) > len(src):
        pieces_list.pop()
    for p, pd in zip(pieces_list, src):
        p.col = pd["col"]
        p.row = pd["row"]
        p.color = pd["color"]
        p.ptype = pd["ptype"]
        p.cooldown = pd["cooldown"]
        p.hasMoved = pd["hasMoved"]
        p.alive = pd["alive"]
        pm = pd.get("premove")
        p.premove = tuple(pm) if pm else None
    ep_raw = data.get("epSq")
    epSq: Optional[tuple] = tuple(ep_raw) if ep_raw else None
    return epSq, float(data.get("epExpiry", 0.0)), float(data.get("cooldownSecs", DEFAULT_CD))


def ptypeName(pt: str) -> str:
    return {'P': 'Pawn', 'N': 'Knight', 'B': 'Bishop', 'R': 'Rook', 'Q': 'Queen', 'K': 'King'}.get(pt, pt)


def analysisCommentary(
    moveHistory: list[dict],
    gameDuration: float,
    gameOver: Optional[str],
    gameMode: str,
    aiDifficulty: str,
    aiColor: str
) -> list[str]:
    notes: list[str] = []

    if not moveHistory:
        notes.append("No moves were recorded.")
        return notes
    wMoves: list[dict] = [m for m in moveHistory if m['color'] == 'w']
    bMoves: list[dict] = [m for m in moveHistory if m['color'] == 'b']
    wCaps: list[dict] = [m for m in wMoves if m['capture']]
    bCaps: list[dict] = [m for m in bMoves if m['capture']]
    total: int = len(moveHistory)
    dur: float = max(1, gameDuration)

    if dur < 20:
        notes.append("Lightning-fast game — blink and you missed it!")
    elif dur < 60:
        notes.append(f"Quick game — finished in {int(dur)}s.")
    elif dur < 180:
        notes.append(f"Steady match lasting {int(dur) // 60}m {int(dur) % 60}s.")
    else:
        notes.append(f"An endurance battle: {int(dur) // 60}m {int(dur) % 60}s of chess!")

    if total > 0:
        pace: float = dur / total
        if pace < 1.5:
            notes.append("Pieces flew across the board at a frantic pace.")
        elif pace < 4.0:
            notes.append("A balanced tempo — neither side lingered.")
        else:
            notes.append("Both players took their time, choosing moves carefully.")

    wAgg: float = len(wCaps) / max(1, len(wMoves))
    bAgg: float = len(bCaps) / max(1, len(bMoves))
    if wAgg > bAgg + 0.15:
        notes.append("White played more aggressively, capturing at every chance.")
    elif bAgg > wAgg + 0.15:
        notes.append("Black was the aggressor, hunting pieces relentlessly.")
    else:
        notes.append("Both sides traded captures at a similar rate.")

    if wMoves:
        wpCnt: Counter = Counter(m['ptype'] for m in wMoves)
        top: tuple = wpCnt.most_common(1)[0]
        notes.append(f"White's most active piece: the {ptypeName(top[0])} ({top[1]} move{'s' if top[1] != 1 else ''}).")
    if bMoves:
        bpCnt: Counter = Counter(m['ptype'] for m in bMoves)
        top = bpCnt.most_common(1)[0]
        notes.append(f"Black's most active piece: the {ptypeName(top[0])} ({top[1]} move{'s' if top[1] != 1 else ''}).")

    if gameOver:
        winner: Optional[str] = (
            'White' if 'White' in gameOver else ('Black' if 'Black' in gameOver else None)
        )

        if winner and gameMode == 'vs_ai':
            aiSide: str = 'White' if aiColor == 'w' else 'Black'

            if winner == aiSide:
                cfg: dict = AI_SETTINGS.get(aiDifficulty, {})
                notes.append(
                    f"{aiDifficulty} ({cfg.get('style', 'AI')}, ~{cfg.get('rating', 0)}) "
                    f"proved too strong — try a lower difficulty."
                )
            else:
                notes.append(f"Impressive! You defeated {aiDifficulty}. Ready for a harder challenge?")
    return notes