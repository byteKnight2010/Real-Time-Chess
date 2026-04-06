import ChessCore
import logging
import math
import socket as _socket
import time
import threading
import pygame
from collections import Counter
from typing import Optional, Dict, List
from ChessCore import (
    FPS, DEFAULT_CD,
    BG, C_LIGHT, C_DARK, C_BORDER, C_TEXT, C_MUTED, C_BTN, C_BTN_H,
    C_BAR_BG, C_BAR_FG, C_BAR_DONE, C_DOT_PRE, C_WIN_OVL, C_MOD_BG, C_MOD_BD,
    C_AI_LBL, C_SLIDER, C_SLIDER_H,
    C_DIFF_CLR,
    HL_SEL, HL_VALID, HL_CAPTURE, HL_EP,
    HL_PREMW, HL_PREMB,
    UNICODE_CHESS, PROMO_TYPES, PROMO_NAMES,
    AI_SETTINGS, DIFFICULTIES, CD_PRESETS,
    PIECE_DISP_PTS,
    pseudoLegalMoves, allThreatened, initPieces,
    toBoard, smartAiPromotion,
    ChessAI,
    ptypeName, analysisCommentary,
    piecesToJSON, piecesFromJSON,
)
from ChessTextures import PieceSheets, STYLE_NAMES
from ChessNetwork import ChessNetwork, get_local_ip


log: logging.Logger = logging.getLogger("chess")


MENU_BG: tuple[int, int, int] = (10, 12, 28)
PANEL_BG: tuple[int, int, int] = (16, 19, 42)
TAB_ACTIVE_BG: tuple[int, int, int] = (30, 180, 100)
TAB_ACTIVE_TXT: tuple[int, int, int] = (255, 255, 255)
TAB_IDLE_BG: tuple[int, int, int] = (22, 27, 56)
TAB_IDLE_TXT: tuple[int, int, int] = (120, 130, 170)
SEC_HDR: tuple[int, int, int] = (88, 150, 230)
DIVIDER: tuple[int, int, int] = (30, 36, 65)
ACCENT: tuple[int, int, int] = (30, 180, 100)
BTN_ACTIVE: tuple[int, int, int] = (30, 148, 88)
BTN_IDLE: tuple[int, int, int] = (26, 32, 62)
BTN_HOVER: tuple[int, int, int] = (40, 50, 90)
MUTE_RED: tuple[int, int, int] = (200, 60, 60)


def makeFonts(sq: int) -> dict[str, pygame.font.Font]:
    sc: float = sq / 80.0
    SYSTEM: str = "segoeuisymbol,seguisym,symbola,dejavusans,freesans,sans"
    UI: str = "segoeui,dejavusans,freesans,ubuntu,sans"

    return {
        'piece':    pygame.font.SysFont(SYSTEM, max(24, int(56 * sc))),
        'symSm':    pygame.font.SysFont(SYSTEM, max(9,  int(13 * sc))),
        'big':      pygame.font.SysFont(UI,     max(16, int(26 * sc)), bold=True),
        'med':      pygame.font.SysFont(UI,     max(12, int(18 * sc)), bold=True),
        'ui':       pygame.font.SysFont(UI,     max(11, int(16 * sc))),
        'sm':       pygame.font.SysFont(UI,     max(9,  int(13 * sc))),
        'promo':    pygame.font.SysFont(SYSTEM, max(20, int(50 * sc))),
        'title':    pygame.font.SysFont(UI,     max(24, int(38 * sc)), bold=True),
        'hero':     pygame.font.SysFont(UI,     max(32, int(52 * sc)), bold=True),
        'tab':      pygame.font.SysFont(UI,     max(12, int(17 * sc)), bold=True),
        # Symbol-font variants at the same sizes — used for icon glyphs in tabs/hero
        'sym_tab':  pygame.font.SysFont(SYSTEM, max(12, int(17 * sc)), bold=True),
        'sym_hero': pygame.font.SysFont(SYSTEM, max(32, int(52 * sc)), bold=True),
    }


PIECE_LETTERS: dict[str, str] = {
    'K': 'K', 'Q': 'Q', 'R': 'R', 'B': 'B', 'N': 'N', 'P': 'P',
}

# ── per-character glyph detection ──────────────────────────────────────────
#
# pygame picks ONE font from the comma-separated SysFont list and uses it for
# every character.  It never falls back per-character.  When a font has no
# glyph for a codepoint it renders a "tofu" box — a hollow rectangle that is
# nearly perfectly square (w/h ≈ 1.0) and has very few filled pixels (just
# the border outline).
#
# We detect tofu with two cheap signals:
#   1. Aspect ratio close to 1.0  (tofu ≈ square)
#   2. Very low filled-pixel density  (tofu ≈ hollow outline)
#
# Emoji (e.g. 🌐 U+1F310) are always rejected — pygame's FreeType back-end
# cannot render color emoji on any platform.

_GLYPH_CACHE: dict[tuple[int, str], bool] = {}
# Codepoints that are known-unreachable in every pygame font (color emoji plane)
_EMOJI_PLANE_START: int = 0x1F000


def glyphOk(font: pygame.font.Font, char: str) -> bool:
    """Return True if *font* renders *char* as a real visible glyph.

    Results are cached by (font id, char).  Call this only after the pygame
    display has been initialised (font rendering requires a video context).
    """
    if not char:
        return False
    cp: int = ord(char[0])
    # Reject entire emoji / supplementary planes up-front — pygame can't do them
    if cp >= _EMOJI_PLANE_START:
        return False

    key: tuple[int, str] = (id(font), char)
    if key in _GLYPH_CACHE:
        return _GLYPH_CACHE[key]

    try:
        surf: pygame.Surface = font.render(char, True, (255, 255, 255))
        w: int
        h: int
        w, h = surf.get_size()
        if w == 0 or h == 0:
            _GLYPH_CACHE[key] = False
            return False

        # Signal 1 — aspect ratio.  Tofu is nearly square (ratio ≈ 1.0).
        ratio: float = w / h
        if ratio > 0.95:
            _GLYPH_CACHE[key] = False
            return False

        # Signal 2 — pixel density.  Lock the surface and count lit pixels.
        # Tofu outline typically fills < 8 % of the bounding box.
        surf.lock()
        lit: int = 0
        total: int = w * h
        step: int = max(1, total // 600)   # sample at most ~600 pixels for speed
        for i in range(0, total, step):
            x: int = i % w
            y: int = i // w
            if surf.get_at((x, y))[0] > 64:
                lit += 1
        surf.unlock()
        # Scale the sampled count back to a density estimate
        density: float = (lit * step) / total
        ok: bool = density > 0.07

        _GLYPH_CACHE[key] = ok
        return ok
    except Exception:
        _GLYPH_CACHE[key] = False
        return False


# Backward-compat alias used by the piece-drawing code below
def fontHasChessGlyphs(font: pygame.font.Font) -> bool:
    return glyphOk(font, '\u2654')   # white king ♔


GLYPH_OK_CACHE: dict[int, bool] = {}   # kept for any external callers


def chessGlyphsOk(font: pygame.font.Font) -> bool:
    fid: int = id(font)
    if fid not in GLYPH_OK_CACHE:
        GLYPH_OK_CACHE[fid] = fontHasChessGlyphs(font)
    return GLYPH_OK_CACHE[fid]


def renderGlyphLabel(
    icon: str,
    text: str,
    sym_font: pygame.font.Font,
    text_font: pygame.font.Font,
    color: tuple,
    gap: int = 5,
) -> pygame.Surface:
    """Composite-render an icon (symbol font) + text (UI font) side by side.

    If *icon* cannot be rendered by *sym_font* the text is returned alone,
    keeping layout predictable regardless of font coverage on the host OS.
    """
    text_surf: pygame.Surface = text_font.render(text, True, color)
    if not icon or not glyphOk(sym_font, icon[0]):
        return text_surf

    icon_surf: pygame.Surface = sym_font.render(icon, True, color)
    total_w: int = icon_surf.get_width() + gap + text_surf.get_width()
    h: int = max(icon_surf.get_height(), text_surf.get_height())
    out: pygame.Surface = pygame.Surface((total_w, h), pygame.SRCALPHA)
    out.blit(icon_surf, (0, (h - icon_surf.get_height()) // 2))
    out.blit(text_surf, (icon_surf.get_width() + gap, (h - text_surf.get_height()) // 2))
    return out


def drawPieceFallback(
    surf: pygame.Surface,
    font: pygame.font.Font,
    color: str,
    ptype: str,
    rect: pygame.Rect
) -> None:
    """Draw a piece as a styled letter when no sprite/glyph is available."""
    letter: str = PIECE_LETTERS.get(ptype, ptype)

    if color == 'w':
        bgCol: tuple[int, int, int] = (230, 220, 190)
        txtCol: tuple[int, int, int] = (30, 25, 20)
        rimCol: tuple[int, int, int] = (160, 140, 100)
    else:
        bgCol = (40, 35, 30)
        txtCol = (220, 215, 200)
        rimCol = (80, 70, 55)

    r: int = max(4, rect.width // 2 - 4)
    cx: int = rect.centerx
    cy: int = rect.centery
    pygame.draw.circle(surf, rimCol, (cx, cy), r + 2)
    pygame.draw.circle(surf, bgCol, (cx, cy), r)
    ls: pygame.Surface = font.render(letter, True, txtCol)
    surf.blit(ls, ls.get_rect(center=(cx, cy)))


def sqRect(col: int, row: int) -> pygame.Rect:
    return pygame.Rect(
        ChessCore.BX + col * ChessCore.SQ,
        ChessCore.BY + row * ChessCore.SQ,
        ChessCore.SQ,
        ChessCore.SQ
    )


def sqFromMouse(mx: int, my: int) -> Optional[tuple[int, int]]:
    c: int = (mx - ChessCore.BX) // ChessCore.SQ
    r: int = (my - ChessCore.BY) // ChessCore.SQ

    return (c, r) if (0 <= c < 8 and 0 <= r < 8) else None


def alphaRect(surf: pygame.Surface, color: tuple, rect: pygame.Rect) -> None:
    s: pygame.Surface = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
    s.fill(color)

    surf.blit(s, rect.topleft)


def alphaCircle(surf: pygame.Surface, color: tuple, cx: int, cy: int, r: int) -> None:
    s: pygame.Surface = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
    pygame.draw.circle(s, color, (r, r), r)
    surf.blit(s, (cx - r, cy - r))


def drawRr(surf: pygame.Surface, color: tuple, rect: pygame.Rect, radius: int = 8) -> None:
    pygame.draw.rect(surf, color, rect, border_radius=radius)


def drawRrBorder(
    surf: pygame.Surface,
    color: tuple,
    rect: pygame.Rect,
    radius: int = 8,
    width: int = 1
) -> None:
    pygame.draw.rect(surf, color, rect, width=width, border_radius=radius)


def drawThreatArrow(
    surf: pygame.Surface,
    ax: float, ay: float,
    bx: float, by: float,
    alpha: int
) -> None:
    dx: float = bx - ax
    dy: float = by - ay
    length: float = math.hypot(dx, dy)
    if length < 1:
        return
    ux: float = dx / length
    uy: float = dy / length
    px: float = -uy
    py: float = ux
    shaftW: int = max(2, int(length * 0.022))
    headLen: int = max(8, int(length * 0.12))
    headW: int = shaftW * 2
    sx1: float = ax + ux * (length - headLen)
    sy1: float = ay + uy * (length - headLen)
    shaftPts: list = [
        (ax + px * shaftW, ay + py * shaftW),
        (ax - px * shaftW, ay - py * shaftW),
        (sx1 - px * shaftW, sy1 - py * shaftW),
        (sx1 + px * shaftW, sy1 + py * shaftW),
    ]
    headPts: list = [
        (bx, by),
        (sx1 + px * headW, sy1 + py * headW),
        (sx1 - px * headW, sy1 - py * headW)
    ]
    allPts: list = shaftPts + headPts
    mnx: int = int(min(p[0] for p in allPts)) - 2
    mny: int = int(min(p[1] for p in allPts)) - 2
    mxx: int = int(max(p[0] for p in allPts)) + 2
    mxy: int = int(max(p[1] for p in allPts)) + 2
    w: int = max(1, mxx - mnx)
    h: int = max(1, mxy - mny)
    try:
        tmp: pygame.Surface = pygame.Surface((w, h), pygame.SRCALPHA)
        col: tuple = (240, 180, 30, alpha)
        pygame.draw.polygon(tmp, col, [(x - mnx, y - mny) for x, y in shaftPts])
        pygame.draw.polygon(tmp, col, [(x - mnx, y - mny) for x, y in headPts])
        surf.blit(tmp, (mnx, mny))
    except Exception:
        pass


class Button:
    def __init__(
        self,
        rect: tuple,
        label: str,
        toggle: bool = False,
        colorOn: Optional[tuple] = None
    ) -> None:
        self.rect: pygame.Rect = pygame.Rect(rect)
        self.label: str = label
        self.toggle: bool = toggle
        self.active: bool = False
        self.hovered: bool = False
        self.colOn: tuple = colorOn or BTN_ACTIVE

    def draw(self, surf: pygame.Surface, font: pygame.font.Font) -> None:
        if self.toggle and self.active:
            col: tuple = self.colOn
        elif self.hovered:
            col = BTN_HOVER
        else:
            col = BTN_IDLE
        drawRr(surf, col, self.rect, 8)
        if self.hovered or (self.toggle and self.active):
            drawRrBorder(surf, (*col[:3], 80) if len(col) == 4 else ACCENT, self.rect, 8, 1)
        t: pygame.Surface = font.render(self.label, True, C_TEXT)
        surf.blit(t, t.get_rect(center=self.rect.center))

    def updateHover(self, mx: int, my: int) -> None:
        self.hovered = self.rect.collidepoint(mx, my)

    def onClick(self, mx: int, my: int) -> bool:
        if self.rect.collidepoint(mx, my):
            if self.toggle:
                self.active = not self.active
            return True
        return False


class Slider:
    TRACK_H: int = 6
    HANDLE_R: int = 9

    def __init__(
        self,
        rect: tuple,
        minVal: float,
        maxVal: float,
        value: float,
        step: float = 0.05
    ) -> None:
        self.rect: pygame.Rect = pygame.Rect(rect)
        self.minVal: float = float(minVal)
        self.maxVal: float = float(maxVal)
        self.value: float = float(value)
        self.step: float = float(step)
        self.drag: bool = False
        self.hover: bool = False

    def valToX(self) -> int:
        t: float = (self.value - self.minVal) / (self.maxVal - self.minVal)
        return int(self.rect.x + t * self.rect.width)

    def xToVal(self, mx: int) -> None:
        t: float = max(0.0, min(1.0, (mx - self.rect.x) / self.rect.width))
        raw: float = self.minVal + t * (self.maxVal - self.minVal)
        self.value = round(max(self.minVal, min(self.maxVal, round(raw / self.step) * self.step)), 3)

    def handleEvent(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            hx: int = self.valToX()
            cy: int = self.rect.centery

            if (
                (event.pos[0] - hx) ** 2 + (event.pos[1] - cy) ** 2 <= (self.HANDLE_R + 6) ** 2
                or self.rect.inflate(0, 16).collidepoint(event.pos)
            ):
                self.drag = True
                self.xToVal(event.pos[0])
                return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            was: bool = self.drag
            self.drag = False
            return was
        elif event.type == pygame.MOUSEMOTION:
            self.hover = self.rect.inflate(0, 20).collidepoint(event.pos)
            if self.drag:
                self.xToVal(event.pos[0])
            return True
        return False

    def draw(
        self,
        surf: pygame.Surface,
        font: pygame.font.Font,
        label: str = '',
        valueFmt: Optional[str] = None
    ) -> None:
        cy: int = self.rect.centery
        tr: pygame.Rect = pygame.Rect(self.rect.x, cy - self.TRACK_H // 2, self.rect.width, self.TRACK_H)
        drawRr(surf, C_BAR_BG, tr, 3)
        hx: int = self.valToX()
        fw: int = hx - self.rect.x
        if fw > 0:
            drawRr(surf, ACCENT, pygame.Rect(self.rect.x, cy - self.TRACK_H // 2, fw, self.TRACK_H), 3)
        hcol: tuple = C_SLIDER_H if (self.drag or self.hover) else C_SLIDER
        pygame.draw.circle(surf, hcol, (hx, cy), self.HANDLE_R)
        pygame.draw.circle(surf, C_TEXT, (hx, cy), self.HANDLE_R, 2)
        if label:
            ls: pygame.Surface = font.render(label, True, C_MUTED)
            surf.blit(ls, (self.rect.x, cy - ls.get_height() - self.HANDLE_R - 2))
        if valueFmt is not None:
            vs: pygame.Surface = font.render(valueFmt, True, C_TEXT)
            surf.blit(vs, (self.rect.right + 12, cy - vs.get_height() // 2))


class MainMenu:
    TAB_PLAY: int = 0
    TAB_LAN: int = 1
    TAB_SETTINGS: int = 2
    TAB_QUIT: int = 3
    # Each entry is (icon_char, label_text).  Icons are rendered with the
    # SYSTEM font; if the glyph is missing the text is shown alone.
    # 🌐 is a color emoji → always absent in pygame; replaced with ◈ (U+25C8).
    TAB_ICONS: list[str]  = ['♟', '◈', '⚙', '✕']
    TAB_TEXTS: list[str]  = ['PLAY', 'LAN', 'SETTINGS', 'QUIT']

    def __init__(
        self,
        screen: pygame.Surface,
        clock: pygame.time.Clock,
        audio: object,
        pieceSheets: PieceSheets,
        prev_config: Optional[dict] = None
    ) -> None:
        self.screen: pygame.Surface = screen
        self.clock: pygame.time.Clock = clock
        self.audio: object = audio
        self.pieceSheets: PieceSheets = pieceSheets
        p: dict = prev_config or {}

        gm: str = p.get('gameMode', 'local')
        # LAN games return to 'local' mode in the Play tab
        if gm in ('lan_host', 'lan_client'):
            self.gameMode: str = 'local'
        else:
            self.gameMode = gm
        self.aiColor: str = p.get('aiColor', 'b')
        d: str = p.get('aiDifficulty', 'Dana')
        self.aiDifficulty: str = d if d in AI_SETTINGS else 'Dana'
        self.cooldownSecs: float = p.get('cooldownSecs', DEFAULT_CD)
        self.fullscreen: bool = p.get('fullscreen', False)

        self.styleIdx: int = (
            STYLE_NAMES.index(pieceSheets.style)
            if pieceSheets.style in STYLE_NAMES else 0
        )
        self.musicVolume: float = audio.musicVolume
        self.sfxVolume: float = audio.sfxVolume

        # ── LAN state ──
        self.lanMode: str = p.get('lanMode', 'host')   # 'host' or 'join'
        self.lanIp: str = p.get('lanIp', '')
        self.lanIpActive: bool = False
        self.lanConnecting: bool = False
        self.lanError: str = ''
        self.lanNet: Optional[ChessNetwork] = None
        self._lanThread: Optional[threading.Thread] = None
        self._lanStop: threading.Event = threading.Event()
        self.localIp: str = get_local_ip()

        self.tab: int = self.TAB_PLAY
        self.fonts: dict[str, pygame.font.Font] = makeFonts(ChessCore.SQ)
        self.build()

    def build(self) -> None:
        f: dict = self.fonts
        W: int = ChessCore.WIN_W
        H: int = ChessCore.WIN_H
        cx: int = W // 2

        self.heroY: int = max(18, int(H * 0.05))
        self.heroH: int = f['hero'].get_height() + 8

        self.tabBarY: int = self.heroY + self.heroH + max(14, int(H * 0.025))
        tabH: int = max(38, f['tab'].get_height() + 18)
        nTabs: int = 4
        tabTotalW: int = min(680, int(W * 0.72))
        tabW: int = tabTotalW // nTabs
        tabX0: int = cx - tabTotalW // 2
        self.tabRects: list[pygame.Rect] = [
            pygame.Rect(tabX0 + i * tabW, self.tabBarY, tabW, tabH)
            for i in range(nTabs)
        ]
        self.tabH: int = tabH

        panelMargin: int = max(24, int(W * 0.06))
        self.panelX: int = panelMargin
        self.panelW: int = W - 2 * panelMargin
        self.panelY: int = self.tabBarY + tabH + 10
        self.panelH: int = H - self.panelY - 16
        self.panelRect: pygame.Rect = pygame.Rect(self.panelX, self.panelY, self.panelW, self.panelH)

        self.buildPlayTab()
        self.buildLanTab()
        self.buildSettingsTab()
        self.buildQuitTab()
        self.syncPlay()
        self.syncPresets()

    def buildPlayTab(self) -> None:
        f: dict = self.fonts
        sc: float = ChessCore.SQ / 80.0
        cx: int = self.panelX + self.panelW // 2
        y: int = self.panelY + max(16, int(24 * sc))

        bh: int = max(34, f['ui'].get_height() + max(8, int(14 * sc)))
        g: int = max(5, int(8 * sc))
        sg: int = max(4, int(6 * sc))
        bw: int = min(420, int((self.panelW - 60) * 0.70))
        x0: int = cx - bw // 2
        hw: int = (bw - sg) // 2

        self.lblY: dict[str, int] = {}

        self.lblY['mode'] = y
        y += f['sm'].get_height() + max(4, int(6 * sc))
        self.btnLocal = Button((x0,        y, hw, bh), "2-Player Local", toggle=True)
        self.btnVsAi  = Button((x0 + hw + sg, y, hw, bh), "vs  AI",       toggle=True)
        y += bh + g + max(8, int(14 * sc))

        self.lblY['ai'] = y
        y += f['sm'].get_height() + max(4, int(6 * sc))
        self.btnAiW = Button((x0,          y, hw, bh), "AI = White", toggle=True)
        self.btnAiB = Button((x0 + hw + sg, y, hw, bh), "AI = Black", toggle=True)
        y += bh + g

        self.lblY['diff'] = y
        y += f['sm'].get_height() + max(4, int(6 * sc))
        aw: int = max(32, bh)
        self.btnDiffPrev = Button((x0,            y, aw, bh), "◄")
        self.btnDiffNext = Button((x0 + bw - aw,  y, aw, bh), "►")
        self.diffRect: pygame.Rect = pygame.Rect(x0 + aw + sg, y, bw - 2 * aw - sg * 2, bh)
        y += bh + max(1, int(2 * sc))
        self.descY: int = y
        y += f['sm'].get_height() + max(8, int(14 * sc))

        self.lblY['cd'] = y
        y += f['sm'].get_height() + max(4, int(6 * sc))
        nPre: int = len(CD_PRESETS)
        preG: int = max(3, int(4 * sc))
        preBh: int = max(28, bh - max(4, int(8 * sc)))
        prW: int = (bw - preG * (nPre - 1)) // nPre
        self.btnPresets: list[Button] = []
        for i, (name, _) in enumerate(CD_PRESETS):
            self.btnPresets.append(Button((x0 + i * (prW + preG), y, prW, preBh), name, toggle=True))
        y += preBh + preG
        slW: int = int(bw * 0.72)
        self.sliderCd: Slider = Slider((x0, y, slW, bh), 0.1, 10.0, self.cooldownSecs, step=0.1)
        y += bh + max(12, int(20 * sc))

        sw: int = min(bw + 40, int((self.panelW - 60) * 0.55))
        self.btnStart: Button = Button(
            (cx - sw // 2, y, sw, bh + max(6, int(10 * sc))),
            "►   START GAME",
            colorOn=(25, 160, 90)
        )
        self.hintYPlay: int = ChessCore.WIN_H - max(14, int(22 * sc))

        self.playButtons: list[Button] = [
            self.btnLocal, self.btnVsAi, self.btnAiW, self.btnAiB,
            self.btnDiffPrev, self.btnDiffNext, self.btnStart,
        ] + self.btnPresets

    def buildLanTab(self) -> None:
        f: dict = self.fonts
        sc: float = ChessCore.SQ / 80.0
        cx: int = self.panelX + self.panelW // 2
        y: int = self.panelY + max(16, int(24 * sc))
        bh: int = max(34, f['ui'].get_height() + max(8, int(14 * sc)))
        g: int = max(5, int(8 * sc))
        sg: int = max(4, int(6 * sc))
        bw: int = min(420, int((self.panelW - 60) * 0.70))
        x0: int = cx - bw // 2
        hw: int = (bw - sg) // 2

        self.lanModeLblY: int = y
        y += f['sm'].get_height() + max(4, int(6 * sc))

        self.btnLanHost: Button = Button((x0, y, hw, bh), "Host Game", toggle=True)
        self.btnLanJoin: Button = Button((x0 + hw + sg, y, hw, bh), "Join Game", toggle=True)
        y += bh + g + max(8, int(14 * sc))

        self.lanIpLblY: int = y
        y += f['sm'].get_height() + max(4, int(6 * sc))
        self.lanIpRect: pygame.Rect = pygame.Rect(x0, y, bw, bh)
        y += bh + g

        self.lanStatusY: int = y
        y += f['sm'].get_height() + max(2, int(4 * sc)) + g + max(8, int(14 * sc))

        sw: int = min(bw + 40, int((self.panelW - 60) * 0.55))
        self.btnLanStart: Button = Button(
            (cx - sw // 2, y, sw, bh + max(6, int(10 * sc))),
            "►   CONNECT",
            colorOn=(25, 160, 90)
        )

        self._syncLanButtons()
        self.lanButtons: list[Button] = [self.btnLanHost, self.btnLanJoin, self.btnLanStart]

    def _syncLanButtons(self) -> None:
        if hasattr(self, 'btnLanHost'):
            self.btnLanHost.active = self.lanMode == 'host'
            self.btnLanJoin.active = self.lanMode == 'join'

    def _lanStart(self) -> None:
        if self.lanConnecting:
            return
        self.lanConnecting = True
        self.lanError = ''
        self.lanNet = None
        self._lanStop.clear()
        mode: str = self.lanMode
        ip: str = self.lanIp.strip()

        def worker() -> None:
            try:
                if mode == 'host':
                    self.lanNet = ChessNetwork.listen(stop_event=self._lanStop)
                else:
                    if not ip:
                        self.lanError = 'Enter the host IP address first'
                        return
                    self.lanNet = ChessNetwork.join(ip)
            except ConnectionAbortedError:
                self.lanError = ''
            except Exception as exc:
                self.lanError = str(exc)[:72]
                log.warning(f"LAN connect failed: {exc}")
            finally:
                if self.lanNet is None:
                    self.lanConnecting = False

        self._lanThread = threading.Thread(target=worker, daemon=True, name="LAN-Connect")
        self._lanThread.start()

    def _lanCancel(self) -> None:
        self._lanStop.set()
        self.lanConnecting = False
        self.lanError = ''
        if self.lanNet:
            self.lanNet.close()
            self.lanNet = None

    def buildSettingsTab(self) -> None:
        f: dict = self.fonts
        sc: float = ChessCore.SQ / 80.0
        cx: int = self.panelX + self.panelW // 2
        bw: int = min(380, int((self.panelW - 80) * 0.65))
        x0: int = cx - bw // 2
        y: int = self.panelY + max(18, int(30 * sc))
        bh: int = max(34, f['ui'].get_height() + max(8, int(14 * sc)))
        aw: int = max(32, bh)
        g: int = max(6, int(10 * sc))

        self.setStyleLblY: int = y
        y += f['med'].get_height() + max(6, int(10 * sc))
        self.btnStylePrev = Button((x0,          y, aw, bh), "◄")
        self.btnStyleNext = Button((x0 + bw - aw, y, aw, bh), "►")
        self.styleRect: pygame.Rect = pygame.Rect(x0 + aw + 4, y, bw - 2 * aw - 8, bh)
        y += bh + g + max(16, int(24 * sc))

        self.setDiv1Y: int = y
        y += max(10, int(16 * sc))

        self.setAudioLblY: int = y
        y += f['med'].get_height() + max(8, int(14 * sc))
        slW: int = int(bw * 0.68)

        self.setMvolLblY: int = y
        y += f['sm'].get_height() + max(4, int(6 * sc))
        self.sliderMusicVol: Slider = Slider((x0, y, slW, bh), 0.0, 1.0, self.musicVolume, step=0.05)
        y += bh + g + max(8, int(12 * sc))

        self.setSvolLblY: int = y
        y += f['sm'].get_height() + max(4, int(6 * sc))
        self.sliderSfxVol: Slider = Slider((x0, y, slW, bh), 0.0, 1.0, self.sfxVolume, step=0.05)
        y += bh + g + max(12, int(20 * sc))

        self.setMuteHintY: int = y
        self.setButtons: list[Button] = [self.btnStylePrev, self.btnStyleNext]

    def buildQuitTab(self) -> None:
        f: dict = self.fonts
        cx: int = self.panelX + self.panelW // 2
        bh: int = max(38, f['ui'].get_height() + 14)
        bw: int = min(240, int(self.panelW * 0.38))
        cy: int = self.panelY + self.panelH // 2
        g: int = 14
        self.btnQuitConfirm: Button = Button(
            (cx - bw // 2, cy - g // 2 - bh, bw, bh),
            "QUIT GAME",
            colorOn=(160, 40, 40)
        )
        self.btnQuitStay: Button = Button((cx - bw // 2, cy + g // 2, bw, bh), "Stay in Game")
        self.quitButtons: list[Button] = [self.btnQuitConfirm, self.btnQuitStay]

    def syncPlay(self) -> None:
        self.btnLocal.active = self.gameMode == 'local'
        self.btnVsAi.active  = self.gameMode == 'vs_ai'
        self.btnAiW.active   = self.aiColor  == 'w'
        self.btnAiB.active   = self.aiColor  == 'b'
        self._syncLanButtons()

    def syncPresets(self) -> None:
        for btn, (_, val) in zip(self.btnPresets, CD_PRESETS):
            btn.active = abs(self.cooldownSecs - val) < 0.05

    def cycleDiff(self, d: int) -> None:
        idx: int = DIFFICULTIES.index(self.aiDifficulty)
        self.aiDifficulty = DIFFICULTIES[(idx + d) % len(DIFFICULTIES)]

    def cycleStyle(self, d: int) -> None:
        self.styleIdx = (self.styleIdx + d) % len(STYLE_NAMES)
        newStyle: str = STYLE_NAMES[self.styleIdx]
        self.pieceSheets.setstyle(newStyle)
        self.pieceSheets.invalidateCache()
        log.info(f"MainMenu: piece style → {newStyle!r}")

    def toggleFs(self) -> None:
        if self.fullscreen:
            nw: int = max(640, ChessCore.WIN_W)
            nh: int = max(480, ChessCore.WIN_H)
            ChessCore.applyLayout(nw, nh)
            self.screen = pygame.display.set_mode((nw, nh), pygame.RESIZABLE)
            self.fullscreen = False
        else:
            info: pygame.display.Info = pygame.display.Info()
            ChessCore.applyLayout(info.current_w, info.current_h)
            self.screen = pygame.display.set_mode((info.current_w, info.current_h), pygame.FULLSCREEN)
            self.fullscreen = True
        self.fonts = makeFonts(ChessCore.SQ)
        self.build()

    def run(self) -> Optional[dict]:
        while True:
            try:
                mx: int
                my: int
                mx, my = pygame.mouse.get_pos()
                self.updateHovers(mx, my)

                # ── LAN connection completed? ───────────────────────────────
                if self.tab == self.TAB_LAN and self.lanNet is not None:
                    return self.cfg()

                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self._lanCancel()
                        pygame.quit()
                        raise SystemExit

                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            if self.fullscreen:
                                self.toggleFs()
                            elif self.tab == self.TAB_PLAY:
                                self._lanCancel()
                                pygame.quit()
                                raise SystemExit
                            elif self.tab == self.TAB_LAN and self.lanConnecting:
                                self._lanCancel()
                        if event.key == pygame.K_F11:
                            self.toggleFs()
                        if event.key == pygame.K_RETURN and self.tab == self.TAB_PLAY:
                            return self.cfg()
                        # LAN tab IP text input
                        if self.tab == self.TAB_LAN and self.lanIpActive and not self.lanConnecting:
                            if event.key == pygame.K_BACKSPACE:
                                self.lanIp = self.lanIp[:-1]
                            elif event.key == pygame.K_RETURN:
                                self._lanStart()
                            elif event.unicode and event.unicode.isprintable() and len(self.lanIp) < 39:
                                self.lanIp += event.unicode

                    if event.type == pygame.VIDEORESIZE and not self.fullscreen:
                        nw: int = max(640, event.w)
                        nh: int = max(480, event.h)
                        self.screen = pygame.display.set_mode((nw, nh), pygame.RESIZABLE)
                        ChessCore.applyLayout(nw, nh)
                        self.fonts = makeFonts(ChessCore.SQ)
                        self.build()

                    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                        ex: int = event.pos[0]
                        ey: int = event.pos[1]
                        for i, tr in enumerate(self.tabRects):
                            if tr.collidepoint(ex, ey):
                                self.tab = i
                                break

                        if self.tab == self.TAB_PLAY:
                            self.sliderCd.handleEvent(event)
                            self.cooldownSecs = round(self.sliderCd.value, 1)
                            self.syncPresets()
                            if self.btnStart.onClick(ex, ey):
                                return self.cfg()
                            elif self.btnLocal.onClick(ex, ey):
                                self.gameMode = 'local'
                                self.btnLocal.active = True
                                self.btnVsAi.active = False
                            elif self.btnVsAi.onClick(ex, ey):
                                self.gameMode = 'vs_ai'
                                self.btnVsAi.active = True
                                self.btnLocal.active = False
                            elif self.btnAiW.onClick(ex, ey) and self.gameMode == 'vs_ai':
                                self.aiColor = 'w'
                                self.btnAiW.active = True
                                self.btnAiB.active = False
                            elif self.btnAiB.onClick(ex, ey) and self.gameMode == 'vs_ai':
                                self.aiColor = 'b'
                                self.btnAiB.active = True
                                self.btnAiW.active = False
                            elif self.btnDiffPrev.onClick(ex, ey) and self.gameMode == 'vs_ai':
                                self.cycleDiff(-1)
                            elif self.btnDiffNext.onClick(ex, ey) and self.gameMode == 'vs_ai':
                                self.cycleDiff(+1)
                            else:
                                for btn, (_, val) in zip(self.btnPresets, CD_PRESETS):
                                    if btn.onClick(ex, ey):
                                        self.cooldownSecs = val
                                        self.sliderCd.value = val
                                        self.syncPresets()
                                        break

                        elif self.tab == self.TAB_LAN:
                            if self.lanConnecting:
                                if self.btnLanStart.onClick(ex, ey):
                                    self._lanCancel()
                            else:
                                if self.btnLanHost.onClick(ex, ey):
                                    self.lanMode = 'host'
                                    self._syncLanButtons()
                                    self.lanIpActive = False
                                elif self.btnLanJoin.onClick(ex, ey):
                                    self.lanMode = 'join'
                                    self._syncLanButtons()
                                    self.lanIpActive = True
                                elif self.btnLanStart.onClick(ex, ey):
                                    self._lanStart()
                                elif self.lanMode == 'join' and self.lanIpRect.collidepoint(ex, ey):
                                    self.lanIpActive = True
                                else:
                                    self.lanIpActive = False

                        elif self.tab == self.TAB_SETTINGS:
                            self.sliderMusicVol.handleEvent(event)
                            self.sliderSfxVol.handleEvent(event)
                            self.audio.setMusicVolume(self.sliderMusicVol.value)
                            self.audio.setSFXVolume(self.sliderSfxVol.value)
                            self.musicVolume = self.sliderMusicVol.value
                            self.sfxVolume = self.sliderSfxVol.value
                            if self.btnStylePrev.onClick(ex, ey):
                                self.cycleStyle(-1)
                            elif self.btnStyleNext.onClick(ex, ey):
                                self.cycleStyle(+1)

                        elif self.tab == self.TAB_QUIT:
                            if self.btnQuitConfirm.onClick(ex, ey):
                                self._lanCancel()
                                pygame.quit()
                                raise SystemExit
                            elif self.btnQuitStay.onClick(ex, ey):
                                self.tab = self.TAB_PLAY

                    elif event.type == pygame.MOUSEMOTION:
                        if self.tab == self.TAB_SETTINGS:
                            self.sliderMusicVol.handleEvent(event)
                            self.sliderSfxVol.handleEvent(event)
                            self.audio.setMusicVolume(self.sliderMusicVol.value)
                            self.audio.setSFXVolume(self.sliderSfxVol.value)
                        elif self.tab == self.TAB_PLAY:
                            self.sliderCd.handleEvent(event)
                            self.cooldownSecs = round(self.sliderCd.value, 1)
                            self.syncPresets()

                    elif event.type == pygame.MOUSEBUTTONUP:
                        if self.tab == self.TAB_SETTINGS:
                            self.sliderMusicVol.handleEvent(event)
                            self.sliderSfxVol.handleEvent(event)
                        elif self.tab == self.TAB_PLAY:
                            self.sliderCd.handleEvent(event)
                            self.cooldownSecs = round(self.sliderCd.value, 1)

                self.draw()
                self.clock.tick(FPS)

            except (SystemExit, pygame.error):
                raise
            except KeyboardInterrupt:
                log.info("KeyboardInterrupt caught in MainMenu.run() — quitting")
                self._lanCancel()
                pygame.quit()
                raise SystemExit

    def updateHovers(self, mx: int, my: int) -> None:
        for btn in self.playButtons:
            btn.updateHover(mx, my)
        for btn in self.lanButtons:
            btn.updateHover(mx, my)
        for btn in self.setButtons:
            btn.updateHover(mx, my)
        for btn in self.quitButtons:
            btn.updateHover(mx, my)

    def cfg(self) -> dict:
        c: dict = {
            'gameMode': self.gameMode,
            'aiColor': self.aiColor,
            'aiDifficulty': self.aiDifficulty,
            'cooldownSecs': self.cooldownSecs,
            'fullscreen': self.fullscreen,
            'screen': self.screen,
            'lanMode': self.lanMode,
            'lanIp': self.lanIp,
        }
        if self.lanNet is not None:
            c['gameMode'] = 'lan_host' if self.lanNet.isHost else 'lan_client'
            c['lanNet'] = self.lanNet
        return c

    def draw(self) -> None:
        surf: pygame.Surface = self.screen
        W: int = ChessCore.WIN_W
        H: int = ChessCore.WIN_H
        f: dict = self.fonts
        surf.fill(MENU_BG)

        sq: int = 28
        for r in range(6):
            for c in range(6):
                col: tuple = (22, 27, 50) if (r + c) % 2 == 0 else (18, 22, 44)
                pygame.draw.rect(surf, col, (c * sq, H - (r + 1) * sq, sq, sq))
                pygame.draw.rect(surf, col, (W - (c + 1) * sq, r * sq, sq, sq))

        cx: int = W // 2

        # ── hero title: queen icon from SYSTEM font + title text from UI font ──
        heroText: str = "REAL-TIME CHESS"
        heroSurf: pygame.Surface = renderGlyphLabel(
            '♛', '  ' + heroText, f['sym_hero'], f['hero'], C_TEXT, gap=0
        )
        surf.blit(heroSurf, heroSurf.get_rect(centerx=cx, top=self.heroY))
        sub: pygame.Surface = f['sm'].render("Real-time piece cooldowns  •  AI opponents  •  Full analysis", True, C_MUTED)
        surf.blit(sub, sub.get_rect(centerx=cx, top=self.heroY + heroSurf.get_height() + 4))

        # ── tabs: render each icon+label independently via renderGlyphLabel ──
        for i, rect in enumerate(self.tabRects):
            active: bool = i == self.tab
            bg: tuple = TAB_ACTIVE_BG  if active else TAB_IDLE_BG
            tc: tuple = TAB_ACTIVE_TXT if active else TAB_IDLE_TXT
            r: pygame.Rect = pygame.Rect(rect.x, rect.y, rect.w, rect.h)
            drawRr(surf, bg, r, 10)
            if active:
                pygame.draw.rect(surf, TAB_ACTIVE_BG, (r.x, r.bottom - 6, r.w, 6))
            ls: pygame.Surface = renderGlyphLabel(
                self.TAB_ICONS[i], self.TAB_TEXTS[i],
                f['sym_tab'], f['tab'], tc
            )
            surf.blit(ls, ls.get_rect(center=r.center))

        drawRr(surf, PANEL_BG, self.panelRect, 14)
        drawRrBorder(surf, DIVIDER, self.panelRect, 14, 1)

        if self.tab == self.TAB_PLAY:
            self.drawPlayTab(surf, f)
        elif self.tab == self.TAB_LAN:
            self.drawLanTab(surf, f)
        elif self.tab == self.TAB_SETTINGS:
            self.drawSettingsTab(surf, f)
        elif self.tab == self.TAB_QUIT:
            self.drawQuitTab(surf, f)

        hint: pygame.Surface = f['sm'].render("F11 = Fullscreen   ESC = Quit", True, C_MUTED)
        surf.blit(hint, hint.get_rect(centerx=cx, bottom=H - 6))

        pygame.display.flip()

    def drawPlayTab(self, surf: pygame.Surface, f: dict) -> None:
        vs: bool = self.gameMode == 'vs_ai'
        cx: int = self.panelX + self.panelW // 2
        x0: int = self.btnLocal.rect.left

        def sec(text: str, y: int) -> None:
            ls: pygame.Surface = f['sm'].render(text, True, SEC_HDR)
            surf.blit(ls, (x0, y))

        def dim(r: pygame.Rect) -> None:
            ov: pygame.Surface = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
            ov.fill((*PANEL_BG, 180))
            surf.blit(ov, r.topleft)

        sec("GAME MODE", self.lblY['mode'])
        sec("AI COLOUR", self.lblY['ai'])
        sec("AI PERSONALITY", self.lblY['diff'])
        sec("PIECE COOLDOWN", self.lblY['cd'])

        aiBtns: set = {self.btnAiW, self.btnAiB, self.btnDiffPrev, self.btnDiffNext}
        
        for btn in self.playButtons:
            btn.draw(surf, f['ui'])
            
            if btn in aiBtns and not vs:
                dim(btn.rect)

        pers: dict = AI_SETTINGS.get(self.aiDifficulty, {})
        dr: pygame.Rect = self.diffRect
        drawRr(surf, C_BTN, dr, 8)
        dotCol: tuple = C_DIFF_CLR.get(self.aiDifficulty, C_TEXT)
        nameS: pygame.Surface = f['ui'].render(self.aiDifficulty, True, C_TEXT)
        ratingS: pygame.Surface = f['sm'].render(f"(~{pers.get('rating', '?')})", True, C_MUTED)
        styleS: pygame.Surface = f['sm'].render(pers.get('style', ''), True, dotCol)
        totalW: int = nameS.get_width() + 6 + ratingS.get_width()
        tx: int = dr.centerx - totalW // 2
        styleReserve: int = (styleS.get_height() + 2) if vs else 0
        ty: int = dr.centery - (nameS.get_height() + styleReserve) // 2
        surf.blit(nameS, (tx, ty))
        surf.blit(
            ratingS,
            (tx + nameS.get_width() + 6, ty + (nameS.get_height() - ratingS.get_height()) // 2 + 1)
        )
        if vs:
            styleY: int = ty + nameS.get_height() + 2
            surf.blit(styleS, styleS.get_rect(centerx=dr.centerx, top=styleY))
        if not vs:
            dim(dr)

        if vs and pers:
            desc: pygame.Surface = f['sm'].render(pers.get('desc', ''), True, (160, 168, 200))
            surf.blit(desc, desc.get_rect(centerx=cx, y=self.descY))

        self.sliderCd.draw(surf, f['sm'], valueFmt=f"{self.cooldownSecs:.1f}s")

    def drawLanTab(self, surf: pygame.Surface, f: dict) -> None:
        cx: int = self.panelX + self.panelW // 2
        x0: int = self.btnLanHost.rect.left

        def sec(text: str, y: int) -> None:
            surf.blit(f['sm'].render(text, True, SEC_HDR), (x0, y))

        sec("CONNECTION MODE", self.lanModeLblY)

        # Mode toggle buttons
        self.btnLanHost.draw(surf, f['ui'])
        self.btnLanJoin.draw(surf, f['ui'])

        # IP section
        if self.lanMode == 'host':
            sec("YOUR LOCAL IP  —  share this with the other player", self.lanIpLblY)
            r: pygame.Rect = self.lanIpRect
            drawRr(surf, C_BAR_BG, r, 8)
            ipS: pygame.Surface = f['ui'].render(self.localIp, True, (140, 210, 160))
            surf.blit(ipS, ipS.get_rect(center=r.center))
        else:
            sec("HOST IP ADDRESS", self.lanIpLblY)
            r = self.lanIpRect
            borderCol: tuple = ACCENT if self.lanIpActive else DIVIDER
            drawRr(surf, C_BAR_BG, r, 8)
            pygame.draw.rect(surf, borderCol, r, 2, border_radius=8)
            cursor: str = '|' if (self.lanIpActive and int(time.time() * 2) % 2 == 0) else ''
            placeholder: bool = not self.lanIp
            ipTxt: str = (self.lanIp + cursor) if not placeholder else 'e.g. 192.168.1.42'
            ipCol: tuple = C_TEXT if not placeholder else C_MUTED
            ipS = f['ui'].render(ipTxt, True, ipCol)
            surf.blit(ipS, ipS.get_rect(midleft=(r.left + 12, r.centery)))

        # Status / error line
        if self.lanConnecting:
            msg: str = "Waiting for opponent to connect..." if self.lanMode == 'host' else "Connecting to host..."
            pulse: float = 0.55 + 0.45 * math.sin(time.time() * 3.0)
            stCol: tuple = (int(140 * pulse + 60), int(200 * pulse + 20), int(100 * pulse + 40))
            st: pygame.Surface = f['sm'].render(msg, True, stCol)
        elif self.lanError:
            st = f['sm'].render(f"  ✕  {self.lanError}", True, (220, 80, 80))
        else:
            hint: str = (
                f"Other player connects to your IP: {self.localIp}"
                if self.lanMode == 'host'
                else "Enter the host's IP above, then click Connect"
            )
            st = f['sm'].render(hint, True, C_MUTED)
        surf.blit(st, st.get_rect(centerx=cx, y=self.lanStatusY))

        # Port info
        portHint: pygame.Surface = f['sm'].render(f"LAN port: 55765  •  Both players must be on the same network", True, (60, 70, 100))
        surf.blit(portHint, portHint.get_rect(centerx=cx, y=self.lanStatusY + st.get_height() + 4))

        # Connect / Cancel button
        self.btnLanStart.label = "■   CANCEL" if self.lanConnecting else "►   CONNECT"
        self.btnLanStart.draw(surf, f['ui'])

    def drawSettingsTab(self, surf: pygame.Surface, f: dict) -> None:
        cx: int = self.panelX + self.panelW // 2
        x0: int = self.btnStylePrev.rect.left

        def sec(text: str, y: int) -> None:
            surf.blit(f['med'].render(text, True, SEC_HDR), (x0, y))

        sec("PIECE STYLE", self.setStyleLblY)
        for btn in self.setButtons:
            btn.draw(surf, f['ui'])

        styleName: str = STYLE_NAMES[self.styleIdx]
        sr: pygame.Rect = self.styleRect
        drawRr(surf, C_BTN, sr, 8)
        availableStyles: list[str] = (
            self.pieceSheets.availablestyles()
            if hasattr(self.pieceSheets, 'availablestyles') else []
        )
        avail: bool = styleName in availableStyles
        dotCol: tuple = ACCENT if avail else (140, 50, 50)
        pygame.draw.circle(surf, dotCol, (sr.x + 14, sr.centery), 5)
        ns: pygame.Surface = f['ui'].render(styleName, True, C_TEXT)
        surf.blit(ns, ns.get_rect(center=sr.center))
        availS: pygame.Surface = f['sm'].render(
            "✓ loaded" if avail else "sheet not found",
            True, dotCol
        )
        surf.blit(availS, (sr.x + 22, sr.bottom + 3))

        pygame.draw.line(
            surf, DIVIDER,
            (x0, self.setDiv1Y + 8),
            (x0 + self.styleRect.right - self.styleRect.left + 80, self.setDiv1Y + 8),
            1
        )

        sec("AUDIO", self.setAudioLblY)

        surf.blit(f['sm'].render("Music Volume", True, C_MUTED), (x0, self.setMvolLblY))
        self.sliderMusicVol.draw(
            surf, f['sm'],
            valueFmt=f"{int(self.sliderMusicVol.value * 100)}%"
        )

        surf.blit(f['sm'].render("SFX Volume", True, C_MUTED), (x0, self.setSvolLblY))
        self.sliderSfxVol.draw(
            surf, f['sm'],
            valueFmt=f"{int(self.sliderSfxVol.value * 100)}%"
        )

        if self.audio.muted:
            ms: pygame.Surface = f['sm'].render("[MUTED]  ALL SOUND MUTED", True, MUTE_RED)
            surf.blit(ms, ms.get_rect(x=x0, y=self.setMuteHintY))
        else:
            hint: pygame.Surface = f['sm'].render(
                "Press  M  during a game to toggle mute all sound",
                True, C_MUTED
            )
            surf.blit(hint, (x0, self.setMuteHintY))

    def drawQuitTab(self, surf: pygame.Surface, f: dict) -> None:
        cx: int = self.panelX + self.panelW // 2

        qs: pygame.Surface = renderGlyphLabel(
            '♔', '  Ready to leave the board?', f['sym_tab'], f['big'], C_TEXT, gap=0
        )
        surf.blit(qs, qs.get_rect(centerx=cx, bottom=self.btnQuitConfirm.rect.top - 20))

        for btn in self.quitButtons:
            btn.draw(surf, f['ui'])


class Game:
    def __init__(self, config: dict, audio: object, pieceSheets: PieceSheets) -> None:
        self.screen: pygame.Surface = config['screen']
        self.fullscreen: bool = config.get('fullscreen', False)
        pygame.display.set_caption("Real-Time Chess")
        self.clock: pygame.time.Clock = pygame.time.Clock()
        self.audio: object = audio
        self.pieceSheets: PieceSheets = pieceSheets

        self.fonts: dict[str, pygame.font.Font] = makeFonts(ChessCore.SQ)

        self.cooldownSecs: float = config['cooldownSecs']
        self.helpMode: bool = False
        self.events: List[str] = []
        self.promoRects: Dict[str, pygame.Rect] = {}

        self.gameMode: str = config['gameMode']
        self.aiColor: str = config['aiColor']
        self.aiDifficulty: str = config['aiDifficulty']
        self.ai: Optional[ChessAI] = None
        self.aiKickTimer: float = 0.0
        self.aiDots: int = 0
        self.aiDotT: float = 0.0

        # ── LAN ───────────────────────────────────────────────────────────
        self.net: Optional[ChessNetwork] = config.get('lanNet', None)
        if self.gameMode == 'lan_host':
            self.lanMyColor: str = 'w'
        elif self.gameMode == 'lan_client':
            self.lanMyColor: str = 'b'
        else:
            self.lanMyColor = 'w'
        self.pendingLanMove: Optional[tuple] = None   # (fc, fr, tc, tr) awaiting promo on client
        self._lanDisconnected: bool = False

        self.moveHistory: List[dict] = []
        self.gameStartTime: float = time.time()
        self.analyzeBtn: Optional[Button] = None

        self.buildSidebar()
        self.reset()

    def buildSidebar(self) -> None:
        f: dict = self.fonts
        sx: int = ChessCore.SB_X
        sc: float = ChessCore.SQ / 80.0
        sg: int = max(2, int(4 * sc))
        mg: int = max(5, int(10 * sc))
        g: int = max(5, int(7 * sc))
        bh: int = max(24, f['ui'].get_height() + max(6, int(10 * sc)))
        tipGap: int = max(3, int(6 * sc))
        divStep: int = max(1, int(2 * sc))
        h: int = (
            mg
            + f['big'].get_height() + sg
            + f['med'].get_height() + sg
            + f['sm'].get_height()  + sg
            + f['sm'].get_height()  + tipGap
            + divStep + mg
        )
        y: int = h
        self.btnHelp: Button    = Button((sx, y, ChessCore.SB_W, bh), "Help Mode",    toggle=True)
        y += bh + g
        self.btnRestart: Button = Button((sx, y, ChessCore.SB_W, bh), "Restart")
        y += bh + g
        self.btnMenu: Button    = Button((sx, y, ChessCore.SB_W, bh), "Back to Menu")
        y += bh + g
        self.sbCdY: int   = y + sg
        self.sbBodyY: int = y + sg + f['ui'].get_height() + max(3, int(6 * sc))
        self.buttons: list[Button] = [self.btnHelp, self.btnRestart, self.btnMenu]
        self.btnHelp.active = self.helpMode

    def applyWindow(self, fullscreen: bool = False, w: Optional[int] = None, h: Optional[int] = None) -> None:
        self.fullscreen = fullscreen
        if fullscreen:
            info: pygame.display.Info = pygame.display.Info()
            ChessCore.applyLayout(info.current_w, info.current_h)
            self.screen = pygame.display.set_mode((info.current_w, info.current_h), pygame.FULLSCREEN)
        else:
            nw: int = max(640, w or ChessCore.WIN_W)
            nh: int = max(480, h or ChessCore.WIN_H)
            ChessCore.applyLayout(nw, nh)
            self.screen = pygame.display.set_mode((nw, nh), pygame.RESIZABLE)
        self.fonts = makeFonts(ChessCore.SQ)
        self.pieceSheets.invalidateCache()
        self.buildSidebar()

    def reset(self) -> None:
        if self.ai:
            self.ai.cancelSearch()
        self.piecesLock: threading.Lock = threading.Lock()
        self.pieces: list = initPieces()
        self.selected: Optional[object] = None
        self.validMvs: set = set()
        self.gameOver: Optional[str] = None
        self.epSq: Optional[tuple[int, int]] = None
        self.epExpiry: float = 0.0
        self.promoPiece: Optional[object] = None
        self.events.clear()
        self.promoRects = {}
        if self.gameMode == 'vs_ai':
            self.ai = ChessAI(self.aiColor, self.aiDifficulty)
            self.aiKickTimer = AI_SETTINGS[self.aiDifficulty]['delay']
        else:
            self.ai = None
            self.aiKickTimer = 0.0
        self.moveHistory = []
        self.gameStartTime = time.time()
        self.analyzeBtn = None
        # LAN: preserve net, reset transient state only
        self.pendingLanMove = None
        self._lanDisconnected = False

    def pieceAt(self, col: int, row: int) -> Optional[object]:
        for p in self.pieces:
            if p.alive and p.col == col and p.row == row:
                return p
        return None

    def logEvent(self, msg: str) -> None:
        self.events.append(msg)
        if len(self.events) > 20:
            self.events.pop(0)

    def epNow(self) -> Optional[tuple[int, int]]:
        return self.epSq if (self.epSq and time.time() < self.epExpiry) else None

    def executeMove(self, piece: object, tc: int, tr: int, *, silent: bool = False) -> None:
        tgt: Optional[object] = self.pieceAt(tc, tr)
        cap: Optional[str] = tgt.ptype if (tgt and tgt.color != piece.color) else None
        self.moveHistory.append({
            'color': piece.color,
            'ptype': piece.ptype,
            'fromSq': (piece.col, piece.row),
            'toSq': (tc, tr),
            'capture': cap,
            't': time.time() - self.gameStartTime,
        })

        wasOver: bool = bool(self.gameOver)

        with self.piecesLock:
            ltr: str = 'abcdefgh'[tc]
            lbl: str = f"{'W' if piece.color == 'w' else 'B'} {piece.ptype}"
            ep: Optional[tuple[int, int]] = self.epNow()

            if piece.ptype == 'P' and ep and (tc, tr) == ep:
                capPiece: Optional[object] = self.pieceAt(tc, piece.row)
                if capPiece and capPiece.color != piece.color:
                    capPiece.alive = False
                    if not silent:
                        self.logEvent(f"{lbl} en passant at {ltr}{8 - tr}!")
            else:
                target: Optional[object] = self.pieceAt(tc, tr)
                if target and target.color != piece.color:
                    target.alive = False
                    if not silent:
                        self.logEvent(f"{lbl} captures {target.ptype} at {ltr}{8 - tr}")
                    if target.ptype == 'K':
                        self.gameOver = ("White wins!" if piece.color == 'w' else "Black wins!")

            if piece.ptype == 'K' and abs(tc - piece.col) == 2:
                br: int = piece.row
                if tc == 6:
                    rk: Optional[object] = self.pieceAt(7, br)
                    if rk:
                        rk.col = 5
                    rk.hasMoved = True
                    rk.cooldown = self.cooldownSecs
                    if not silent:
                        self.logEvent(f"{lbl} castles kingside")
                else:
                    rk = self.pieceAt(0, br)
                    if rk:
                        rk.col = 3
                    rk.hasMoved = True
                    rk.cooldown = self.cooldownSecs
                    if not silent:
                        self.logEvent(f"{lbl} castles queenside")

            if piece.ptype == 'P' and abs(tr - piece.row) == 2:
                self.epSq    = (tc, (piece.row + tr) // 2)
                self.epExpiry = time.time() + self.cooldownSecs

            piece.col = tc
            piece.row = tr
            piece.hasMoved = True
            piece.cooldown = self.cooldownSecs
            piece.premove = None

            if piece.ptype == 'P' and (tr == 0 or tr == 7):
                if self.gameMode == 'vs_ai' and piece.color == self.aiColor:
                    best: str = smartAiPromotion(toBoard(self.pieces), tc, tr, piece.color)
                    piece.ptype = best
                    piece.cooldown = self.cooldownSecs
                    if not silent:
                        self.logEvent(f"AI promotes to {PROMO_NAMES[best]}!")
                else:
                    self.promoPiece = piece
                    piece.cooldown = 9999.0

        if self.gameOver and not wasOver:
            self.audio.fadeoutMusic(1500)

        if not silent:
            self.logEvent(f"{lbl} -> {ltr}{8 - tr}")
            self.audio.playMove()

        # LAN host: push authoritative snapshot to client after every resolved move
        # (skip if promoPiece is now set — choosePromotion will broadcast after the choice)
        if self.gameMode == 'lan_host' and self.net and self.net.alive:
            if not self.promoPiece:
                self._broadcastState()

    def aiTick(self, dt: float) -> None:
        if not self.ai or self.gameOver or self.promoPiece:
            return
        self.aiDotT += dt
        if self.aiDotT >= 0.4:
            self.aiDotT = 0.0
            self.aiDots = (self.aiDots + 1) % 4
        if self.aiKickTimer > 0:
            self.aiKickTimer = max(0.0, self.aiKickTimer - dt)
            return
        if not self.ai.isThinking() and self.ai.getResult() is None:
            with self.piecesLock:
                anyReady: bool = any(
                    p.alive and p.color == self.aiColor and p.cooldown <= 0
                    for p in self.pieces
                )
            if not anyReady:
                self.aiKickTimer = 0.1
                return
            self.ai.kickOff(self.pieces, self.epNow(), self.piecesLock)
            return
        r: Optional[tuple] = self.ai.consumeResult()
        if r is None:
            return
        sc, sr, tc, tr = r
        real: Optional[object] = self.pieceAt(sc, sr)
        if real is None or real.color != self.aiColor:
            self.aiKickTimer = AI_SETTINGS[self.aiDifficulty]['delay']
            return
        if real.ready():
            valid: set = pseudoLegalMoves(real, self.pieces, self.epNow())
            if (tc, tr) in valid:
                self.executeMove(real, tc, tr)
            self.aiKickTimer = AI_SETTINGS[self.aiDifficulty]['delay']
        else:
            self.aiKickTimer = 0.1

    def _broadcastState(self) -> None:
        """Host → Client: push authoritative board snapshot over the socket."""
        if not self.net or not self.net.isHost or not self.net.alive:
            return
        epNow: Optional[tuple] = self.epSq if (self.epSq and time.time() < self.epExpiry) else None
        with self.piecesLock:
            js: str = piecesToJSON(
                self.pieces, epNow, self.epExpiry, self.cooldownSecs, self.gameOver
            )
        self.net.sendState(js)

    def lanTick(self) -> None:
        """Drain the incoming network queue and react to each message (called every frame)."""
        if not self.net:
            return
        if not self.net.alive:
            if not self.gameOver and not self._lanDisconnected:
                self.gameOver = "Opponent disconnected"
                self._lanDisconnected = True
                self.audio.fadeoutMusic(1500)
            return

        for kind, data in self.net.drainIncoming():
            if kind == 'DISCONNECT':
                if not self.gameOver and not self._lanDisconnected:
                    self.gameOver = "Opponent disconnected"
                    self._lanDisconnected = True
                    self.audio.fadeoutMusic(1500)

            elif kind == 'MOVE' and self.gameMode == 'lan_host':
                # Host receives move intention from client, validates and applies it
                fc: int
                fr: int
                tc: int
                tr: int
                promo: str
                fc, fr, tc, tr, promo = data
                with self.piecesLock:
                    piece = self.pieceAt(fc, fr)
                if piece and piece.color != self.lanMyColor and piece.ready():
                    ep: Optional[tuple] = self.epNow()
                    valid: set = pseudoLegalMoves(piece, self.pieces, ep)
                    if (tc, tr) in valid:
                        self.executeMove(piece, tc, tr)
                        if self.promoPiece and self.promoPiece is piece:
                            pt: str = promo if promo in PROMO_TYPES else 'Q'
                            self.choosePromotion(pt)
                # Always broadcast so client sees the result (or rejected move)
                self._broadcastState()

            elif kind == 'STATE' and self.gameMode == 'lan_client':
                # Client replaces its board with the host's authoritative snapshot
                with self.piecesLock:
                    ep2, epExp2, _ = piecesFromJSON(data, self.pieces)
                    self.epSq = ep2
                    self.epExpiry = epExp2
                go: Optional[str] = data.get('gameOver')
                if go and not self.gameOver:
                    self.gameOver = go
                    self.audio.fadeoutMusic(1500)
                self.audio.playMove()

            elif kind == 'GAME_OVER':
                if not self.gameOver:
                    self.gameOver = data
                    self.audio.fadeoutMusic(1500)

    def update(self, dt: float) -> None:
        if self.selected and not self.selected.alive:
            self.selected = None
            self.validMvs = set()
        # LAN: always drain network, even when gameOver (to catch DISCONNECT)
        try:
            self.lanTick()
        except Exception:
            log.exception("EXCEPTION in lanTick")
        if self.gameOver:
            return
        try:
            self.aiTick(dt)
        except Exception:
            log.exception("EXCEPTION in aiTick")
        try:
            # Client cooldowns are authoritative only on the host; client shows
            # real-time bars by ticking locally between STATE updates (cosmetic only)
            with self.piecesLock:
                for p in self.pieces:
                    if not p.alive:
                        continue
                    if p.cooldown > 0 and p is not self.promoPiece:
                        p.cooldown = max(0.0, p.cooldown - dt)
        except Exception:
            log.exception("EXCEPTION in cooldown update")
        try:
            # Premoves only for local/vs_ai modes
            if self.gameMode not in ('lan_host', 'lan_client'):
                for p in list(self.pieces):
                    if self.gameOver:
                        break
                    if p.ready() and p.premove is not None:
                        tc, tr = p.premove
                        if (tc, tr) in pseudoLegalMoves(p, self.pieces, self.epNow()):
                            self.executeMove(p, tc, tr, silent=True)
                            self.logEvent(
                                f"{'W' if p.color == 'w' else 'B'} {p.ptype} premove"
                                f" -> {'abcdefgh'[tc]}{8 - tr}"
                            )
                        else:
                            p.premove = None
                            self.logEvent(f"{'W' if p.color == 'w' else 'B'} premove cancelled")
        except Exception:
            log.exception("EXCEPTION in premove loop")

    def choosePromotion(self, ptype: str) -> None:
        if not self.promoPiece:
            return
        pp: object = self.promoPiece

        # LAN CLIENT — send the complete move (with chosen promo type) to host,
        # then unfreeze the piece locally; the incoming STATE will correct the board.
        if self.gameMode == 'lan_client' and self.pendingLanMove:
            fc: int
            fr: int
            tc: int
            tr: int
            fc, fr, tc, tr = self.pendingLanMove
            if self.net and self.net.alive:
                self.net.sendMove(fc, fr, tc, tr, ptype)
            with self.piecesLock:
                pp.cooldown = 0.0   # unfreeze locally; host STATE overwrites momentarily
            self.promoPiece = None
            self.pendingLanMove = None
            return

        # Local / LAN-host promotion
        pp.ptype = ptype
        pp.cooldown = self.cooldownSecs
        self.logEvent(f"{'W' if pp.color == 'w' else 'B'} promotes to {PROMO_NAMES[ptype]}!")
        self.promoPiece = None

        # LAN host: broadcast the now-resolved promotion state
        if self.gameMode == 'lan_host' and self.net and self.net.alive:
            self._broadcastState()

    def handleBoardClick(self, mx: int, my: int, btn: int) -> None:
        if self.gameOver:
            return
        sq: Optional[tuple[int, int]] = sqFromMouse(mx, my)
        if sq is None:
            return
        col: int = sq[0]
        row: int = sq[1]
        clicked: Optional[object] = self.pieceAt(col, row)
        ep: Optional[tuple[int, int]] = self.epNow()
        isLan: bool = self.gameMode in ('lan_host', 'lan_client')

        if btn == 3:
            if self.selected:
                self.selected.premove = None
            self.selected = None
            self.validMvs = set()
            return

        if self.selected:
            piece: object = self.selected
            if clicked and clicked.color == piece.color:
                # Switching selection to another own piece
                if self.gameMode == 'vs_ai' and clicked.color == self.aiColor:
                    self.selected = None
                    self.validMvs = set()
                    return
                if isLan and clicked.color != self.lanMyColor:
                    self.selected = None
                    self.validMvs = set()
                    return
                self.selected = clicked
                self.validMvs = pseudoLegalMoves(clicked, self.pieces, ep)
                return

            if (col, row) in self.validMvs:
                if self.gameMode == 'lan_client':
                    # Client sends intention to host; board is read-only until STATE arrives
                    if piece.ready():
                        fc: int = piece.col
                        fr: int = piece.row
                        promo_row: int = 0 if piece.color == 'b' else 7
                        if piece.ptype == 'P' and row == promo_row:
                            # Show promotion modal; defer MOVE send until promo chosen
                            self.pendingLanMove = (fc, fr, col, row)
                            with self.piecesLock:
                                self.promoPiece = piece
                                piece.cooldown = 9999.0
                        else:
                            if self.net and self.net.alive:
                                self.net.sendMove(fc, fr, col, row)
                    # Premoves disabled for LAN client (host is the clock authority)
                elif piece.ready():
                    self.executeMove(piece, col, row)
                else:
                    if not isLan:   # premoves only in local/vs_ai modes
                        piece.premove = (col, row)
                        self.logEvent(
                            f"{'W' if piece.color == 'w' else 'B'} {piece.ptype}"
                            f" premoved -> {'abcdefgh'[col]}{8 - row}"
                        )

            self.selected = None
            self.validMvs = set()
        else:
            if clicked:
                if self.gameMode == 'vs_ai' and clicked.color == self.aiColor:
                    return
                if isLan and clicked.color != self.lanMyColor:
                    return
                self.selected = clicked
                self.validMvs = pseudoLegalMoves(clicked, self.pieces, ep)

    def drawBoard(self) -> None:
        f: dict = self.fonts
        pygame.draw.rect(
            self.screen, C_BORDER,
            pygame.Rect(ChessCore.BX - 4, ChessCore.BY - 4, ChessCore.BOARD_PX + 8, ChessCore.BOARD_PX + 8),
            border_radius=6
        )
        for r in range(8):
            for c in range(8):
                pygame.draw.rect(
                    self.screen,
                    C_LIGHT if (c + r) % 2 == 0 else C_DARK,
                    sqRect(c, r)
                )
        offF: int = max(3, ChessCore.SQ // 16)
        offR: int = max(3, ChessCore.SQ // 14)
        fileY: int = ChessCore.BY + ChessCore.BOARD_PX + offF
        for i in range(8):
            lf: pygame.Surface = f['sm'].render("abcdefgh"[i], True, C_MUTED)
            if fileY + lf.get_height() <= ChessCore.WIN_H - 2:
                self.screen.blit(
                    lf,
                    (ChessCore.BX + i * ChessCore.SQ + ChessCore.SQ // 2 - lf.get_width() // 2, fileY)
                )
            lr: pygame.Surface = f['sm'].render(str(8 - i), True, C_MUTED)
            rankX: int = ChessCore.BX - lr.get_width() - offR
            if rankX >= 0:
                self.screen.blit(
                    lr,
                    (rankX, ChessCore.BY + i * ChessCore.SQ + ChessCore.SQ // 2 - lr.get_height() // 2)
                )

    def drawHighlights(self) -> None:
        try:
            alive: list = self.pieces
            sel: Optional[object] = self.selected
            ep: Optional[tuple[int, int]] = self.epNow()
            t: float = time.time()
            bThr: set = allThreatened(alive, 'b', ep)
            wThr: set = allThreatened(alive, 'w', ep)

            if ep:
                alphaRect(self.screen, HL_EP, sqRect(*ep))

            for p in alive:
                if not p.alive or (self.ai and p.color == self.ai.color) or p.ptype != 'K':
                    continue
                oppColor: str = 'b' if p.color == 'w' else 'w'
                oppThr: set = allThreatened(alive, oppColor, ep)
                if (p.col, p.row) in oppThr:
                    pulse: float = 0.5 + 0.5 * math.sin(t * 6.0)
                    alphaRect(self.screen, (220, 35, 35, int(130 + 80 * pulse)), sqRect(p.col, p.row))
                    kx: int = ChessCore.BX + p.col * ChessCore.SQ + ChessCore.SQ // 2
                    ky: int = ChessCore.BY + p.row * ChessCore.SQ + ChessCore.SQ // 2
                    for attacker in alive:
                        if not attacker.alive or attacker.color != oppColor:
                            continue
                        if (p.col, p.row) in pseudoLegalMoves(attacker, alive, ep):
                            ax: int = ChessCore.BX + attacker.col * ChessCore.SQ + ChessCore.SQ // 2
                            ay: int = ChessCore.BY + attacker.row * ChessCore.SQ + ChessCore.SQ // 2
                            drawThreatArrow(self.screen, ax, ay, kx, ky, 200)

            for p in alive:
                if not p.alive:
                    continue
                rect: pygame.Rect = sqRect(p.col, p.row)
                if p.premove:
                    col: tuple = HL_PREMW if p.color == 'w' else HL_PREMB
                    alphaRect(self.screen, col, rect)
                    tc, tr = p.premove
                    alphaRect(self.screen, col, sqRect(tc, tr))

            if sel:
                alphaRect(self.screen, HL_SEL, sqRect(sel.col, sel.row))

                def squareThreatLevel(c: int, r: int) -> str:
                    if sel.color == 'w':
                        if (c, r) in bThr:
                            return 'danger'
                        for p2 in alive:
                            if (p2.alive and p2.color == 'b'
                                    and p2.cooldown < self.cooldownSecs * 0.5):
                                if (c, r) in pseudoLegalMoves(p2, alive, ep):
                                    return 'warned'
                        return 'safe'
                    else:
                        if (c, r) in wThr:
                            return 'danger'
                        for p2 in alive:
                            if (p2.alive and p2.color == 'w'
                                    and p2.cooldown < self.cooldownSecs * 0.5):
                                if (c, r) in pseudoLegalMoves(p2, alive, ep):
                                    return 'warned'
                        return 'safe'

                for (c, r) in self.validMvs:
                    rect = sqRect(c, r)
                    if self.pieceAt(c, r) and self.pieceAt(c, r).color != sel.color:
                        alphaRect(self.screen, HL_CAPTURE, rect)
                    else:
                        dr: int = max(6, ChessCore.SQ // 8)
                        cx_: int = rect.centerx
                        cy_: int = rect.centery
                        if self.helpMode:
                            threat: str = squareThreatLevel(c, r)
                            if threat == 'danger':
                                alphaCircle(self.screen, (210, 50, 50, 160), cx_, cy_, dr)
                            elif threat == 'warned':
                                alphaCircle(self.screen, (210, 185, 40, 150), cx_, cy_, dr)
                            else:
                                alphaCircle(self.screen, HL_VALID, cx_, cy_, dr)
                        else:
                            alphaCircle(self.screen, HL_VALID, cx_, cy_, dr)
        except Exception:
            log.exception("EXCEPTION in drawHighlights")

    def drawPieces(self) -> None:
        try:
            f: dict = self.fonts
            t: float = time.time()
            useImg: bool = self.pieceSheets.available
            for p in self.pieces:
                if not p.alive:
                    continue
                rect: pygame.Rect = sqRect(p.col, p.row)

                if p.cooldown > 0 and p is not self.promoPiece:
                    dim: int = int(80 * min(p.cooldown, self.cooldownSecs) / self.cooldownSecs)
                    alphaRect(self.screen, (0, 0, 0, dim), rect)

                if p is self.promoPiece:
                    pulse: float = abs((t * 3) % 2 - 1)
                    alphaRect(self.screen, (int(255 * pulse), int(180 * pulse), 0, 120), rect)

                drewImg: bool = False
                if useImg:
                    img: Optional[pygame.Surface] = self.pieceSheets.get(p.color, p.ptype, ChessCore.SQ)
                    if img is not None:
                        self.screen.blit(img, rect.topleft)
                        drewImg = True
                if not drewImg:
                    if chessGlyphsOk(f['piece']):
                        sym: str = UNICODE_CHESS.get((p.color, p.ptype), p.ptype)
                        tc: tuple = (255, 255, 255) if p.color == 'w' else (15, 15, 15)
                        sh: pygame.Surface = f['piece'].render(sym, True, (0, 0, 0))
                        self.screen.blit(sh, sh.get_rect(center=(rect.centerx + 2, rect.centery + 3)))
                        gl: pygame.Surface = f['piece'].render(sym, True, tc)
                        self.screen.blit(gl, gl.get_rect(center=rect.center))
                    else:
                        drawPieceFallback(self.screen, f['big'], p.color, p.ptype, rect)

                barH: int = max(4, ChessCore.SQ // 16)
                bx_: int = rect.left + 3
                bw_: int = ChessCore.SQ - 6
                by_: int = rect.bottom - barH - 2
                pygame.draw.rect(self.screen, C_BAR_BG, (bx_, by_, bw_, barH), border_radius=2)
                if p is self.promoPiece:
                    pulse = abs((t * 3) % 2 - 1)
                    pygame.draw.rect(
                        self.screen,
                        (int(210 + 40 * pulse), int(160 + 40 * pulse), 0),
                        (bx_, by_, bw_, barH),
                        border_radius=2
                    )
                elif p.cooldown > 0:
                    fill: int = int(bw_ * (1.0 - min(p.cooldown, self.cooldownSecs) / self.cooldownSecs))
                    if fill > 0:
                        pygame.draw.rect(self.screen, C_BAR_FG, (bx_, by_, fill, barH), border_radius=2)
                else:
                    pygame.draw.rect(self.screen, C_BAR_DONE, (bx_, by_, bw_, barH), border_radius=2)

                if p.premove:
                    dr: int = max(4, ChessCore.SQ // 14)
                    pygame.draw.circle(self.screen, C_DOT_PRE, (rect.right - dr - 2, rect.top + dr + 2), dr)
        except Exception:
            log.exception("EXCEPTION in drawPieces")

    def drawPromotionModal(self) -> None:
        if not self.promoPiece:
            return
        try:
            pp: object = self.promoPiece
            f: dict = self.fonts
            s: pygame.Surface = pygame.Surface((ChessCore.BOARD_PX, ChessCore.BOARD_PX), pygame.SRCALPHA)
            s.fill((0, 0, 0, 148))
            self.screen.blit(s, (ChessCore.BX, ChessCore.BY))
            bsz: int = max(56, min(ChessCore.SQ, int(ChessCore.SQ * 1.0)))
            gap: int = max(6, ChessCore.SQ // 10)
            totW: int = 4 * bsz + 3 * gap
            pw: int = totW + 40
            ph: int = bsz + 60
            px: int = ChessCore.BX + (ChessCore.BOARD_PX - pw) // 2
            py: int = ChessCore.BY + (ChessCore.BOARD_PX - ph) // 2
            drawRr(self.screen, C_MOD_BG, (px, py, pw, ph), 14)
            pygame.draw.rect(self.screen, C_MOD_BD, (px, py, pw, ph), 2, border_radius=14)
            who: str = 'White' if pp.color == 'w' else 'Black'
            title: pygame.Surface = f['med'].render(f"{who} pawn promotes — choose:", True, C_TEXT)
            self.screen.blit(title, title.get_rect(center=(px + pw // 2, py + 16)))
            bx0: int = px + (pw - totW) // 2
            by0: int = py + 34
            mx: int
            my: int
            mx, my = pygame.mouse.get_pos()
            self.promoRects = {}
            useImg: bool = self.pieceSheets.available
            for i, pt in enumerate(PROMO_TYPES):
                bx: int = bx0 + i * (bsz + gap)
                rect: pygame.Rect = pygame.Rect(bx, by0, bsz, bsz)
                self.promoRects[pt] = rect
                drawRr(self.screen, C_BTN_H if rect.collidepoint(mx, my) else C_BTN, rect, 10)
                drewImg: bool = False
                if useImg:
                    img: Optional[pygame.Surface] = self.pieceSheets.get(pp.color, pt, bsz)
                    if img:
                        self.screen.blit(img, rect.topleft)
                        drewImg = True
                if not drewImg:
                    if chessGlyphsOk(f['promo']):
                        sym: str = UNICODE_CHESS.get((pp.color, pt), pt)
                        gl: pygame.Surface = f['promo'].render(
                            sym,
                            True,
                            (255, 255, 255) if pp.color == 'w' else (20, 20, 20)
                        )
                        self.screen.blit(
                            gl,
                            gl.get_rect(center=(rect.centerx, rect.centery - max(4, ChessCore.SQ // 18)))
                        )
                    else:
                        drawPieceFallback(self.screen, f['big'], pp.color, pt, rect)
                lb: pygame.Surface = f['sm'].render(PROMO_NAMES[pt], True, C_MUTED)
                self.screen.blit(lb, lb.get_rect(center=(rect.centerx, rect.bottom - lb.get_height())))
        except Exception:
            log.exception("EXCEPTION in drawPromotionModal")

    def drawSidebar(self) -> None:
        try:
            f: dict = self.fonts
            sx: int = ChessCore.SB_X
            t: float = time.time()
            sc: float = ChessCore.SQ / 80.0
            sg: int = max(2, int(4 * sc))
            mg: int = max(5, int(10 * sc))
            tipGap: int = max(3, int(6 * sc))
            divStep: int = max(1, int(2 * sc))
            y: int = mg

            title: pygame.Surface = f['big'].render("Real-Time Chess", True, C_TEXT)
            self.screen.blit(title, (sx, y))
            y += title.get_height() + sg

            if self.gameOver:
                st: pygame.Surface = f['med'].render(self.gameOver, True, (220, 100, 80))
            elif self.promoPiece:
                st = f['med'].render("Choose promotion (see board)", True, (220, 200, 60))
            elif self.gameMode == 'lan_host':
                pulse: float = 0.55 + 0.45 * math.sin(time.time() * 2.5)
                pc: tuple = (int(60 + 140 * pulse), int(180 + 60 * pulse), int(100 + 80 * pulse))
                st = f['med'].render("LAN — You are WHITE", True, pc)
            elif self.gameMode == 'lan_client':
                pulse = 0.55 + 0.45 * math.sin(time.time() * 2.5)
                pc = (int(100 + 100 * pulse), int(140 + 80 * pulse), int(200 + 40 * pulse))
                st = f['med'].render("LAN — You are BLACK", True, pc)
            elif self.gameMode == 'vs_ai':
                if self.ai and self.ai.isThinking():
                    dots: str = '.' * self.aiDots
                    st = f['med'].render(f"AI thinking{dots:<3}  ({self.aiDifficulty})", True, (180, 180, 60))
                else:
                    who: str = 'Black' if self.aiColor == 'b' else 'White'
                    st  = f['med'].render(f"vs AI ({self.aiDifficulty})  |  AI={who}", True, C_AI_LBL)
            else:
                st = f['med'].render("2-Player Local  •  Click any piece", True, (88, 208, 108))
            if st.get_width() > ChessCore.SB_W:
                st = pygame.transform.scale(st, (ChessCore.SB_W, st.get_height()))
            self.screen.blit(st, (sx, y))
            y += st.get_height() + sg

            mutedSlotH: int = f['sm'].get_height() + sg
            if self.audio.muted:
                ms: pygame.Surface = f['sm'].render("[MUTED]  (M to unmute)", True, MUTE_RED)
                self.screen.blit(ms, (sx, y))
            y += mutedSlotH

            tipText: str = "Right-click cancels selection / premove"
            tipS: pygame.Surface = f['sm'].render(tipText, True, C_MUTED)
            if tipS.get_width() > ChessCore.SB_W:
                tipS = f['sm'].render("R-click cancels selection", True, C_MUTED)
            self.screen.blit(tipS, (sx, y))
            y += tipS.get_height() + tipGap
            pygame.draw.line(self.screen, DIVIDER, (sx, y), (sx + ChessCore.SB_W, y))
            y += divStep

            for btn in self.buttons:
                btn.draw(self.screen, f['ui'])

            ep: Optional[tuple[int, int]] = self.epNow()
            epT: str = f"EP: {'abcdefgh'[ep[0]]}{8 - ep[1]}" if ep else "EP: —"
            cdS: pygame.Surface = f['ui'].render(f"CD: {self.cooldownSecs:.1f}s   {epT}", True, C_TEXT)
            self.screen.blit(cdS, (sx, self.sbCdY))
            div1Y: int = self.sbCdY + cdS.get_height() + sg
            pygame.draw.line(self.screen, DIVIDER, (sx, div1Y), (sx + ChessCore.SB_W, div1Y))

            ly: int = div1Y + max(3, int(6 * sc))
            lh: int = max(14, f['sm'].get_height() + divStep)

            dead: list = [p for p in self.pieces if not p.alive]
            wCaps: list = sorted(
                [p for p in dead if p.color == 'b'],
                key=lambda p: -PIECE_DISP_PTS.get(p.ptype, 0)
            )
            bCaps: list = sorted(
                [p for p in dead if p.color == 'w'],
                key=lambda p: -PIECE_DISP_PTS.get(p.ptype, 0)
            )
            wPts: int = sum(PIECE_DISP_PTS.get(p.ptype, 0) for p in wCaps)
            bPts: int = sum(PIECE_DISP_PTS.get(p.ptype, 0) for p in bCaps)

            hkH: int = lh * 2 + sg
            hkY: int = ChessCore.WIN_H - hkH - max(3, int(6 * sc))
            nLog: int = min(6, len(self.events))
            logH: int = f['med'].get_height() + sg + nLog * lh
            logY: int = max(hkY - max(3, int(6 * sc)) - logH, ly)
            maxLegY: int = logY - mg

            if ly + f['med'].get_height() + sg <= maxLegY:
                hdr: pygame.Surface = f['med'].render("Captured", True, SEC_HDR)
                self.screen.blit(hdr, (sx, ly))
                ly += hdr.get_height() + sg

            for sideLabel, caps, pts, lblCol in [
                ("White", wCaps, wPts, (230, 230, 240)),
                ("Black", bCaps, bPts, (150, 155, 170)),
            ]:
                if ly + lh > maxLegY:
                    break
                syms: str = ''.join(UNICODE_CHESS.get((p.color, p.ptype), p.ptype) for p in caps)
                ptStr: str = f"+{pts} pts" if pts else "—"
                hd: pygame.Surface = f['sm'].render(f"{sideLabel}:  {ptStr}", True, lblCol)
                self.screen.blit(hd, (sx, ly))
                ly += lh
                if ly + lh > maxLegY:
                    break
                if syms:
                    chunkW: int = ChessCore.SB_W - sg
                    if chessGlyphsOk(f['symSm']):
                        ls: pygame.Surface = f['symSm'].render(syms, True, C_MUTED)
                        if ls.get_width() <= chunkW:
                            self.screen.blit(ls, (sx + sg, ly))
                            ly += lh
                        else:
                            cpl: int = max(1, chunkW // max(1, f['symSm'].size(syms[0])[0]))
                            for i in range(0, len(syms), cpl):
                                if ly + lh > maxLegY:
                                    break
                                rs: pygame.Surface = f['symSm'].render(syms[i:i + cpl], True, C_MUTED)
                                self.screen.blit(rs, (sx + sg, ly))
                                ly += lh
                    else:
                        letters: list[str] = [PIECE_LETTERS.get(p.ptype, p.ptype) for p in caps]
                        abbrev: str = ' '.join(letters)
                        abbrS: pygame.Surface = f['sm'].render(abbrev, True, C_MUTED)
                        self.screen.blit(abbrS, (sx + sg, ly))
                        ly += lh
                else:
                    ns: pygame.Surface = f['sm'].render("  none", True, C_MUTED)
                    self.screen.blit(ns, (sx + sg, ly))
                    ly += lh
                ly += divStep

            pygame.draw.line(self.screen, DIVIDER, (sx, logY - sg), (sx + ChessCore.SB_W, logY - sg))
            self.screen.blit(f['med'].render("Event Log", True, SEC_HDR), (sx, logY))
            ely: int = logY + f['med'].get_height() + divStep
            for entry in self.events[-nLog:]:
                if ely + lh > hkY - sg:
                    break
                text: str = entry
                ts: pygame.Surface = f['sm'].render(text, True, C_MUTED)
                while ts.get_width() > ChessCore.SB_W and len(text) > 4:
                    text = text[:-4] + '…'
                    ts = f['sm'].render(text, True, C_MUTED)
                self.screen.blit(ts, (sx, ely))
                ely += lh

            pygame.draw.line(self.screen, DIVIDER, (sx, hkY - sg), (sx + ChessCore.SB_W, hkY - sg))
            hkFull: str = "H=Help  R=Restart  M=Mute  F11=Full  ESC=Menu"
            hkSurf: pygame.Surface = f['sm'].render(hkFull, True, C_MUTED)
            if hkSurf.get_width() <= ChessCore.SB_W:
                self.screen.blit(hkSurf, (sx, hkY))
            else:
                line1: pygame.Surface = f['sm'].render("H=Help  R=Restart  M=Mute", True, C_MUTED)
                line2: pygame.Surface = f['sm'].render("F11=Fullscreen  ESC=Menu",   True, C_MUTED)
                self.screen.blit(line1, (sx, hkY))
                if hkY + lh + divStep < ChessCore.WIN_H:
                    self.screen.blit(line2, (sx, hkY + lh))
        except Exception:
            log.exception("EXCEPTION in drawSidebar")

    def drawGameOver(self) -> None:
        if not self.gameOver:
            return
        try:
            f: dict = self.fonts
            s: pygame.Surface = pygame.Surface((ChessCore.BOARD_PX, ChessCore.BOARD_PX), pygame.SRCALPHA)
            s.fill(C_WIN_OVL)
            self.screen.blit(s, (ChessCore.BX, ChessCore.BY))
            cx: int = ChessCore.BX + ChessCore.BOARD_PX // 2
            cy: int = ChessCore.BY + ChessCore.BOARD_PX // 2
            msg: pygame.Surface = f['big'].render(self.gameOver, True, C_TEXT)
            hint: pygame.Surface = f['med'].render("R = restart   ESC = menu", True, C_MUTED)
            abh: int = max(32, f['ui'].get_height() + 12)
            totalH: int = msg.get_height() + 8 + hint.get_height() + 14 + abh
            stackTop: int = cy - totalH // 2
            stackTop = max(ChessCore.BY + 10, min(stackTop, ChessCore.BY + ChessCore.BOARD_PX - totalH - 10))
            msgY: int = stackTop
            hintY: int = msgY + msg.get_height() + 8
            btnY: int = hintY + hint.get_height() + 14
            self.screen.blit(msg,  msg.get_rect(center=(cx, msgY  + msg.get_height() // 2)))
            self.screen.blit(hint, hint.get_rect(center=(cx, hintY + hint.get_height() // 2)))
            abw: int = max(160, int(ChessCore.BOARD_PX * 0.38))
            self.analyzeBtn = Button((cx - abw // 2, btnY, abw, abh), "Analyze Game")
            mx: int
            my: int
            mx, my = pygame.mouse.get_pos()
            self.analyzeBtn.updateHover(mx, my)
            self.analyzeBtn.draw(self.screen, f['ui'])
        except Exception:
            log.exception("EXCEPTION in drawGameOver")

    def draw(self) -> None:
        self.screen.fill(BG)
        self.drawBoard()
        self.drawHighlights()
        self.drawPieces()
        self.drawSidebar()
        self.drawPromotionModal()
        self.drawGameOver()
        pygame.display.flip()

    def run(self) -> dict:
        self.audio.playMusic()
        prev: float = time.time()
        frame: int = 0
        while True:
            try:
                now: float = time.time()
                dt: float = min(now - prev, 0.10)
                prev = now
                frame += 1
                mx: int
                my: int
                mx, my = pygame.mouse.get_pos()
                for btn in self.buttons:
                    btn.updateHover(mx, my)

                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        if self.ai:
                            self.ai.cancelSearch()
                        pygame.quit()
                        raise SystemExit

                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            if self.fullscreen:
                                self.applyWindow(fullscreen=False)
                            else:
                                if self.ai:
                                    self.ai.cancelSearch()
                                self.audio.stopMusic()
                                return self.ret()
                        if event.key == pygame.K_r:
                            self.reset()
                        if event.key == pygame.K_h:
                            self.btnHelp.active = not self.btnHelp.active
                            self.helpMode = self.btnHelp.active
                        if event.key == pygame.K_m:
                            self.audio.toggleMute()
                        if event.key == pygame.K_F11:
                            self.applyWindow(fullscreen=not self.fullscreen)

                    if event.type == pygame.VIDEORESIZE and not self.fullscreen:
                        nw: int = max(640, event.w)
                        nh: int = max(480, event.h)
                        self.screen = pygame.display.set_mode((nw, nh), pygame.RESIZABLE)
                        ChessCore.applyLayout(nw, nh)
                        self.fonts = makeFonts(ChessCore.SQ)
                        self.pieceSheets.invalidateCache()
                        self.buildSidebar()

                    if event.type == pygame.MOUSEBUTTONDOWN:
                        ex: int = event.pos[0]
                        ey: int = event.pos[1]
                        if self.gameOver and self.analyzeBtn and self.analyzeBtn.onClick(ex, ey):
                            r: dict = self.ret()
                            r['show_analysis'] = True
                            self.audio.stopMusic()
                            return r
                        if self.promoPiece and event.button == 1:
                            if self.gameMode == 'vs_ai' and self.promoPiece.color == self.aiColor:
                                continue
                            for pt, rect in self.promoRects.items():
                                if rect.collidepoint(ex, ey):
                                    self.choosePromotion(pt)
                                break
                            continue
                        if self.btnHelp.onClick(ex, ey):
                            self.helpMode = self.btnHelp.active
                        elif self.btnRestart.onClick(ex, ey):
                            self.reset()
                        elif self.btnMenu.onClick(ex, ey):
                            if self.ai:
                                self.ai.cancelSearch()
                            self.audio.stopMusic()
                            return self.ret()
                        else:
                            self.handleBoardClick(ex, ey, event.button)

                try:
                    self.update(dt)
                except Exception:
                    log.exception(f"EXCEPTION in Game.update() frame {frame}")
                try:
                    self.draw()
                except Exception:
                    log.exception(f"EXCEPTION in Game.draw() frame {frame}")
                self.clock.tick(FPS)

            except (SystemExit, pygame.error):
                raise
            except KeyboardInterrupt:
                log.info("KeyboardInterrupt caught in Game.run() — returning to menu")
                if self.ai:
                    self.ai.cancelSearch()
                self.audio.stopMusic()
                return self.ret()

    def ret(self) -> dict:
        d: dict = {
            'gameMode':       self.gameMode,
            'aiColor':        self.aiColor,
            'aiDifficulty':   self.aiDifficulty,
            'cooldownSecs':   self.cooldownSecs,
            'fullscreen':     self.fullscreen,
            'screen':         self.screen,
            'gameOver':       self.gameOver,
            'moveHistory':    list(self.moveHistory),
            'gameDuration':   time.time() - self.gameStartTime,
            'piecesSnapshot': [(p.color, p.ptype, p.alive) for p in self.pieces],
        }
        if self.net is not None:
            d['lanNet'] = self.net
        return d


class AnalysisScreen:
    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock, config: dict) -> None:
        self.screen: pygame.Surface = screen
        self.clock: pygame.time.Clock = clock
        self.fullscreen: bool = config.get('fullscreen', False)
        self.fonts: dict[str, pygame.font.Font] = makeFonts(ChessCore.SQ)
        self.gameOver: str = config.get('gameOver') or 'Game Over'
        self.moveHistory: list[dict] = config.get('moveHistory', [])
        self.gameDuration: float = config.get('gameDuration', 0.0)
        self.gameMode: str = config.get('gameMode', 'local')
        self.aiDifficulty: str = config.get('aiDifficulty', '')
        self.aiColor: str = config.get('aiColor', 'b')
        self.cooldownSecs: float = config.get('cooldownSecs', DEFAULT_CD)
        self.notes: list[str] = analysisCommentary(
            self.moveHistory, self.gameDuration,
            self.gameOver, self.gameMode, self.aiDifficulty, self.aiColor,
        )
        self.build()

    def build(self) -> None:
        f: dict = self.fonts
        sc: float = ChessCore.SQ / 80.0
        cx: int = ChessCore.WIN_W // 2
        pw: int = min(680, int(ChessCore.WIN_W * 0.80))
        self.px: int = cx - pw // 2
        self.pw: int = pw
        bh: int = max(34, f['ui'].get_height() + max(8, int(14 * sc)))
        bw: int = max(140, pw // 3)
        gap: int = max(10, int(16 * sc))
        btnY: int = ChessCore.WIN_H - bh - max(12, int(20 * sc))
        self.btnAgain: Button = Button((cx - bw - gap // 2, btnY, bw, bh), "Play Again")
        self.btnMenu: Button  = Button((cx + gap // 2,       btnY, bw, bh), "Back to Menu")
        self.buttons: list[Button] = [self.btnAgain, self.btnMenu]
        self.btnY: int = btnY

    def run(self) -> str:
        while True:
            try:
                mx: int
                my: int
                mx, my = pygame.mouse.get_pos()
                for btn in self.buttons:
                    btn.updateHover(mx, my)
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        pygame.quit()
                        raise SystemExit
                    if event.type == pygame.KEYDOWN:
                        if event.key in (pygame.K_ESCAPE, pygame.K_m):
                            return 'menu'
                        if event.key == pygame.K_r:
                            return 'again'
                    if event.type == pygame.VIDEORESIZE and not self.fullscreen:
                        nw: int = max(640, event.w)
                        nh: int = max(480, event.h)
                        self.screen = pygame.display.set_mode((nw, nh), pygame.RESIZABLE)
                        ChessCore.applyLayout(nw, nh)
                        self.fonts = makeFonts(ChessCore.SQ)
                        self.build()
                    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                        if self.btnAgain.onClick(*event.pos):
                            return 'again'
                        if self.btnMenu.onClick(*event.pos):
                            return 'menu'
                self.drawScreen()
                self.clock.tick(FPS)
            except (SystemExit, pygame.error):
                raise
            except KeyboardInterrupt:
                log.info("KeyboardInterrupt caught in AnalysisScreen.run() — returning to menu")
                return 'menu'

    def drawScreen(self) -> None:
        try:
            self.screen.fill(BG)
            f: dict = self.fonts
            sc: float = ChessCore.SQ / 80.0
            cx: int = ChessCore.WIN_W // 2
            px: int = self.px
            pw: int = self.pw

            g3: int  = max(2, int(3  * sc))
            g4: int  = max(2, int(4  * sc))
            g6: int  = max(3, int(6  * sc))
            g8: int  = max(4, int(8  * sc))
            g10: int = max(6, int(10 * sc))
            g12: int = max(6, int(12 * sc))
            g14: int = max(7, int(14 * sc))
            g18: int = max(9, int(18 * sc))

            lhM: int = f['med'].get_height() + g4
            lhS: int = f['sm'].get_height()  + g3

            titleY: int = max(14, int(28 * sc))
            title: pygame.Surface = f['big'].render("GAME ANALYSIS", True, C_TEXT)
            self.screen.blit(title, title.get_rect(center=(cx, titleY)))

            goLower: str = self.gameOver.lower()
            if 'white wins' in goLower:
                rc: tuple = (230, 210, 80)
            elif 'black wins' in goLower:
                rc = (80, 200, 230)
            else:
                rc = C_TEXT
            res: pygame.Surface = f['med'].render(self.gameOver, True, rc)
            resY: int = titleY + title.get_height() + g6
            self.screen.blit(res, res.get_rect(center=(cx, resY)))

            y: int = resY + res.get_height() + g18
            pygame.draw.line(self.screen, DIVIDER, (px, y), (px + pw, y))
            y += g10

            dur: float = self.gameDuration
            durStr: str = f"{int(dur) // 60}m {int(dur) % 60}s" if dur >= 60 else f"{int(dur)}s"
            total: int = len(self.moveHistory)
            statsS: pygame.Surface = f['sm'].render(
                f"Duration: {durStr}   •   Moves: {total}   •   CD: {self.cooldownSecs:.1f}s",
                True, C_MUTED
            )
            self.screen.blit(statsS, statsS.get_rect(center=(cx, y + statsS.get_height() // 2)))
            y += statsS.get_height() + g14
            pygame.draw.line(self.screen, DIVIDER, (px, y), (px + pw, y))
            y += g10

            sec: pygame.Surface = f['med'].render("MATERIAL", True, SEC_HDR)
            self.screen.blit(sec, (px, y))
            y += lhM

            wCaps: list[str] = [m['capture'] for m in self.moveHistory if m['color'] == 'w' and m['capture']]
            bCaps: list[str] = [m['capture'] for m in self.moveHistory if m['color'] == 'b' and m['capture']]
            wPts: int = sum(PIECE_DISP_PTS.get(pt, 0) for pt in wCaps)
            bPts: int = sum(PIECE_DISP_PTS.get(pt, 0) for pt in bCaps)

            for side, pts, caps, col in [
                ("White", wPts, wCaps, (200, 220, 255)),
                ("Black", bPts, bCaps, (120, 130, 160)),
            ]:
                syms: str = ''.join(
                    UNICODE_CHESS.get(('b' if side == 'White' else 'w', pt), pt)
                    for pt in caps
                )
                ptsLbl: str = f"+{pts} pts" if pts else "0 pts"
                lblText: str = f"  {side} captured: {ptsLbl}  "
                ls: pygame.Surface = f['sm'].render(lblText, True, col)
                self.screen.blit(ls, (px, y))
                if syms:
                    if chessGlyphsOk(f['symSm']):
                        symS: pygame.Surface = f['symSm'].render(syms, True, col)
                        self.screen.blit(
                            symS,
                            (px + ls.get_width(), y + (ls.get_height() - symS.get_height()) // 2)
                        )
                    else:
                        abbrev: str = ' '.join(PIECE_LETTERS.get(pt, pt) for pt in caps)
                        abbrS: pygame.Surface = f['sm'].render(abbrev, True, col)
                        self.screen.blit(
                            abbrS,
                            (px + ls.get_width(), y + (ls.get_height() - abbrS.get_height()) // 2)
                        )
                else:
                    self.screen.blit(f['sm'].render('—', True, col), (px + ls.get_width(), y))
                y += lhS

            totalPts: int = max(1, wPts + bPts)
            barH: int = max(6, f['sm'].get_height() // 2)
            pygame.draw.rect(self.screen, DIVIDER, (px, y, pw, barH), border_radius=4)
            wFill: int = int(pw * wPts / totalPts) if totalPts > 0 else pw // 2
            if wFill > 0:
                pygame.draw.rect(self.screen, (170, 190, 235), (px, y, wFill, barH), border_radius=4)
            adv: int = abs(wPts - bPts)
            advSide: Optional[str] = (
                'White' if wPts > bPts else ('Black' if bPts > wPts else None)
            )
            advStr: str = f"  {advSide} +{adv}" if advSide else "  Even"
            advS: pygame.Surface = f['sm'].render(advStr, True, C_MUTED)
            self.screen.blit(advS, (px + pw + g8, y + barH // 2 - advS.get_height() // 2))
            y += barH + g12
            pygame.draw.line(self.screen, DIVIDER, (px, y), (px + pw, y))
            y += g10

            sec2: pygame.Surface = f['med'].render("MOVE ACTIVITY", True, SEC_HDR)
            self.screen.blit(sec2, (px, y))
            y += lhM

            wMvs: list[dict] = [m for m in self.moveHistory if m['color'] == 'w']
            bMvs: list[dict] = [m for m in self.moveHistory if m['color'] == 'b']
            wCapC: int = sum(1 for m in wMvs if m['capture'])
            bCapC: int = sum(1 for m in bMvs if m['capture'])
            dur2: float = max(1, self.gameDuration)
            wAvg: float = dur2 / max(1, len(wMvs))
            bAvg: float = dur2 / max(1, len(bMvs))
            for line in [
                f"  White: {len(wMvs)} moves  ({wCapC} captures)  avg {wAvg:.1f}s/move",
                f"  Black: {len(bMvs)} moves  ({bCapC} captures)  avg {bAvg:.1f}s/move",
            ]:
                self.screen.blit(f['sm'].render(line, True, C_TEXT), (px, y))
                y += lhS

            PTYPES: list[str] = ['P', 'N', 'B', 'R', 'Q', 'K']
            PT_COLS: dict[str, tuple[int, int, int]] = {
                'P': (120, 180, 120), 'N': (100, 160, 220), 'B': (200, 160, 80),
                'R': (180, 100, 100), 'Q': (200, 120, 200), 'K': (220, 200, 80)
            }
            allCnt: Counter = Counter(m['ptype'] for m in self.moveHistory)
            totalPt: int = max(1, sum(allCnt.values()))
            barH2: int = max(8, f['sm'].get_height() // 2 + 2)
            y += g4
            bx2: int = px
            for pt in PTYPES:
                cnt: int = allCnt.get(pt, 0)
                seg: int = int(pw * cnt / totalPt)
                if seg > 0:
                    pygame.draw.rect(self.screen, PT_COLS[pt], (bx2, y, seg, barH2), border_radius=3)
                    bx2 += seg
            y += barH2 + g3

            dr: int = max(3, int(4 * sc))
            lx: int = px
            for pt in PTYPES:
                if not allCnt.get(pt):
                    continue
                pygame.draw.circle(self.screen, PT_COLS[pt], (lx + dr, y + dr), dr)
                leg: pygame.Surface = f['sm'].render(f" {ptypeName(pt)}: {allCnt[pt]}", True, C_MUTED)
                self.screen.blit(leg, (lx + dr * 2 + g3, y))
                lx += dr * 2 + g3 + leg.get_width() + g8
                if lx + max(50, int(60 * sc)) > px + pw:
                    lx = px
                    y += lhS
            y += lhS + g6
            pygame.draw.line(self.screen, DIVIDER, (px, y), (px + pw, y))
            y += g10

            if self.gameMode == 'vs_ai' and self.aiDifficulty in AI_SETTINGS:
                cfg: dict = AI_SETTINGS[self.aiDifficulty]
                sec3: pygame.Surface = f['med'].render("AI OPPONENT", True, SEC_HDR)
                self.screen.blit(sec3, (px, y))
                y += lhM
                dotR: int = max(3, int(5 * sc))
                dotX: int = px + max(5, int(8 * sc))
                dotCol: tuple = C_DIFF_CLR.get(self.aiDifficulty, C_TEXT)
                pygame.draw.circle(
                    self.screen, dotCol,
                    (dotX, y + f['sm'].get_height() // 2), dotR
                )
                aiLine: pygame.Surface = f['sm'].render(
                    f"    {self.aiDifficulty} — {cfg.get('style', '')} "
                    f"(Elo ~{cfg.get('rating', '?')})  |  {cfg.get('desc', '')}",
                    True, C_TEXT
                )
                self.screen.blit(aiLine, (px, y))
                y += lhS + g4
                pygame.draw.line(self.screen, DIVIDER, (px, y), (px + pw, y))
                y += g10

            btnTop: int = self.btnY - g8
            sec4: pygame.Surface = f['med'].render("INSIGHTS", True, SEC_HDR)
            self.screen.blit(sec4, (px, y))
            y += lhM
            for note in self.notes:
                if y + lhS > btnTop - g10:
                    break
                words: list[str] = note.split()
                lineBuf: list[str] = []
                linesOut: list[str] = []
                for w in words:
                    test: str = ' '.join(lineBuf + [w])
                    if f['sm'].size(test)[0] > pw - g12:
                        if lineBuf:
                            linesOut.append(' '.join(lineBuf))
                        lineBuf = [w]
                    else:
                        lineBuf.append(w)
                if lineBuf:
                    linesOut.append(' '.join(lineBuf))
                for li, ln in enumerate(linesOut):
                    if y + lhS > btnTop - g10:
                        break
                    prefix: str = "• " if li == 0 else "  "
                    ns: pygame.Surface = f['sm'].render(prefix + ln, True, (170, 178, 198))
                    self.screen.blit(ns, (px, y))
                    y += lhS

            pygame.draw.line(self.screen, DIVIDER, (px, self.btnY - g10), (px + pw, self.btnY - g10))
            for btn in self.buttons:
                btn.draw(self.screen, f['ui'])

            hint: pygame.Surface = f['sm'].render("R = Play Again   ESC = Menu", True, C_MUTED)
            btnBottom: int = max(b.rect.bottom for b in self.buttons)
            hintY: int = btnBottom + (ChessCore.WIN_H - btnBottom) // 2 - hint.get_height() // 2
            hintY = min(hintY, ChessCore.WIN_H - hint.get_height() - g4)
            self.screen.blit(hint, hint.get_rect(centerx=ChessCore.WIN_W // 2, top=hintY))
            pygame.display.flip()
        except Exception:
            log.exception("EXCEPTION in AnalysisScreen.drawScreen")