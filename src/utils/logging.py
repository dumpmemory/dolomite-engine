import logging
import os
from argparse import Namespace
from typing import Any
from warnings import warn

from aim import Run
from aim.sdk.types import AimObject
from tqdm import tqdm

from src.utils.distributed import get_world_size, run_rank_n


@run_rank_n
def print_rank_0(*args, **kwargs) -> None:
    """print on a single process"""

    print(*args, **kwargs)


def print_ranks_all(*args, **kwargs) -> None:
    """print on all processes sequentially, blocks other process and is slow. Please us sparingly."""

    for rank in range(get_world_size()):
        run_rank_n(print, rank=rank, barrier=True)(f"rank {rank}:", *args, **kwargs)


@run_rank_n
def warn_rank_0(*args, **kwargs) -> None:
    """warn on a single process"""

    warn(*args, **kwargs)


class RunningMean:
    """tracks running mean for loss"""

    def __init__(self, window: int = 100) -> None:
        self.loss_list = []
        self.loss_sum = 0
        self.window = window

    @run_rank_n
    def add_loss(self, loss: float) -> float:
        """accumulates loss of the current step to the running mean

        Args:
            loss (float): loss at current step

        Returns:
            float: running mean of loss
        """

        self.loss_list.append(loss)
        self.loss_sum += loss

        if len(self.loss_list) > self.window:
            loss_remove = self.loss_list[0]
            self.loss_list = self.loss_list[1:]
            self.loss_sum -= loss_remove

        loss_mean = self.loss_sum / len(self.loss_list)
        return loss_mean


class ProgressBar:
    """progress bar for training or validation"""

    def __init__(self, start: int, end: int, desc: str = None) -> None:
        self.progress_bar: tqdm = run_rank_n(tqdm)(total=end, desc=desc)
        self.update(start)

    @run_rank_n
    def update(self, n: int = 1) -> None:
        """updates progress bar

        Args:
            n (int, optional): Number of steps to update the progress bar with. Defaults to 1.
        """

        self.progress_bar.update(n=n)

    @run_rank_n
    def track(self, **loss_kwargs) -> None:
        """track specific metrics in progress bar"""

        # for key in loss_kwargs:
        #     loss_kwargs[key] = "{0:.5f}".format(loss_kwargs[key])
        self.progress_bar.set_postfix(**loss_kwargs)


class AimTracker:
    """aim tracker for training"""

    def __init__(self, experiment: str, repo: str, disable: bool = False) -> None:
        if disable:
            self.run = None
        else:
            run_rank_n(os.makedirs)(repo, exist_ok=True)
            self.run: Run = run_rank_n(Run)(experiment=experiment, repo=repo)

    @run_rank_n
    def log_hyperparam(self, name: str, value: Any) -> None:
        """for logging a single hyperparameter

        Args:
            name (str): name of the hyperparameter
            value (Any): value of the hyperparameter
        """

        if self.run is None:
            return

        try:
            self.run[name] = value
        except TypeError:
            self.run[name] = str(value)

    @run_rank_n
    def log_args(self, args: Namespace) -> None:
        """log args

        Args:
            args (Namespace): arguments based on training / inference mode
        """

        if self.run is None:
            return

        for k, v in vars(args).items():
            self.log_hyperparam(k, v)

    @run_rank_n
    def track(
        self, value: Any, name: str = None, step: int = None, epoch: int = None, context: AimObject = None
    ) -> None:
        """main tracking method

        Args:
            value (Any): value of the object to track
            name (str, optional): name of the object to track. Defaults to None.
            step (int, optional): current step, auto-incremented if None. Defaults to None.
            epoch (int, optional): the training epoch. Defaults to None.
            context (AimObject, optional): context for tracking. Defaults to None.
        """

        if self.run is None:
            return

        self.run.track(value=value, name=name, step=step, epoch=epoch, context=context)


class Logger:
    """logger class for logging to a directory"""

    def __init__(
        self,
        name: str,
        logfile: str,
        level: int = logging.INFO,
        format: str = "%(asctime)s - [%(levelname)s]: %(message)s",
        # format: str = "%(asctime)s - [%(levelname)s] - (%(filename)s:%(lineno)d): %(message)s",
        disable_stdout: bool = False,
    ) -> None:
        dirname = os.path.dirname(logfile)
        if dirname is not None and dirname not in ["", "."]:
            run_rank_n(os.makedirs)(dirname, exist_ok=True)

        # for writing to file
        handlers = [run_rank_n(logging.FileHandler)(logfile, "a")]
        # for writing to stdout
        if not disable_stdout:
            handlers.append(run_rank_n(logging.StreamHandler)())

        run_rank_n(logging.basicConfig)(level=level, handlers=handlers, format=format)

        self.logger: logging.Logger = run_rank_n(logging.getLogger)(name)
        self.stacklevel = 3

    @run_rank_n
    def info(self, msg) -> None:
        self.logger.info(msg, stacklevel=self.stacklevel)

    @run_rank_n
    def debug(self, msg) -> None:
        self.logger.debug(msg, stacklevel=self.stacklevel)

    @run_rank_n
    def critical(self, msg) -> None:
        self.logger.critical(msg, stacklevel=self.stacklevel)

    @run_rank_n
    def error(self, msg) -> None:
        self.logger.error(msg, stacklevel=self.stacklevel)

    @run_rank_n
    def warn(self, msg) -> None:
        self.logger.warn(msg, stacklevel=self.stacklevel)


class ExperimentsTracker(Logger, AimTracker):
    """_summary_

    Args:
        Logger (_type_): _description_
        AimTracker (_type_): _description_
    """

    def __init__(
        self,
        logger_name: str,
        experiment_name: str,
        aim_repo: str,
        logdir: str,
        disable_aim: bool,
    ) -> None:
        Logger.__init__(self, logger_name, os.path.join(logdir, f"{experiment_name}.log"), disable_stdout=True)
        AimTracker.__init__(self, experiment_name, aim_repo, disable_aim)
