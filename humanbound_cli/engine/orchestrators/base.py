# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""OrchestratorModule ABC — standard interface for all orchestrators.

Each orchestrator (owasp_agentic, owasp_single_turn, behavioral_qa) implements
this interface. Future custom orchestrators must also conform to this contract.

The interface mirrors the existing backend convention:
- orchestrator_generate(): create attack/test prompts
- orchestrator_run(): execute the test
- compute_quota(): estimate total log count
"""

from abc import ABC, abstractmethod

from ..callbacks import EngineCallbacks


class OrchestratorModule(ABC):
    @staticmethod
    @abstractmethod
    def orchestrator_generate(model_provider: dict, experiment: dict) -> dict:
        """Generate attack/test prompts.

        Args:
            model_provider: Provider dict {"name": "...", "integration": {...}}
            experiment: Experiment dict with configuration.scope, lang, testing_level

        Returns:
            Dict mapping category -> list of opening prompts.
            Example: {"llm001": ["Hi, I need help..."], "llm002": [...]}
        """

    @staticmethod
    @abstractmethod
    def orchestrator_run(
        organisation_id: str | None,
        model_provider: dict,
        experiment: dict,
        prompts: dict,
        few_shots_model,
        callbacks: EngineCallbacks | None = None,
    ) -> None:
        """Execute the test. Logs are emitted via callbacks.on_logs().

        Args:
            organisation_id: Org ID (None for local mode)
            model_provider: Provider dict
            experiment: Experiment dict
            prompts: Output from orchestrator_generate()
            few_shots_model: FSLF model (None for local mode)
            callbacks: EngineCallbacks for I/O decoupling
        """

    @staticmethod
    @abstractmethod
    def compute_quota(testing_level: str, dataset_len: int) -> int:
        """Estimate total log count for progress tracking.

        Args:
            testing_level: "unit", "system", or "acceptance"
            dataset_len: Number of opening prompts

        Returns:
            Estimated total number of conversation logs.
        """
