# tvlogo.py (hardened)
import json
from bs4 import BeautifulSoup

def extract_payload_from_file(file_path):
    """
    Extracts GitHub's embedded 'payload' JSON from the repository tree page,
    and computes a raw.githubusercontent.com initial_path for logos.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            html = f.read()

        soup = BeautifulSoup(html, 'html.parser')

        # GitHub embeds state here
        script_tag = soup.find('script', {
            'type': 'application/json',
            'data-target': 'react-app.embeddedData'
        })
        if not script_tag or not script_tag.string:
            print('Script tag with the payload not found.')
            return {}

        data = json.loads(script_tag.string)
        payload = data.get('payload', {})

        # Derive a raw path like:
        # https://raw.githubusercontent.com/<owner>/<repo>/<branch>/<path...>
        # The original code tried to reconstruct from <react-app initial-path>,
        # but we can be explicit:
        # Find repo info and the current path in the payload.
        repo = payload.get('repo', {}) or payload.get('repository', {})
        owner_login = (repo.get('ownerLogin')
                       or repo.get('owner', {}).get('login')
                       or 'tv-logo')
        repo_name = repo.get('name') or 'tv-logos'

        # GitHub's tree payload usually has 'refInfo' or similar:
        branch = (
            payload.get('refInfo', {}).get('name') or
            payload.get('ref', 'main') or
            'main'
        )

        # Current directory path from the UI:
        # payload['path'] or payload['currentPath'] depending on shape
        current_path = (
            payload.get('path') or
            payload.get('currentPath') or
            'countries/united-states'
        )

        # Normalize current_path (strip leading slashes)
        current_path = current_path.lstrip('/')

        # Compose initial_path to raw content (no /tree)
        initial_path = f"/{owner_login}/{repo_name}/{branch}/"

        # Store both the raw prefix and the original payload for items
        payload['initial_path'] = initial_path
        payload['current_path'] = current_path

        return payload

    except FileNotFoundError:
        print(f'The file {file_path} does not exist.')
        return {}
    except Exception as e:
        print(f'An error occurred: {e}')
        return {}

def search_tree_items(search_string, json_obj):
    """
    Searches payload.tree.items[] for filenames containing words in search_string.
    Returns list of {'id': {'path': <path>}, 'source': ''}.
    """
    matches = []
    search_words = search_string.lower().split()

    tree = json_obj.get('tree', {})
    items = tree.get('items', [])

    for item in items:
        name = (item.get('name') or '').lower()
        if not name:
            continue
        if any(w in name for w in search_words):
            # Prefer .png/.svg images; attach a relative path we can join to initial_path
            # The GitHub payload item often carries a 'path' field; fall back to name
            path = item.get('path') or json_obj.get('current_path', '') + '/' + item.get('name', '')
            matches.append({'id': {'path': path}, 'source': ''})

    return matches
