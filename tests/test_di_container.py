from unittest.mock import MagicMock

import pytest

from src.infrastructure.di import create_container


@pytest.mark.asyncio
async def test_container_builds_with_experiment_service_provider():
    container = create_container(config=MagicMock(), bg_manager_factory=MagicMock())

    await container.close()
