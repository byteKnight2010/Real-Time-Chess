import sys
import io
import os
import logging
import traceback
import threading
import signal
from typing import Any


if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.kernel32.FreeConsole()
        nul: io.TextIOWrapper = open(os.devnull, "w")
        sys.stdout = nul
        sys.stderr = nul
    except Exception:
        pass


LOG_PATH: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chess_debug.log")
fmt: logging.Formatter = logging.Formatter(
    "%(asctime)s.%(msecs)03d [%(threadName)s] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S"
)
fileHandler: logging.FileHandler = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
fileHandler.setFormatter(fmt)

consoleStream: io.TextIOWrapper = (
    io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    if hasattr(sys.stdout, "buffer") else None
)
if consoleStream is not None:
    consoleHandler: logging.StreamHandler = logging.StreamHandler(consoleStream)
    consoleHandler.setFormatter(fmt)
    logging.basicConfig(level=logging.DEBUG, handlers=[fileHandler, consoleHandler])
else:
    logging.basicConfig(level=logging.DEBUG, handlers=[fileHandler])
log: logging.Logger = logging.getLogger("chess")
log.info("=== Real-Time Chess debug session started ===")
log.info(f"Log file: {LOG_PATH}")

originalExceptionHook: Any = sys.excepthook


def exceptionHook(excType: type, excValue: BaseException, excTb: Any) -> None:
    log.critical(
        "UNHANDLED EXCEPTION in main thread:\n"
        + "".join(traceback.format_exception(excType, excValue, excTb))
    )
    originalExceptionHook(excType, excValue, excTb)


sys.excepthook = exceptionHook


def threadExceptionHook(args: threading.ExceptHookArgs) -> None:
    log.critical(
        f"UNHANDLED EXCEPTION in thread '{args.thread.name}':\n"
        + "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_tb))
    )


threading.excepthook = threadExceptionHook
sys.setswitchinterval(0.005)

shutdownRequested: bool = False


def sigintHandler(sig: int, frame: Any) -> None:
    global shutdownRequested
    shutdownRequested = True
    log.info("SIGINT received — requesting clean shutdown")


try:
    signal.signal(signal.SIGINT, sigintHandler)
except (OSError, ValueError):
    pass

import pygame
from pygame import Surface
from pygame.time import Clock
pygame.init()
pygame.font.init()

from ChessCore import WIN_W, WIN_H
from ChessAudio import AudioManager
from ChessTextures import PieceSheets, STYLE_NAMES
from ChessScreens import MainMenu, Game, AnalysisScreen
from ChessNetwork import ChessNetwork


if __name__ == "__main__":
    log.info(f"pygame version: {pygame.version.ver}")
    log.info(f"Python version: {sys.version}")

    screen: Surface = pygame.display.set_mode((max(640, WIN_W), max(480, WIN_H)), pygame.RESIZABLE)
    pygame.display.set_caption("Real-Time Chess")
    clock: Clock = Clock()

    audio: AudioManager = AudioManager()
    pieceSheets: PieceSheets = PieceSheets(STYLE_NAMES[0])

    config: dict = None

    menu: MainMenu = None
    game: Game = None

    try:
        while True:
            if shutdownRequested:
                raise SystemExit

            menu = MainMenu(screen, clock, audio, pieceSheets, prev_config=config)

            try:
                config = menu.run()
                print(config)
            except KeyboardInterrupt:
                raise SystemExit
            screen = config['screen']

            if shutdownRequested:
                raise SystemExit

            game = Game(config, audio, pieceSheets)

            try:
                config = game.run()
            except KeyboardInterrupt:
                raise SystemExit

            screen = config['screen']

            # Close the LAN socket after the game ends so the next menu starts clean
            lanNet = config.get('lanNet')
            if lanNet is not None:
                lanNet.close()
                config.pop('lanNet', None)

            if shutdownRequested:
                raise SystemExit

            # Analysis is only shown for local / vs_ai games, not LAN
            if (config.get('show_analysis') and config.get('gameOver')
                    and config.get('gameMode') not in ('lan_host', 'lan_client')):
                analysis: AnalysisScreen = AnalysisScreen(screen, clock, config)
                try:
                    action: str = analysis.run()
                except KeyboardInterrupt:
                    raise SystemExit

                config.pop('show_analysis', None)

                if action == 'again':
                    try:
                        game2: Game = Game(config, audio, pieceSheets)
                        config = game2.run()
                    except KeyboardInterrupt:
                        raise SystemExit

                    screen = config['screen']
    except (KeyboardInterrupt, SystemExit):
        # Close any open LAN connection on clean exit
        if config and config.get('lanNet'):
            config['lanNet'].close()
        log.info("Exiting — goodbye!")
        pygame.quit()
        sys.exit(0)
    except Exception:
        if config and config.get('lanNet'):
            config['lanNet'].close()
        log.exception("FATAL unhandled exception in main loop")
        pygame.quit()
        raise