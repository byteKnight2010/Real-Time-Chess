import os
import logging
import pygame
from typing import Optional


log: logging.Logger = logging.getLogger("chess")


HERE: str = os.path.dirname(os.path.abspath(__file__))


def asset(rel: str) -> str:
    return os.path.join(HERE, rel)


PIECE_STYLES: dict[str, str] = {
    'Classic': asset(r"assets/pieces/classic.png"),
    'Neo':     asset(r"assets/pieces/neo.png"),
    'Marble':  asset(r"assets/pieces/marble.png"),
    'Wood':    asset(r"assets/pieces/wood.png"),
    'Pixel':   asset(r"assets/pieces/pixel.png"),
}

STYLE_NAMES: list[str] = list(PIECE_STYLES.keys())

COL_ORDER: list[str] = ['K', 'Q', 'R', 'B', 'N', 'P']
ROW_INDEX: dict[str, int] = {'w': 0, 'b': 1}


class PieceSheets:
    def __init__(self, style: str = STYLE_NAMES[0]):
        self.style: str = style
        self.sheet: Optional[pygame.Surface] = None
        self.cellW: int = 0
        self.cellH: int = 0
        self.cache: dict[tuple[str, str, int], pygame.Surface] = {}
        self.available: bool = False
        self.converted: bool = False
        self.load(style)


    def load(self, style: str) -> None:
        self.available = False
        self.sheet = None
        self.cache.clear()
        self.converted = False

        path: str = PIECE_STYLES.get(style, '')
        if not path:
            log.warning(f"PieceSheets: no path configured for style {style!r}")
            return
        if not os.path.isfile(path):
            log.warning(f"PieceSheets: spritesheet not found — {path!r}")
            return
        try:
            sheet: pygame.Surface = pygame.image.load(path)
            self.sheet = sheet
            self.cellW = sheet.get_width() // 6
            self.cellH = sheet.get_height() // 2
            self.available = True
            log.info(f"PieceSheets: loaded {style!r} ({sheet.get_width()}×{sheet.get_height()}, "f"cell={self.cellW}×{self.cellH})")
        except Exception:
            log.exception(f"PieceSheets: failed to load {path!r}")

    def setstyle(self, style: str) -> None:
        if style != self.style:
            self.style = style
            self.load(style)

    @staticmethod
    def availablestyles() -> list[str]:
        return [name for name, path in PIECE_STYLES.items() if os.path.isfile(path)]

    def invalidateCache(self) -> None:
        self.cache.clear()
        self.converted = False

    def get(self, color: str, ptype: str, sq: int) -> Optional[pygame.Surface]:
        if not self.available:
            return None

        if not self.converted:
            try:
                self.sheet = self.sheet.convert_alpha()
            except Exception:
                log.exception("PieceSheets: convert_alpha failed")
            self.converted = True

        key: tuple[str, str, int] = (color, ptype, sq)
        if key in self.cache:
            return self.cache[key]

        columnIndex: int = COL_ORDER.index(ptype) if ptype in COL_ORDER else -1
        rowIndex: int = ROW_INDEX.get(color, -1)

        if columnIndex < 0 or rowIndex < 0:
            return None

        srcRect: pygame.Rect = pygame.Rect(columnIndex * self.cellW, rowIndex * self.cellH, self.cellW, self.cellH)
        cell: pygame.Surface = self.sheet.subsurface(srcRect)
        pad: int = max(2, sq // 14)
        sz: int = sq - pad * 2
        scaled: pygame.Surface = pygame.transform.smoothscale(cell, (sz, sz))
        surf: pygame.Surface = pygame.Surface((sq, sq), pygame.SRCALPHA)
        surf.blit(scaled, (pad, pad))
        self.cache[key] = surf

        return surf
