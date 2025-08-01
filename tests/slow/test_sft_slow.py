# Copyright 2020-2025 The HuggingFace Team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import gc
import itertools
import tempfile
import unittest

import pytest
import torch
from accelerate.utils.memory import release_memory
from datasets import load_dataset
from parameterized import parameterized
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from transformers.testing_utils import (
    backend_empty_cache,
    require_liger_kernel,
    require_peft,
    require_torch_accelerator,
    require_torch_multi_accelerator,
    torch_device,
)
from transformers.utils import is_peft_available

from trl import SFTConfig, SFTTrainer
from trl.models.utils import setup_chat_format

from ..testing_utils import require_bitsandbytes
from .testing_constants import DEVICE_MAP_OPTIONS, GRADIENT_CHECKPOINTING_KWARGS, MODELS_TO_TEST, PACKING_OPTIONS


if is_peft_available():
    from peft import LoraConfig, PeftModel


@pytest.mark.slow
@require_torch_accelerator
@require_peft
class SFTTrainerSlowTester(unittest.TestCase):
    def setUp(self):
        self.train_dataset = load_dataset("stanfordnlp/imdb", split="train[:10%]")
        self.eval_dataset = load_dataset("stanfordnlp/imdb", split="test[:10%]")
        self.max_length = 128
        self.peft_config = LoraConfig(
            lora_alpha=16,
            lora_dropout=0.1,
            r=8,
            bias="none",
            task_type="CAUSAL_LM",
        )

    def tearDown(self):
        gc.collect()
        backend_empty_cache(torch_device)
        gc.collect()

    @parameterized.expand(list(itertools.product(MODELS_TO_TEST, PACKING_OPTIONS)))
    def test_sft_trainer_str(self, model_name, packing):
        """
        Simply tests if passing a simple str to `SFTTrainer` loads and runs the trainer as expected.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            training_args = SFTConfig(
                output_dir=tmp_dir,
                logging_strategy="no",
                report_to="none",
                per_device_train_batch_size=2,
                max_steps=10,
                packing=packing,
                max_length=self.max_length,
            )

            trainer = SFTTrainer(
                model_name,
                args=training_args,
                train_dataset=self.train_dataset,
                eval_dataset=self.eval_dataset,
            )

            trainer.train()

    @parameterized.expand(list(itertools.product(MODELS_TO_TEST, PACKING_OPTIONS)))
    def test_sft_trainer_transformers(self, model_name, packing):
        """
        Simply tests if passing a transformers model to `SFTTrainer` loads and runs the trainer as expected.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            training_args = SFTConfig(
                output_dir=tmp_dir,
                logging_strategy="no",
                report_to="none",
                per_device_train_batch_size=2,
                max_steps=10,
                packing=packing,
                max_length=self.max_length,
            )

            model = AutoModelForCausalLM.from_pretrained(model_name)
            tokenizer = AutoTokenizer.from_pretrained(model_name)

            trainer = SFTTrainer(
                model,
                args=training_args,
                processing_class=tokenizer,
                train_dataset=self.train_dataset,
                eval_dataset=self.eval_dataset,
            )

            trainer.train()

        release_memory(model, trainer)

    @parameterized.expand(list(itertools.product(MODELS_TO_TEST, PACKING_OPTIONS)))
    @require_peft
    def test_sft_trainer_peft(self, model_name, packing):
        """
        Simply tests if passing a transformers model + peft config to `SFTTrainer` loads and runs the trainer as
        expected.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            training_args = SFTConfig(
                output_dir=tmp_dir,
                logging_strategy="no",
                report_to="none",
                per_device_train_batch_size=2,
                max_steps=10,
                fp16=True,
                packing=packing,
                max_length=self.max_length,
            )

            model = AutoModelForCausalLM.from_pretrained(model_name)
            tokenizer = AutoTokenizer.from_pretrained(model_name)

            trainer = SFTTrainer(
                model,
                args=training_args,
                processing_class=tokenizer,
                train_dataset=self.train_dataset,
                eval_dataset=self.eval_dataset,
                peft_config=self.peft_config,
            )

            self.assertIsInstance(trainer.model, PeftModel)

            trainer.train()

        release_memory(model, trainer)

    @parameterized.expand(list(itertools.product(MODELS_TO_TEST, PACKING_OPTIONS)))
    def test_sft_trainer_transformers_mp(self, model_name, packing):
        """
        Simply tests if passing a transformers model to `SFTTrainer` loads and runs the trainer as expected in mixed
        precision.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            training_args = SFTConfig(
                output_dir=tmp_dir,
                logging_strategy="no",
                report_to="none",
                per_device_train_batch_size=2,
                max_steps=10,
                fp16=True,  # this is sufficient to enable amp
                packing=packing,
                max_length=self.max_length,
            )

            model = AutoModelForCausalLM.from_pretrained(model_name)
            tokenizer = AutoTokenizer.from_pretrained(model_name)

            trainer = SFTTrainer(
                model,
                args=training_args,
                processing_class=tokenizer,
                train_dataset=self.train_dataset,
                eval_dataset=self.eval_dataset,
            )

            trainer.train()

        release_memory(model, trainer)

    @parameterized.expand(list(itertools.product(MODELS_TO_TEST, PACKING_OPTIONS, GRADIENT_CHECKPOINTING_KWARGS)))
    def test_sft_trainer_transformers_mp_gc(self, model_name, packing, gradient_checkpointing_kwargs):
        """
        Simply tests if passing a transformers model to `SFTTrainer` loads and runs the trainer as expected in mixed
        precision + different scenarios of gradient_checkpointing.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            training_args = SFTConfig(
                output_dir=tmp_dir,
                logging_strategy="no",
                report_to="none",
                per_device_train_batch_size=2,
                max_steps=10,
                packing=packing,
                max_length=self.max_length,
                fp16=True,  # this is sufficient to enable amp
                gradient_checkpointing=True,
                gradient_checkpointing_kwargs=gradient_checkpointing_kwargs,
            )

            model = AutoModelForCausalLM.from_pretrained(model_name)
            tokenizer = AutoTokenizer.from_pretrained(model_name)

            trainer = SFTTrainer(
                model,
                args=training_args,
                processing_class=tokenizer,
                train_dataset=self.train_dataset,
                eval_dataset=self.eval_dataset,
            )

            trainer.train()

        release_memory(model, trainer)

    @parameterized.expand(list(itertools.product(MODELS_TO_TEST, PACKING_OPTIONS, GRADIENT_CHECKPOINTING_KWARGS)))
    @require_peft
    def test_sft_trainer_transformers_mp_gc_peft(self, model_name, packing, gradient_checkpointing_kwargs):
        """
        Simply tests if passing a transformers model + PEFT to `SFTTrainer` loads and runs the trainer as expected in
        mixed precision + different scenarios of gradient_checkpointing.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            training_args = SFTConfig(
                output_dir=tmp_dir,
                logging_strategy="no",
                report_to="none",
                per_device_train_batch_size=2,
                max_steps=10,
                packing=packing,
                max_length=self.max_length,
                fp16=True,  # this is sufficient to enable amp
                gradient_checkpointing=True,
                gradient_checkpointing_kwargs=gradient_checkpointing_kwargs,
            )

            model = AutoModelForCausalLM.from_pretrained(model_name)
            tokenizer = AutoTokenizer.from_pretrained(model_name)

            trainer = SFTTrainer(
                model,
                args=training_args,
                processing_class=tokenizer,
                train_dataset=self.train_dataset,
                eval_dataset=self.eval_dataset,
                peft_config=self.peft_config,
            )

            self.assertIsInstance(trainer.model, PeftModel)

            trainer.train()

        release_memory(model, trainer)

    @parameterized.expand(
        list(itertools.product(MODELS_TO_TEST, PACKING_OPTIONS, GRADIENT_CHECKPOINTING_KWARGS, DEVICE_MAP_OPTIONS))
    )
    @require_torch_multi_accelerator
    def test_sft_trainer_transformers_mp_gc_device_map(
        self, model_name, packing, gradient_checkpointing_kwargs, device_map
    ):
        """
        Simply tests if passing a transformers model to `SFTTrainer` loads and runs the trainer as expected in mixed
        precision + different scenarios of gradient_checkpointing (single, multi-gpu, etc).
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            training_args = SFTConfig(
                output_dir=tmp_dir,
                logging_strategy="no",
                report_to="none",
                per_device_train_batch_size=2,
                max_steps=10,
                packing=packing,
                max_length=self.max_length,
                fp16=True,  # this is sufficient to enable amp
                gradient_checkpointing=True,
                gradient_checkpointing_kwargs=gradient_checkpointing_kwargs,
            )

            model = AutoModelForCausalLM.from_pretrained(model_name, device_map=device_map)
            tokenizer = AutoTokenizer.from_pretrained(model_name)

            trainer = SFTTrainer(
                model,
                args=training_args,
                processing_class=tokenizer,
                train_dataset=self.train_dataset,
                eval_dataset=self.eval_dataset,
            )

            trainer.train()

        release_memory(model, trainer)

    @parameterized.expand(list(itertools.product(MODELS_TO_TEST, PACKING_OPTIONS, GRADIENT_CHECKPOINTING_KWARGS)))
    @require_peft
    @require_bitsandbytes
    def test_sft_trainer_transformers_mp_gc_peft_qlora(self, model_name, packing, gradient_checkpointing_kwargs):
        """
        Simply tests if passing a transformers model + PEFT + bnb to `SFTTrainer` loads and runs the trainer as
        expected in mixed precision + different scenarios of gradient_checkpointing.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            training_args = SFTConfig(
                output_dir=tmp_dir,
                logging_strategy="no",
                report_to="none",
                per_device_train_batch_size=2,
                max_steps=10,
                packing=packing,
                max_length=self.max_length,
                fp16=True,  # this is sufficient to enable amp
                gradient_checkpointing=True,
                gradient_checkpointing_kwargs=gradient_checkpointing_kwargs,
            )

            quantization_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)

            model = AutoModelForCausalLM.from_pretrained(model_name, quantization_config=quantization_config)
            tokenizer = AutoTokenizer.from_pretrained(model_name)

            trainer = SFTTrainer(
                model,
                args=training_args,
                processing_class=tokenizer,
                train_dataset=self.train_dataset,
                eval_dataset=self.eval_dataset,
                peft_config=self.peft_config,
            )

            self.assertIsInstance(trainer.model, PeftModel)

            trainer.train()

        release_memory(model, trainer)

    @parameterized.expand(list(itertools.product(MODELS_TO_TEST, PACKING_OPTIONS)))
    @require_peft
    @require_bitsandbytes
    def test_sft_trainer_with_chat_format_qlora(self, model_name, packing):
        """
        Simply tests if using setup_chat_format with a transformers model + peft + bnb config to `SFTTrainer` loads and
        runs the trainer as expected.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            train_dataset = load_dataset("trl-internal-testing/dolly-chatml-sft", split="train")

            training_args = SFTConfig(
                packing=packing,
                max_length=self.max_length,
                output_dir=tmp_dir,
                logging_strategy="no",
                report_to="none",
                per_device_train_batch_size=2,
                max_steps=10,
                fp16=True,
            )

            quantization_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)

            model = AutoModelForCausalLM.from_pretrained(model_name, quantization_config=quantization_config)
            tokenizer = AutoTokenizer.from_pretrained(model_name)

            if tokenizer.chat_template is None:
                model, tokenizer = setup_chat_format(model, tokenizer)

            trainer = SFTTrainer(
                model,
                args=training_args,
                processing_class=tokenizer,
                train_dataset=train_dataset,
                peft_config=self.peft_config,
            )

            self.assertIsInstance(trainer.model, PeftModel)

            trainer.train()

        release_memory(model, trainer)

    @parameterized.expand(list(itertools.product(MODELS_TO_TEST, PACKING_OPTIONS)))
    @require_liger_kernel
    def test_sft_trainer_with_liger(self, model_name, packing):
        """
        Tests if passing use_liger=True to SFTConfig loads and runs the trainer with AutoLigerKernelForCausalLM as
        expected.
        """
        import importlib

        def cleanup_liger_patches(trainer):
            """Clean up liger_kernel patches by reloading the model's specific module"""
            try:
                # Get the specific module that was used by the trainer's model
                module_path = trainer.model.__module__
                reload_module = importlib.import_module(module_path)
                importlib.reload(reload_module)
            except Exception:
                pass  # Continue if reload fails

        with tempfile.TemporaryDirectory() as tmp_dir:
            training_args = SFTConfig(
                output_dir=tmp_dir,
                logging_strategy="no",
                report_to="none",
                per_device_train_batch_size=2,
                max_steps=2,
                packing=packing,
                max_length=self.max_length,
                use_liger_kernel=True,
            )

            trainer = SFTTrainer(
                model_name,
                args=training_args,
                train_dataset=self.train_dataset,
                eval_dataset=self.eval_dataset,
            )

            # Register cleanup now that we have the trainer
            self.addCleanup(cleanup_liger_patches, trainer)

            trainer.train()

        release_memory(trainer.model, trainer)

    @parameterized.expand(list(itertools.product(MODELS_TO_TEST, PACKING_OPTIONS)))
    @require_torch_accelerator
    def test_train_offloading(self, model_name, packing):
        """Test that activation offloading works with SFTTrainer."""

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Initialize the trainer
            training_args = SFTConfig(
                output_dir=tmp_dir,
                activation_offloading=True,
                report_to="none",
                per_device_train_batch_size=2,
                max_steps=2,
                packing=packing,
                max_length=self.max_length,
            )
            trainer = SFTTrainer(
                model=model_name, args=training_args, train_dataset=self.train_dataset, eval_dataset=self.eval_dataset
            )

            # Save the initial parameters to compare them later
            previous_trainable_params = {n: param.clone() for n, param in trainer.model.named_parameters()}

            # Train the model
            trainer.train()

            # Check that the training loss is not None
            self.assertIsNotNone(trainer.state.log_history[-1]["train_loss"])

            # Check the params have changed
            for n, param in previous_trainable_params.items():
                new_param = trainer.model.get_parameter(n)
                self.assertFalse(torch.allclose(param, new_param), f"Parameter {n} has not changed")

            release_memory(trainer.model, trainer)
