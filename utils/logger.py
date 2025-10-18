import logging
import os
import sys
from enum import Enum
from logging.handlers import RotatingFileHandler
from io import TextIOWrapper


# For one app with multiple components
class BaseLogModule(Enum):
    pass


# Config object/dataclass
class LogConfig:
    def __init__(
            self,
            log_module_cls: type[BaseLogModule] | str | None = None,
            log_level: int = logging.INFO,
            log_std_level: int = logging.INFO,
            log_std_stream: TextIOWrapper | None = sys.stdout,
            log_file_path: str | None = None,
            log_errors_file_path: str | None = None,
            log_file_max_size: int = 1 * 1024 ** 2,
            log_file_backup_count: int = 10,
            log_format: str = (
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ),
    ):
        self.log_module_cls = log_module_cls
        self.log_level = log_level
        self.log_std_stream = log_std_stream
        self.log_std_level = log_std_level
        self.log_file_path = log_file_path
        self.log_errors_file_path = log_errors_file_path
        self.log_file_max_size = log_file_max_size
        self.log_file_backup_count = log_file_backup_count
        self.format = log_format


loggers = {} # All loggers
log_handlers = [] # All handlers
log_config: LogConfig | None = LogConfig(BaseLogModule)


def init_logging(config: LogConfig):
    global log_config
    log_config = config # Assign the module config

    if config.log_file_path:
        try:
            os.makedirs(os.path.dirname(config.log_file_path))
        except PermissionError:
            print(
                f"Unable to init log file, insufficient"
                f"permission for path {config.log_file_path}"
            )
            exit(1)
        except OSError:
            # Dir exists
            pass


def get_logger(module: BaseLogModule | str= None, log_level=None, std_log_level=None) -> logging.Logger:
    global log_config

    if log_level is None:
        log_level = log_config.log_level
    if std_log_level is None:
        std_log_level = log_config.log_std_level

    # Handle both enum and string
    if isinstance(module, str):
        name = module
    elif module:
        name = module.value
    else:
        name = None

    # If the module logger exists, use it
    if name in loggers.keys():
        log = loggers[name]
        log.setLevel(log_level)
        return loggers[name]

    # Else create a new one
    else:
        log = logging.getLogger(name)
        loggers[name] = log
        lh = [] # List of the logger's handlers

        # Console handler
        if log_config.log_std_stream:
            handler = logging.StreamHandler(log_config.log_std_stream)
            handler.setLevel(std_log_level)
            lh.append(handler)
            log_handlers.append(handler)

        if log_config.log_file_path:
            try:
                # Handler for the modules
                module_handler = RotatingFileHandler(
                    log_config.log_file_path,
                    'a',
                    log_config.log_file_max_size,
                    log_config.log_file_backup_count,
                    'utf-8',
                )
                # Errors handler, all logs above warning from all modules go here
                errors_handler = RotatingFileHandler(
                    log_config.log_errors_file_path,
                    'a',
                    log_config.log_file_max_size,
                    log_config.log_file_backup_count,
                    'utf-8',
                )
                errors_handler.setLevel(logging.ERROR)
                module_handler.setLevel(log_level)

                lh.extend([module_handler, errors_handler])
                log_handlers.extend([module_handler, errors_handler])

            except PermissionError:
                print(
                    f'Unable to init logging to file, insufficient '
                    f'permissions for path "{log_config.log_file_path}"'
                )
                exit(1)
            except OSError as e:
                print(f'Unable to create RotatingFileHandler, error: {e}')

        # Set the other properties
        for handler in lh:
            handler.setFormatter(logging.Formatter(log_config.format))
            log.addHandler(handler)
            log.setLevel(log_level)

        log.debug(f'Logging initialized (name={name})')
        return log


def destroy():
    for handler in log_handlers:
        handler.close()