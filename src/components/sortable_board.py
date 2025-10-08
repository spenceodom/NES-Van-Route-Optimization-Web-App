from __future__ import annotations

from pathlib import Path
from typing import Any, List, Dict, Optional

import streamlit.components.v1 as components


_COMP_PATH = Path(__file__).parent.parent / "web_components" / "sortable_board"

sortable_board_component = components.declare_component(
    "sortable_board",
    path=str(_COMP_PATH),
)


def render_sortable_board(
    vans: List[Dict[str, Any]],
    key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Render the sortable board component and return the latest interaction event.

    Args:
        vans: List of van descriptors with fields:
              - section: "regular" | "wheelchair"
              - vehicle_id: int
              - title: str (e.g., "Van 1")
              - duration_text: str (e.g., "42m")
              - stops: List[{ address: str, passengers: List[str] }]
        key: Optional Streamlit widget key

    Returns:
        A dict event or None. Event shapes:
          { type: 'reorder_stops', section, vehicle_id, new_order: [address] }
          { type: 'move_passenger', from_section, to_section, from_vehicle_id, to_vehicle_id, from_address, to_address, passenger }
          { type: 'create_stop_from_passenger', to_section, to_vehicle_id, insert_index, passenger }
          { type: 'reorder_passengers', section, vehicle_id, address, new_order: [passenger] }
    """
    return sortable_board_component(vans=vans, key=key, default=None)


