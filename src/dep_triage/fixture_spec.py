"""The curated package set the fixture is built from.

Curation matters more than size here. The set needs three properties, or whole
question classes become unanswerable:

1. **Packages with rich CVE history** — so "minimum safe version" has a real
   answer and the affected-version ranges are non-trivial.
2. **Packages with no known vulnerabilities** — otherwise "is X vulnerable?"
   is always yes and the question measures nothing.
3. **Packages that commonly appear pinned together** in a real
   ``requirements.txt``, so the multi-package question class reads naturally.

M0 scope §3.2 sets the target at ~80 packages with a floor of 20. If the build
overruns, ``CORE`` alone is the floor — it preserves all six question classes
on its own.
"""

from __future__ import annotations

#: Heavy CVE history. The backbone of the vulnerability question classes.
CORE: tuple[str, ...] = (
    "urllib3",
    "requests",
    "pyyaml",
    "jinja2",
    "pillow",
    "django",
    "flask",
    "cryptography",
    "lxml",
    "werkzeug",
    "tornado",
    "aiohttp",
    "paramiko",
    "celery",
    "sqlalchemy",
    "numpy",
    "setuptools",
    "pip",
    "twisted",
    "scrapy",
)

#: Moderate CVE history — widens the range of "minimum safe version" answers.
SECONDARY: tuple[str, ...] = (
    "bleach",
    "sphinx",
    "notebook",
    "nltk",
    "redis",
    "pymongo",
    "gunicorn",
    "fastapi",
    "pydantic",
    "httpx",
    "protobuf",
    "grpcio",
    "ansible-core",
    "docker",
    "kubernetes",
    "boto3",
    "markdown",
    "pygments",
    "babel",
    "rsa",
    "pyjwt",
    "oauthlib",
    "httplib2",
    "zipp",
    "mako",
    "starlette",
    "uvicorn",
    "transformers",
    "gradio",
    "streamlit",
    "plotly",
    "matplotlib",
    "pandas",
    "scikit-learn",
    "scipy",
    "psycopg2",
    "pymysql",
    "alembic",
    "peewee",
    "keras",
)

#: Expected to carry few or no advisories. Without these, every answer to
#: "is X vulnerable?" would be yes, and the class would be free to guess.
CLEAN: tuple[str, ...] = (
    "typing-extensions",
    "packaging",
    "six",
    "attrs",
    "click",
    "iniconfig",
    "tomli",
    "pluggy",
    "platformdirs",
    "filelock",
    "tqdm",
    "isort",
    "pycodestyle",
    "pyflakes",
    "markupsafe",
    "itsdangerous",
    "certifi",
    "idna",
    "charset-normalizer",
    "pyparsing",
)

#: Packages deliberately absent from the fixture, used by the abstention probe
#: (M0 scope §3.4). Asking about these has exactly one correct answer:
#: "unknown". Never add these to the sets above.
HELD_OUT_UNKNOWN: tuple[str, ...] = (
    "left-pad-python",
    "quicksort-turbo",
    "yaml-fast-parser",
    "requests-ng",
    "flask-supercharge",
    "numpy-lite",
    "cryptography-plus",
    "urllib4",
)

#: Build order is the declared order, so a truncated build still yields a
#: usable fixture rather than an arbitrary slice.
PACKAGES: tuple[str, ...] = CORE + SECONDARY + CLEAN


def validate_spec() -> None:
    """Raise if the curated sets overlap or collide with the unknown probes.

    A package appearing in both ``PACKAGES`` and ``HELD_OUT_UNKNOWN`` would make
    the abstention probe unanswerable, and a duplicate would silently weight one
    package twice in the task set.
    """
    seen: set[str] = set()
    duplicates: set[str] = set()
    for name in PACKAGES:
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    if duplicates:
        raise ValueError(f"duplicate packages in spec: {sorted(duplicates)}")

    collisions = seen & set(HELD_OUT_UNKNOWN)
    if collisions:
        raise ValueError(f"abstention probes must stay out of the fixture: {sorted(collisions)}")
