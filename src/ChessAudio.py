import os
import logging
import pygame
from typing import Optional


log: logging.Logger = logging.getLogger("chess")


MUSIC_PATH: str = r"assets/audio/background.mp3"
MOVE_SFX_PATH: str = r"assets/audio/move.wav"


class AudioManager:
    def __init__(self) -> None:
        self.musicLoaded: bool = False
        self.sfxLoaded: bool = False
        self.moveSound: Optional[pygame.mixer.Sound] = None
        self.musicVolume: float = 0.50
        self.sfxVolume: float = 0.70
        self.muted: bool = False
        self.musicPlaying: bool = False
        self.mixerFunctional: bool = False

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)

            self.mixerFunctional = True
        except Exception:
            log.exception("AudioManager: pygame.mixer.init failed — audio disabled")
            return

        self.loadMusic(MUSIC_PATH)
        self.loadSFX(MOVE_SFX_PATH)


    def loadMusic(self, path: str) -> None:
        if not path or not os.path.isfile(path):
            log.warning(f"AudioManager: music not found at {path!r}")
            return

        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(0.0 if self.muted else self.musicVolume)
            self.musicLoaded = True
            log.info(f"AudioManager: music loaded from {path!r}")
        except Exception:
            log.exception(f"AudioManager: failed to load music {path!r}")

    def loadSFX(self, path: str) -> None:
        if not path or not os.path.isfile(path):
            log.warning(f"AudioManager: SFX not found at {path!r}")
            return

        try:
            self.moveSound = pygame.mixer.Sound(path)
            self.moveSound.set_volume(0.0 if self.muted else self.sfxVolume)
            self.sfxLoaded = True
            log.info(f"AudioManager: SFX loaded from {path!r}")
        except Exception:
            log.exception(f"AudioManager: failed to load SFX {path!r}")

    def playMusic(self) -> None:
        if not self.mixerFunctional or not self.musicLoaded or self.musicPlaying:
            return

        try:
            pygame.mixer.music.play(-1)
            self.musicPlaying = True
            log.debug("AudioManager: music started")
        except Exception:
            log.exception("AudioManager: playMusic failed")

    def stopMusic(self) -> None:
        if not self.mixerFunctional or not self.musicPlaying:
            return

        try:
            pygame.mixer.music.stop()
            self.musicPlaying = False
            log.debug("AudioManager: music stopped")
        except Exception:
            log.exception("AudioManager: stopMusic failed")

    def fadeoutMusic(self, ms: int = 1500) -> None:
        if not self.mixerFunctional or not self.musicPlaying:
            return

        try:
            pygame.mixer.music.fadeout(ms)
            self.musicPlaying = False
            log.debug(f"AudioManager: music fadeout started ({ms}ms)")
        except Exception:
            log.exception("AudioManager: fadeoutMusic failed")

    def playMove(self) -> None:
        if not self.mixerFunctional or not self.sfxLoaded or self.muted:
            return

        try:
            self.moveSound.play()
        except Exception:
            log.exception("AudioManager: playMove failed")

    def setMusicVolume(self, vol: float) -> None:
        self.musicVolume = max(0.0, min(1.0, float(vol)))

        if self.mixerFunctional and not self.muted:
            try:
                pygame.mixer.music.set_volume(self.musicVolume)
            except Exception:
                pass

    def setSFXVolume(self, vol: float) -> None:
        self.sfxVolume = max(0.0, min(1.0, float(vol)))

        if self.moveSound and not self.muted:
            self.moveSound.set_volume(self.sfxVolume)

    def toggleMute(self) -> bool:
        self.muted = not self.muted

        if self.mixerFunctional:
            try:
                pygame.mixer.music.set_volume(0.0 if self.muted else self.musicVolume)
            except Exception:
                pass

        if self.moveSound:
            self.moveSound.set_volume(0.0 if self.muted else self.sfxVolume)

        log.info(f"AudioManager: muted={self.muted}")
        return self.muted
