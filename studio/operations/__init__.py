from .catalog import OPERATIONS, operation_instructions, operation_reference
from .merge import merge_asset_entries, merge_fact_entries


def apply(project, scope: str, target: str, changes: dict, presentation: str = "", slide: str = "") -> None:
    from ..edits import apply_edits
    from ..resource_edits import apply_resource_edits
    if scope == "recipe_run":
        from .workspace import apply_workspace_edits
        apply_workspace_edits(project, changes)
    elif scope in ("slide", "presentation"):
        apply_edits(project, presentation, scope, slide, changes)
    else:
        apply_resource_edits(project, scope, target, changes)
