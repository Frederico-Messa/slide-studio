from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from .project import LANGUAGES, SLIDE, Project, load_json, save_json, split_qmd, validate_bilingual_sources
from .variants import normalize_variants

UNSAFE_MARKUP = re.compile(r'(?im)<\s*(?:script|iframe|object|embed)\b|\{\{<|^\s*```\s*\{(?:python|bash|r|julia|ojs)\b')
UNSAFE_CSS = re.compile(r'(?i)@import\b|url\s*\(\s*[\'"]?\s*(?:https?:|//|data:)|expression\s*\(')
UNSAFE_YAML = re.compile(r'(?im)^\s*(?:filters|include-in-header|include-before-body|include-after-body|resource-path):')


def slide_boundaries(document: str, slide_id: str) -> tuple[int, int]:
    matches = list(SLIDE.finditer(document))
    for index, match in enumerate(matches):
        if match.group(1) == slide_id:
            return match.start(), matches[index + 1].start() if index + 1 < len(matches) else len(document)
    raise ValueError(f'Slide not found: {slide_id}')


def languages_for(edit: dict[str, Any]) -> list[str]:
    languages = edit.get('languages', list(LANGUAGES))
    if not isinstance(languages, list) or not languages or len(languages) != len(set(map(str, languages))) or any(language not in LANGUAGES for language in languages):
        raise ValueError('Invalid edit languages')
    return languages


def exact_replace(original: str, find: str, replacement: str, replace_all: bool, description: str) -> str:
    if not isinstance(find, str) or not find or len(find) > 8_000_000 or not isinstance(replacement, str):
        raise ValueError('An exact replacement requires nonempty find text and replacement text')
    count = original.count(find)
    if count == 0:
        raise ValueError(f'Exact text not found in {description}: {find[:120]!r}')
    if count != 1 and not replace_all:
        raise ValueError(f'Exact text appears {count} times in {description}; choose a narrower target or use all=true')
    if find == replacement:
        raise ValueError(f'Edit does not change {description}')
    return original.replace(find, replacement, -1 if replace_all else 1)


def check_source(original: str, proposed: str) -> None:
    if len(proposed) > 16_000_000:
        raise ValueError('Source exceeds maximum size')
    previous_header, _ = split_qmd(original)
    header, _ = split_qmd(proposed)
    if not re.search(r'(?m)^format:\s*\n  revealjs:\s*$', header) or not re.search(r'(?m)^execute:\s*\n  enabled:\s*false\s*$', header):
        raise ValueError('The source must use Reveal.js with code execution disabled')
    if len(UNSAFE_YAML.findall(header)) > len(UNSAFE_YAML.findall(previous_header)):
        raise ValueError('Rendering extensions or includes cannot be introduced by AI edits')
    if len(UNSAFE_MARKUP.findall(proposed)) > len(UNSAFE_MARKUP.findall(original)):
        raise ValueError('Executable markup and Quarto shortcodes cannot be introduced by AI edits')


def apply_edits(project: Project, pid: str, scope: str, selected_slide: str, changes: dict[str, Any]) -> None:
    if scope not in ('slide', 'presentation'):
        raise ValueError('Invalid editing scope')
    if not isinstance(changes, dict) or set(changes) != {'edits'} or not isinstance(changes['edits'], list) or not 1 <= len(changes['edits']) <= 1_000:
        raise ValueError('Expected a JSON object containing 1–1000 edit operations')

    def operation() -> None:
        folder = project.presentation_path(pid)
        original = {language: (folder / f'{language}.qmd').read_text(encoding='utf-8') for language in LANGUAGES}
        documents = original.copy()
        previous_variants = project.variants(pid)
        variants = copy.deepcopy(previous_variants)
        metadata = load_json(folder / 'presentation.json', {})
        slide_descriptions = project.slide_descriptions(pid)
        slide_metadata_changed = False
        stylesheet: str | None = None
        css_changed = False
        metadata_changed = False
        variants_changed = False

        def current_css() -> str:
            for language in LANGUAGES:
                match = re.search(r'(?m)^    css:\s*([^\n]+)', documents[language])
                if match:
                    location = (folder / match.group(1).strip()).resolve()
                    if not location.is_relative_to(project.current.resolve()):
                        raise ValueError('CSS path is outside the workspace')
                    return location.read_text(encoding='utf-8') if location.is_file() else ''
            return ''

        for index, edit in enumerate(changes['edits'], 1):
            if not isinstance(edit, dict):
                raise ValueError(f'Edit {index} must be an object')
            kind = edit.get('op')
            if kind == 'replace_text':
                target = edit.get('target')
                if target not in ('slide', 'document', 'preamble', 'css'):
                    raise ValueError('Invalid replacement target')
                if scope == 'slide' and target != 'slide':
                    raise ValueError('Current-slide edits cannot modify shared configuration or other slides')
                replace_all = edit.get('all', False)
                if type(replace_all) is not bool:
                    raise ValueError('all must be a boolean')
                languages = languages_for(edit) if target != 'css' else list(LANGUAGES)
                if target == 'css':
                    stylesheet = exact_replace(stylesheet if css_changed else current_css(), edit.get('find'), edit.get('replace'), replace_all, 'presentation stylesheet')
                    css_changed = True
                    continue
                slides = edit.get('slide_ids')
                if target == 'slide':
                    if not isinstance(slides, list) or not slides or len(slides) != len(set(map(str, slides))) or any(not isinstance(slide, str) for slide in slides):
                        raise ValueError('A slide replacement requires slide_ids')
                    if scope == 'slide' and slides != [selected_slide]:
                        raise ValueError('Current-slide edits must target the selected slide')
                elif 'slide_ids' in edit:
                    raise ValueError('slide_ids applies only to slide targets')
                for language in languages:
                    document = documents[language]
                    if target == 'slide':
                        for slide_id in slides:
                            start, end = slide_boundaries(document, slide_id)
                            document = document[:start] + exact_replace(document[start:end], edit.get('find'), edit.get('replace'), replace_all, f'{language} / {slide_id}') + document[end:]
                    elif target == 'preamble':
                        preamble, _ = split_qmd(document)
                        document = exact_replace(preamble, edit.get('find'), edit.get('replace'), replace_all, f'{language} preamble') + document[len(preamble):]
                    else:
                        document = exact_replace(document, edit.get('find'), edit.get('replace'), replace_all, f'{language} document')
                    documents[language] = document
            elif kind in ('replace_slide', 'insert_slide'):
                slide_id = edit.get('slide_id')
                sources = edit.get('sources')
                if not isinstance(slide_id, str) or not isinstance(sources, dict) or set(sources) != set(LANGUAGES) or any(not isinstance(text, str) for text in sources.values()):
                    raise ValueError('Slide operations require slide_id and both language sources')
                if scope == 'slide' and (kind != 'replace_slide' or slide_id != selected_slide):
                    raise ValueError('Only the selected slide can be replaced in current-slide scope')
                for language in LANGUAGES:
                    prefix, _ = split_qmd(documents[language])
                    _, proposed_slides = split_qmd(prefix + sources[language].strip() + '\n')
                    if len(proposed_slides) != 1 or proposed_slides[0]['id'] != slide_id:
                        raise ValueError(f'Invalid replacement slide {slide_id} in {language}')
                    if kind == 'replace_slide':
                        start, end = slide_boundaries(documents[language], slide_id)
                        documents[language] = documents[language][:start] + sources[language].strip() + '\n\n' + documents[language][end:]
                    else:
                        if scope != 'presentation':
                            raise ValueError('Only whole-presentation edits can insert slides')
                        anchor = edit.get('anchor')
                        position = edit.get('position', 'after')
                        if position not in ('before', 'after', 'end'):
                            raise ValueError('Invalid insertion position')
                        if slide_id in [item['id'] for item in split_qmd(documents[language])[1]]:
                            raise ValueError(f'Slide already exists: {slide_id}')
                        if position == 'end':
                            documents[language] = documents[language].rstrip() + '\n\n' + sources[language].strip() + '\n'
                        else:
                            if not isinstance(anchor, str):
                                raise ValueError('An insertion requires an anchor slide')
                            start, end = slide_boundaries(documents[language], anchor)
                            offset = start if position == 'before' else end
                            documents[language] = documents[language][:offset] + sources[language].strip() + '\n\n' + documents[language][offset:]
            elif kind == 'delete_slide':
                if scope != 'presentation':
                    raise ValueError('Only whole-presentation edits can delete slides')
                slide_id = edit.get('slide_id')
                if not isinstance(slide_id, str):
                    raise ValueError('Missing slide_id')
                for language in LANGUAGES:
                    start, end = slide_boundaries(documents[language], slide_id)
                    documents[language] = documents[language][:start] + documents[language][end:]
            elif kind == 'set_presentation_name':
                if scope != 'presentation':
                    raise ValueError('Presentation settings require entire-presentation scope')
                name = edit.get('name')
                if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
                    raise ValueError('Invalid presentation name')
                metadata['name'] = name.strip()
                metadata_changed = True
            elif kind == 'set_presentation_description':
                description = edit.get('description')
                if scope != 'presentation' or not isinstance(description, str) or len(description) > 2000:
                    raise ValueError('Invalid presentation description')
                metadata['description'] = description
                metadata_changed = True
            elif kind == 'set_slide_description':
                description = edit.get('description')
                slide_id = edit.get('slide_id')
                if not isinstance(description, str) or len(description) > 2000 or not isinstance(slide_id, str):
                    raise ValueError('Invalid slide description')
                if scope == 'slide' and slide_id != selected_slide:
                    raise ValueError('Slide description is outside the current scope')
                if slide_id not in validate_bilingual_sources(documents['pt-BR'], documents['en']):
                    raise ValueError('Slide not found')
                slide_descriptions[slide_id] = description
                slide_metadata_changed = True
            elif kind == 'set_variants':
                if scope != 'presentation' or not isinstance(edit.get('value'), dict):
                    raise ValueError('Invalid variants update')
                variants = copy.deepcopy(edit['value'])
                variants_changed = True
            elif kind == 'set_variant':
                if scope != 'presentation' or not isinstance(edit.get('id'), str) or not isinstance(edit.get('value'), dict):
                    raise ValueError('Invalid variant update')
                if edit['id'] not in variants.get('variants', {}):
                    raise ValueError(f"Variant not found: {edit['id']}")
                variants['variants'][edit['id']] = copy.deepcopy(edit['value'])
                variants_changed = True
            elif kind == 'replace_stylesheet':
                if scope != 'presentation' or not isinstance(edit.get('source'), str):
                    raise ValueError('Invalid stylesheet replacement')
                stylesheet = edit['source']
                css_changed = True
            else:
                raise ValueError(f'Unsupported edit operation: {kind}')

        if css_changed:
            if stylesheet is None or len(stylesheet) > 200_000 or UNSAFE_CSS.search(stylesheet):
                raise ValueError('Invalid stylesheet content')
            for language in LANGUAGES:
                source = documents[language]
                if re.search(r'(?m)^    css:.*$', source):
                    source = re.sub(r'(?m)^    css:.*$', '    css: studio.css', source, count=1)
                else:
                    source = source.replace('  revealjs:\n', '  revealjs:\n    css: studio.css\n', 1)
                documents[language] = source

        slide_ids = validate_bilingual_sources(documents['pt-BR'], documents['en'])
        for language in LANGUAGES:
            check_source(original[language], documents[language])
        variants = normalize_variants(variants, slide_ids)
        retained_descriptions = {key: value for key, value in slide_descriptions.items() if key in slide_ids}
        if retained_descriptions != slide_descriptions:
            slide_descriptions = retained_descriptions
            slide_metadata_changed = True
        if not any(documents[language] != original[language] for language in LANGUAGES) and not css_changed and not metadata_changed and not variants_changed and not slide_metadata_changed:
            raise ValueError('The model returned no changes')
        if variants != previous_variants:
            save_json(folder / 'variants.json', variants)
        if metadata_changed:
            save_json(folder / 'presentation.json', metadata)
        if slide_metadata_changed:
            save_json(folder / 'slides.json', {'descriptions': {key: value for key, value in slide_descriptions.items() if key in slide_ids}})
        if css_changed:
            (folder / 'studio.css').write_text(stylesheet, encoding='utf-8')
        for language in LANGUAGES:
            if documents[language] != original[language]:
                (folder / f'{language}.qmd').write_text(documents[language], encoding='utf-8')

    with project.lock:
        project._mutate(operation)
