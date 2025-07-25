# **************************************************
# Copyright (c) 2025, Mayank Mishra
# **************************************************

from __future__ import annotations

from datasets import load_dataset

from lm_engine.tokenizers import TOKENIZER_TYPE

from ..enums import DatasetSplit
from .base import BaseDataset


class HuggingFaceDataset(BaseDataset):
    """A dataset class to load any HuggingFace dataset, expects a tuple of input and output keys"""

    def __init__(
        self,
        class_args: dict,
        split: DatasetSplit,
        use_output: bool,
        tokenizer: TOKENIZER_TYPE,
        data_name: str,
        input_format: str,
        output_format: str,
        max_input_tokens: int,
        max_output_tokens: int,
    ) -> HuggingFaceDataset:
        super().__init__(
            class_args=class_args,
            split=split,
            use_output=use_output,
            tokenizer=tokenizer,
            data_name=data_name,
            input_format=input_format,
            output_format=output_format,
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
        )

        self.examples = self.prepare_examples()

    def prepare_examples(self) -> list[dict]:
        assert "data_path" in self.class_args, "`data_path` is not specified"

        data_path: str = self.class_args.get("data_path")
        input_key: str = self.class_args.get("input_key", "input")
        output_key: str = self.class_args.get("output_key", "output")

        split = "validation" if self.split == DatasetSplit.val else self.split.value
        dataset = load_dataset(data_path)[split]

        examples = []
        for raw_example in dataset:
            input = self.construct_input_from_format(raw_example[input_key])
            output = self.construct_output_from_format(raw_example[output_key]) if self.use_output else None

            example = self.get_input_output_token_ids(input, output)
            examples.append(example)

        return examples
