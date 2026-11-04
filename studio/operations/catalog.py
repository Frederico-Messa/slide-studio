from __future__ import annotations

from typing import Any

OPERATIONS: dict[str, dict[str, Any]] = {
    "replace_text": {"scopes": ["slide", "presentation"], "fields": "target, find, replace, slide_ids? (required for slide target), languages?, all?", "effect": "Exact text replacement within specified slide(s), document, preamble, or CSS. Slide scope permits only selected slide. Exact matching is mandatory."},
    "replace_slide": {"scopes": ["slide", "presentation"], "fields": "slide_id, sources:{pt-BR,en}", "effect": "Replace complete bilingual slide while preserving its identifier."},
    "insert_slide": {"scopes": ["presentation"], "fields": "slide_id, anchor?, position:before|after|end, sources:{pt-BR,en}", "effect": "Insert a new bilingual slide."},
    "delete_slide": {"scopes": ["presentation"], "fields": "slide_id", "effect": "Remove a bilingual slide."},
    "set_presentation_name": {"scopes": ["presentation"], "fields": "name", "effect": "Change the presentation name."},
    "set_presentation_description": {"scopes": ["presentation"], "fields": "description", "effect": "Change the presentation description."},
    "set_slide_description": {"scopes": ["slide", "presentation"], "fields": "slide_id, description", "effect": "Set language-independent slide description; selected slide only in slide scope."},
    "set_variant": {"scopes": ["presentation"], "fields": "id, value:{name,description,width,height,hidden_slides}", "effect": "Update an existing variant."},
    "set_variants": {"scopes": ["presentation"], "fields": "value:{default,variants}", "effect": "Replace variant configuration."},
    "replace_stylesheet": {"scopes": ["presentation"], "fields": "source", "effect": "Replace presentation-local stylesheet."},
    "create_table": {"scopes": ["facts"], "fields": "table", "effect": "Create a fact table (all-facts scope)."},
    "delete_table": {"scopes": ["fact_table", "facts"], "fields": "table", "effect": "Delete a table (all-facts scope); existing references remain unresolved."},
    "rename_table": {"scopes": ["fact_table", "facts"], "fields": "table,new_table", "effect": "Rename table and update all source references."},
    "set_fact": {"scopes": ["fact_table", "facts"], "fields": "table,key,value,updated?,description?", "effect": "Create or update a fact."},
    "rename_fact": {"scopes": ["fact_table", "facts"], "fields": "table,key,new_key", "effect": "Rename fact and update references."},
    "delete_fact": {"scopes": ["fact_table", "facts"], "fields": "table,key", "effect": "Delete fact, leaving unresolved references."},
    "merge_facts": {"scopes": ["fact_table", "facts"], "fields": "entries:[{category,key},...],survivor:{category,key}", "effect": "Keep survivor's value and metadata; replace references to removed facts throughout workspace."},
    "create_folder": {"scopes": ["asset_folder", "assets"], "fields": "folder", "effect": "Create virtual asset folder."},
    "delete_folder": {"scopes": ["asset_folder", "assets"], "fields": "folder", "effect": "Delete asset folder and descendants; existing references remain unresolved."},
    "copy_asset": {"scopes": ["asset_folder", "assets"], "fields": "alias,from_alias,description?", "effect": "Create another registered alias pointing to an existing image."},
    "set_asset_metadata": {"scopes": ["asset_folder", "assets"], "fields": "alias,description?,added?", "effect": "Update description and inclusion date."},
    "move_asset": {"scopes": ["asset_folder", "assets"], "fields": "alias,destination", "effect": "Rename or move asset and update all source references."},
    "delete_asset": {"scopes": ["asset_folder", "assets"], "fields": "alias", "effect": "Delete registered asset, leaving unresolved references."},
    "use_asset_image": {"scopes": ["asset_folder", "assets"], "fields": "alias,from_alias", "effect": "Use another registered asset's image bytes."},
    "merge_assets": {"scopes": ["asset_folder", "assets"], "fields": "aliases:[...],survivor", "effect": "Keep survivor's image and metadata and update all references to it."},
    "create_script": {"scopes": ["script", "scripts"], "fields": "id,source,metadata:{name,description,parameters}", "effect": "Create Python script."},
    "replace_script_text": {"scopes": ["script", "scripts"], "fields": "id,find,replace,all?", "effect": "Exact text replacement in script."},
    "replace_script_source": {"scopes": ["script", "scripts"], "fields": "id,source", "effect": "Replace complete script source."},
    "set_script_metadata": {"scopes": ["script", "scripts"], "fields": "id,metadata:{name,description,parameters}", "effect": "Replace script metadata."},
    "delete_script": {"scopes": ["script", "scripts"], "fields": "id", "effect": "Delete script."},
    "create_recipe": {"scopes": ["recipe", "recipes"], "fields": "id,instructions,metadata:{name,description}", "effect": "Create reusable AI instructions."},
    "replace_recipe_text": {"scopes": ["recipe", "recipes"], "fields": "id,find,replace,all?", "effect": "Exact text replacement in recipe instructions."},
    "replace_recipe_instructions": {"scopes": ["recipe", "recipes"], "fields": "id,instructions", "effect": "Replace complete recipe instructions."},
    "set_recipe_metadata": {"scopes": ["recipe", "recipes"], "fields": "id,metadata:{name,description}", "effect": "Replace recipe metadata."},
    "delete_recipe": {"scopes": ["recipe", "recipes"], "fields": "id", "effect": "Delete recipe."},
}


def operation_instructions(scope: str) -> str:
    entries = [f"{name} {{{'presentation,' if scope == 'recipe_run' and ('presentation' in spec['scopes'] or 'slide' in spec['scopes']) else ''}{spec['fields']}}}: {spec['effect']}" for name, spec in OPERATIONS.items() if scope in spec["scopes"] or scope == "recipe_run"]
    return "Return a JSON object with edit operations under 'edits' (empty only when provisional edits have already been applied). Each operation has an 'op' field. Available operations:\n" + "\n".join(entries)


def operation_reference() -> str:
    lines = ["# Workspace editing operations", "", "Each operation is a JSON object with an `op` field, applied in sequence within one atomic, undoable transaction. AI Edit is subject to editing scope. GUI callers can use the same underlying workspace methods.", ""]
    for name, spec in OPERATIONS.items():
        lines.extend([f"## `{name}`", "", f"Scopes: {', '.join(spec['scopes'])}", "", f"Fields: `{spec['fields']}`", "", spec["effect"], ""])
    return "\n".join(lines)


if __name__ == "__main__":
    print(operation_reference())

PROVISIONAL_EDIT_TOOL: dict[str, Any] = {
    'type': 'function',
    'function': {
        'name': 'apply_provisional_edits',
        'description': 'Apply structured edits to a temporary working state. Subsequent read-only tools inspect that state, including its rendered slides. Edits become one undoable operation only after a successful final response.',
        'parameters': {
            'type': 'object',
            'properties': {
                'edits': {
                    'type': 'array', 'minItems': 1,
                    'items': {'type': 'object', 'properties': {'op': {'type': 'string'}}, 'required': ['op'], 'additionalProperties': True},
                },
            },
            'required': ['edits'], 'additionalProperties': False,
        },
    },
}
