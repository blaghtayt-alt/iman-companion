"""Report every supported language/category without approving absent sources."""
from pathlib import Path
import argparse
import json

from book_edition_scope import MAP, available, select
from book_content_coverage import discover_readers, scope_coverage

COLLECTIONS = ('tadabbur-extended', 'hadith', 'seerah', 'articles')


def inventory(root):
    root = Path(root).resolve()
    config = json.loads((root / 'books/config.json').read_bytes())
    catalog = json.loads((root / 'materials/catalog.json').read_bytes())
    declarations = json.loads((root / 'books/reviewed-books.json').read_bytes())
    published_path = root / 'books/published-library.json'
    published = json.loads(published_path.read_bytes()) if published_path.is_file() else {'entries': []}
    downloads = {(entry['book']['language'], entry['book']['collection']): entry['book']
                 for entry in published.get('entries', [])}
    discovery = discover_readers(root, config['languages'], catalog)
    by_scope = {}
    for row in declarations.get('books', []):
        identity = row.get('language'), row.get('collection')
        if identity in by_scope:
            raise ValueError('Duplicate automatic book scope')
        by_scope[identity] = row
    rows = []
    for language in config['languages']:
        for collection in COLLECTIONS:
            material = [row for row in catalog.get('entries', [])
                        if row.get('language') == language and MAP.get(row.get('collection')) == collection]
            current = [row for row in material if available(row)]
            legacy = []
            if collection == 'seerah':
                legacy = [row for row in current if row.get('edition') != 'new-adult']
                current = [row for row in current if row.get('edition') == 'new-adult']
            historical = [row for row in catalog.get('historicalArticleEntries', {}).get('entries', [])
                          if collection == 'articles' and row.get('language') == language]
            declaration = by_scope.get((language, collection))
            selected = []
            selection_error = None
            item = {'language': language, 'collection': collection,
                    'automaticApprovedSourceIntake': True,
                    'currentSourceUnits': len(current), 'eligibleUnits': 0,
                    'unboundCurrentUnits': len(current),
                    'legacyEditionUnits': len(legacy), 'historicalUnits': len(historical),
                    'heldOrWithdrawnUnits': len(material) - len([row for row in material if available(row)]),
                    'automaticBuild': bool(declaration and declaration.get('automaticBuild')),
                    'automaticRelease': bool(declaration and declaration.get('automaticRelease')),
                    'sourceApprovalCreated': False}
            if declaration and declaration.get('state') == 'reviewed-current' and declaration.get('automaticBuild') is True:
                try:
                    selected, reconciliation = select(root, catalog, declaration)
                    item['eligibleUnits'] = len(selected)
                    item['unboundCurrentUnits'] = len(reconciliation.get('unknownLegacyRows', [])) if reconciliation else 0
                    item['state'] = 'automatic-preparation-ready' if selected else 'waiting-for-approved-source'
                    if selected:
                        item['includedIds'] = [row['id'] for row in selected]
                    if reconciliation and reconciliation.get('unknownLegacyRows'):
                        item['unboundIds'] = [row['id'] for row in reconciliation['unknownLegacyRows']]
                        item['unboundReason'] = 'Current rows lack an exact supported reviewed reader binding; existing status and source qualifications remain unchanged.'
                    if declaration.get('releaseHold'):
                        item['releaseHold'] = declaration['releaseHold']
                    item['requiredReleaseChecks'] = [name for field, name in
                        (('requireActualWordLayout', 'actual-microsoft-word-layout'),
                         ('requireFinalVisualAcceptance', 'final-visual-acceptance'))
                        if declaration.get(field) is True]
                except Exception as error:
                    item['state'] = 'source-binding-error'
                    item['reason'] = str(error)
                    selection_error = str(error)
            elif declaration:
                item['state'] = 'explicit-scope-hold'
                item['reason'] = declaration.get('releaseHold', 'Existing scope is not declared for automatic preparation.')
            elif current:
                item['state'] = 'waiting-for-approved-source-binding'
                item['reason'] = 'Source rows exist, but no exact supported whole-material review/reader declaration is installed.'
            else:
                item['state'] = 'waiting-for-current-source'
                item['reason'] = ('Only legacy Seerah editions are present; the current new-adult edition is not installed in this language.'
                    if legacy else 'Only superseded standalone article translations are present; they are not translations of the current merged edition.'
                    if historical else 'No current source material is installed for this language/category.')
            item['coverage'] = scope_coverage(root, language, collection, catalog, declaration,
                selected=selected, book=downloads.get((language, collection)), discovered=discovery,
                selection_error=selection_error)
            item['unregisteredSourceUnits'] = len(item['coverage']['unregisteredSourceIds'])
            item['absentEarlierLessons'] = item['coverage']['absentEarlierLessons']
            rows.append(item)
    return {'schema': 'iman-multilingual-book-readiness-v1',
            'languages': list(config['languages']), 'languageCount': len(config['languages']),
            'scopeCount': len(rows), 'scopes': rows,
            'automaticPreparationScopes': sum(row['state'] == 'automatic-preparation-ready' for row in rows),
            'unregisteredSourceUnits': sum(row['unregisteredSourceUnits'] for row in rows),
            'scopesWithUnincludedCurrentMaterial': sum(bool(row['coverage']['missingCurrent']) for row in rows),
            'sourceApprovalCreated': False, 'sourceQualificationsChanged': False,
            'futureSourcePath': 'Exact reviewed source publications enter via materials/book-publication-intake with their normalized reader and original approval evidence.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = inventory(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'languages': result['languageCount'], 'scopes': result['scopeCount'],
                      'automaticPreparationScopes': result['automaticPreparationScopes']}))


if __name__ == '__main__':
    main()
