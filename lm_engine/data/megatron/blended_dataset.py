# Copyright (c) 2022, NVIDIA CORPORATION. All rights reserved.

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections import OrderedDict

import numpy as np
import torch

from ...utils import log_rank_0
from .blended_megatron_dataset_config import BlendedMegatronDatasetConfig
from .megatron_dataset import MegatronDataset
from .utils import build_blending_indices, normalize


_VERBOSE = False


class BlendedDataset(torch.utils.data.Dataset):
    """Conjugating class for a set of MegatronDataset instances

    Args:
        datasets (list[MegatronDataset]): The MegatronDataset instances to blend

        weights (list[float]): The weights which determines the dataset blend ratios

        size (int): The number of samples to draw from the blend

        config (BlendedMegatronDatasetConfig): The config object which informs dataset creation

    Raises:
        RuntimeError: When the dataset has fewer or more samples than 'size' post-initialization
    """

    def __init__(
        self,
        datasets: list[MegatronDataset],
        weights: list[float],
        size: int,
        config: BlendedMegatronDatasetConfig,
        caching_allowed: bool,
    ) -> BlendedDataset:
        assert len(datasets) < np.iinfo(np.int16).max
        assert len(datasets) == len(weights)
        assert np.isclose(sum(weights), 1.0)
        assert all(map(lambda _: type(_) == type(datasets[0]), datasets))

        # Alert user to unnecessary blending
        if len(datasets) == 1:
            log_rank_0(logging.WARNING, f"Building a BlendedDataset for a single MegatronDataset")

        # Redundant normalization for bitwise identical comparison with Megatron-LM
        weights = normalize(weights)

        self.datasets = datasets
        self.weights = weights
        self.size = size
        self.config = config
        self.caching_allowed = caching_allowed

        unique_identifiers = OrderedDict()
        unique_identifiers["class"] = type(self).__name__
        unique_identifiers["datasets"] = [dataset.unique_identifiers for dataset in self.datasets]
        unique_identifiers["weights"] = self.weights
        unique_identifiers["size"] = self.size

        self.unique_description = json.dumps(unique_identifiers, indent=4)
        self.unique_description_hash = hashlib.md5(self.unique_description.encode("utf-8")).hexdigest()

        self.dataset_index, self.dataset_sample_index = self._build_indices()

        # Check size
        _ = self[self.size - 1]
        try:
            _ = self[self.size]
            raise RuntimeError(f"{type(self).__name__} size is improperly bounded")
        except IndexError:
            log_rank_0(logging.INFO, f"> {type(self).__name__} length: {len(self)}")

    def __len__(self) -> int:
        return self.size

    def __getitem__(self, idx: int) -> dict[str, int | np.ndarray]:
        dataset_id = self.dataset_index[idx]
        dataset_sample_id = self.dataset_sample_index[idx]
        return {
            "dataset_id": dataset_id,
            **self.datasets[dataset_id][dataset_sample_id],
        }

    def _build_indices(self) -> tuple[np.ndarray, np.ndarray]:
        """Build and optionally cache the dataset index and the dataset sample index

        The dataset index is a 1-D mapping which determines the dataset to query. The dataset
        sample index is a 1-D mapping which determines the sample to request from the queried
        dataset.

        Returns:
            tuple[np.ndarray, np.ndarray]: The dataset index and the dataset sample index
        """

        path_to_cache = getattr(self.config, "path_to_cache")

        if path_to_cache:
            get_path_to = lambda suffix: os.path.join(
                path_to_cache, f"{self.unique_description_hash}-{type(self).__name__}-{suffix}"
            )
            path_to_description = get_path_to("description.txt")
            path_to_dataset_index = get_path_to("dataset_index.npy")
            path_to_dataset_sample_index = get_path_to("dataset_sample_index.npy")
            cache_hit = all(
                map(
                    os.path.isfile,
                    [path_to_description, path_to_dataset_index, path_to_dataset_sample_index],
                )
            )
        else:
            cache_hit = False

        if not path_to_cache or (not cache_hit and self.caching_allowed):
            log_rank_0(logging.INFO, f"Build and save the {type(self).__name__} indices")

            # Build the dataset and dataset sample indexes
            log_rank_0(logging.INFO, f"\tBuild and save the dataset and dataset sample indexes")
            t_beg = time.time()

            dataset_index = np.zeros(self.size, dtype=np.int16)
            dataset_sample_index = np.zeros(self.size, dtype=np.int64)
            build_blending_indices(
                dataset_index, dataset_sample_index, self.weights, len(self.datasets), self.size, _VERBOSE
            )

            if path_to_cache:
                os.makedirs(path_to_cache, exist_ok=True)
                # Write the description
                with open(path_to_description, "wt") as writer:
                    writer.write(self.unique_description)
                # Save the indexes
                np.save(path_to_dataset_index, dataset_index, allow_pickle=True)
                np.save(path_to_dataset_sample_index, dataset_sample_index, allow_pickle=True)
            else:
                log_rank_0(logging.WARNING, "Unable to save the indexes because path_to_cache is None")

            t_end = time.time()
            log_rank_0(logging.DEBUG, f"\t> time elapsed: {t_end - t_beg:4f} seconds")

            return dataset_index, dataset_sample_index

        log_rank_0(logging.INFO, f"Load the {type(self).__name__} indices")

        log_rank_0(logging.INFO, f"\tLoad the dataset index from {path_to_dataset_index}")
        t_beg = time.time()
        dataset_index = np.load(path_to_dataset_index, allow_pickle=True, mmap_mode="r")
        t_end = time.time()
        log_rank_0(logging.DEBUG, f"\t> time elapsed: {t_end - t_beg:4f} seconds")

        log_rank_0(logging.INFO, f"\tLoad the dataset sample index from {path_to_dataset_sample_index}")
        t_beg = time.time()
        dataset_sample_index = np.load(path_to_dataset_sample_index, allow_pickle=True, mmap_mode="r")
        t_end = time.time()
        log_rank_0(logging.DEBUG, f"\t> time elapsed: {t_end - t_beg:4f} seconds")

        return dataset_index, dataset_sample_index
