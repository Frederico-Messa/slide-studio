from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from studio.project import Project


class LibraryToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(Path(self.temp.name) / 'workspace')
        self.addCleanup(self.project.temporary.cleanup)
        self.pid = self.project.create_presentation('Example')

    def test_slide_resources_show_both_languages_and_unresolved_references(self) -> None:
        self.project.set_fact('Office', 'dean', 'Alice', '2026-11-01', 'Current dean')
        self.project.set_asset('People/dean', 'dean.png', b'image one', 'Portrait', 'People')
        self.project.update_source(self.pid, 'en', self.project.sources(self.pid)[1] + '\n{{fact:Office.dean}} {{asset:People/dean}} {{fact:Office.missing}}')
        self.project.update_source(self.pid, 'pt-BR', self.project.sources(self.pid)[0] + '\n{{fact:Office.dean}} {{asset:People/dean}} {{asset:People/missing}}')
        resources = self.project.slide_resources(self.pid, 'opening')
        self.assertEqual([row['id'] for row in resources['facts']], ['Office.dean', 'Office.missing'])
        self.assertEqual(resources['facts'][0]['languages'], ['en', 'pt-BR'])
        self.assertEqual(resources['facts'][0]['metadata']['value'], 'Alice')
        self.assertIsNone(resources['facts'][1]['metadata'])
        self.assertEqual(resources['assets'][0]['metadata']['description'], 'Portrait')
        self.assertIsNone(resources['assets'][1]['metadata'])
        with self.assertRaisesRegex(ValueError, 'Slide not found'):
            self.project.slide_resources(self.pid, 'missing')

    def test_duplicate_asset_is_physically_independent_and_undoable(self) -> None:
        self.project.set_asset('People/portrait', 'portrait.png', b'first image', 'Original', 'People', '2026-01-01')
        self.project.duplicate_asset('People/portrait', 'Archive/portrait-copy')
        assets = self.project.assets()['assets']
        first = assets['People/portrait']
        second = assets['Archive/portrait-copy']
        self.assertNotEqual(first['file'], second['file'])
        self.assertEqual((self.project.current / first['file']).read_bytes(), (self.project.current / second['file']).read_bytes())
        self.assertEqual(second['description'], 'Original')
        self.assertEqual(second['category'], 'Archive')
        self.assertIn('Archive', self.project.assets()['folders'])
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.project.duplicate_asset('People/portrait', 'Archive/portrait-copy')
        with self.assertRaisesRegex(ValueError, 'Source asset not found'):
            self.project.duplicate_asset('People/unknown', 'Archive/unknown')
        self.project.set_asset('People/portrait', 'portrait.png', b'replaced image', 'Replaced', 'People')
        self.assertEqual((self.project.current / second['file']).read_bytes(), b'first image')
        self.project.history_move(-1)
        self.project.history_move(-1)
        self.assertNotIn('Archive/portrait-copy', self.project.assets()['assets'])

    def test_move_facts_updates_sources_and_preserves_metadata(self) -> None:
        self.project.create_fact_category('Current')
        self.project.create_fact_category('Archive')
        self.project.set_fact('Current', 'dean', 'Alice', '2026-10-01', 'Dean')
        self.project.set_fact('Current', 'faculty', '900', '2026-10-02', 'Staff')
        for language, source in zip(('pt-BR', 'en'), self.project.sources(self.pid)):
            self.project.update_source(self.pid, language, source + '\n{{fact:Current.dean}} {{fact:Current.faculty}}')
        self.project.move_facts([{'category': 'Current', 'key': 'dean'}, {'category': 'Current', 'key': 'faculty'}], 'Archive')
        self.assertEqual(sorted(self.project.facts()['categories']['Archive']), ['dean', 'faculty'])
        self.assertEqual(self.project.facts()['categories']['Archive']['dean']['description'], 'Dean')
        for source in self.project.sources(self.pid):
            self.assertIn('{{fact:Archive.dean}}', source)
            self.assertNotIn('{{fact:Current.dean}}', source)
        self.project.history_move(-1)
        self.assertIn('dean', self.project.facts()['categories']['Current'])

    def test_fact_move_collisions_leave_state_intact(self) -> None:
        for table in ('A', 'B', 'C', 'D'):
            self.project.create_fact_category(table)
        for table in ('A', 'B'):
            self.project.set_fact(table, 'same', table, '', '')
        self.project.set_fact('C', 'same', 'C', '', '')
        revision = self.project.revision
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.project.move_facts([{'category': 'A', 'key': 'same'}], 'C')
        self.assertEqual(self.project.revision, revision)
        with self.assertRaisesRegex(ValueError, 'same destination key'):
            self.project.move_facts([{'category': 'A', 'key': 'same'}, {'category': 'B', 'key': 'same'}], 'D')
        self.assertEqual(self.project.revision, revision)
        self.assertEqual(self.project.facts()['categories']['A']['same']['value'], 'A')
        with self.assertRaisesRegex(ValueError, 'Destination table'):
            self.project.move_facts([{'category':'A', 'key':'same'}], 'Nonexistent')

    def test_move_entire_nested_folder_to_parent_and_breadcrumb(self) -> None:
        for folder in ('Photos', 'Photos/Leadership', 'Archive', 'Archive/Old'):
            self.project.create_asset_folder(folder)
        self.project.set_asset('Photos/Leadership/dean', 'dean.png', b'portrait', 'Dean', 'Photos/Leadership')
        for language, source in zip(('pt-BR', 'en'), self.project.sources(self.pid)):
            self.project.update_source(self.pid, language, source + '\n{{asset:Photos/Leadership/dean}}')
        self.project.move_asset_folder('Photos/Leadership', 'Archive/Leadership')
        self.assertIn('Archive/Leadership/dean', self.project.assets()['assets'])
        self.assertIn('{{asset:Archive/Leadership/dean}}', self.project.sources(self.pid)[0])
        self.project.move_asset_folder('Archive/Leadership', 'Leadership')
        self.assertIn('Leadership/dean', self.project.assets()['assets'])
        self.assertNotIn('Archive/Leadership', self.project.assets()['folders'])
        with self.assertRaisesRegex(ValueError, 'inside itself'):
            self.project.move_asset_folder('Archive', 'Archive/Old/Archive')
