# Workspace editing operations

Each operation is a JSON object with an `op` field, applied in sequence within one atomic, undoable transaction. AI Edit is subject to editing scope. GUI callers can use the same underlying workspace methods.

## `replace_text`

Scopes: slide, presentation

Fields: `target, find, replace, slide_ids? (required for slide target), languages?, all?`

Exact text replacement within specified slide(s), document, preamble, or CSS. Slide scope permits only selected slide. Exact matching is mandatory.

## `replace_slide`

Scopes: slide, presentation

Fields: `slide_id, sources:{pt-BR,en}`

Replace complete bilingual slide while preserving its identifier.

## `insert_slide`

Scopes: presentation

Fields: `slide_id, anchor?, position:before|after|end, sources:{pt-BR,en}`

Insert a new bilingual slide.

## `delete_slide`

Scopes: presentation

Fields: `slide_id`

Remove a bilingual slide.

## `set_presentation_name`

Scopes: presentation

Fields: `name`

Change the presentation name.

## `set_presentation_description`

Scopes: presentation

Fields: `description`

Change the presentation description.

## `set_slide_description`

Scopes: slide, presentation

Fields: `slide_id, description`

Set language-independent slide description; selected slide only in slide scope.

## `set_variant`

Scopes: presentation

Fields: `id, value:{name,description,width,height,hidden_slides}`

Update an existing variant.

## `set_variants`

Scopes: presentation

Fields: `value:{default,variants}`

Replace variant configuration.

## `replace_stylesheet`

Scopes: presentation

Fields: `source`

Replace presentation-local stylesheet.

## `create_table`

Scopes: facts

Fields: `table`

Create a fact table (all-facts scope).

## `delete_table`

Scopes: fact_table, facts

Fields: `table`

Delete a table (all-facts scope); existing references remain unresolved.

## `rename_table`

Scopes: fact_table, facts

Fields: `table,new_table`

Rename table and update all source references.

## `set_fact`

Scopes: fact_table, facts

Fields: `table,key,value,updated?,description?`

Create or update a fact.

## `rename_fact`

Scopes: fact_table, facts

Fields: `table,key,new_key`

Rename fact and update references.

## `delete_fact`

Scopes: fact_table, facts

Fields: `table,key`

Delete fact, leaving unresolved references.

## `merge_facts`

Scopes: fact_table, facts

Fields: `entries:[{category,key},...],survivor:{category,key}`

Keep survivor's value and metadata; replace references to removed facts throughout workspace.

## `create_folder`

Scopes: asset_folder, assets

Fields: `folder`

Create virtual asset folder.

## `delete_folder`

Scopes: asset_folder, assets

Fields: `folder`

Delete asset folder and descendants; existing references remain unresolved.

## `copy_asset`

Scopes: asset_folder, assets

Fields: `alias,from_alias,description?`

Create another registered alias pointing to an existing image.

## `set_asset_metadata`

Scopes: asset_folder, assets

Fields: `alias,description?,added?`

Update description and inclusion date.

## `move_asset`

Scopes: asset_folder, assets

Fields: `alias,destination`

Rename or move asset and update all source references.

## `delete_asset`

Scopes: asset_folder, assets

Fields: `alias`

Delete registered asset, leaving unresolved references.

## `use_asset_image`

Scopes: asset_folder, assets

Fields: `alias,from_alias`

Use another registered asset's image bytes.

## `merge_assets`

Scopes: asset_folder, assets

Fields: `aliases:[...],survivor`

Keep survivor's image and metadata and update all references to it.

## `create_script`

Scopes: script, scripts

Fields: `id,source,metadata:{name,description,parameters}`

Create Python script.

## `replace_script_text`

Scopes: script, scripts

Fields: `id,find,replace,all?`

Exact text replacement in script.

## `replace_script_source`

Scopes: script, scripts

Fields: `id,source`

Replace complete script source.

## `set_script_metadata`

Scopes: script, scripts

Fields: `id,metadata:{name,description,parameters}`

Replace script metadata.

## `delete_script`

Scopes: script, scripts

Fields: `id`

Delete script.

## `create_recipe`

Scopes: recipe, recipes

Fields: `id,instructions,metadata:{name,description}`

Create reusable AI instructions.

## `replace_recipe_text`

Scopes: recipe, recipes

Fields: `id,find,replace,all?`

Exact text replacement in recipe instructions.

## `replace_recipe_instructions`

Scopes: recipe, recipes

Fields: `id,instructions`

Replace complete recipe instructions.

## `set_recipe_metadata`

Scopes: recipe, recipes

Fields: `id,metadata:{name,description}`

Replace recipe metadata.

## `delete_recipe`

Scopes: recipe, recipes

Fields: `id`

Delete recipe.


# Read-only retrieval operations

Tools use registered identifiers except read_workspace_diff, which accepts workspace-relative paths. Slide sources and rendered images always include PT-BR and English. Retrieval does not grant edit permissions.

## `list_all_facts`

List all fact table names and fact identifiers without values or metadata.

Required: none. Optional: none.

## `list_all_assets`

List all asset aliases organized by virtual folder, without image metadata or content.

Required: none. Optional: none.

## `read_slide_source`

Complete Quarto source of the identified slide in both Portuguese and English.

Required: presentation, slide. Optional: none.

## `read_presentation_source`

Complete Quarto sources of the entire presentation in both Portuguese and English. May be large; prefer individual slides when possible.

Required: presentation. Optional: none.

## `read_slide_images`

Rendered images of one slide in both languages, including hidden slides. Requests local rendering and sends image pixels to the model.

Required: presentation, slide. Optional: variant.

## `read_presentation_images`

Rendered images of all slides in both languages, including hidden slides. Potentially large and costly.

Required: presentation. Optional: variant.

## `read_facts_metadata`

Facts and their values, descriptions and dates. Omit prefix for all; give a table name for its facts or Table.key for one fact.

Required: none. Optional: prefix.

## `read_assets_metadata`

Asset aliases, descriptions, dates, file sizes and dimensions. Omit prefix for all; give a folder path for its descendants or an exact alias for one asset.

Required: none. Optional: prefix.

## `read_script`

Read the complete source and metadata of a script.

Required: id. Optional: none.

## `read_recipe`

Read complete instructions and metadata of a recipe.

Required: id. Optional: none.

## `read_variants`

Read the complete variants configuration for a presentation.

Required: presentation. Optional: none.

## `read_stylesheet`

Read the stylesheets referenced by the presentation in both languages.

Required: presentation. Optional: none.


## `read_workspace_diff`

List changed workspace files or retrieve their unified text diffs, comparing the current state against the saved workspace or previous editing state. During AI editing, provisional modifications are included without changing the comparison baseline.

Required: none. Optional: against (`saved` or `previous`, default `saved`), path (workspace-relative file or folder). Without a path, returns changed filenames only.

## Provisional editing

AI Edit and recipe runs expose the `apply_provisional_edits` tool, which accepts the same validated editing operations as the final response. The model can inspect the temporary state using retrieval tools. A successful request installs all edits as one undoable session operation; failures and cancellation discard the temporary state. AI Chat never receives modifying tools. Recipe runs accept operations for any supported presentation or resource; presentation and slide operations must include a `presentation` identifier.
