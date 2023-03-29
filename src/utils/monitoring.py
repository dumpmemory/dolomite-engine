import os
import time
from typing import Callable

import torch
from pynvml import nvmlDeviceGetCount, nvmlDeviceGetHandleByIndex, nvmlDeviceGetMemoryInfo, nvmlInit

from src.utils.distributed import run_rank_n


def is_debugging_enabled() -> bool:
    """check whether debugging is enabled

    Returns:
        bool: whether debugging is enabled
    """

    return bool(os.getenv("DEBUG"))


def setup_debugging() -> None:
    """setup debugging if enabled"""

    if is_debugging_enabled():
        run_rank_n(nvmlInit)()


def register_timer(timer_name: str, rank: int = 0) -> Callable:
    """wraps a function with a timer

    Args:
        timer_name (str): name of the timer
        rank (int, optional): rank on which to run the timer. Defaults to 0.

    Returns:
        Callable: wrapped function on the specified rank and the original function on other ranks
    """

    def run_and_time(func: Callable) -> Callable:
        def timed_func(*args, **kwargs):
            start_time = time.perf_counter()
            output = func(*args, **kwargs)
            end_time = time.perf_counter()
            run_rank_n(print, rank=rank)(
                f"\ntime for {timer_name} on rank {rank} = {'{0:.4f}'.format(end_time - start_time)} sec"
            )
            return output

        if is_debugging_enabled():
            return timed_func
        return func

    return run_and_time


def bytes_to_gigabytes(value: int) -> str:
    """converts B to GB and returns a string with 'GB' appended at the end

    Args:
        value (int): bytes

    Returns:
        str: gigabytes
    """

    gb = round(value / 1024**3, 3)
    return str(gb) + " GB"


@run_rank_n
def report_memory(profiler_name: str, point: str) -> None:
    """print the device memory at current point

    Args:
        profiler_name (str): name of the profiler
        point (str): start / end
    """

    memory_stats = ""

    for device_id in range(nvmlDeviceGetCount()):
        handle = nvmlDeviceGetHandleByIndex(device_id)
        info = nvmlDeviceGetMemoryInfo(handle)

        memory_stats += f"""
GPU {device_id}:
total memory at {profiler_name} ({point}) = {bytes_to_gigabytes(info.total)}
free memory at {profiler_name} ({point}) = {bytes_to_gigabytes(info.free)}
used memory at {profiler_name} ({point}) = {bytes_to_gigabytes(info.used)}
memory allocated at {profiler_name} ({point}) = {bytes_to_gigabytes(torch.cuda.memory_allocated(device_id))}
max memory allocated at {profiler_name} ({point}) = {bytes_to_gigabytes(torch.cuda.max_memory_allocated(device_id))}
max memory reserved at {profiler_name} ({point}) = {bytes_to_gigabytes(torch.cuda.max_memory_reserved(device_id))}"""

    print(memory_stats)


def register_profiler(profiler_name: str) -> Callable:
    """wraps a function with a memory profiler

    Args:
        profiler_name (str): name of the profiler

    Returns:
        Callable: wrapped function on the specified rank and the original function on other ranks
    """

    def run_and_profile(func: Callable) -> Callable:
        def profiled_func(*args, **kwargs):
            report_memory(profiler_name, "start")
            output = func(*args, **kwargs)
            report_memory(profiler_name, "end")
            return output

        if is_debugging_enabled():
            return profiled_func
        return func

    return run_and_profile
