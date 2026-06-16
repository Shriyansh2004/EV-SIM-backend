"""Simulation loop utilities for virtual chargers."""

from __future__ import annotations

import asyncio
import logging

from app.virtual_charger.charger_pool import charger_pool

logger = logging.getLogger(__name__)


class Simulator:
  def __init__(self) -> None:
    self._running = False
    self._task: asyncio.Task | None = None

  async def start(self) -> None:
    if self._running:
      return
    self._running = True
    self._task = asyncio.create_task(self._loop())
    logger.info("Simulator started")

  async def stop(self) -> None:
    self._running = False
    if self._task:
      self._task.cancel()
      self._task = None
    logger.info("Simulator stopped")

  async def _loop(self) -> None:
    while self._running:
      await asyncio.sleep(1)


simulator = Simulator()
