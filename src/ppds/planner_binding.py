# src/ppds/planner_binding.py

from dataclasses import dataclass
from typing import List, Union

from .types import Granularity, ContractBundle  # or equivalent output type


@dataclass
class PlannerConstraint:
    forbid_group_by_keys: Union[List[str], str]
    min_group_cardinality: int
    forbid_joins_on: Union[List[str], str]
    require_pre_aggregation: bool


def compile_to_planner_constraints(
    contract: ContractBundle
) -> PlannerConstraint:
    """
    Compile a privacy ContractBundle into planner-enforceable constraints.
    This function is the ONLY place where privacy decisions touch query planning.
    """

    if contract.granularity == Granularity.ITEM:
        return PlannerConstraint(
            forbid_group_by_keys=[],
            min_group_cardinality=1,
            forbid_joins_on=[],
            require_pre_aggregation=False,
        )

    if contract.granularity == Granularity.CLUSTER:
        return PlannerConstraint(
            forbid_group_by_keys=contract.item_level_keys,
            min_group_cardinality=contract.k_min,
            forbid_joins_on=contract.join_keys,
            require_pre_aggregation=True,
        )

    if contract.granularity == Granularity.AGGREGATE:
        return PlannerConstraint(
            forbid_group_by_keys="*",
            min_group_cardinality=contract.k_min,
            forbid_joins_on="*",
            require_pre_aggregation=True,
        )

    raise ValueError(f"Unsupported granularity: {contract.granularity}")
