"""Core services: event bus, config, commands, tasks, logging, plugins."""

from ocode.core.commands import Command, CommandRegistry
from ocode.core.config import OcodeConfig, load_config
from ocode.core.events import EventBus
from ocode.core.logging import get_logger, setup_logging
from ocode.core.plugins import PluginAPI, PluginError, PluginInfo, PluginRegistry
from ocode.core.proto import (
    FramedReader,
    FramingBuffer,
    encode_message,
    read_message,
    reap_subprocess,
    write_message,
)
from ocode.core.tasks import TaskScheduler

__all__ = [
    "Command",
    "CommandRegistry",
    "EventBus",
    "FramedReader",
    "FramingBuffer",
    "OcodeConfig",
    "PluginAPI",
    "PluginError",
    "PluginInfo",
    "PluginRegistry",
    "TaskScheduler",
    "encode_message",
    "get_logger",
    "load_config",
    "read_message",
    "reap_subprocess",
    "setup_logging",
    "write_message",
]
