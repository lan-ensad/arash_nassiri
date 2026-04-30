"""
Setup pytest : ajoute le dossier parent au path pour permettre `import config`,
`import zones`, etc., depuis les tests sans installer le projet en package.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
