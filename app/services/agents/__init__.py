"""Agents package — public API re-exports for compatibility."""
from __future__ import annotations

from .constants import (
    ACTION_HISTORY_DAYS,
)

from .types import (
    _AgentContext,
)

from .store_io import (
    _load_store,
)

from .workflow import (
    _workflow_phase,
)

from .menu import (
    apply_menu_bundle,
    apply_menu_cleanup,
    apply_menu_patch,
    _build_menu_agent,
)

from .product import (
    apply_product_action,
    create_product_action,
    _build_product_agent,
    _product_sync_queue_with_suggestions,
)

from .competition import (
    _build_competition_agent,
    _distance_m,
    _positioning,
)

from .diagnosis import (
    _build_diagnosis_agent,
)

from .growth import (
    _build_growth_agent,
    _growth_sync_queue_with_selection,
)

from .matrix_bridge import (
    create_matrix_agent_action,
)

from .storefront import (
    assist_storefront_image,
    assist_storefront_renovation,
    create_storefront_action,
    _build_storefront_agent,
)

from .context import (
    build_agent_context,
    _build_context,
)

from .orchestrator import (
    build_single_agent,
    build_single_agent_cached,
    build_store_agents,
    _build_one_agent,
)

__all__ = [
    "ACTION_HISTORY_DAYS",
    "apply_menu_bundle",
    "apply_menu_cleanup",
    "apply_menu_patch",
    "apply_product_action",
    "assist_storefront_image",
    "assist_storefront_renovation",
    "build_agent_context",
    "build_single_agent",
    "build_single_agent_cached",
    "build_store_agents",
    "create_matrix_agent_action",
    "create_product_action",
    "create_storefront_action",
    "_AgentContext",
    "_build_competition_agent",
    "_build_context",
    "_build_diagnosis_agent",
    "_build_growth_agent",
    "_build_menu_agent",
    "_build_one_agent",
    "_build_product_agent",
    "_build_storefront_agent",
    "_distance_m",
    "_growth_sync_queue_with_selection",
    "_load_store",
    "_positioning",
    "_product_sync_queue_with_suggestions",
    "_workflow_phase",
]
